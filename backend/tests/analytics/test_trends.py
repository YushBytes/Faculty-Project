"""F9: trend classification, including every way it must refuse to classify.

The rule being defended: a direction of travel is a claim about a student, and this system
makes it only when the series supports it. One assessment is never "stable" and never
"declining" — it is not enough information, and the output says so.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.outputs import DIFFICULTY_CAVEAT
from app.modules.analytics.core.policy import build_student_series
from app.modules.analytics.core.results import MeasureStatus
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.trends import (
    classify_slope,
    least_squares_slope,
    student_trend,
    trend_for,
    trend_slope,
)
from app.modules.analytics.core.vocabulary import TrendLabel, TrendMethod
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def dec(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


class TestSlope:
    def test_a_perfectly_linear_series_has_its_own_slope(self) -> None:
        assert least_squares_slope(dec("40", "50", "60")) == Decimal("10")
        assert least_squares_slope(dec("80", "70", "60")) == Decimal("-10")

    def test_a_flat_series_has_no_slope(self) -> None:
        assert least_squares_slope(dec("60", "60", "60", "60")) == Decimal("0")

    def test_the_least_squares_fit_is_not_just_the_endpoints(self) -> None:
        """90, 88, 50: endpoints would say -20 per step; the fit says -20 too, via the mean.

        Worked by hand: mean 76, index mean 2,
        numerator = (-1)(14) + (0)(12) + (1)(-26) = -40, denominator = 2, slope = -20.
        """
        assert least_squares_slope(dec("90", "88", "50")) == Decimal("-20")

    def test_a_dip_in_the_middle_does_not_swing_the_fit(self) -> None:
        """60, 20, 60: the line through them is flat, which is the point of a fit."""
        assert least_squares_slope(dec("60", "20", "60")) == Decimal("0")

    def test_two_points_use_the_plain_difference(self) -> None:
        slope, method = trend_slope(dec("30", "70"))
        assert slope == Decimal("40")
        assert method is TrendMethod.TWO_POINT_DELTA

    def test_three_points_use_the_fit(self) -> None:
        _, method = trend_slope(dec("30", "50", "70"))
        assert method is TrendMethod.LEAST_SQUARES

    def test_one_point_has_no_slope_at_all(self) -> None:
        with pytest.raises(ValueError, match="at least two completed"):
            trend_slope(dec("50"))


class TestClassification:
    @pytest.mark.parametrize(
        ("slope", "expected"),
        [
            ("10", TrendLabel.IMPROVING),
            ("5", TrendLabel.IMPROVING),
            ("4.99", TrendLabel.STABLE),
            ("0", TrendLabel.STABLE),
            ("-4.99", TrendLabel.STABLE),
            ("-5", TrendLabel.DECLINING),
            ("-10", TrendLabel.DECLINING),
        ],
    )
    def test_the_threshold_is_inclusive_on_both_sides(
        self, slope: str, expected: TrendLabel
    ) -> None:
        """A slope exactly on the threshold is classified, not shrugged at."""
        assert classify_slope(Decimal(slope), Decimal("5")) is expected

    def test_a_configured_threshold_changes_the_answer(self) -> None:
        assert classify_slope(Decimal("6"), Decimal("5")) is TrendLabel.IMPROVING
        assert classify_slope(Decimal("6"), Decimal("8")) is TrendLabel.STABLE


class TestCanonicalTrends:
    """Hand-computed slopes for the canonical cohort (threshold 5 pp per assessment).

    S1 90, 92, 95 -> +2.50   Stable      (rising, but not by enough to say so)
    S2 80, 60, 40 -> -20.00  Declining
    S3 90, 88, 50 -> -20.00  Declining
    S4 42, 40, 41 -> -0.50   Stable
    S5 30, 32, 35 -> +2.50   Stable
    S6 60         -> insufficient (1 completed assessment)
    S7 50         -> insufficient (1 completed assessment)
    """

    @pytest.mark.parametrize(
        ("student", "slope", "expected"),
        [
            (fx.S1, "2.50", TrendLabel.STABLE),
            (fx.S2, "-20.00", TrendLabel.DECLINING),
            (fx.S3, "-20.00", TrendLabel.DECLINING),
            (fx.S4, "-0.50", TrendLabel.STABLE),
            (fx.S5, "2.50", TrendLabel.STABLE),
        ],
        ids=["S1", "S2", "S3", "S4", "S5"],
    )
    def test_slope_and_label(self, student: object, slope: str, expected: TrendLabel) -> None:
        trend = trend_for(fx.snapshot(), student, defaults())  # type: ignore[arg-type]
        assert trend.slope.value == Decimal(slope)
        assert trend.label.value == expected.value
        assert trend.method is TrendMethod.LEAST_SQUARES
        assert trend.slope.n == 3

    def test_a_rising_series_below_the_threshold_is_stable_not_improving(self) -> None:
        """S1 gained 5 points across the whole course; that is not an improving trend."""
        trend = trend_for(fx.snapshot(), fx.S1, defaults())
        assert trend.label.value == "stable"
        assert trend.percentages_used == (Decimal("90.00"), Decimal("92.00"), Decimal("95.00"))

    @pytest.mark.parametrize("student", [fx.S6, fx.S7], ids=["S6", "S7"])
    def test_a_single_assessment_is_never_a_trend(self, student: object) -> None:
        trend = trend_for(fx.snapshot(), student, defaults())  # type: ignore[arg-type]
        assert trend.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert trend.label.value is None
        assert trend.slope.value is None
        assert trend.method is None
        assert trend.label.reason == "only 1 completed assessment available (minimum 2)"

    def test_an_absence_does_not_break_the_series(self) -> None:
        """S6 was absent then exempt; the series is what remains, not a run of zeroes."""
        trend = trend_for(fx.snapshot(), fx.S6, defaults())
        assert trend.percentages_used == (Decimal("60.00"),)
        assert trend.points_used == ("FT1",)

    def test_the_threshold_and_its_source_travel_with_the_answer(self) -> None:
        trend = trend_for(fx.snapshot(), fx.S2, defaults())
        assert trend.threshold.key is ThresholdKey.TREND_DELTA_PP
        assert trend.threshold.value == Decimal("5")
        assert trend.explanation.thresholds == (trend.threshold,)

    def test_a_looser_threshold_reclassifies_the_same_series(self) -> None:
        """S2's -20 slope is Declining at 5 pp, Stable at 25 pp — configuration, not code."""
        loose = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"), offering_overrides={"trend_delta_pp": "25"}
        )
        assert trend_for(fx.snapshot(), fx.S2, loose).label.value == "stable"

    def test_the_difficulty_caveat_is_always_present(self) -> None:
        for student in (fx.S1, fx.S7):
            trend = trend_for(fx.snapshot(), student, defaults())
            assert DIFFICULTY_CAVEAT in trend.explanation.caveats

    def test_the_explanation_quotes_the_series_and_the_method(self) -> None:
        trend = trend_for(fx.snapshot(), fx.S2, defaults())
        assert "CT1 80.00%, CT2 60.00%, FT1 40.00%" in trend.explanation.narrative
        assert "-20.00 pp per assessment" in trend.explanation.narrative
        evidence = {item.name: item.value for item in trend.explanation.evidence}
        assert evidence["Method"] == "least_squares"


