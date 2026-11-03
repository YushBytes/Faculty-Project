"""Student performance intelligence: the composed answer, and what it refuses to say.

Two things are being checked throughout.

*The composition adds no arithmetic.* Every number in a profile must equal the Phase 2
measure it came from — asserted directly, so the day someone "simplifies" by recomputing a
mean here, the two disagree and a test says so.

*Thin data produces no verdict.* A condition that cannot be evaluated is ``detected=None``,
never ``False``, and never a label.

Canonical expectations (pass mark 40; the series are in `canonical.py`):

=====  ====================  =========  ==========  =========  ===================
who    percentages           previous   latest      change pp  prior mean / vs it
=====  ====================  =========  ==========  =========  ===================
S1     90, 92, 95            92         95          +3.00      91.00  /  +4.00
S2     80, 60, 40            60         40          -20.00     70.00  / -30.00
S3     90, 88, 50            88         50          -38.00     89.00  / -39.00
S4     42, 40, 41            40         41          +1.00      41.00  /   0.00
S5     30, 32, 35            32         35          +3.00      31.00  /  +4.00
S6     absent, exempt, 60    none       60          insuff.    insufficient
S7     50, then nothing      none       50          insuff.    insufficient
=====  ====================  =========  ==========  =========  ===================
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.outputs import StudentPerformanceProfile
from app.modules.analytics.core.policy import DerivedState, build_student_series
from app.modules.analytics.core.profile import (
    cohort_profiles,
    improvement_finding,
    repeated_low_finding,
    sharp_decline_finding,
    student_profile,
)
from app.modules.analytics.core.results import MeasureStatus, Unit
from app.modules.analytics.core.student import (
    consistency,
    decline_against_earlier_mean,
    latest_change,
    prior_average,
    volatility_range,
    weighted_course_score,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import StudentFindingCode
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def profile(student: object, snapshot: object | None = None) -> StudentPerformanceProfile:
    used = snapshot or fx.snapshot()
    thresholds = resolve_thresholds(pass_mark_percent=used.pass_mark_percent)
    return student_profile(used, student, thresholds)  # type: ignore[arg-type]


def series(student: object, snapshot: object | None = None):  # noqa: ANN201 - StudentSeries
    return build_student_series(snapshot or fx.snapshot(), student)  # type: ignore[arg-type]


class TestCompositionAddsNoArithmetic:
    """Phase 3 composes; Phase 2 computes. These must stay the same numbers."""

    @pytest.mark.parametrize(
        "student", [fx.S1, fx.S2, fx.S3, fx.S4, fx.S5, fx.S6, fx.S7], ids=lambda s: str(s)[-2:]
    )
    def test_every_measure_equals_its_phase_2_source(self, student: object) -> None:
        built = profile(student)
        student_series = series(student)
        thresholds = defaults()
        assert built.change_from_previous == latest_change(student_series)
        assert built.historical_average == prior_average(student_series, thresholds)
        assert built.change_from_historical_average == decline_against_earlier_mean(
            student_series, thresholds
        )
        assert built.history.weighted_course_score == weighted_course_score(student_series)
        assert built.history.consistency_std_dev == consistency(student_series, thresholds)
        assert built.history.volatility_range == volatility_range(student_series, thresholds)

    def test_the_trend_is_the_history_s_trend_not_a_second_one(self) -> None:
        built = profile(fx.S2)
        assert built.trend is built.history.trend

    def test_the_latest_performance_is_the_history_s_latest(self) -> None:
        built = profile(fx.S2)
        assert built.latest is not None and built.history.latest is not None
        assert built.latest.assessment.id == built.history.latest.assessment.id
        assert built.latest.percentage.value == built.history.latest.percentage.value


class TestHistoryAndOrdering:
    def test_the_history_is_in_sequence_order_with_its_gaps(self) -> None:
        built = profile(fx.S6)
        assert [p.assessment_code for p in built.history.points] == ["CT1", "CT2", "FT1"]
        assert [p.state for p in built.history.points] == [
            DerivedState.ABSENT,
            DerivedState.EXEMPT,
            DerivedState.ASSESSED,
        ]

    def test_each_point_carries_what_is_needed_to_read_it(self) -> None:
        point = profile(fx.S1).history.points[0]
        assert (point.assessment_code, point.sequence_no) == ("CT1", 1)
        assert (point.score, point.max_marks, point.percentage) == (
            Decimal("45.00"),
            Decimal("50.00"),
            Decimal("90.00"),
        )
        assert point.weightage == Decimal("1")

    def test_order_follows_sequence_no_not_the_order_rows_arrive_in(self) -> None:
        """The snapshot is built from an unordered result list; sequence_no decides."""
        snapshot = b.build_snapshot({"s1": (50, 60, 70)})
        shuffled = snapshot.model_copy(
            update={
                "assessments": tuple(reversed(snapshot.assessments)),
                "results": tuple(reversed(snapshot.results)),
            }
        )
        built = student_profile(shuffled, b.student_id("s1"), defaults())
        assert [p.assessment_code for p in built.history.points] == ["CT1", "CT2", "CT3"]
        assert built.latest is not None and built.latest.assessment.code == "CT3"
        assert built.change_from_previous.value == Decimal("10.00")

    def test_coverage_describes_the_series(self) -> None:
        built = profile(fx.S6)
        assert (built.history.coverage.assessed, built.history.coverage.absent) == (1, 1)
        assert built.history.coverage.exempt == 1
        assert built.history.coverage.completion_denominator == 2


class TestLatestAndPrevious:
    @pytest.mark.parametrize(
        ("student", "previous", "latest", "change"),
        [
            (fx.S1, "92.00", "95.00", "3.00"),
            (fx.S2, "60.00", "40.00", "-20.00"),
            (fx.S3, "88.00", "50.00", "-38.00"),
            (fx.S4, "40.00", "41.00", "1.00"),
            (fx.S5, "32.00", "35.00", "3.00"),
        ],
        ids=["S1", "S2", "S3", "S4", "S5"],
    )
    def test_the_pair_and_the_change(
        self, student: object, previous: str, latest: str, change: str
    ) -> None:
        built = profile(student)
        assert built.previous is not None and built.latest is not None
        assert built.previous.percentage.value == Decimal(previous)
        assert built.latest.percentage.value == Decimal(latest)
        assert built.change_from_previous.value == Decimal(change)

    def test_the_change_is_percentage_points_not_a_percentage_change(self) -> None:
        """40% to 44% is +4 pp. It is not "+10%", which is a different true statement."""
        snapshot = b.build_snapshot({"s1": (40, 44)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.change_from_previous.value == Decimal("4.00")
        assert built.change_from_previous.unit is Unit.PERCENTAGE_POINTS

    def test_previous_skips_an_absence(self) -> None:
        """ "Compared with last time" means the last time there was a performance."""
        snapshot = b.build_snapshot({"s1": (60, b.ABSENT, 75)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.previous is not None
        assert built.previous.assessment.code == "CT1"
        assert built.change_from_previous.value == Decimal("15.00")

    def test_one_assessment_gives_a_latest_and_no_previous(self) -> None:
        built = profile(fx.S7)
        assert built.latest is not None
        assert built.latest.percentage.value == Decimal("50.00")
        assert built.previous is None
        assert built.change_from_previous.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.change_from_previous.reason == (
            "only 1 completed assessment available (minimum 2)"
        )

    def test_no_completed_assessment_gives_neither(self) -> None:
        built = profile(b.student_id("s3"), b.missing_results())
        assert built.latest is None and built.previous is None
        assert built.change_from_previous.value is None


class TestHistoricalAverage:
    @pytest.mark.parametrize(
        ("student", "average", "against"),
        [
            (fx.S1, "91.00", "4.00"),
            (fx.S2, "70.00", "-30.00"),
            (fx.S3, "89.00", "-39.00"),
            (fx.S4, "41.00", "0.00"),
            (fx.S5, "31.00", "4.00"),
        ],
        ids=["S1", "S2", "S3", "S4", "S5"],
    )
    def test_prior_history_excludes_the_latest_result(
        self, student: object, average: str, against: str
    ) -> None:
        """The latest assessment is the thing being compared, not part of its own baseline."""
        built = profile(student)
        assert built.historical_average.value == Decimal(average)
        assert built.change_from_historical_average.value == Decimal(against)

    def test_the_baseline_n_is_the_earlier_assessments_only(self) -> None:
        built = profile(fx.S3)
        assert built.historical_average.n == 2, "CT1 and CT2, not FT1"

    def test_including_the_latest_would_give_a_different_number(self) -> None:
        """S3: prior mean 89.00; the mean of all three is 76.00. The spec says prior."""
        built = profile(fx.S3)
        assert built.historical_average.value == Decimal("89.00")
        assert built.history.weighted_course_score.value == Decimal("69.50")

    def test_one_assessment_has_no_prior_history(self) -> None:
        built = profile(fx.S7)
        assert built.historical_average.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.change_from_historical_average.value is None


class TestFindings:
    def finding(self, student: object, code: StudentFindingCode, snapshot: object | None = None):  # noqa: ANN201
        found = profile(student, snapshot).finding(code)
        assert found is not None
        return found

    @pytest.mark.parametrize(
        ("student", "detected", "drop"),
        [
            (fx.S3, True, "-39.00"),
            (fx.S2, True, "-30.00"),
            (fx.S1, False, "4.00"),
            (fx.S4, False, "0.00"),
        ],
        ids=["cliff", "steady-decline", "improving", "flat"],
    )
    def test_sharp_decline(self, student: object, detected: bool, drop: str) -> None:
        found = self.finding(student, StudentFindingCode.SHARP_DECLINE)
        assert found.detected is detected
        assert found.measure.value == Decimal(drop)
        assert found.threshold is not None
        assert found.threshold.key is ThresholdKey.DECLINE_DROP_PP

    def test_a_score_below_your_own_average_is_not_by_itself_a_sharp_decline(self) -> None:
        """S4 is 0.00 pp against their prior mean; S1 is +4. Neither is a decline."""
        snapshot = b.build_snapshot({"s1": (60, 62, 58)})
        found = self.finding(b.student_id("s1"), StudentFindingCode.SHARP_DECLINE, snapshot)
        assert found.measure.value == Decimal("-3.00")
        assert found.detected is False
        assert "does not reach the configured drop" in found.explanation.narrative

    def test_sharp_decline_cannot_be_judged_from_one_assessment(self) -> None:
        found = self.finding(fx.S7, StudentFindingCode.SHARP_DECLINE)
        assert found.detected is None, "None, not False: it is unknown, not absent"
        assert found.measure.status is MeasureStatus.INSUFFICIENT_DATA
        assert "cannot be assessed" in found.explanation.narrative

    @pytest.mark.parametrize(
        ("student", "detected", "run"),
        [(fx.S5, True, 3), (fx.S4, False, 0), (fx.S2, False, 0), (fx.S1, False, 0)],
        ids=["persistently-low", "borderline", "declining-but-passing", "high"],
    )
    def test_repeated_low(self, student: object, detected: bool, run: int) -> None:
        found = self.finding(student, StudentFindingCode.REPEATED_LOW)
        assert found.detected is detected
        assert found.measure.value == Decimal(run)
        assert found.pass_mark_percent == Decimal("40.00")

    def test_repeated_low_lists_the_assessments_in_the_run(self) -> None:
        found = self.finding(fx.S5, StudentFindingCode.REPEATED_LOW)
        assert found.explanation.assessments_used == ("CT1", "CT2", "FT1")
        assert "CT1 30.00%, CT2 32.00%, FT1 35.00%" in found.explanation.narrative

    def test_a_recovered_student_is_not_still_in_a_run(self) -> None:
        snapshot = b.build_snapshot({"s1": (30, 30, 30, 70)})
        found = self.finding(b.student_id("s1"), StudentFindingCode.REPEATED_LOW, snapshot)
        assert found.detected is False
        assert found.measure.value == Decimal(0)
        assert "Not currently below" in found.explanation.narrative

    def test_absent_and_exempt_are_not_low_scores(self) -> None:
        """They are not in the run, and they do not break it either."""
        snapshot = b.build_snapshot({"s1": (30, b.ABSENT, b.EXEMPT, 35)})
        found = self.finding(b.student_id("s1"), StudentFindingCode.REPEATED_LOW, snapshot)
        assert found.measure.value == Decimal(2)

    @pytest.mark.parametrize(
        ("key", "detected", "change"),
        [("s1", True, "10.00"), ("s2", True, "5.00"), ("s3", False, "2.00")],
        ids=["clear", "on-the-threshold", "below-the-threshold"],
    )
    def test_improvement(self, key: str, detected: bool, change: str) -> None:
        found = self.finding(
            b.student_id(key), StudentFindingCode.IMPROVEMENT, b.improving_students()
        )
        assert found.detected is detected
        assert found.measure.value == Decimal(change)
        assert found.threshold is not None
        assert found.threshold.key is ThresholdKey.IMPROVEMENT_DELTA_PP

    def test_improvement_is_about_one_student_not_a_ranking(self) -> None:
        """Two students both improve by enough; neither is compared with the other."""
        snapshot = b.build_snapshot({"s1": (40, 60), "s2": (70, 80)})
        for key in ("s1", "s2"):
            found = self.finding(b.student_id(key), StudentFindingCode.IMPROVEMENT, snapshot)
            assert found.detected is True

    def test_a_decline_is_not_an_improvement(self) -> None:
        found = self.finding(fx.S2, StudentFindingCode.IMPROVEMENT)
        assert found.detected is False
        assert found.measure.value == Decimal("-20.00")

    def test_improvement_needs_two_completed_assessments(self) -> None:
        found = self.finding(fx.S7, StudentFindingCode.IMPROVEMENT)
        assert found.detected is None

    def test_every_profile_carries_each_finding_exactly_once(self) -> None:
        codes = [f.code for f in profile(fx.S1).findings]
        assert codes == [
            StudentFindingCode.SHARP_DECLINE,
            StudentFindingCode.REPEATED_LOW,
            StudentFindingCode.IMPROVEMENT,
        ]

    def test_findings_can_be_built_from_a_series_alone(self) -> None:
        """No snapshot, no database: a finding is a function of the series."""
        student_series = series(fx.S3)
        assert sharp_decline_finding(student_series, defaults()).detected is True
        assert repeated_low_finding(student_series, defaults()).detected is False
        assert improvement_finding(student_series, defaults()).detected is False


class TestExplainability:
    def test_the_summary_quotes_the_numbers_behind_every_claim(self) -> None:
        narrative = profile(fx.S2).explanation.narrative
        quoted_numbers = ("FT1 40.00%", "-20.00 pp", "70.00%", "declining")
        for quoted in quoted_numbers:
            assert quoted in narrative, quoted

    def test_the_summary_names_the_method_and_the_sample_size(self) -> None:
        narrative = profile(fx.S1).explanation.narrative
        assert "least_squares" in narrative
        assert "3 completed assessments" in narrative

    def test_an_unexplained_verdict_is_impossible_because_findings_carry_evidence(self) -> None:
        for found in profile(fx.S3).findings:
            assert found.explanation.narrative
            assert found.explanation.evidence or found.measure.reason

    def test_the_thresholds_that_decided_anything_travel_with_the_profile(self) -> None:
        keys = {t.key for t in profile(fx.S1).explanation.thresholds}
        assert keys == {
            ThresholdKey.TREND_DELTA_PP,
            ThresholdKey.DECLINE_DROP_PP,
            ThresholdKey.REPEATED_LOW_COUNT,
            ThresholdKey.IMPROVEMENT_DELTA_PP,
        }

    def test_the_pass_mark_is_stated(self) -> None:
        built = profile(fx.S1)
        assert built.explanation.pass_mark_percent == Decimal("40.00")
        assert "pass mark of 40.00%" in built.explanation.narrative

    def test_a_student_with_nothing_says_why_rather_than_showing_zeroes(self) -> None:
        built = profile(b.student_id("s3"), b.missing_results())
        assert "No completed assessment" in built.explanation.narrative
        assert "none of which is a score of 0" in built.explanation.narrative


class TestEdgeCases:
    """The matrix this phase was asked for, one test per row."""

    def test_1_zero_valid_assessments(self) -> None:
        built = profile(b.student_id("s3"), b.missing_results())
        assert built.history.weighted_course_score.value is None
        assert built.trend.label.value is None
        assert all(f.detected in (None, False) for f in built.findings)

    def test_2_one_valid_assessment(self) -> None:
        built = profile(fx.S7)
        assert built.history.weighted_course_score.value == Decimal("50.00")
        assert built.trend.label.value is None
        assert built.change_from_previous.value is None

    def test_3_two_assessments(self) -> None:
        built = profile(b.student_id("s1"), b.small_class())
        assert built.trend.label.value is not None
        assert built.trend.method is not None and built.trend.method.value == "two_point_delta"
        assert built.history.consistency_std_dev.status is MeasureStatus.INSUFFICIENT_DATA

    def test_4_three_assessments(self) -> None:
        built = profile(fx.S1)
        assert built.trend.method is not None and built.trend.method.value == "least_squares"
        assert built.history.consistency_std_dev.value == Decimal("2.05")

    def test_5_missing_assessment(self) -> None:
        built = profile(fx.S7)
        assert [p.state for p in built.history.points][1:] == [
            DerivedState.MISSING,
            DerivedState.MISSING,
        ]
        assert built.history.completion_percent.value == Decimal("33.33")

    def test_6_absent_assessment(self) -> None:
        built = profile(b.student_id("s2"), b.absent_students())
        assert built.history.completion_percent.value == Decimal("66.67")
        assert built.history.weighted_course_score.value == Decimal("62.00")

    def test_7_exempt_assessment(self) -> None:
        built = profile(b.student_id("s3"), b.absent_students())
        assert built.history.completion_percent.value == Decimal("100.00")
        assert built.history.completion_percent.n == 2

    def test_8_improving_student(self) -> None:
        built = profile(b.student_id("s1"), b.improving_students())
        assert built.trend.label.value == "improving"
        assert built.finding(StudentFindingCode.IMPROVEMENT).detected is True  # type: ignore[union-attr]

    def test_9_stable_student(self) -> None:
        built = profile(b.student_id("s3"), b.improving_students())
        assert built.trend.label.value == "stable"
        assert built.finding(StudentFindingCode.IMPROVEMENT).detected is False  # type: ignore[union-attr]

    def test_10_declining_student(self) -> None:
        built = profile(b.student_id("s1"), b.declining_students())
        assert built.trend.label.value == "declining"

    def test_11_sharp_decline(self) -> None:
        built = profile(b.student_id("s4"), b.declining_students())
        assert built.finding(StudentFindingCode.SHARP_DECLINE).detected is True  # type: ignore[union-attr]
        assert built.change_from_historical_average.value == Decimal("-39.00")

    def test_12_repeated_low_performance(self) -> None:
        built = profile(fx.S5)
        assert built.finding(StudentFindingCode.REPEATED_LOW).detected is True  # type: ignore[union-attr]

    def test_13_low_high_low(self) -> None:
        """The dip-and-fall shape: no trend to speak of, but the latest fall is real."""
        snapshot = b.build_snapshot({"s1": (30, 80, 30)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.trend.slope.value == Decimal("0.00")
        assert built.trend.label.value == "stable"
        assert built.change_from_historical_average.value == Decimal("-25.00")
        assert built.finding(StudentFindingCode.SHARP_DECLINE).detected is True  # type: ignore[union-attr]

    def test_14_high_low_high(self) -> None:
        snapshot = b.build_snapshot({"s1": (80, 30, 80)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.trend.label.value == "stable"
        assert built.change_from_previous.value == Decimal("50.00")
        assert built.finding(StudentFindingCode.IMPROVEMENT).detected is True  # type: ignore[union-attr]
        assert built.history.consistency_std_dev.value == Decimal("23.57")

    def test_15_identical_scores(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 60, 60)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.change_from_previous.value == Decimal("0.00")
        assert built.change_from_historical_average.value == Decimal("0.00")
        assert built.history.consistency_std_dev.value == Decimal("0.00")
        assert built.trend.label.value == "stable"
        assert all(f.detected is False for f in built.findings)

    def test_16_large_improvement(self) -> None:
        snapshot = b.build_snapshot({"s1": (20, 30, 85)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.change_from_previous.value == Decimal("55.00")
        assert built.change_from_historical_average.value == Decimal("60.00")
        assert built.finding(StudentFindingCode.IMPROVEMENT).detected is True  # type: ignore[union-attr]
        assert built.finding(StudentFindingCode.SHARP_DECLINE).detected is False  # type: ignore[union-attr]

    def test_17_large_decline(self) -> None:
        snapshot = b.build_snapshot({"s1": (95, 90, 10)})
        built = student_profile(snapshot, b.student_id("s1"), defaults())
        assert built.change_from_historical_average.value == Decimal("-82.50")
        assert built.finding(StudentFindingCode.SHARP_DECLINE).detected is True  # type: ignore[union-attr]
        assert built.trend.label.value == "declining"

    def test_18_insufficient_consistency_observations(self) -> None:
        built = profile(b.student_id("s1"), b.small_class())
        assert built.history.consistency_std_dev.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.history.consistency_std_dev.minimum_n == 3
        assert built.history.volatility_range.status is MeasureStatus.INSUFFICIENT_DATA

    def test_19_assessment_ordering_differences(self) -> None:
        """Sequence order decides, not the order the rows happen to be in."""
        snapshot = b.build_snapshot({"s1": (50, 60, 70)})
        reordered = snapshot.model_copy(
            update={"assessments": tuple(reversed(snapshot.assessments))}
        )
        assert (
            student_profile(reordered, b.student_id("s1"), defaults()).trend.slope.value
            == student_profile(snapshot, b.student_id("s1"), defaults()).trend.slope.value
        )

    def test_20_multiple_students_have_independent_histories(self) -> None:
        profiles = cohort_profiles(fx.snapshot(), defaults())
        assert len(profiles) == 7, "S8 is inactive"
        assert [p.history.weighted_course_score.value for p in profiles] == [
            Decimal("93.00"),
            Decimal("55.00"),
            Decimal("69.50"),
            Decimal("41.00"),
            Decimal("33.00"),
            Decimal("60.00"),
            Decimal("50.00"),
        ]
        assert [p.student.id for p in profiles] == [
            fx.S1,
            fx.S2,
            fx.S3,
            fx.S4,
            fx.S5,
            fx.S6,
            fx.S7,
        ]
        assert profiles[5].change_from_previous.value is None, "S6 has one completed"
        assert profiles[1].change_from_previous.value == Decimal("-20.00")


class TestThresholdsAndPassMark:
    def test_a_different_pass_mark_changes_the_run_below_it(self) -> None:
        snapshot = fx.snapshot(pass_mark=Decimal("50"))
        built = student_profile(snapshot, fx.S4, defaults("50.00"))
        found = built.finding(StudentFindingCode.REPEATED_LOW)
        assert found is not None and found.detected is True
        assert found.pass_mark_percent == Decimal("50")

    def test_a_configured_decline_threshold_changes_the_verdict_not_the_number(self) -> None:
        strict = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"), offering_overrides={"decline_drop_pp": "50"}
        )
        built = student_profile(fx.snapshot(), fx.S3, strict)
        found = built.finding(StudentFindingCode.SHARP_DECLINE)
        assert found is not None
        assert found.measure.value == Decimal("-39.00"), "the drop is what it is"
        assert found.detected is False, "but it no longer reaches the configured magnitude"

    def test_thresholds_from_another_offering_are_refused(self) -> None:
        with pytest.raises(ValueError, match="pass mark"):
            student_profile(fx.snapshot(), fx.S1, defaults("50.00"))
