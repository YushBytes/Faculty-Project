"""F20: the change observed after an intervention, and everything it refuses to claim.

The working fixture — eight students, three assessments, four of them targeted after CT2:

=======  =================  =========================  =========  =========
who      CT1, CT2, CT3      pre = mean(CT1, CT2)       post       change
=======  =================  =========================  =========  =========
t1       50, 52, 70         51.00                      70.00      +19.00
t2       48, 50, 68         49.00                      68.00      +19.00
t3       52, 54, 66         53.00                      66.00      +13.00
t4       46, 48, 64         47.00                      64.00      +17.00
p1       70, 72, 74         71.00                      74.00       +3.00
p2       68, 70, 71         69.00                      71.00       +2.00
p3       66, 68, 70         67.00                      70.00       +3.00
p4       72, 74, 75         73.00                      75.00       +2.00
=======  =================  =========================  =========  =========

    target  pre 50.00 → post 67.00 = +17.00 pp
    peers   pre 70.00 → post 72.50 =  +2.50 pp
    observed difference in change   = +14.50 pp

Every number above is a description of marks. The targeted students were chosen *because*
they were behind, which is exactly why the comparison is observational and nothing here may
say the sessions worked.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.attention import student_flags
from app.modules.analytics.core.contracts import Intervention, InterventionReason
from app.modules.analytics.core.interventions import (
    OVERLAP_CAVEAT,
    baseline_assessments,
    boundary_from_date,
    follow_up_assessment,
    intervention_outcome,
    intervention_outcomes,
    outcome_summary,
    reason_from_flag,
)
from app.modules.analytics.core.outputs import OBSERVATIONAL_CAVEAT, InterventionOutcome
from app.modules.analytics.core.policy import build_student_series
from app.modules.analytics.core.results import MeasureStatus, Unit
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import InterventionKind, InterventionStatus
from tests.analytics import builders as b
from tests.analytics import canonical as fx

TARGETS = ("t1", "t2", "t3", "t4")
PEERS = ("p1", "p2", "p3", "p4")

COHORT = {
    "t1": (50, 52, 70),
    "t2": (48, 50, 68),
    "t3": (52, 54, 66),
    "t4": (46, 48, 64),
    "p1": (70, 72, 74),
    "p2": (68, 70, 71),
    "p3": (66, 68, 70),
    "p4": (72, 74, 75),
}


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def cohort(rows: dict | None = None, **kwargs):  # noqa: ANN201
    return b.build_snapshot(rows if rows is not None else COHORT, **kwargs)


def intervention(
    snapshot,  # noqa: ANN001
    *,
    targets: tuple[str, ...] = TARGETS,
    after: int = 2,
    kind: InterventionKind = InterventionKind.REMEDIAL_SESSION,
    status: InterventionStatus = InterventionStatus.COMPLETED,
    note: str | None = "weekly remedial sessions",
    reasons: tuple[InterventionReason, ...] = (),
    identifier: uuid.UUID | None = None,
) -> Intervention:
    return Intervention(
        id=identifier or uuid.uuid4(),
        offering_id=snapshot.offering_id,
        student_ids=tuple(b.student_id(key) for key in targets),
        kind=kind,
        status=status,
        after_sequence_no=after,
        reasons=reasons,
        note=note,
    )


def outcome_for(snapshot, **kwargs) -> InterventionOutcome:  # noqa: ANN001
    thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
    return intervention_outcome(snapshot, intervention(snapshot, **kwargs), thresholds)


class TestTheInterventionRecord:
    def test_a_target_and_a_reason_are_required(self) -> None:
        snapshot = cohort()
        with pytest.raises(ValidationError):
            Intervention(
                id=uuid.uuid4(),
                offering_id=snapshot.offering_id,
                student_ids=(),
                kind=InterventionKind.ACADEMIC_SUPPORT,
                after_sequence_no=1,
                note="no targets",
            )
        with pytest.raises(ValidationError, match="must record why it was raised"):
            Intervention(
                id=uuid.uuid4(),
                offering_id=snapshot.offering_id,
                student_ids=(b.student_id("t1"),),
                kind=InterventionKind.ACADEMIC_SUPPORT,
                after_sequence_no=1,
            )

    def test_a_student_cannot_be_listed_twice(self) -> None:
        snapshot = cohort()
        with pytest.raises(ValidationError, match="listed twice"):
            Intervention(
                id=uuid.uuid4(),
                offering_id=snapshot.offering_id,
                student_ids=(b.student_id("t1"), b.student_id("t1")),
                kind=InterventionKind.PEER_SUPPORT,
                after_sequence_no=1,
                note="duplicate",
            )

    def test_a_reason_must_name_a_student_who_is_targeted(self) -> None:
        snapshot = cohort()
        with pytest.raises(ValidationError, match="not targets"):
            Intervention(
                id=uuid.uuid4(),
                offering_id=snapshot.offering_id,
                student_ids=(b.student_id("t1"),),
                kind=InterventionKind.PEER_SUPPORT,
                after_sequence_no=1,
                reasons=(InterventionReason(student_id=b.student_id("p1"), note="wrong one"),),
            )

    def test_a_reason_carries_the_flag_that_prompted_it(self) -> None:
        """The evidence a teacher saw, frozen at the moment of the decision."""
        series = build_student_series(fx.snapshot(), fx.S5)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code.startswith("R1")][0]
        reason = reason_from_flag(flag)
        assert reason.student_id == fx.S5
        assert reason.rule_code is AttentionRuleCode.R1_LOW_PERFORMANCE
        assert reason.observed == flag.actual
        assert reason.threshold == flag.threshold
        assert reason.assessments == flag.reference_assessments

    def test_a_reason_must_say_something(self) -> None:
        with pytest.raises(ValidationError, match="must name a rule, a finding or a note"):
            InterventionReason(student_id=uuid.uuid4())


class TestWindows:
    def test_pre_is_everything_up_to_the_boundary_and_post_is_the_next_one(self) -> None:
        snapshot = cohort()
        assert [a.code for a in baseline_assessments(snapshot, 2)] == ["CT1", "CT2"]
        follow_up = follow_up_assessment(snapshot, 2)
        assert follow_up is not None and follow_up.code == "CT3"

    def test_an_unpublished_assessment_is_never_the_follow_up(self) -> None:
        """The canonical quiz is unpublished; FT1 is the last published assessment."""
        assert follow_up_assessment(fx.snapshot(), 3) is None

    def test_a_date_resolves_to_a_sequence_when_every_assessment_is_dated(self) -> None:
        snapshot = fx.snapshot()
        dated = snapshot.model_copy(
            update={
                "assessments": tuple(
                    a.model_copy(update={"held_on": date(2026, 8, a.sequence_no)})
                    for a in snapshot.assessments
                )
            }
        )
        assert boundary_from_date(dated, date(2026, 8, 15)) == 3
        assert boundary_from_date(dated, date(2026, 7, 15)) == 0, "before any assessment"

    def test_a_date_refuses_when_an_assessment_has_none(self) -> None:
        """Dates are optional in this system, so ordering by them is not always possible."""
        assert boundary_from_date(fx.snapshot(), date(2026, 9, 1)) is None

    def test_a_date_refuses_on_the_day_of_an_assessment(self) -> None:
        """Same-day ambiguity: there is no way to know which came first."""
        snapshot = fx.snapshot()
        dated = snapshot.model_copy(
            update={
                "assessments": tuple(
                    a.model_copy(update={"held_on": date(2026, 8, a.sequence_no)})
                    for a in snapshot.assessments
                )
            }
        )
        assert boundary_from_date(dated, date(2026, 8, 2)) is None


class TestTheBasicOutcome:
    def test_target_and_peer_change(self) -> None:
        built = outcome_for(cohort())
        assert built.target.n == 4
        assert built.target.pre_mean.value == Decimal("50.00")
        assert built.target.post_mean.value == Decimal("67.00")
        assert built.target.change.value == Decimal("17.00")
        assert built.peers.n == 4
        assert built.peers.pre_mean.value == Decimal("70.00")
        assert built.peers.post_mean.value == Decimal("72.50")
        assert built.peers.change.value == Decimal("2.50")

    def test_the_observed_difference_in_change(self) -> None:
        built = outcome_for(cohort())
        assert built.net_change.value == Decimal("14.50")
        assert built.net_change.unit is Unit.PERCENTAGE_POINTS
        assert built.label.value == "target_improved_more"
        assert built.is_measured is True

    def test_the_windows_are_named(self) -> None:
        built = outcome_for(cohort())
        assert [a.code for a in built.baseline_assessments] == ["CT1", "CT2"]
        assert built.follow_up_assessment is not None
        assert built.follow_up_assessment.code == "CT3"

    def test_each_student_contributes_one_pre_value(self) -> None:
        """t1 sat two baselines; their pre is the mean of them, not two observations."""
        built = outcome_for(cohort())
        assert built.target.n == 4, "four students, not eight observations"
        assert [s.register_no for s in built.target.students] == [
            "RA0001",
            "RA0002",
            "RA0003",
            "RA0004",
        ]

    def test_the_peer_group_is_everyone_else_in_the_cohort(self) -> None:
        built = outcome_for(cohort())
        assert {s.register_no for s in built.peers.students} == {
            "RA0005",
            "RA0006",
            "RA0007",
            "RA0008",
        }


class TestPositiveNegativeAndZeroChange:
    def test_a_positive_observed_change(self) -> None:
        assert outcome_for(cohort()).target.change.value > 0

    def test_a_negative_observed_change(self) -> None:
        rows = dict(COHORT)
        rows.update({k: (v[0], v[1], 30) for k, v in COHORT.items() if k in TARGETS})
        built = outcome_for(cohort(rows))
        assert built.target.change.value == Decimal("-20.00")
        assert built.net_change.value == Decimal("-22.50")
        assert built.label.value == "target_improved_less"

    def test_a_zero_observed_change(self) -> None:
        flat = {k: (60, 60, 60) for k in TARGETS} | {k: (70, 70, 70) for k in PEERS}
        built = outcome_for(cohort(flat))
        assert built.target.change.value == Decimal("0.00")
        assert built.peers.change.value == Decimal("0.00")
        assert built.net_change.value == Decimal("0.00")
        assert built.label.value == "no_measurable_difference"

    def test_a_small_difference_is_not_called_a_difference(self) -> None:
        """Both groups move; the gap between them is below the configured magnitude."""
        rows = {k: (50, 50, 54) for k in TARGETS} | {k: (70, 70, 72) for k in PEERS}
        built = outcome_for(cohort(rows))
        assert built.net_change.value == Decimal("2.00")
        assert built.label.value == "no_measurable_difference"

    def test_the_magnitude_is_configurable(self) -> None:
        snapshot = cohort({k: (50, 50, 54) for k in TARGETS} | {k: (70, 70, 72) for k in PEERS})
        sensitive = resolve_thresholds(
            pass_mark_percent=snapshot.pass_mark_percent,
            offering_overrides={"cohort_shift_pp": "1"},
        )
        built = intervention_outcome(snapshot, intervention(snapshot), sensitive)
        assert built.label.value == "target_improved_more"
        assert built.explanation.thresholds[-1].key is ThresholdKey.COHORT_SHIFT_PP
        assert built.explanation.thresholds[-1].source.value == "offering_override"


class TestInsufficientData:
    def test_no_assessment_since_the_intervention(self) -> None:
        built = outcome_for(cohort(), after=3)
        assert built.follow_up_assessment is None
        assert built.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.net_change.value is None
        assert built.is_measured is False
        assert "nothing yet to measure" in built.explanation.narrative
        assert "not a finding that nothing changed" in built.explanation.narrative

    def test_nothing_before_the_intervention(self) -> None:
        built = outcome_for(cohort(), after=0)
        assert built.baseline_assessments == ()
        assert built.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert "nothing to compare" in built.explanation.narrative

    def test_a_target_group_below_the_minimum(self) -> None:
        built = outcome_for(cohort(), targets=("t1", "t2"))
        assert built.target.n == 2
        assert built.target.change.status is MeasureStatus.INSUFFICIENT_DATA
        assert "minimum 3" in (built.target.change.reason or "")
        assert built.net_change.value is None
        assert built.label.value is None

    def test_a_peer_group_below_the_minimum(self) -> None:
        """Six targeted of eight leaves two peers: the comparison cannot be made."""
        built = outcome_for(cohort(), targets=(*TARGETS, "p1", "p2"))
        assert built.peers.n == 2
        assert built.target.change.is_ok, "the targets are still measurable"
        assert built.net_change.value is None
        assert built.label.value is None

    def test_insufficient_never_becomes_zero(self) -> None:
        built = outcome_for(cohort(), after=3)
        assert built.target.change.value is None
        assert built.net_change.value is None
        assert built.label.value is None

    def test_a_cancelled_intervention_is_not_measured(self) -> None:
        built = outcome_for(cohort(), status=InterventionStatus.CANCELLED)
        assert built.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert "was cancelled" in built.explanation.narrative
        assert "did not happen is not an outcome of it" in built.explanation.narrative

    def test_a_planned_intervention_is_not_measured(self) -> None:
        built = outcome_for(cohort(), status=InterventionStatus.PLANNED)
        assert built.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert "has not taken place yet" in built.explanation.narrative


class TestMissingDataRules:
    def test_an_absent_follow_up_drops_the_student_from_both_groups(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, b.ABSENT)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 3, "t1 cannot be paired"
        assert "RA0001" not in {s.register_no for s in built.target.students}
        assert built.target.pre_mean.value == Decimal("49.67"), "(49 + 53 + 47) / 3"
        assert built.coverage.absent == 1

    def test_an_absent_result_is_never_read_as_zero(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, b.ABSENT)}
        with_absence = outcome_for(cohort(rows))
        assert with_absence.target.post_mean.value == Decimal("66.00"), "(68 + 66 + 64) / 3"

    def test_a_missing_follow_up_drops_the_student(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, b.MISSING)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 3
        assert built.coverage.missing == 1

    def test_an_exempt_follow_up_drops_the_student(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, b.EXEMPT)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 3
        assert built.coverage.exempt == 1

    def test_a_student_with_no_baseline_is_dropped(self) -> None:
        rows = dict(COHORT) | {"t1": (b.ABSENT, b.ABSENT, 70)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 3

    def test_a_partial_baseline_still_counts(self) -> None:
        """t1 sat only CT2: their pre is that one assessment, not a penalty."""
        rows = dict(COHORT) | {"t1": (b.ABSENT, 52, 70)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 4
        assert built.target.pre_mean.value == Decimal("50.25"), "(52 + 49 + 53 + 47) / 4"

    def test_a_genuine_zero_is_a_real_score(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, 0)}
        built = outcome_for(cohort(rows))
        assert built.target.n == 4, "a zero is an assessed result"
        assert built.target.post_mean.value == Decimal("49.50"), "(0 + 68 + 66 + 64) / 4"

    def test_an_inactive_student_is_not_in_the_peer_group(self) -> None:
        built = outcome_for(cohort(COHORT, inactive=("p4",)))
        assert built.peers.n == 3
        assert "RA0008" not in {s.register_no for s in built.peers.students}


class TestMultipleInterventions:
    def test_each_intervention_gets_its_own_window(self) -> None:
        snapshot = cohort()
        thresholds = defaults()
        early = intervention(snapshot, targets=TARGETS, after=1)
        late = intervention(snapshot, targets=TARGETS, after=2)
        outcomes = intervention_outcomes(snapshot, [early, late], thresholds)
        assert [a.code for a in outcomes[0].baseline_assessments] == ["CT1"]
        assert outcomes[0].follow_up_assessment.code == "CT2"
        assert [a.code for a in outcomes[1].baseline_assessments] == ["CT1", "CT2"]
        assert outcomes[1].follow_up_assessment.code == "CT3"

    def test_windows_are_never_silently_merged(self) -> None:
        snapshot = cohort()
        outcomes = intervention_outcomes(
            snapshot,
            [intervention(snapshot, after=1), intervention(snapshot, after=2)],
            defaults(),
        )
        assert outcomes[0].target.change.value != outcomes[1].target.change.value
        assert len(outcomes) == 2

    def test_overlapping_interventions_both_say_so(self) -> None:
        """Two actions, same students, same window: the change sits after both."""
        snapshot = cohort()
        outcomes = intervention_outcomes(
            snapshot,
            [
                intervention(snapshot, after=2, kind=InterventionKind.REMEDIAL_SESSION),
                intervention(snapshot, after=2, kind=InterventionKind.PEER_SUPPORT),
            ],
            defaults(),
        )
        for built in outcomes:
            assert OVERLAP_CAVEAT in built.explanation.caveats

    def test_interventions_for_different_students_do_not_overlap(self) -> None:
        snapshot = cohort()
        outcomes = intervention_outcomes(
            snapshot,
            [
                intervention(snapshot, targets=("t1", "t2", "t3"), after=2),
                intervention(snapshot, targets=("p1", "p2", "p3"), after=2),
            ],
            defaults(),
        )
        for built in outcomes:
            assert OVERLAP_CAVEAT not in built.explanation.caveats

    def test_outcomes_follow_the_order_they_were_given(self) -> None:
        snapshot = cohort()
        first, second = intervention(snapshot, after=1), intervention(snapshot, after=2)
        outcomes = intervention_outcomes(snapshot, [first, second], defaults())
        assert [o.intervention_id for o in outcomes] == [first.id, second.id]


class TestSummary:
    def test_descriptive_statistics_across_interventions(self) -> None:
        snapshot = cohort()
        rising = intervention(snapshot, after=2)
        falling_rows = dict(COHORT) | {k: (COHORT[k][0], COHORT[k][1], 30) for k in TARGETS}
        falling = intervention(cohort(falling_rows), after=2)
        outcomes = [
            intervention_outcome(snapshot, rising, defaults()),
            intervention_outcome(cohort(falling_rows), falling, defaults()),
        ]
        summary = outcome_summary(outcomes, offering_id=snapshot.offering_id)
        assert summary.interventions == 2
        assert summary.measurable == 2
        assert summary.improved == 1
        assert summary.declined == 1
        assert summary.unchanged == 0
        assert summary.mean_observed_change.value == Decimal("-1.50"), "(17.00 + -20.00) / 2"
        assert summary.median_observed_change.value == Decimal("-1.50")

    def test_unmeasurable_interventions_are_counted_but_not_averaged(self) -> None:
        snapshot = cohort()
        outcomes = [
            intervention_outcome(snapshot, intervention(snapshot, after=2), defaults()),
            intervention_outcome(snapshot, intervention(snapshot, after=3), defaults()),
        ]
        summary = outcome_summary(outcomes, offering_id=snapshot.offering_id)
        assert summary.interventions == 2
        assert summary.measurable == 1
        assert summary.mean_observed_change.value == Decimal("17.00")

    def test_nothing_measurable_is_not_a_mean_of_zero(self) -> None:
        snapshot = cohort()
        outcomes = [intervention_outcome(snapshot, intervention(snapshot, after=3), defaults())]
        summary = outcome_summary(outcomes, offering_id=snapshot.offering_id)
        assert summary.measurable == 0
        assert summary.mean_observed_change.status is MeasureStatus.INSUFFICIENT_DATA
        assert summary.mean_observed_change.value is None
        assert "No intervention has a measurable change yet" in summary.explanation.narrative

    def test_the_counts_must_add_up(self) -> None:
        snapshot = cohort()
        summary = outcome_summary([], offering_id=snapshot.offering_id)
        with pytest.raises(ValidationError, match="counted up, down or unchanged"):
            summary.__class__(**{**summary.model_dump(), "improved": 3})


class TestObservationalOnly:
    def test_every_outcome_carries_the_observational_caveat(self) -> None:
        for built in (
            outcome_for(cohort()),
            outcome_for(cohort(), after=3),
            outcome_for(cohort(), status=InterventionStatus.CANCELLED),
        ):
            assert OBSERVATIONAL_CAVEAT in built.explanation.caveats

    def test_the_summary_carries_it_too(self) -> None:
        snapshot = cohort()
        summary = outcome_summary(
            [intervention_outcome(snapshot, intervention(snapshot), defaults())],
            offering_id=snapshot.offering_id,
        )
        assert OBSERVATIONAL_CAVEAT in summary.explanation.caveats

    @pytest.mark.parametrize(
        "narrative",
        [
            "The remedial sessions caused by the intervention raised the average.",
            "Treatment effect of +14.50 percentage points.",
            "This proves the sessions worked.",
            "The rise resulted from the intervention.",
            "Effectiveness: high.",
            "A causal improvement of 14.50 pp.",
            "This was an effective intervention.",
        ],
    )
    def test_causal_wording_is_refused_by_the_contract(self, narrative: str) -> None:
        snapshot = cohort()
        built = outcome_for(snapshot)
        with pytest.raises(ValidationError, match="forbidden wording"):
            built.__class__(
                **{
                    **built.model_dump(),
                    "explanation": {
                        **built.explanation.model_dump(),
                        "narrative": narrative,
                    },
                }
            )

    def test_the_real_narrative_says_observed_not_caused(self) -> None:
        narrative = outcome_for(cohort()).explanation.narrative
        assert "observed difference in change" in narrative
        for banned in ("caused", "effect", "proves", "worked", "because"):
            assert banned not in narrative.lower()

    def test_percentage_points_not_percent(self) -> None:
        built = outcome_for(cohort())
        assert "17.00 percentage points" in built.explanation.narrative
        assert "17.00%" not in built.explanation.narrative
        assert built.target.change.unit is Unit.PERCENTAGE_POINTS


class TestExplainability:
    def test_the_narrative_reproduces_the_arithmetic(self) -> None:
        narrative = outcome_for(cohort()).explanation.narrative
        for quoted in ("4 targeted", "50.00%", "67.00%", "70.00%", "72.50%", "14.50"):
            assert quoted in narrative

    def test_the_evidence_names_the_windows_and_the_groups(self) -> None:
        evidence = {i.name: i.value for i in outcome_for(cohort()).explanation.evidence}
        assert evidence["Baseline assessments"] == "CT1, CT2"
        assert evidence["Follow-up assessment"] == "CT3"
        assert evidence["Targeted and measurable"] == "4"
        assert evidence["Comparison group"] == "4"
        assert evidence["Intervention"] == "remedial_session"

    def test_both_thresholds_travel_with_their_provenance(self) -> None:
        keys = {t.key for t in outcome_for(cohort()).explanation.thresholds}
        assert keys == {ThresholdKey.MIN_OUTCOME_GROUP_N, ThresholdKey.COHORT_SHIFT_PP}
        assert all(
            t.source.value == "system_default" for t in outcome_for(cohort()).explanation.thresholds
        )

    def test_coverage_explains_who_could_not_be_paired(self) -> None:
        rows = dict(COHORT) | {"t1": (50, 52, b.ABSENT), "p1": (70, 72, b.MISSING)}
        built = outcome_for(cohort(rows))
        assert built.coverage.assessed == 6
        assert built.coverage.absent == 1
        assert built.coverage.missing == 1
        assert built.coverage.considered == 8


class TestDeterminismAndSafety:
    def test_the_same_inputs_give_the_same_output(self) -> None:
        snapshot = cohort()
        thresholds = defaults()
        raised = intervention(snapshot)
        stamp = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
        first = intervention_outcome(snapshot, raised, thresholds, generated_at=stamp)
        second = intervention_outcome(snapshot, raised, thresholds, generated_at=stamp)
        assert first.model_dump() == second.model_dump()

    def test_reordering_students_changes_no_number(self) -> None:
        snapshot = cohort()
        reordered = snapshot.model_copy(update={"students": tuple(reversed(snapshot.students))})
        thresholds = defaults()
        raised = intervention(snapshot)
        original = intervention_outcome(snapshot, raised, thresholds)
        shuffled = intervention_outcome(reordered, raised, thresholds)
        assert original.target.change.value == shuffled.target.change.value
        assert original.net_change.value == shuffled.net_change.value

    def test_reordering_assessments_changes_no_number(self) -> None:
        snapshot = cohort()
        reordered = snapshot.model_copy(
            update={"assessments": tuple(reversed(snapshot.assessments))}
        )
        thresholds = defaults()
        raised = intervention(snapshot)
        assert (
            intervention_outcome(snapshot, raised, thresholds).net_change.value
            == intervention_outcome(reordered, raised, thresholds).net_change.value
        )

    def test_no_payload_contains_a_non_finite_number(self) -> None:
        snapshot = cohort()
        thresholds = defaults()
        for raised in (
            intervention(snapshot),
            intervention(snapshot, after=0),
            intervention(snapshot, after=3),
            intervention(snapshot, targets=("t1",)),
            intervention(snapshot, status=InterventionStatus.CANCELLED),
        ):
            built = intervention_outcome(snapshot, raised, thresholds)
            text = built.model_dump_json()
            assert "NaN" not in text and "Infinity" not in text
            for value in _numbers(json.loads(text)):
                assert math.isfinite(value)

    def test_the_engine_does_not_mutate_the_snapshot(self) -> None:
        snapshot = cohort()
        before = snapshot.model_dump()
        intervention_outcome(snapshot, intervention(snapshot), defaults())
        assert snapshot.model_dump() == before

    def test_rounding_is_two_decimal_places(self) -> None:
        """(49 + 53 + 47) / 3 = 49.6667 -> 49.67, once, at the point it is published."""
        rows = dict(COHORT) | {"t1": (50, 52, b.ABSENT)}
        built = outcome_for(cohort(rows))
        assert built.target.pre_mean.value == Decimal("49.67")
        assert built.target.pre_mean.value.as_tuple().exponent == -2


def _numbers(payload: object) -> list[float]:
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [float(payload)]
    if isinstance(payload, dict):
        return [n for value in payload.values() for n in _numbers(value)]
    if isinstance(payload, list):
        return [n for value in payload for n in _numbers(value)]
    return []
