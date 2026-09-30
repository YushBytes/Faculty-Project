"""F20: what happened after an intervention — observed, never attributed.

This module measures. It does not judge whether an intervention worked, and it cannot: a
class that improves after extra sessions may have improved anyway, sat an easier paper, or
been taught differently for reasons nobody recorded. Every output here is a description of
marks, carries :data:`OBSERVATIONAL_CAVEAT`, and is screened for causal wording by the
contract itself.

The measurement, in full:

* **Pre** is every published assessment at or below the intervention's ``after_sequence_no``;
  **post** is the first published assessment after it. The boundary is a *sequence*, not a
  date — assessment dates are optional in this system and ordering never depends on them.
  :func:`boundary_from_date` converts a date where the data allows and refuses where it
  does not, including when an assessment falls on the intervention's own date.
* A student contributes **one** pre value (the mean of their assessed baselines) and **one**
  post value (their follow-up percentage), so a student who sat four baselines does not
  outweigh one who sat two. Only students assessed in **both** windows count; the rest are
  reported in ``coverage``, never as zeroes.
* The **target** group is the intervention's students; the **peers** are the rest of the
  active cohort. Both are gated at ``min_outcome_group_n``.
* ``net_change = target.change - peers.change``, and the label reads it against
  ``cohort_shift_pp`` — the same magnitude every other cohort movement is judged by.

The peer group is the point. Without it, "the targeted students went up 8 pp" says nothing:
the whole class may have gone up 8 pp. With it, the comparison is at least about something,
while still being observational — the groups were not randomised, and nobody was withheld
support to make the arithmetic cleaner.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import (
    AssessmentRef,
    Intervention,
    InterventionReason,
    OfferingSnapshot,
    StudentRef,
)
from app.modules.analytics.core.outputs import (
    OBSERVATIONAL_CAVEAT,
    AttentionFlag,
    DataCoverage,
    EvidenceItem,
    Explanation,
    InterventionOutcome,
    InterventionOutcomeSummary,
    OutcomeGroup,
)
from app.modules.analytics.core.policy import DerivedState, classify
from app.modules.analytics.core.results import (
    Label,
    Measure,
    Unit,
    insufficient_label,
    insufficient_measure,
    label,
    measure,
    shortfall,
)
from app.modules.analytics.core.statistics import (
    arithmetic_mean,
    mean_percent,
    median_of,
    quantize_percent,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet
from app.modules.analytics.core.vocabulary import (
    OUTCOME_VOCABULARY,
    InterventionStatus,
    OutcomeLabel,
)

STUDENT_NOUN = "paired student"
"""A student assessed in **both** windows — the only kind either group can count."""

OVERLAP_CAVEAT = (
    "More than one intervention targeted these students across the same assessments, so the "
    "change after this one cannot be separated from the change after the others."
)
"""Added when windows overlap. Not a disclaimer to bury — it is the finding."""


def reason_from_flag(flag: AttentionFlag) -> InterventionReason:
    """Capture an attention flag as the reason an intervention was raised.

    Freezes what the teacher saw: the rule, the value at that moment and the threshold it
    was compared against. Recomputing the flag next week may give a different number, which
    is precisely why the original is kept rather than a reference to a live one.
    """
    return InterventionReason(
        student_id=flag.student_id,
        rule_code=flag.rule_code,
        observed=flag.actual,
        threshold=flag.threshold,
        assessments=flag.reference_assessments,
        note=flag.message,
    )


# ------------------------------------------------------------------------ the two windows


def boundary_from_date(
    snapshot: OfferingSnapshot, raised_on: date, *, published_only: bool = True
) -> int | None:
    """The sequence boundary a date implies, or ``None`` when the data cannot resolve it.

    Refuses in two cases, rather than guessing:

    * any published assessment has no ``held_on`` — the order by date is unknowable;
    * an assessment falls **on** the intervention's own date — there is no way to tell
      whether it was sat before or after the conversation, and inventing an answer would
      silently move a result from one window to the other.
    """
    assessments = snapshot.ordered_assessments(published_only=published_only)
    if any(assessment.held_on is None for assessment in assessments):
        return None
    if any(assessment.held_on == raised_on for assessment in assessments):
        return None
    earlier = [a for a in assessments if a.held_on is not None and a.held_on < raised_on]
    return earlier[-1].sequence_no if earlier else 0


def baseline_assessments(
    snapshot: OfferingSnapshot, after_sequence_no: int, *, published_only: bool = True
) -> tuple[AssessmentRef, ...]:
    """Published assessments at or before the boundary."""
    return tuple(
        assessment
        for assessment in snapshot.ordered_assessments(published_only=published_only)
        if assessment.sequence_no <= after_sequence_no
    )


def follow_up_assessment(
    snapshot: OfferingSnapshot, after_sequence_no: int, *, published_only: bool = True
) -> AssessmentRef | None:
    """The first published assessment after the boundary, or ``None`` if none has happened."""
    later = [
        assessment
        for assessment in snapshot.ordered_assessments(published_only=published_only)
        if assessment.sequence_no > after_sequence_no
    ]
    return later[0] if later else None


def _percentage(
    snapshot: OfferingSnapshot, student_id: uuid.UUID, assessment: AssessmentRef
) -> Decimal | None:
    """One assessed percentage, or ``None`` for absent, exempt or missing."""
    from app.modules.analytics.core.policy import assessment_percentage

    result = snapshot.result_for(student_id, assessment.id)
    if result is None or result.score is None or not classify(result.status).is_assessed:
        return None
    return assessment_percentage(result.score, assessment.max_marks)


def _paired(
    snapshot: OfferingSnapshot,
    student: StudentRef,
    baselines: Sequence[AssessmentRef],
    follow_up: AssessmentRef,
) -> tuple[Decimal, Decimal] | None:
    """This student's pre and post values, or ``None`` if either window is empty.

    Pre is the mean of the baselines they were actually assessed in — one value per student,
    so someone who sat four papers does not outweigh someone who sat two.
    """
    assessed = [
        value
        for value in (_percentage(snapshot, student.id, a) for a in baselines)
        if value is not None
    ]
    post = _percentage(snapshot, student.id, follow_up)
    if not assessed or post is None:
        return None
    return quantize_percent(arithmetic_mean(assessed)), post


def _group(
    name: str,
    paired: Sequence[tuple[StudentRef, Decimal, Decimal]],
    thresholds: ThresholdSet,
) -> OutcomeGroup:
    """One side of the comparison, gated on its own size."""
    minimum = thresholds.count(ThresholdKey.MIN_OUTCOME_GROUP_N)
    students = tuple(student for student, _, _ in paired)
    pre_values = [pre for _, pre, _ in paired]
    post_values = [post for _, _, post in paired]

    if len(paired) < minimum:
        reason = shortfall(have=len(paired), need=minimum, noun=STUDENT_NOUN)
        withheld_percent = insufficient_measure(
            unit=Unit.PERCENT, n=len(paired), minimum_n=minimum, reason=reason
        )
        return OutcomeGroup(
            name=name,
            n=len(paired),
            pre_mean=withheld_percent,
            post_mean=withheld_percent,
            change=insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS,
                n=len(paired),
                minimum_n=minimum,
                reason=reason,
            ),
            students=students,
        )

    pre = mean_percent(pre_values, noun=STUDENT_NOUN)
    post = mean_percent(post_values, noun=STUDENT_NOUN)
    return OutcomeGroup(
        name=name,
        n=len(paired),
        pre_mean=pre,
        post_mean=post,
        change=measure(
            quantize_percent((post.value or Decimal(0)) - (pre.value or Decimal(0))),
            unit=Unit.PERCENTAGE_POINTS,
            n=len(paired),
            minimum_n=minimum,
        ),
        students=students,
    )


def _coverage(
    snapshot: OfferingSnapshot,
    baselines: Sequence[AssessmentRef],
    follow_up: AssessmentRef | None,
    *,
    active_only: bool = True,
) -> DataCoverage:
    """Who could be measured, and why the rest could not.

    ``assessed`` counts students present in both windows. Everyone else is counted under
    their state in the follow-up when that is not assessed, and otherwise under the baseline
    — the reason they fell out, rather than a bare shortfall.
    """
    students = snapshot.active_students() if active_only else snapshot.students
    states: list[DerivedState] = []
    for student in students:
        post_state = DerivedState.MISSING
        if follow_up is not None:
            result = snapshot.result_for(student.id, follow_up.id)
            post_state = classify(result.status if result else None)
        has_baseline = any(
            _percentage(snapshot, student.id, assessment) is not None for assessment in baselines
        )
        if has_baseline and post_state.is_assessed:
            states.append(DerivedState.ASSESSED)
        elif not post_state.is_assessed:
            states.append(post_state)
        else:
            states.append(DerivedState.MISSING)
    return DataCoverage.from_states(
        states, basis="active enrolled students, paired across the pre and post windows"
    )


# --------------------------------------------------------------------------- the outcome


def _unmeasurable(
    intervention: Intervention,
    snapshot: OfferingSnapshot,
    baselines: Sequence[AssessmentRef],
    follow_up: AssessmentRef | None,
    *,
    reason: str,
    narrative: str,
    stamp: datetime,
    active_only: bool,
) -> InterventionOutcome:
    """An outcome that cannot be measured, saying exactly what was missing."""
    withheld_percent = insufficient_measure(unit=Unit.PERCENT, n=0, minimum_n=1, reason=reason)
    withheld_points = insufficient_measure(
        unit=Unit.PERCENTAGE_POINTS, n=0, minimum_n=1, reason=reason
    )
    empty = OutcomeGroup(
        name="target",
        n=0,
        pre_mean=withheld_percent,
        post_mean=withheld_percent,
        change=withheld_points,
    )
    return InterventionOutcome(
        generated_at=stamp,
        intervention_id=intervention.id,
        offering_id=intervention.offering_id,
        baseline_assessments=tuple(baselines),
        follow_up_assessment=follow_up,
        target=empty,
        peers=empty.model_copy(update={"name": "peers"}),
        net_change=withheld_points,
        label=insufficient_label(vocabulary=OUTCOME_VOCABULARY, n=0, minimum_n=1, reason=reason),
        coverage=_coverage(snapshot, baselines, follow_up, active_only=active_only),
        explanation=Explanation(
            narrative=narrative,
            evidence=(
                EvidenceItem(
                    name="Baseline assessments",
                    value=str(len(baselines)),
                    unit=Unit.COUNT,
                ),
                EvidenceItem(
                    name="Follow-up assessment",
                    value=follow_up.code if follow_up else "none",
                ),
            ),
            caveats=(OBSERVATIONAL_CAVEAT,),
        ),
    )


def intervention_outcome(
    snapshot: OfferingSnapshot,
    intervention: Intervention,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    overlapping: bool = False,
    generated_at: datetime | None = None,
) -> InterventionOutcome:
    """**Contract 10.** The change observed after one intervention, against its peers.

    ``overlapping`` adds :data:`OVERLAP_CAVEAT`; :func:`intervention_outcomes` sets it for
    interventions that share students and a follow-up window.
    """
    stamp = generated_at or datetime.now(UTC)
    baselines = baseline_assessments(
        snapshot, intervention.after_sequence_no, published_only=published_only
    )
    follow_up = follow_up_assessment(
        snapshot, intervention.after_sequence_no, published_only=published_only
    )

    if not intervention.status.has_happened:
        wording = (
            "was cancelled"
            if intervention.status is InterventionStatus.CANCELLED
            else "has not taken place yet"
        )
        return _unmeasurable(
            intervention,
            snapshot,
            baselines,
            follow_up,
            reason=f"the intervention {wording}, so there is no change after it to report",
            narrative=(
                f"This intervention {wording}. No outcome is reported: a change measured "
                "after an action that did not happen is not an outcome of it."
            ),
            stamp=stamp,
            active_only=active_only,
        )

    if not baselines:
        return _unmeasurable(
            intervention,
            snapshot,
            baselines,
            follow_up,
            reason="no published assessment precedes this intervention",
            narrative=(
                "No published assessment precedes this intervention, so there is nothing to "
                "compare the later results against."
            ),
            stamp=stamp,
            active_only=active_only,
        )

    if follow_up is None:
        return _unmeasurable(
            intervention,
            snapshot,
            baselines,
            follow_up,
            reason="no published assessment has been held since this intervention",
            narrative=(
                "No published assessment has been held since this intervention, so there is "
                "nothing yet to measure. This is not a finding that nothing changed."
            ),
            stamp=stamp,
            active_only=active_only,
        )

    students = snapshot.active_students() if active_only else snapshot.students
    target_rows: list[tuple[StudentRef, Decimal, Decimal]] = []
    peer_rows: list[tuple[StudentRef, Decimal, Decimal]] = []
    for student in students:
        paired = _paired(snapshot, student, baselines, follow_up)
        if paired is None:
            continue
        pre, post = paired
        row = (student, pre, post)
        (target_rows if student.id in intervention.targets else peer_rows).append(row)

    target = _group("target", target_rows, thresholds)
    peers = _group("peers", peer_rows, thresholds)
    net = _net_change(target, peers, thresholds)
    verdict = _label(net, thresholds)

    return InterventionOutcome(
        generated_at=stamp,
        intervention_id=intervention.id,
        offering_id=intervention.offering_id,
        baseline_assessments=baselines,
        follow_up_assessment=follow_up,
        target=target,
        peers=peers,
        net_change=net,
        label=verdict,
        coverage=_coverage(snapshot, baselines, follow_up, active_only=active_only),
        explanation=_outcome_explanation(
            intervention=intervention,
            baselines=baselines,
            follow_up=follow_up,
            target=target,
            peers=peers,
            net=net,
            thresholds=thresholds,
            overlapping=overlapping,
        ),
    )


def _net_change(target: OutcomeGroup, peers: OutcomeGroup, thresholds: ThresholdSet) -> Measure:
    """``target.change - peers.change``, carrying either side's insufficiency forward."""
    minimum = thresholds.count(ThresholdKey.MIN_OUTCOME_GROUP_N)
    for group in (target, peers):
        if not group.change.is_ok or group.change.value is None:
            return insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS,
                n=group.n,
                minimum_n=minimum,
                reason=f"change not measurable for the {group.name} group: {group.change.reason}",
            )
    return measure(
        quantize_percent((target.change.value or Decimal(0)) - (peers.change.value or Decimal(0))),
        unit=Unit.PERCENTAGE_POINTS,
        n=target.n + peers.n,
        minimum_n=minimum * 2,
    )


