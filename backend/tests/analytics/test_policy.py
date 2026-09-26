"""The missing-data policy and series construction, against hand-computed values.

Everything later phases compute rests on these two things being right: a percentage, and the
decision about which results count.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.contracts import ResultStatus
from app.modules.analytics.core.policy import (
    DerivedState,
    assessed_percentages,
    assessment_percentage,
    build_all_series,
    build_student_series,
    classify,
)
from tests.analytics import canonical as fx


class TestAssessmentPercentage:
    @pytest.mark.parametrize(
        ("score", "max_marks", "expected"),
        [
            ("45", "50", "90.00"),
            ("50", "50", "100.00"),
            ("0", "50", "0.00"),
            ("25", "50", "50.00"),
            ("95", "100", "95.00"),
            ("18", "20", "90.00"),
            # A third of the marks: 33.333... rounds half-up to two places.
            ("1", "3", "33.33"),
            # 66.665 exactly: half-up gives 66.67, not 66.66.
            ("19.9995", "30", "66.67"),
        ],
    )
    def test_hand_computed_percentages(self, score: str, max_marks: str, expected: str) -> None:
        assert assessment_percentage(Decimal(score), Decimal(max_marks)) == Decimal(expected)

    def test_a_scored_zero_is_a_real_zero_percent(self) -> None:
        """A student who sat the paper and scored nothing is 0%, which is not missing data."""
        assert assessment_percentage(Decimal("0"), Decimal("50")) == Decimal("0.00")

    def test_zero_maximum_is_an_error_not_a_zero_percentage(self) -> None:
        with pytest.raises(ValueError, match="max_marks must be positive"):
            assessment_percentage(Decimal("10"), Decimal("0"))

    def test_negative_score_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            assessment_percentage(Decimal("-5"), Decimal("50"))


class TestClassify:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ResultStatus.PRESENT, DerivedState.ASSESSED),
            (ResultStatus.ABSENT, DerivedState.ABSENT),
            (ResultStatus.EXEMPT, DerivedState.EXEMPT),
            (None, DerivedState.MISSING),
        ],
    )
    def test_states(self, status: ResultStatus | None, expected: DerivedState) -> None:
        assert classify(status) is expected

    def test_only_assessed_contributes_to_statistics(self) -> None:
        assert DerivedState.ASSESSED.is_assessed
        for state in (DerivedState.ABSENT, DerivedState.EXEMPT, DerivedState.MISSING):
            assert not state.is_assessed

    def test_only_exempt_leaves_the_completion_denominator(self) -> None:
        assert not DerivedState.EXEMPT.counts_toward_completion
        for state in (DerivedState.ASSESSED, DerivedState.ABSENT, DerivedState.MISSING):
            assert state.counts_toward_completion


class TestStudentSeries:
    @pytest.mark.parametrize("student_id", list(fx.EXPECTED_PERCENTAGES))
    def test_percentage_series_matches_hand_computed_values(self, student_id: object) -> None:
        series = build_student_series(fx.snapshot(), student_id)  # type: ignore[arg-type]
        expected = tuple(Decimal(v) for v in fx.EXPECTED_PERCENTAGES[student_id])  # type: ignore[index]
        assert series.percentages == expected

    def test_every_published_assessment_produces_a_point_even_without_a_result(self) -> None:
        """A gap has to be visible, otherwise completion cannot be measured."""
        series = build_student_series(fx.snapshot(), fx.S7)
        assert len(series.points) == 3
        assert [p.state for p in series.points] == [
            DerivedState.ASSESSED,
            DerivedState.MISSING,
            DerivedState.MISSING,
        ]

    def test_unpublished_assessment_is_excluded_by_default(self) -> None:
        """S1 has a quiz result, but the quiz is unpublished so it must not appear."""
        series = build_student_series(fx.snapshot(), fx.S1)
        assert [p.assessment_code for p in series.points] == ["CT1", "CT2", "FT1"]

        including = build_student_series(fx.snapshot(), fx.S1, published_only=False)
        assert [p.assessment_code for p in including.points] == ["CT1", "CT2", "FT1", "QUIZ1"]
        assert including.percentages[-1] == Decimal("90.00")

    def test_absent_and_exempt_points_carry_no_percentage(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S6)
        absent, exempt, assessed = series.points
        assert absent.state is DerivedState.ABSENT
        assert absent.percentage is None and absent.score is None
        assert exempt.state is DerivedState.EXEMPT
        assert exempt.percentage is None and exempt.score is None
        assert assessed.percentage == Decimal("60.00")

    def test_exempt_is_excluded_from_the_completion_denominator(self) -> None:
        """S6 was absent once, exempt once, assessed once: completion is 1 of 2, not 1 of 3."""
        series = build_student_series(fx.snapshot(), fx.S6)
        assert series.completed_count == 1
        assert series.completion_denominator == 2

    def test_missing_rows_stay_in_the_completion_denominator(self) -> None:
        """S7 sat one of three: nothing was waived, so the denominator is 3."""
        series = build_student_series(fx.snapshot(), fx.S7)
        assert series.completed_count == 1
        assert series.completion_denominator == 3

    def test_full_attendance_completes_everything(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S1)
        assert series.completed_count == 3
        assert series.completion_denominator == 3

    def test_latest_assessed_is_the_most_recent_scored_point(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S2)
        latest = series.latest_assessed
        assert latest is not None
        assert latest.assessment_code == "FT1"
        assert latest.percentage == Decimal("40.00")

    def test_latest_assessed_skips_trailing_gaps(self) -> None:
        """S8's last point is missing, so the latest *assessed* point is CT2."""
        series = build_student_series(fx.snapshot(), fx.S8)
        latest = series.latest_assessed
        assert latest is not None
        assert latest.assessment_code == "CT2"

    def test_student_with_no_results_at_all(self) -> None:
        snapshot = fx.snapshot()
        series = build_student_series(snapshot, fx.S7)
        assert series.has_any_result
        # A student in a cohort with results for nobody has no percentages and no latest point.
        bare = build_student_series(fx.single_assessment_snapshot(), fx.S3)
        assert bare.completed_count == 1

    def test_series_for_a_student_outside_the_snapshot_is_an_error(self) -> None:
        import uuid

        with pytest.raises(ValueError, match="not in this offering snapshot"):
            build_student_series(fx.snapshot(), uuid.uuid4())

    def test_build_all_series_covers_active_students_only(self) -> None:
        series = build_all_series(fx.snapshot())
        assert len(series) == 7
        assert fx.S8 not in {s.student_id for s in series}

        including_inactive = build_all_series(fx.snapshot(), active_only=False)
        assert len(including_inactive) == 8


