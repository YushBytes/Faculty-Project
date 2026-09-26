"""F15 and F16: what moved between two assessments, and who moved.

The one idea this module exists to enforce: **a change is measured over the students who
sat both assessments.** Two assessments' published means are over different cohorts — an
absence here, a new enrolment there — so subtracting them measures the change in who sat
the paper as much as the change in how they did.

In the canonical fixture, CT1's mean is 63.67 (n=6) and CT2's is 62.40 (n=5). Subtracting
gives -1.27 pp, which is not a fact about anybody: S7 sat CT1 and not CT2. Over the five
students who sat both, CT1 is 66.40 and CT2 is 62.40, so the class moved **-4.00 pp**. Both
numbers appear in the output — the intersection deltas, and each assessment's own
statistics — so neither can be mistaken for the other.

Participation is the deliberate exception. "Did fewer students turn up?" is a question about
the whole cohort, not about the ones who turned up, so ``completion_change`` is measured
over every active student and its two denominators are quoted, because they differ whenever
someone is exempt from one assessment and not the other.

Nothing here computes a statistic. Every number is a Phase 2 function applied to a pair of
filtered lists, and every verdict is a threshold comparison — there are no significance
tests, no p-values and no inference. Assessments are not equated for difficulty, so a
movement is a fact about the marks and never, on its own, a claim about the students.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import AssessmentRef, OfferingSnapshot, StudentRef
from app.modules.analytics.core.outputs import (
    DIFFICULTY_CAVEAT,
    AssessmentComparison,
    ChangeAnalysis,
    ChangeGroup,
    ClassFinding,
    DataCoverage,
    EvidenceItem,
    Explanation,
)
from app.modules.analytics.core.policy import (
    DerivedState,
    assessed_scores,
    build_student_series,
    classify,
    series_up_to,
)
from app.modules.analytics.core.results import Measure, Unit, insufficient_measure, measure
from app.modules.analytics.core.statistics import (
    assessment_analytics,
    assessment_coverage,
    completion_percent,
    mean_percent,
    median_percent,
    pass_percent,
    quantize_percent,
    std_dev_percentage_points,
)
from app.modules.analytics.core.student import is_sharp_decline
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet
from app.modules.analytics.core.vocabulary import ChangeDirection, ClassFindingCode

PAIRED_NOUN = "student assessed in both"

ATTENTION_NOT_EVALUATED = (
    "Attention flags were not evaluated in this analysis, so no flag counts are reported. "
    "An empty list here does not mean no student needs attention."
)
"""Said out loud rather than implied by an empty tuple; see ``ChangeAnalysis.new_flags``."""


class PairedResult(tuple[StudentRef, Decimal, Decimal]):
    """One student's percentages in the two assessments being compared."""

    __slots__ = ()

    @property
    def student(self) -> StudentRef:
        return self[0]

    @property
    def before(self) -> Decimal:
        return self[1]

    @property
    def after(self) -> Decimal:
        return self[2]

    @property
    def change(self) -> Decimal:
        """Signed movement in percentage points."""
        return quantize_percent(self.after - self.before)


def cohort_intersection(
    snapshot: OfferingSnapshot,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    *,
    active_only: bool = True,
) -> tuple[PairedResult, ...]:
    """The students assessed in **both** assessments, with both percentages.

    In the snapshot's cohort order, so two renderings of the same comparison list the same
    students in the same sequence.
    """
    before = dict(assessed_scores(snapshot, from_assessment, active_only=active_only))
    after = dict(assessed_scores(snapshot, to_assessment, active_only=active_only))
    return tuple(
        PairedResult((student, before[student], after[student]))
        for student in before
        if student in after
    )


