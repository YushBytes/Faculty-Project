"""F15 and F16: what moved between two assessments, and who moved.

The arithmetic, worked by hand from `canonical.py` (pass mark 40):

CT1 assessed: S1 90, S2 80, S3 90, S4 42, S5 30, S7 50   (S6 absent)        n=6
CT2 assessed: S1 92, S2 60, S3 88, S4 40, S5 32          (S6 exempt, S7 no row)  n=5
FT1 assessed: S1 95, S2 40, S3 50, S4 41, S5 35, S6 60   (S7 no row)        n=6

CT1 -> CT2, intersection {S1,S2,S3,S4,S5} = 5
    mean      (90+80+90+42+30)/5 = 66.40  ->  (92+60+88+40+32)/5 = 62.40   = -4.00
    median    80.00 -> 60.00                                              = -20.00
    pass %    4/5 = 80.00 -> 4/5 = 80.00                                  =  0.00
    spread    25.37 -> 24.34                                              = -1.03
    completion 6/7 = 85.71 -> 5/6 = 83.33                                 = -2.38

CT2 -> FT1, intersection {S1,S2,S3,S4,S5} = 5
    mean      62.40 -> (95+40+50+41+35)/5 = 52.20                         = -10.20
    declined by >= 5 pp: S2 (-20), S3 (-38)
    newly sharp decline: S3 only — S2 already qualified at CT2 (60 against a mean of 80)
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.comparison import (
    change_analysis,
    change_groups,
    class_findings,
    cohort_intersection,
    compare_assessments,
    comparison_for,
    consecutive_comparisons,
    latest_published,
    preceding_published,
)
from app.modules.analytics.core.outputs import DIFFICULTY_CAVEAT
from app.modules.analytics.core.results import MeasureStatus, Unit
from app.modules.analytics.core.statistics import assessment_analytics
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import ChangeDirection, ClassFindingCode
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def group(analysis: object, fragment: str) -> object:
    found = [g for g in analysis.groups if fragment in g.label]  # type: ignore[attr-defined]
    assert len(found) == 1, f"expected one group matching {fragment!r}, got {len(found)}"
    return found[0]


def finding(findings: object, code: ClassFindingCode) -> object:
    """The one finding with this code, asserting there is exactly one."""
    found = [f for f in findings if f.code is code]  # type: ignore[attr-defined]
    assert len(found) == 1, f"expected one {code.value} finding, got {len(found)}"
    return found[0]


class TestCohortIntersection:
    def test_only_students_assessed_in_both_are_paired(self) -> None:
        paired = cohort_intersection(fx.snapshot(), fx.CT1, fx.CT2)
        assert [p.student.id for p in paired] == [fx.S1, fx.S2, fx.S3, fx.S4, fx.S5]
        assert paired[1].before == Decimal("80.00")
        assert paired[1].after == Decimal("60.00")
        assert paired[1].change == Decimal("-20.00")

    def test_an_absence_in_either_assessment_excludes_the_student(self) -> None:
        """S6 was absent in CT1 and exempt in CT2; S7 sat CT1 and nothing after."""
        paired = {p.student.id for p in cohort_intersection(fx.snapshot(), fx.CT1, fx.CT2)}
        assert fx.S6 not in paired
        assert fx.S7 not in paired

    def test_inactive_students_are_not_in_the_intersection(self) -> None:
        paired = cohort_intersection(fx.snapshot(), fx.CT1, fx.CT2)
        assert fx.S8 not in {p.student.id for p in paired}

    def test_the_pairing_is_in_cohort_order(self) -> None:
        paired = cohort_intersection(fx.snapshot(), fx.CT1, fx.FT1)
        assert [p.student.register_no for p in paired] == [
            "RA001",
            "RA002",
            "RA003",
            "RA004",
            "RA005",
        ]


class TestAssessmentComparison:
    def test_canonical_ct1_to_ct2(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        assert comparison.intersection_n == 5
        assert comparison.mean_change.value == Decimal("-4.00")
        assert comparison.median_change.value == Decimal("-20.00")
        assert comparison.pass_percent_change.value == Decimal("0.00")
        assert comparison.spread_change.value == Decimal("-1.03")
        assert comparison.completion_change.value == Decimal("-2.38")

    def test_canonical_ct2_to_ft1(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT2, fx.FT1)
        assert comparison.intersection_n == 5
        assert comparison.mean_change.value == Decimal("-10.20")
        assert comparison.completion_change.value == Decimal("2.38"), "5/6 -> 6/7"

    def test_the_intersection_is_not_the_difference_of_the_published_means(self) -> None:
        """The whole reason this module exists.

        CT1's published mean is 63.67 over 6 students and CT2's is 62.40 over 5. Subtracting
        them gives -1.27 pp, which is a fact about nobody: S7 sat CT1 and not CT2. Over the
        five students who sat both, the class moved -4.00 pp.
        """
        snapshot = fx.snapshot()
        naive = (
            assessment_analytics(snapshot, fx.CT2).mean.value
            - assessment_analytics(snapshot, fx.CT1).mean.value
        )
        assert naive == Decimal("-1.27")
        assert compare_assessments(snapshot, fx.CT1, fx.CT2).mean_change.value == Decimal("-4.00")

    def test_both_assessments_own_statistics_travel_along(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        assert comparison.from_analytics is not None
        assert comparison.to_analytics is not None
        assert comparison.from_analytics.mean.value == Decimal("63.67"), "over its own 6"
        assert comparison.to_analytics.mean.value == Decimal("62.40")

    def test_every_change_is_in_percentage_points(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        for change in (
            comparison.mean_change,
            comparison.median_change,
            comparison.pass_percent_change,
            comparison.spread_change,
            comparison.completion_change,
        ):
            assert change.unit is Unit.PERCENTAGE_POINTS

    def test_the_deltas_use_the_phase_2_functions(self) -> None:
        """Composition, not a second calculation: the endpoints are the canonical means."""
        from app.modules.analytics.core.statistics import mean_percent

        snapshot = fx.snapshot()
        paired = cohort_intersection(snapshot, fx.CT1, fx.CT2)
        before = mean_percent([p.before for p in paired])
        after = mean_percent([p.after for p in paired])
        assert compare_assessments(snapshot, fx.CT1, fx.CT2).mean_change.value == (
            after.value - before.value
        )

    def test_coverage_says_who_is_in_the_comparison_and_why_the_rest_are_not(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        coverage = comparison.coverage
        assert coverage.assessed == 5, "the intersection"
        assert coverage.exempt == 1, "S6, exempt in CT2"
        assert coverage.missing == 1, "S7, no CT2 row"
        assert coverage.considered == 7

    def test_the_difficulty_caveat_is_mandatory(self) -> None:
        assert (
            DIFFICULTY_CAVEAT
            in compare_assessments(fx.snapshot(), fx.CT1, fx.CT2).explanation.caveats
        )

    def test_the_explanation_quotes_both_means_and_the_intersection(self) -> None:
        narrative = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2).explanation.narrative
        assert "66.40%" in narrative and "62.40%" in narrative
        assert "-4.00 pp" in narrative
        assert "5 students assessed in both" in narrative

    def test_a_comparison_must_read_forwards(self) -> None:
        with pytest.raises(ValidationError, match="a comparison reads forwards"):
            compare_assessments(fx.snapshot(), fx.CT2, fx.CT1)

    def test_an_assessment_cannot_be_compared_with_itself(self) -> None:
        with pytest.raises(ValidationError, match="compared with itself"):
            compare_assessments(fx.snapshot(), fx.CT1, fx.CT1)

    def test_either_order_may_be_asked_for_by_id(self) -> None:
        backwards = comparison_for(fx.snapshot(), fx.CT2_ID, fx.CT1_ID)
        assert backwards.from_assessment.code == "CT1"
        assert backwards.mean_change.value == Decimal("-4.00")


class TestEmptyAndThinComparisons:
    def test_no_shared_student_reports_no_movement(self) -> None:
        """Two assessments sat by disjoint halves of a class change nothing measurable."""
        snapshot = b.build_snapshot({"s1": (60, b.ABSENT), "s2": (b.ABSENT, 70)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        assert comparison.intersection_n == 0
        assert comparison.mean_change.status is MeasureStatus.INSUFFICIENT_DATA
        assert comparison.mean_change.value is None
        assert "no student was assessed in both" in comparison.explanation.narrative.lower()

    def test_one_shared_student_gives_a_mean_but_no_spread(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 70), "s2": (50, b.ABSENT)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        assert comparison.intersection_n == 1
        assert comparison.mean_change.value == Decimal("10.00")
        assert comparison.spread_change.status is MeasureStatus.INSUFFICIENT_DATA

    def test_identical_results_move_nothing(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 60), "s2": (40, 40), "s3": (80, 80)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        for change in (
            comparison.mean_change,
            comparison.median_change,
            comparison.pass_percent_change,
            comparison.spread_change,
            comparison.completion_change,
        ):
            assert change.value == Decimal("0.00")

    def test_a_whole_cohort_absent_in_the_later_assessment(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, b.ABSENT), "s2": (70, b.ABSENT)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        assert comparison.intersection_n == 0
        assert comparison.completion_change.value == Decimal("-100.00")
        assert comparison.mean_change.value is None, "nobody sat it: not a fall to zero"


class TestClassFindings:
    def test_a_material_fall_is_detected_with_its_direction(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT2, fx.FT1)
        found = finding(class_findings(comparison, defaults()), ClassFindingCode.CLASS_MEAN_MOVED)
        assert found.detected is True
        assert found.direction is ChangeDirection.DOWN
        assert found.measure.value == Decimal("-10.20")
        assert found.threshold is not None
        assert found.threshold.key is ThresholdKey.COHORT_SHIFT_PP

    def test_a_movement_below_the_threshold_is_reported_as_not_detected(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        found = finding(class_findings(comparison, defaults()), ClassFindingCode.CLASS_MEAN_MOVED)
        assert found.measure.value == Decimal("-4.00")
        assert found.detected is False
        assert found.direction is ChangeDirection.DOWN
        assert "does not reach the configured shift" in found.explanation.narrative

    def test_all_four_movements_are_always_reported(self) -> None:
        found = class_findings(compare_assessments(fx.snapshot(), fx.CT1, fx.CT2), defaults())
        assert [f.code for f in found] == [
            ClassFindingCode.CLASS_MEAN_MOVED,
            ClassFindingCode.PASS_RATE_MOVED,
            ClassFindingCode.PARTICIPATION_MOVED,
            ClassFindingCode.SPREAD_MOVED,
        ]

    def test_an_unchanged_measure_has_a_direction_of_unchanged(self) -> None:
        found = finding(
            class_findings(compare_assessments(fx.snapshot(), fx.CT1, fx.CT2), defaults()),
            ClassFindingCode.PASS_RATE_MOVED,
        )
        assert found.measure.value == Decimal("0.00")
        assert found.direction is ChangeDirection.UNCHANGED
        assert found.detected is False

    def test_a_cohort_below_the_minimum_gets_the_number_but_no_verdict(self) -> None:
        """n = 2 is below min_group_n; the movement is real, the judgement is withheld."""
        snapshot = b.build_snapshot({"s1": (40, 80), "s2": (50, 90)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        found = finding(class_findings(comparison, defaults()), ClassFindingCode.CLASS_MEAN_MOVED)
        assert found.measure.value == Decimal("40.00")
        assert found.detected is None, "None, not False: too few students to judge"
        assert found.direction is None
        assert found.n == 2 and found.minimum_n == 5
        assert "no judgement is made" in found.explanation.narrative

    def test_an_uncomputable_movement_is_undetermined(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, b.ABSENT), "s2": (b.ABSENT, 70)})
        comparison = compare_assessments(snapshot, *snapshot.assessments[:2])
        found = finding(class_findings(comparison, defaults()), ClassFindingCode.CLASS_MEAN_MOVED)
        assert found.detected is None
        assert found.measure.value is None
        assert "cannot be assessed" in found.explanation.narrative

    def test_the_threshold_is_configurable(self) -> None:
        strict = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"), offering_overrides={"cohort_shift_pp": "15"}
        )
        comparison = compare_assessments(fx.snapshot(), fx.CT2, fx.FT1)
        code = ClassFindingCode.CLASS_MEAN_MOVED
        assert finding(class_findings(comparison, strict), code).detected is False
        assert finding(class_findings(comparison, defaults()), code).detected is True

    def test_participation_is_judged_over_the_whole_cohort_not_the_intersection(self) -> None:
        comparison = compare_assessments(fx.snapshot(), fx.CT1, fx.CT2)
        found = finding(
            class_findings(comparison, defaults()), ClassFindingCode.PARTICIPATION_MOVED
        )
        assert found.n == 6, "the CT2 completion denominator, not the intersection of 5"


class TestChangeGroups:
    def test_declines_name_their_students(self) -> None:
        groups = change_groups(fx.snapshot(), fx.CT2, fx.FT1, defaults())
        declined = [g for g in groups if "Declined" in g.label][0]
        assert [s.id for s in declined.students] == [fx.S2, fx.S3]
        assert declined.count == 2
        assert declined.direction is ChangeDirection.DOWN

    def test_every_count_equals_its_member_list(self) -> None:
        for groups in (
            change_groups(fx.snapshot(), fx.CT1, fx.CT2, defaults()),
            change_groups(fx.snapshot(), fx.CT2, fx.FT1, defaults()),
        ):
            for found in groups:
                assert found.count == len(found.students)

    def test_all_five_groups_are_always_present(self) -> None:
        groups = change_groups(fx.snapshot(), fx.CT1, fx.CT2, defaults())
        assert len(groups) == 5
        assert sum(g.count for g in groups) >= 0

    def test_crossing_the_pass_mark_is_measured_both_ways(self) -> None:
        snapshot = b.build_snapshot({"up": (30, 55), "down": (55, 30), "steady": (60, 62)})
        groups = change_groups(snapshot, *snapshot.assessments[:2], defaults())
        crossed_up = [g for g in groups if "Crossed up" in g.label][0]
        crossed_down = [g for g in groups if "Crossed below" in g.label][0]
        assert [s.register_no for s in crossed_up.students] == ["RA0001"]
        assert [s.register_no for s in crossed_down.students] == ["RA0002"]

    def test_landing_exactly_on_the_pass_mark_is_not_crossing_below(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 40)})
        groups = change_groups(snapshot, *snapshot.assessments[:2], defaults())
        assert [g.count for g in groups if "Crossed below" in g.label] == [0]

    def test_improvement_uses_the_configured_margin(self) -> None:
        snapshot = b.build_snapshot({"big": (40, 50), "exact": (40, 45), "small": (40, 44)})
        groups = change_groups(snapshot, *snapshot.assessments[:2], defaults())
        improved = [g for g in groups if "Improved" in g.label][0]
        assert [s.register_no for s in improved.students] == ["RA0001", "RA0002"], (
            "exactly 5 pp qualifies; 4 pp does not"
        )

    def test_newly_sharp_decline_excludes_a_student_who_already_qualified(self) -> None:
        """S2 fell 80 -> 60 at CT2, already a sharp decline; only S3's is new at FT1."""
        groups = change_groups(fx.snapshot(), fx.CT2, fx.FT1, defaults())
        newly = [g for g in groups if "Newly" in g.label][0]
        assert [s.id for s in newly.students] == [fx.S3]

    def test_a_student_whose_earlier_series_was_too_short_counts_as_new(self) -> None:
        snapshot = b.build_snapshot({"s1": (80, 90, 40)})
        groups = change_groups(
            snapshot, snapshot.assessments[1], snapshot.assessments[2], defaults()
        )
        newly = [g for g in groups if "Newly" in g.label][0]
        assert newly.count == 1