def _label(net: Measure, thresholds: ThresholdSet) -> Label:
    """Read the net change against the cohort-movement magnitude.

    Reuses ``cohort_shift_pp`` rather than inventing a threshold: this is a movement of one
    group against another, which is what that key already governs.
    """
    minimum = thresholds.count(ThresholdKey.MIN_OUTCOME_GROUP_N)
    if not net.is_ok or net.value is None:
        return insufficient_label(
            vocabulary=OUTCOME_VOCABULARY,
            n=net.n,
            minimum_n=minimum,
            reason=net.reason or "the net change could not be computed",
        )
    shift = thresholds.value(ThresholdKey.COHORT_SHIFT_PP)
    if net.value >= shift:
        chosen = OutcomeLabel.TARGET_IMPROVED_MORE
    elif net.value <= -shift:
        chosen = OutcomeLabel.TARGET_IMPROVED_LESS
    else:
        chosen = OutcomeLabel.NO_MEASURABLE_DIFFERENCE
    return label(chosen, vocabulary=OUTCOME_VOCABULARY, n=net.n, minimum_n=minimum)


def _outcome_explanation(
    *,
    intervention: Intervention,
    baselines: Sequence[AssessmentRef],
    follow_up: AssessmentRef,
    target: OutcomeGroup,
    peers: OutcomeGroup,
    net: Measure,
    thresholds: ThresholdSet,
    overlapping: bool,
) -> Explanation:
    codes = ", ".join(a.code for a in baselines)

    if target.change.is_ok:
        sentences = [
            f"Across the {target.n} targeted "
            f"{'student' if target.n == 1 else 'students'} assessed in both windows, the "
            f"average moved from {target.pre_mean.value}% before the intervention "
            f"({codes}) to {target.post_mean.value}% in {follow_up.code}: "
            f"{target.change.value} percentage points."
        ]
    else:
        sentences = [
            f"The targeted group cannot be measured: {target.change.reason}. "
            f"Baseline {codes}; follow-up {follow_up.code}."
        ]

    if peers.change.is_ok:
        sentences.append(
            f"The {peers.n} other students assessed in both windows moved from "
            f"{peers.pre_mean.value}% to {peers.post_mean.value}%: "
            f"{peers.change.value} percentage points."
        )
    else:
        sentences.append(f"The comparison group cannot be measured: {peers.change.reason}.")

    if net.is_ok:
        sentences.append(f"The observed difference in change is {net.value} percentage points.")
    else:
        sentences.append("No difference in change can be reported.")

    caveats = (OBSERVATIONAL_CAVEAT,) + ((OVERLAP_CAVEAT,) if overlapping else ())

    evidence = [
        EvidenceItem(
            name="Intervention",
            value=intervention.kind.value,
            note=f"status {intervention.status.value}",
        ),
        EvidenceItem(name="Baseline assessments", value=codes or "none"),
        EvidenceItem(name="Follow-up assessment", value=follow_up.code),
        EvidenceItem(name="Targeted and measurable", value=str(target.n), unit=Unit.COUNT),
        EvidenceItem(name="Comparison group", value=str(peers.n), unit=Unit.COUNT),
    ]
    if target.pre_mean.is_ok:
        evidence.append(
            EvidenceItem(name="Target before", value=str(target.pre_mean.value), unit=Unit.PERCENT)
        )
        evidence.append(
            EvidenceItem(name="Target after", value=str(target.post_mean.value), unit=Unit.PERCENT)
        )

    return Explanation(
        narrative=" ".join(sentences),
        formula=(
            "per student: pre = mean of assessed baselines, post = follow-up percentage; "
            "group change = mean(post) - mean(pre); net = target change - peers change"
        ),
        evidence=tuple(evidence),
        thresholds=(
            thresholds.resolved[ThresholdKey.MIN_OUTCOME_GROUP_N],
            thresholds.resolved[ThresholdKey.COHORT_SHIFT_PP],
        ),
        assessments_used=(*[a.code for a in baselines], follow_up.code),
        caveats=caveats,
    )