def _delta(
    before: Measure,
    after: Measure,
    *,
    n: int,
    minimum_n: int | None = None,
    what: str,
) -> Measure:
    """``after - before`` as a movement, carrying either side's insufficiency forward.

    A composition, not a calculation: both operands were computed by the Phase 2 function
    that owns them, and this only subtracts and re-labels the unit as percentage points.
    """
    if not before.is_ok or before.value is None:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=before.n,
            minimum_n=before.minimum_n or 1,
            reason=f"no {what} for the earlier assessment: {before.reason}",
        )
    if not after.is_ok or after.value is None:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=after.n,
            minimum_n=after.minimum_n or 1,
            reason=f"no {what} for the later assessment: {after.reason}",
        )
    return measure(
        quantize_percent(after.value - before.value),
        unit=Unit.PERCENTAGE_POINTS,
        n=n,
        minimum_n=minimum_n,
    )


def _comparison_coverage(
    snapshot: OfferingSnapshot,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    *,
    active_only: bool = True,
) -> DataCoverage:
    """Who is in the comparison, and why the rest are not.

    ``assessed`` counts the intersection. Everyone else is counted under the state that kept
    them out — their state in the later assessment when that is not assessed, otherwise their
    state in the earlier one — so the numbers name the reason rather than just the shortfall.
    """
    students = snapshot.active_students() if active_only else snapshot.students
    states: list[DerivedState] = []
    for student in students:
        earlier = snapshot.result_for(student.id, from_assessment.id)
        later = snapshot.result_for(student.id, to_assessment.id)
        before = classify(earlier.status if earlier else None)
        after = classify(later.status if later else None)
        if before.is_assessed and after.is_assessed:
            states.append(DerivedState.ASSESSED)
        elif not after.is_assessed:
            states.append(after)
        else:
            states.append(before)
    return DataCoverage.from_states(
        states,
        basis=(
            f"active enrolled students, paired across {from_assessment.code} and "
            f"{to_assessment.code}"
        ),
    )


def compare_assessments(
    snapshot: OfferingSnapshot,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    *,
    active_only: bool = True,
    include_analytics: bool = True,
    generated_at: datetime | None = None,
) -> AssessmentComparison:
    """**F15, contract 13.** How the same students' results moved between two assessments."""
    stamp = generated_at or datetime.now(UTC)
    paired = cohort_intersection(snapshot, from_assessment, to_assessment, active_only=active_only)
    before = [pair.before for pair in paired]
    after = [pair.after for pair in paired]
    pass_mark = snapshot.pass_mark_percent

    from_coverage = assessment_coverage(snapshot, from_assessment, active_only=active_only)
    to_coverage = assessment_coverage(snapshot, to_assessment, active_only=active_only)

    mean_change = _delta(
        mean_percent(before, noun=PAIRED_NOUN),
        mean_percent(after, noun=PAIRED_NOUN),
        n=len(paired),
        what="mean",
    )
    median_change = _delta(
        median_percent(before, noun=PAIRED_NOUN),
        median_percent(after, noun=PAIRED_NOUN),
        n=len(paired),
        what="median",
    )
    pass_change = _delta(
        pass_percent(before, pass_mark),
        pass_percent(after, pass_mark),
        n=len(paired),
        what="pass rate",
    )
    spread_change = _delta(
        std_dev_percentage_points(before, noun=PAIRED_NOUN),
        std_dev_percentage_points(after, noun=PAIRED_NOUN),
        n=len(paired),
        what="spread",
    )
    completion_change = _delta(
        completion_percent(from_coverage),
        completion_percent(to_coverage),
        n=to_coverage.completion_denominator,
        what="completion",
    )

    return AssessmentComparison(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        from_assessment=from_assessment,
        to_assessment=to_assessment,
        intersection_n=len(paired),
        mean_change=mean_change,
        median_change=median_change,
        pass_percent_change=pass_change,
        spread_change=spread_change,
        completion_change=completion_change,
        from_analytics=(
            assessment_analytics(
                snapshot, from_assessment, active_only=active_only, generated_at=stamp
            )
            if include_analytics
            else None
        ),
        to_analytics=(
            assessment_analytics(
                snapshot, to_assessment, active_only=active_only, generated_at=stamp
            )
            if include_analytics
            else None
        ),
        coverage=_comparison_coverage(
            snapshot, from_assessment, to_assessment, active_only=active_only
        ),
        explanation=_comparison_explanation(
            from_assessment=from_assessment,
            to_assessment=to_assessment,
            paired=paired,
            before=before,
            after=after,
            mean_change=mean_change,
            completion_change=completion_change,
            from_coverage=from_coverage,
            to_coverage=to_coverage,
        ),
    )


