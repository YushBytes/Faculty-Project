"""F19: the offering's KPIs, and the two means that must never be confused.

Hand-computed from `canonical.py` (pass 40, 7 active students, 3 published assessments):

    weighted course scores  93.00, 55.00, 69.50, 41.00, 33.00, 60.00, 50.00  (sum 401.50)
    class mean              401.50 / 7 = 57.36
    median                  33, 41, 50, 55, 60, 69.5, 93 -> 55.00
    pass %                  6 of 7 at or above 40 -> 85.71
    matrix                  7 students x 3 assessments = 21 cells
                            17 assessed, 1 absent, 1 exempt, 2 no row
    completion              17 / (21 - 1 exempt) = 17/20 = 85.00

The latest assessment, FT1, has a mean of 53.50 over its own 6 assessed students. That is a
different number answering a different question, and `latest_assessment` is where it lives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.class_health import (
    class_health,
    cohort_course_scores,
    matrix_coverage,
)
from app.modules.analytics.core.outputs import ClassHealth, DataCoverage
from app.modules.analytics.core.profile import cohort_profiles
from app.modules.analytics.core.results import MeasureStatus
from app.modules.analytics.core.rules import FlagSeverity
from app.modules.analytics.core.statistics import assessment_analytics
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import ClassFindingCode, SegmentLabel
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def health(snapshot: object | None = None) -> ClassHealth:
    used = snapshot or fx.snapshot()
    return class_health(used, resolve_thresholds(pass_mark_percent=used.pass_mark_percent))  # type: ignore[arg-type]


class TestCanonicalKpis:
    def test_the_headline_numbers(self) -> None:
        built = health()
        assert built.cohort_n == 7
        assert built.published_assessments == 3
        assert built.class_mean.value == Decimal("57.36")
        assert built.median.value == Decimal("55.00")
        assert built.pass_percent.value == Decimal("85.71")
        assert built.completion_percent.value == Decimal("85.00")

    def test_the_class_mean_is_the_mean_of_course_scores(self) -> None:
        """401.50 / 7, stated as the arithmetic so the expectation is reviewable."""
        scores = [s for _, s in cohort_course_scores(cohort_profiles(fx.snapshot(), defaults()))]
        assert sum(scores) == Decimal("401.50")
        assert len(scores) == 7
        assert health().class_mean.value == Decimal("57.36")

    def test_the_class_mean_is_not_the_latest_assessments_mean(self) -> None:
        """The distinction D-2 settled: two questions, two numbers, both available."""
        built = health()
        assert built.latest_assessment is not None
        assert built.latest_assessment.assessment.code == "FT1"
        assert built.latest_assessment.mean.value == Decimal("53.50")
        assert built.class_mean.value == Decimal("57.36")
        assert built.class_mean.value != built.latest_assessment.mean.value

    def test_the_kpis_are_the_phase_2_functions_over_the_course_scores(self) -> None:
        from app.modules.analytics.core.statistics import mean_percent, pass_percent

        scores = [s for _, s in cohort_course_scores(cohort_profiles(fx.snapshot(), defaults()))]
        built = health()
        assert built.class_mean == mean_percent(scores)
        assert built.pass_percent == pass_percent(scores, Decimal("40.00"))

    def test_the_pass_rate_is_over_course_scores_not_the_latest_paper(self) -> None:
        built = health()
        assert built.pass_percent.value == Decimal("85.71"), "6 of 7 course scores reach 40"
        assert built.latest_assessment is not None
        assert built.latest_assessment.pass_percent.value == Decimal("83.33"), "5 of 6 in FT1"


class TestMatrixCoverage:
    def test_completion_is_over_cells_not_students(self) -> None:
        coverage = matrix_coverage(fx.snapshot())
        assert coverage.considered == 21, "7 students x 3 published assessments"
        assert (coverage.assessed, coverage.absent, coverage.exempt, coverage.missing) == (
            17,
            1,
            1,
            2,
        )
        assert coverage.completion_denominator == 20, "the exempt sitting is not required"

    def test_the_unpublished_assessment_is_not_a_required_sitting(self) -> None:
        coverage = matrix_coverage(fx.snapshot())
        assert coverage.considered == 21
        every = matrix_coverage(fx.snapshot(), published_only=False)
        assert every.considered == 28, "the quiz adds a fourth column"

    def test_inactive_students_are_not_in_the_matrix(self) -> None:
        assert matrix_coverage(fx.snapshot()).considered == 21
        assert matrix_coverage(fx.snapshot(), active_only=False).considered == 24

    def test_a_cohort_that_sat_nothing_is_not_zero_percent_complete_by_accident(self) -> None:
        snapshot = b.build_snapshot({"s1": (b.ABSENT,), "s2": (b.MISSING,)})
        built = health(snapshot)
        assert built.completion_percent.value == Decimal("0.00"), "0 of 2 required sittings"
        assert built.class_mean.status is MeasureStatus.INSUFFICIENT_DATA


class TestCourseScoreCoverage:
    def test_students_without_a_course_score_are_counted_not_dropped(self) -> None:
        snapshot = b.missing_results()
        built = health(snapshot)
        assert built.cohort_n == 4
        assert built.class_mean.n == 3, "s3 has no completed assessment"
        assert built.course_score_distribution is not None
        assert built.course_score_distribution.n == 3
        assert built.course_score_distribution.coverage.missing == 1

    def test_the_distribution_bins_the_course_scores(self) -> None:
        built = health()
        assert built.course_score_distribution is not None
        counts = {b_.lower: b_.count for b_ in built.course_score_distribution.bins if b_.count}
        assert counts == {30: 1, 40: 1, 50: 2, 60: 2, 90: 1}
        assert sum(counts.values()) == 7


class TestSegmentsAndAttention:
    def test_segment_counts_are_present_and_primary_only(self) -> None:
        built = health()
        assert {k.value: v for k, v in built.segment_counts.items()} == {
            "persistently_low": 3,
            "declining": 2,
            "high_performer": 1,
        }

    def test_unsegmented_students_leave_a_visible_gap(self) -> None:
        built = health()
        assert sum(built.segment_counts.values()) == 6
        assert built.cohort_n == 7
        assert "1 student could not be segmented" in built.explanation.narrative

    def test_attention_is_reported_as_not_evaluated_rather_than_as_none_needed(self) -> None:
        """D-1: "we did not look" is not "we looked and found nobody"."""
        built = health()
        assert built.students_requiring_attention is None
        assert built.flag_counts == {}
        assert "not evaluated" in built.explanation.narrative
        assert "not a finding that none do" in built.explanation.narrative

    def test_flag_counts_cannot_be_reported_without_evaluating_attention(self) -> None:
        fields = health().model_dump()
        with pytest.raises(ValidationError, match="without evaluating attention"):
            ClassHealth(**{**fields, "flag_counts": {FlagSeverity.HIGH: 2}})

    def test_segment_counts_cannot_exceed_the_cohort(self) -> None:
        fields = health().model_dump()
        with pytest.raises(ValidationError, match="each student has exactly one primary"):
            ClassHealth(**{**fields, "segment_counts": {SegmentLabel.STABLE: 99}})


class TestLatestComparison:
    def test_the_latest_comparison_is_carried_with_its_findings(self) -> None:
        built = health()
        assert built.latest_comparison is not None
        assert built.latest_comparison.from_assessment.code == "CT2"
        assert built.latest_comparison.to_assessment.code == "FT1"
        assert built.latest_comparison.mean_change.value == Decimal("-10.20")
        assert [f.code for f in built.findings] == list(ClassFindingCode)

    def test_a_material_movement_reaches_the_narrative(self) -> None:
        assert "class_mean_moved" in health().explanation.narrative

    def test_a_single_assessment_offering_has_no_comparison(self) -> None:
        built = health(b.build_snapshot({"s1": (60,), "s2": (70,)}))
        assert built.latest_comparison is None
        assert built.findings == ()
        assert built.latest_assessment is not None

    def test_an_offering_with_no_assessments_has_no_latest(self) -> None:
        built = health(b.build_snapshot({"s1": ()}))
        assert built.latest_assessment is None
        assert built.latest_comparison is None


class TestSmallAndEmptyCohorts:
    def test_an_empty_offering_computes_nothing_and_raises_nothing(self) -> None:
        built = health(b.empty_offering())
        assert built.cohort_n == 0
        assert built.published_assessments == 0
        assert built.class_mean.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.completion_percent.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.segment_counts == {}
        assert "No student in this offering has a completed assessment" in (
            built.explanation.narrative
        )

    def test_a_cohort_below_the_minimum_gets_its_numbers_and_a_stated_caveat(self) -> None:
        """n = 3 is below min_group_n: the mean is real, the judgement is withheld."""
        built = health(b.small_class())
        assert built.cohort_n == 3
        assert built.class_mean.value == Decimal("60.00")
        assert "below the minimum of 5 for a cohort-level judgement" in (
            built.explanation.narrative
        )

    def test_a_single_student_offering(self) -> None:
        built = health(b.single_student())
        assert built.cohort_n == 1
        assert built.class_mean.value == Decimal("74.00"), "(70 + 74 + 78) / 3"
        assert built.class_mean.n == 1


class TestExplainability:
    def test_the_narrative_quotes_the_numbers_and_their_denominators(self) -> None:
        narrative = health().explanation.narrative
        assert "57.36%" in narrative
        assert "85.71%" in narrative
        assert "85.00% of the 20 assessment sittings" in narrative
        assert "40.00% pass mark" in narrative

    def test_the_evidence_separates_cohort_from_scored(self) -> None:
        evidence = {item.name: item.value for item in health().explanation.evidence}
        assert evidence["Cohort"] == "7"
        assert evidence["With a course score"] == "7"
        assert evidence["Assessed sittings"] == "17"
        assert evidence["Exempt sittings"] == "1"

    def test_students_without_a_score_are_explained_not_hidden(self) -> None:
        narrative = health(b.missing_results()).explanation.narrative
        assert "no completed assessment" in narrative
        assert "not as zeroes" in narrative

    def test_the_thresholds_that_shaped_the_segments_travel_with_the_header(self) -> None:
        keys = {t.key for t in health().explanation.thresholds}
        assert keys == {
            ThresholdKey.MIN_GROUP_N,
            ThresholdKey.LOW_PERFORMANCE_PERCENT,
            ThresholdKey.HIGH_PERFORMANCE_PERCENT,
        }


class TestDeterminism:
    def test_two_builds_of_the_same_snapshot_agree(self) -> None:
        from datetime import UTC, datetime

        stamp = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
        first = class_health(fx.snapshot(), defaults(), generated_at=stamp)
        second = class_health(fx.snapshot(), defaults(), generated_at=stamp)
        assert first.model_dump() == second.model_dump()

    def test_a_different_pass_mark_changes_the_answer(self) -> None:
        strict = class_health(
            fx.snapshot(pass_mark=Decimal("60")),
            resolve_thresholds(pass_mark_percent=Decimal("60")),
        )
        assert strict.pass_percent.value == Decimal("42.86"), "3 of 7 course scores reach 60"
        assert health().pass_percent.value == Decimal("85.71")

    def test_coverage_is_the_matrix_coverage(self) -> None:
        built = health()
        assert built.coverage == matrix_coverage(fx.snapshot())
        assert isinstance(built.coverage, DataCoverage)


class TestAssessmentAnalyticsStillOwnsItsOwnNumbers:
    def test_the_latest_assessment_block_is_the_phase_2_contract(self) -> None:
        built = health()
        assert built.latest_assessment is not None
        direct = assessment_analytics(
            fx.snapshot(), fx.FT1, generated_at=built.latest_assessment.generated_at
        )
        assert built.latest_assessment.model_dump() == direct.model_dump()