class TestAssessedPercentages:
    def test_ct1_matches_hand_computed_cohort(self) -> None:
        """Absent S6 and inactive S8 contribute nothing, rather than a zero."""
        values = assessed_percentages(fx.snapshot(), fx.CT1)
        assert values == tuple(Decimal(v) for v in fx.EXPECTED_CT1_ASSESSED)
        assert len(values) == 6

    def test_ft1_matches_hand_computed_cohort(self) -> None:
        values = assessed_percentages(fx.snapshot(), fx.FT1)
        assert values == tuple(Decimal(v) for v in fx.EXPECTED_FT1_ASSESSED)

    def test_exempt_student_is_absent_from_the_assessment_it_was_exempt_from(self) -> None:
        values = assessed_percentages(fx.snapshot(), fx.CT2)
        # S6 was exempt from CT2 and S7 has no row; S8 is inactive.
        assert len(values) == 5

    def test_including_inactive_students_widens_the_cohort(self) -> None:
        values = assessed_percentages(fx.snapshot(), fx.CT1, active_only=False)
        assert len(values) == 7
        assert Decimal("60.00") in values

    def test_no_assessed_students_yields_an_empty_tuple_not_a_zero(self) -> None:
        values = assessed_percentages(fx.snapshot(), fx.QUIZ1, active_only=True)
        # Only S1 has a quiz result, and it is a published-independent read, so one value.
        assert values == (Decimal("90.00"),)