def _comparison_explanation(
    *,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    paired: Sequence[PairedResult],
    before: Sequence[Decimal],
    after: Sequence[Decimal],
    mean_change: Measure,
    completion_change: Measure,
    from_coverage: DataCoverage,
    to_coverage: DataCoverage,
) -> Explanation:
    if paired:
        from_mean = mean_percent(before, noun=PAIRED_NOUN)
        to_mean = mean_percent(after, noun=PAIRED_NOUN)
        narrative = (
            f"Across the {len(paired)} "
            f"{'student' if len(paired) == 1 else 'students'} assessed in both "
            f"{from_assessment.code} and {to_assessment.code}, the mean moved from "
            f"{from_mean.value}% to {to_mean.value}%: {mean_change.value} pp. "
            f"{from_assessment.code}'s own mean is over {from_coverage.assessed} assessed "
            f"students and {to_assessment.code}'s over {to_coverage.assessed}, which is why "
            "the comparison uses only the students common to both."
        )
    else:
        narrative = (
            f"No student was assessed in both {from_assessment.code} and "
            f"{to_assessment.code}, so no movement can be reported. "
            f"{from_coverage.assessed} were assessed in the first and "
            f"{to_coverage.assessed} in the second."
        )

    evidence = [
        EvidenceItem(
            name=f"{from_assessment.code} assessed",
            value=str(from_coverage.assessed),
            unit=Unit.COUNT,
        ),
        EvidenceItem(
            name=f"{to_assessment.code} assessed",
            value=str(to_coverage.assessed),
            unit=Unit.COUNT,
        ),
        EvidenceItem(
            name="Assessed in both",
            value=str(len(paired)),
            unit=Unit.COUNT,
            note="the cohort intersection: every movement below is over these students",
        ),
        EvidenceItem(
            name="Completion denominators",
            value=f"{from_coverage.completion_denominator} -> {to_coverage.completion_denominator}",
            unit=Unit.COUNT,
            note="participation is over the whole cohort, and exempt students leave it",
        ),
    ]
    if completion_change.is_ok:
        evidence.append(
            EvidenceItem(
                name="Participation change",
                value=str(completion_change.value),
                unit=Unit.PERCENTAGE_POINTS,
            )
        )

    return Explanation(
        narrative=narrative,
        formula=(
            "delta = f(P over students assessed in both) after - before, for f in "
            "{mean, median, pass %, population sd}; participation over the whole cohort"
        ),
        evidence=tuple(evidence),
        assessments_used=(str(from_assessment.code), str(to_assessment.code)),
        caveats=(DIFFICULTY_CAVEAT,),
    )


# --------------------------------------------------------------------- cohort findings


def _direction(value: Decimal) -> ChangeDirection:
    if value > 0:
        return ChangeDirection.UP
    if value < 0:
        return ChangeDirection.DOWN
    return ChangeDirection.UNCHANGED