# ------------------------------------------------------------------- many interventions


def _overlaps(one: Intervention, other: Intervention) -> bool:
    """Whether two interventions share a student and land in the same follow-up window."""
    return bool(one.targets & other.targets) and one.after_sequence_no == other.after_sequence_no


def intervention_outcomes(
    snapshot: OfferingSnapshot,
    interventions: Sequence[Intervention],
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[InterventionOutcome, ...]:
    """One outcome per intervention, each measured in its own window.

    Interventions are never merged. Where two of them share students and a window, both
    outcomes are reported and both carry :data:`OVERLAP_CAVEAT`: the same change sits after
    both actions, and saying which one it belongs to would be an attribution this layer
    cannot make.

    Order follows the interventions as given, so a caller controls it.
    """
    stamp = generated_at or datetime.now(UTC)
    return tuple(
        intervention_outcome(
            snapshot,
            intervention,
            thresholds,
            active_only=active_only,
            published_only=published_only,
            overlapping=any(
                _overlaps(intervention, other)
                for other in interventions
                if other.id != intervention.id
            ),
            generated_at=stamp,
        )
        for intervention in interventions
    )


def outcome_summary(
    outcomes: Sequence[InterventionOutcome],
    *,
    offering_id: uuid.UUID,
    generated_at: datetime | None = None,
) -> InterventionOutcomeSummary:
    """**Contract 15.** Descriptive statistics over several outcomes.

    Counts and averages of *observed change*, nothing more. There is no success rate here
    and no effectiveness: the interventions were not assigned at random, the students who
    received them were chosen because they were struggling, and a mean of their changes is a
    description of some marks — not a measure of whether the actions worked.
    """
    stamp = generated_at or datetime.now(UTC)
    measurable = [
        outcome
        for outcome in outcomes
        if outcome.target.change.is_ok and outcome.target.change.value is not None
    ]
    changes = [outcome.target.change.value for outcome in measurable]  # type: ignore[misc]

    if changes:
        mean_change = measure(
            quantize_percent(arithmetic_mean(changes)),
            unit=Unit.PERCENTAGE_POINTS,
            n=len(changes),
            minimum_n=1,
        )
        median_change = measure(
            quantize_percent(median_of(changes)),
            unit=Unit.PERCENTAGE_POINTS,
            n=len(changes),
            minimum_n=1,
        )
    else:
        reason = shortfall(have=0, need=1, noun="measurable intervention")
        mean_change = insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS, n=0, minimum_n=1, reason=reason
        )
        median_change = insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS, n=0, minimum_n=1, reason=reason
        )

    positive = sum(1 for value in changes if value > 0)
    negative = sum(1 for value in changes if value < 0)
    unchanged = sum(1 for value in changes if value == 0)

    narrative = (
        f"{len(outcomes)} {'intervention' if len(outcomes) == 1 else 'interventions'}, "
        f"{len(measurable)} with enough data on both sides to report a change. "
        + (
            f"Observed changes in the targeted groups: mean {mean_change.value} pp, median "
            f"{median_change.value} pp; {positive} up, {negative} down, {unchanged} "
            "unchanged."
            if changes
            else "No intervention has a measurable change yet."
        )
    )

    return InterventionOutcomeSummary(
        generated_at=stamp,
        offering_id=offering_id,
        interventions=len(outcomes),
        measurable=len(measurable),
        mean_observed_change=mean_change,
        median_observed_change=median_change,
        improved=positive,
        declined=negative,
        unchanged=unchanged,
        explanation=Explanation(
            narrative=narrative,
            formula="descriptive statistics over each intervention's target-group change",
            evidence=(
                EvidenceItem(name="Interventions", value=str(len(outcomes)), unit=Unit.COUNT),
                EvidenceItem(
                    name="With a measurable change",
                    value=str(len(measurable)),
                    unit=Unit.COUNT,
                    note="both groups met the minimum size and both windows had results",
                ),
            ),
            caveats=(OBSERVATIONAL_CAVEAT,),
        ),
    )