class TestScenarioTrends:
    @pytest.mark.parametrize(
        ("key", "slope", "expected"),
        [
            ("s1", "10.00", TrendLabel.IMPROVING),
            ("s2", "5.00", TrendLabel.IMPROVING),
            ("s3", "2.00", TrendLabel.STABLE),
        ],
        ids=["clear", "on-the-threshold", "below-the-threshold"],
    )
    def test_improving_students(self, key: str, slope: str, expected: TrendLabel) -> None:
        trend = trend_for(b.improving_students(), b.student_id(key), defaults())
        assert trend.slope.value == Decimal(slope)
        assert trend.label.value == expected.value

    @pytest.mark.parametrize(
        ("key", "slope", "expected"),
        [
            ("s1", "-10.00", TrendLabel.DECLINING),
            ("s2", "-5.00", TrendLabel.DECLINING),
            ("s3", "-2.00", TrendLabel.STABLE),
            ("s4", "-20.00", TrendLabel.DECLINING),
        ],
        ids=["clear", "on-the-threshold", "below-the-threshold", "cliff"],
    )
    def test_declining_students(self, key: str, slope: str, expected: TrendLabel) -> None:
        trend = trend_for(b.declining_students(), b.student_id(key), defaults())
        assert trend.slope.value == Decimal(slope)
        assert trend.label.value == expected.value

    def test_a_two_point_series_says_so(self) -> None:
        trend = trend_for(b.improving_students(), b.student_id("s4"), defaults())
        assert trend.method is TrendMethod.TWO_POINT_DELTA
        assert trend.slope.value == Decimal("40.00")
        assert "Difference between the two completed assessments" in trend.explanation.narrative

    def test_a_flat_series_is_stable_with_a_zero_slope(self) -> None:
        trend = trend_for(b.volatile_students(), b.student_id("s2"), defaults())
        assert trend.slope.value == Decimal("0.00")
        assert trend.label.value == "stable"

    def test_a_volatile_series_still_gets_a_trend_and_it_can_mislead(self) -> None:
        """90, 30, 85, 35 fits a slope of -11.00 and so reads as Declining.

        Worked by hand: mean 60, index mean 2.5,
        numerator = (-1.5)(30) + (-0.5)(-30) + (0.5)(25) + (1.5)(-25) = -55, denominator = 5.

        The label is arithmetically right and substantively thin: this student is not on a
        downward path, they are all over the place. That is exactly why consistency (F13) is
        reported beside the trend rather than instead of it — see
        ``test_student.py::TestConsistency``.
        """
        trend = trend_for(b.volatile_students(), b.student_id("s1"), defaults())
        assert trend.slope.value == Decimal("-11.00")
        assert trend.label.value == "declining"

    def test_a_student_with_no_results_at_all_has_no_trend(self) -> None:
        trend = trend_for(b.missing_results(), b.student_id("s3"), defaults())
        assert trend.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert trend.percentages_used == ()
        assert trend.label.reason == "only 0 completed assessments available (minimum 2)"

    def test_the_series_may_be_passed_directly(self) -> None:
        """The contract is the series, not the snapshot: no database is ever involved."""
        snapshot = b.declining_students()
        series = build_student_series(snapshot, b.student_id("s1"))
        assert student_trend(series, defaults()).slope.value == Decimal("-10.00")