def _class_finding(
    code: ClassFindingCode,
    movement: Measure,
    *,
    thresholds: ThresholdSet,
    n: int,
    what: str,
    unit_phrase: str = "pp",
) -> ClassFinding:
    """One movement, judged against ``cohort_shift_pp`` once the cohort is big enough."""
    threshold = thresholds.resolved[ThresholdKey.COHORT_SHIFT_PP]
    minimum = thresholds.count(ThresholdKey.MIN_GROUP_N)

    if not movement.is_ok or movement.value is None:
        return ClassFinding(
            code=code,
            detected=None,
            direction=None,
            measure=movement,
            threshold=threshold,
            n=n,
            minimum_n=minimum,
            explanation=Explanation(
                narrative=f"{what} cannot be assessed: {movement.reason}.",
                thresholds=(threshold,),
                caveats=(DIFFICULTY_CAVEAT,),
            ),
        )

    if n < minimum:
        return ClassFinding(
            code=code,
            detected=None,
            direction=None,
            measure=movement,
            threshold=threshold,
            n=n,
            minimum_n=minimum,
            explanation=Explanation(
                narrative=(
                    f"{what} moved {movement.value} {unit_phrase}, but over only {n} "
                    f"{'student' if n == 1 else 'students'} (minimum {minimum}). The number "
                    "is reported; no judgement is made about a cohort this small."
                ),
                evidence=(
                    EvidenceItem(
                        name="Movement",
                        value=str(movement.value),
                        unit=Unit.PERCENTAGE_POINTS,
                    ),
                ),
                thresholds=(threshold,),
                caveats=(DIFFICULTY_CAVEAT,),
            ),
        )

    detected = abs(movement.value) >= threshold.value
    direction = _direction(movement.value)
    narrative = f"{what} moved {movement.value} {unit_phrase} across {n} students. " + (
        f"That reaches the configured shift of {threshold.value} pp."
        if detected
        else f"That does not reach the configured shift of {threshold.value} pp."
    )
    return ClassFinding(
        code=code,
        detected=detected,
        direction=direction,
        measure=movement,
        threshold=threshold,
        n=n,
        minimum_n=minimum,
        explanation=Explanation(
            narrative=narrative,
            formula="detected = abs(movement) >= cohort_shift_pp",
            evidence=(
                EvidenceItem(
                    name="Movement", value=str(movement.value), unit=Unit.PERCENTAGE_POINTS
                ),
                EvidenceItem(name="Students", value=str(n), unit=Unit.COUNT),
            ),
            thresholds=(threshold,),
            caveats=(DIFFICULTY_CAVEAT,),
        ),
    )


def class_findings(
    comparison: AssessmentComparison, thresholds: ThresholdSet
) -> tuple[ClassFinding, ...]:
    """The four cohort movements, each judged against the same configured magnitude.

    All four are always returned, detected or not: "the pass rate did not move" is an answer
    a teacher wants, and a list that only ever contains bad news is a list nobody trusts.
    """
    paired_n = comparison.intersection_n
    participation_n = comparison.coverage.completion_denominator
    return (
        _class_finding(
            ClassFindingCode.CLASS_MEAN_MOVED,
            comparison.mean_change,
            thresholds=thresholds,
            n=paired_n,
            what="The class mean",
        ),
        _class_finding(
            ClassFindingCode.PASS_RATE_MOVED,
            comparison.pass_percent_change,
            thresholds=thresholds,
            n=paired_n,
            what="The pass rate",
        ),
        _class_finding(
            ClassFindingCode.PARTICIPATION_MOVED,
            comparison.completion_change,
            thresholds=thresholds,
            n=participation_n,
            what="Participation",
        ),
        _class_finding(
            ClassFindingCode.SPREAD_MOVED,
            comparison.spread_change,
            thresholds=thresholds,
            n=paired_n,
            what="The spread of scores",
        ),
    )


# ----------------------------------------------------------------------- movement groups