class TestChangeAnalysis:
    def test_the_latest_assessment_is_analysed_by_default(self) -> None:
        analysis = change_analysis(fx.snapshot(), defaults())
        assert analysis.to_assessment.code == "FT1"
        assert analysis.from_assessment is not None
        assert analysis.from_assessment.code == "CT2"
        assert analysis.intersection_n == 5
        assert analysis.class_mean_change.value == Decimal("-10.20")

    def test_the_top_level_change_is_the_comparison_s_own_measure(self) -> None:
        """Not a second calculation: the same object, enforced by the contract."""
        analysis = change_analysis(fx.snapshot(), defaults())
        assert analysis.comparison is not None
        assert analysis.class_mean_change is analysis.comparison.mean_change
        assert analysis.pass_percent_change is analysis.comparison.pass_percent_change

    def test_the_unpublished_assessment_is_never_the_subject(self) -> None:
        assert latest_published(fx.snapshot()).code == "FT1"
        assert preceding_published(fx.snapshot(), fx.FT1).code == "CT2"

    def test_the_first_assessment_changed_nothing_because_there_was_nothing_before(
        self,
    ) -> None:
        snapshot = b.build_snapshot({"s1": (60,), "s2": (70,)})
        analysis = change_analysis(snapshot, defaults())
        assert analysis.from_assessment is None
        assert analysis.class_mean_change.status is MeasureStatus.INSUFFICIENT_DATA
        assert analysis.groups == ()
        assert analysis.comparison is None
        assert analysis.findings == ()
        assert "first published assessment" in analysis.class_mean_change.reason

    def test_an_offering_with_no_published_assessment_is_refused(self) -> None:
        snapshot = b.build_snapshot({"s1": (60,)}, unpublished=("CT1",))
        with pytest.raises(ValueError, match="no published assessment"):
            change_analysis(snapshot, defaults())

    def test_attention_is_not_pretended_to_have_been_evaluated(self) -> None:
        analysis = change_analysis(fx.snapshot(), defaults(), evaluate_attention=False)
        assert analysis.new_flags == ()
        assert "not evaluated" in analysis.explanation.narrative

    def test_newly_raised_flags_are_reported_when_attention_is_evaluated(self) -> None:
        """CT2 -> FT1: S3 newly declines (R4, R5) and S5 reaches a run of three (R3).

        S2 is not here: it already held R4 and R5 at CT2, so nothing of theirs is new.
        """
        analysis = change_analysis(fx.snapshot(), defaults())
        assert [f.rule_code.value for f in analysis.new_flags] == [
            "R4_SHARP_DECLINE",
            "R5_DECLINING_TREND",
            "R3_REPEATED_LOW",
        ]
        assert {f.student_id for f in analysis.new_flags} == {fx.S3, fx.S5}
        assert "Newly raised since the previous assessment: 3 flags" in (
            analysis.explanation.narrative
        )

    def test_a_flag_that_already_held_is_not_new(self) -> None:
        analysis = change_analysis(fx.snapshot(), defaults())
        assert fx.S2 not in {f.student_id for f in analysis.new_flags}

    def test_the_first_assessment_raises_nothing_new(self) -> None:
        """A flag needs an earlier state to be new against."""
        snapshot = b.build_snapshot({"s1": (20,), "s2": (30,)})
        analysis = change_analysis(snapshot, defaults())
        assert analysis.new_flags == ()

    def test_the_narrative_reports_the_movements_and_the_movers(self) -> None:
        narrative = change_analysis(fx.snapshot(), defaults()).explanation.narrative
        assert "class_mean_moved (down)" in narrative
        assert "declined by at least 5 pp — 2" in narrative

    def test_a_specific_assessment_may_be_analysed(self) -> None:
        analysis = change_analysis(fx.snapshot(), defaults(), to_assessment=fx.CT2)
        assert analysis.from_assessment is not None
        assert analysis.from_assessment.code == "CT1"
        assert analysis.class_mean_change.value == Decimal("-4.00")

    def test_the_difficulty_caveat_is_mandatory(self) -> None:
        assert DIFFICULTY_CAVEAT in change_analysis(fx.snapshot(), defaults()).explanation.caveats


class TestConsecutiveComparisons:
    def test_every_adjacent_pair_is_compared_in_order(self) -> None:
        comparisons = consecutive_comparisons(fx.snapshot())
        assert [(c.from_assessment.code, c.to_assessment.code) for c in comparisons] == [
            ("CT1", "CT2"),
            ("CT2", "FT1"),
        ]
        assert [c.mean_change.value for c in comparisons] == [
            Decimal("-4.00"),
            Decimal("-10.20"),
        ]

    def test_a_single_assessment_has_nothing_to_compare(self) -> None:
        assert consecutive_comparisons(b.build_snapshot({"s1": (60,)})) == ()

    def test_an_empty_offering_has_nothing_to_compare(self) -> None:
        assert consecutive_comparisons(b.empty_offering()) == ()

    def test_the_results_are_not_ranked(self) -> None:
        """Chronological order, so nobody reads a league table into it."""
        comparisons = consecutive_comparisons(fx.snapshot())
        assert [c.from_assessment.sequence_no for c in comparisons] == [1, 2]