def change_groups(
    snapshot: OfferingSnapshot,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
) -> tuple[ChangeGroup, ...]:
    """Who moved, by name. Five groups, always present, empty when nobody qualifies.

    A count with no member list is not actionable — "four students crossed below the pass
    mark" leaves a teacher with nothing to do — so :class:`ChangeGroup` carries the students
    and derives the count from them.
    """
    paired = cohort_intersection(snapshot, from_assessment, to_assessment, active_only=active_only)
    pass_mark = snapshot.pass_mark_percent
    delta = thresholds.value(ThresholdKey.IMPROVEMENT_DELTA_PP)

    crossed_up = [p.student for p in paired if p.before < pass_mark <= p.after]
    crossed_down = [p.student for p in paired if p.after < pass_mark <= p.before]
    improved = [p.student for p in paired if p.change >= delta]
    declined = [p.student for p in paired if p.change <= -delta]
    newly_declining = _newly_sharp_decline(
        snapshot, from_assessment, to_assessment, thresholds, active_only=active_only
    )

    return (
        ChangeGroup(
            label=f"Crossed up to the {pass_mark}% pass mark",
            direction=ChangeDirection.UP,
            students=tuple(crossed_up),
        ),
        ChangeGroup(
            label=f"Crossed below the {pass_mark}% pass mark",
            direction=ChangeDirection.DOWN,
            students=tuple(crossed_down),
        ),
        ChangeGroup(
            label=f"Improved by at least {delta} pp",
            direction=ChangeDirection.UP,
            students=tuple(improved),
        ),
        ChangeGroup(
            label=f"Declined by at least {delta} pp",
            direction=ChangeDirection.DOWN,
            students=tuple(declined),
        ),
        ChangeGroup(
            label="Newly showing a sharp decline",
            direction=ChangeDirection.DOWN,
            students=tuple(newly_declining),
        ),
    )


def _newly_sharp_decline(
    snapshot: OfferingSnapshot,
    from_assessment: AssessmentRef,
    to_assessment: AssessmentRef,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
) -> list[StudentRef]:
    """Students whose sharp decline (F10) is true now and was not true before.

    "New" is a claim about two states, so the rule is evaluated twice: once on the series
    truncated at the earlier assessment, once on the series as it stands. A student whose
    earlier series was too short to judge counts as new if the condition holds now — the
    condition has appeared, which is what the word means.
    """
    students = snapshot.active_students() if active_only else snapshot.students
    newly: list[StudentRef] = []
    for student in students:
        series = build_student_series(snapshot, student.id)
        now = series_up_to(series, to_assessment.sequence_no)
        if is_sharp_decline(now, thresholds) is not True:
            continue
        before = series_up_to(series, from_assessment.sequence_no)
        if is_sharp_decline(before, thresholds) is not True:
            newly.append(student)
    return newly


# ------------------------------------------------------------------- 9. ChangeAnalysis


def latest_published(snapshot: OfferingSnapshot) -> AssessmentRef | None:
    """The most recent published assessment, or ``None`` when there are none."""
    published = snapshot.ordered_assessments()
    return published[-1] if published else None


def preceding_published(
    snapshot: OfferingSnapshot, assessment: AssessmentRef
) -> AssessmentRef | None:
    """The published assessment immediately before ``assessment`` in sequence order."""
    published = snapshot.ordered_assessments()
    earlier = [a for a in published if a.sequence_no < assessment.sequence_no]
    return earlier[-1] if earlier else None


def change_analysis(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    to_assessment: AssessmentRef | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> ChangeAnalysis:
    """**F16, contract 9.** What the latest assessment changed, against the state before it.

    The first assessment of an offering changes nothing — there is no earlier state to
    compare with, which is not the same as a change of zero — so every movement comes back
    as insufficient data with that reason, and no group is reported.
    """
    stamp = generated_at or datetime.now(UTC)
    target = to_assessment or latest_published(snapshot)
    if target is None:
        raise ValueError("this offering has no published assessment to analyse")
    previous = preceding_published(snapshot, target)

    if previous is None:
        reason = (
            f"{target.code} is the first published assessment in this offering, so there is "
            "no earlier result to compare it with"
        )
        withheld = insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS, n=0, minimum_n=1, reason=reason
        )
        return ChangeAnalysis(
            generated_at=stamp,
            offering_id=snapshot.offering_id,
            from_assessment=None,
            to_assessment=target,
            intersection_n=0,
            class_mean_change=withheld,
            pass_percent_change=withheld,
            groups=(),
            comparison=None,
            findings=(),
            coverage=assessment_coverage(snapshot, target, active_only=active_only),
            explanation=Explanation(
                narrative=f"{reason.capitalize()}.",
                evidence=(
                    EvidenceItem(
                        name=f"{target.code} assessed",
                        value=str(
                            assessment_coverage(snapshot, target, active_only=active_only).assessed
                        ),
                        unit=Unit.COUNT,
                    ),
                ),
                assessments_used=(str(target.code),),
                caveats=(DIFFICULTY_CAVEAT,),
            ),
        )

    comparison = compare_assessments(
        snapshot, previous, target, active_only=active_only, generated_at=stamp
    )
    groups = change_groups(snapshot, previous, target, thresholds, active_only=active_only)
    findings = class_findings(comparison, thresholds)

    return ChangeAnalysis(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        from_assessment=previous,
        to_assessment=target,
        intersection_n=comparison.intersection_n,
        class_mean_change=comparison.mean_change,
        pass_percent_change=comparison.pass_percent_change,
        groups=groups,
        comparison=comparison,
        findings=findings,
        new_flags=(),
        coverage=comparison.coverage,
        explanation=_change_explanation(comparison=comparison, groups=groups, findings=findings),
    )


def _change_explanation(
    *,
    comparison: AssessmentComparison,
    groups: Sequence[ChangeGroup],
    findings: Sequence[ClassFinding],
) -> Explanation:
    moved = [
        f"{f.code.value} ({f.direction.value})"
        for f in findings
        if f.detected and f.direction is not None
    ]
    populated = [g for g in groups if g.count]

    sentences = [comparison.explanation.narrative]
    sentences.append(
        "Movements reaching the configured shift: " + ", ".join(moved) + "."
        if moved
        else "No movement reached the configured shift."
    )
    if populated:
        sentences.append(
            "Students who moved: "
            + "; ".join(f"{g.label.lower()} — {g.count}" for g in populated)
            + "."
        )
    else:
        sentences.append("No student crossed the pass mark or moved by the configured margin.")
    sentences.append(ATTENTION_NOT_EVALUATED)

    return Explanation(
        narrative=" ".join(sentences),
        formula="see the comparison; groups are exact sets over the cohort intersection",
        evidence=(
            *comparison.explanation.evidence,
            *(
                EvidenceItem(name=group.label, value=str(group.count), unit=Unit.COUNT)
                for group in groups
            ),
        ),
        thresholds=tuple(f.threshold for f in findings if f.threshold is not None)[:1],
        assessments_used=comparison.explanation.assessments_used,
        caveats=(DIFFICULTY_CAVEAT,),
    )


def consecutive_comparisons(
    snapshot: OfferingSnapshot,
    *,
    active_only: bool = True,
    include_analytics: bool = False,
    generated_at: datetime | None = None,
) -> tuple[AssessmentComparison, ...]:
    """Every adjacent pair of published assessments, in order.

    Answers "which assessments show movement?" without ranking them: the comparisons are
    returned in the order they happened, and the reader decides what matters.
    """
    stamp = generated_at or datetime.now(UTC)
    published = snapshot.ordered_assessments()
    return tuple(
        compare_assessments(
            snapshot,
            earlier,
            later,
            active_only=active_only,
            include_analytics=include_analytics,
            generated_at=stamp,
        )
        for earlier, later in zip(published, published[1:], strict=False)
    )


def comparison_for(
    snapshot: OfferingSnapshot,
    from_assessment_id: uuid.UUID,
    to_assessment_id: uuid.UUID,
    *,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> AssessmentComparison:
    """Compare two assessments by id, in whichever order they were asked for.

    The contract requires the earlier assessment first, so the pair is ordered by
    ``sequence_no`` here rather than refusing a reasonable request.
    """
    from app.modules.analytics.core.student import assessment_for

    first = assessment_for(snapshot, from_assessment_id)
    second = assessment_for(snapshot, to_assessment_id)
    earlier, later = sorted((first, second), key=lambda a: a.sequence_no)
    return compare_assessments(
        snapshot, earlier, later, active_only=active_only, generated_at=generated_at
    )
