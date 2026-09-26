"""F2, F7, F10-F13 and contracts 2 and 3: one student at a time.

The arithmetic for the canonical cohort, worked by hand (pass mark 40; weights CT1 1,
CT2 1, FT1 2, so the denominator is 4 for a student who completed all three):

=====  =====================  =========================================  =======  ==========
who    percentages            weighted course score                      complete  sd / range
=====  =====================  =========================================  =======  ==========
S1     90, 92, 95             (90 + 92 + 190) / 4 = 93.00                100.00    2.05 / 5
S2     80, 60, 40             (80 + 60 +  80) / 4 = 55.00                100.00   16.33 / 40
S3     90, 88, 50             (90 + 88 + 100) / 4 = 69.50                100.00   18.40 / 40
S4     42, 40, 41             (42 + 40 +  82) / 4 = 41.00                100.00    0.82 / 2
S5     30, 32, 35             (30 + 32 +  70) / 4 = 33.00                100.00    2.05 / 5
S6     absent, exempt, 60     (60 * 2) / 2        = 60.00                 50.00   insufficient
S7     50, then nothing       (50 * 1) / 1        = 50.00                 33.33   insufficient
=====  =====================  =========================================  =======  ==========

S6 is the case the whole policy exists for: one completed assessment out of two required
(the exempt one leaves the denominator), and a course score of 60 — not 20, which is what
counting the absence and the exemption as zeroes would give.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.policy import DerivedState, build_student_series
from app.modules.analytics.core.results import MeasureStatus, Unit
from app.modules.analytics.core.student import (
    average_percentage,
    cohort_histories,
    completion_percent,
    consistency,
    decline_against_earlier_mean,
    is_borderline,
    is_repeated_low,
    is_sharp_decline,
    latest_change,
    pass_mark_distance,
    repeated_low_run,
    student_assessment_performance,
    student_performance_history,
    volatility_range,
    weighted_course_score,
)
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def series(student: object, snapshot: object | None = None):  # noqa: ANN201 - StudentSeries
    return build_student_series(snapshot or fx.snapshot(), student)  # type: ignore[arg-type]


class TestWeightedCourseScore:
    @pytest.mark.parametrize(
        ("student", "expected", "n"),
        [
            (fx.S1, "93.00", 3),
            (fx.S2, "55.00", 3),
            (fx.S3, "69.50", 3),
            (fx.S4, "41.00", 3),
            (fx.S5, "33.00", 3),
            (fx.S6, "60.00", 1),
            (fx.S7, "50.00", 1),
        ],
        ids=["S1", "S2", "S3", "S4", "S5", "S6", "S7"],
    )
    def test_canonical_scores(self, student: object, expected: str, n: int) -> None:
        score = weighted_course_score(series(student))
        assert score.value == Decimal(expected)
        assert score.n == n, "n is the number of completed assessments behind the score"

    def test_an_absence_does_not_drag_the_score_down(self) -> None:
        """S6: 60% for the one assessment sat, not 20% for "60, 0, 0"."""
        assert weighted_course_score(series(fx.S6)).value == Decimal("60.00")

    def test_a_missing_future_assessment_does_not_drag_the_score_down(self) -> None:
        """S7 sat one of three. The score is that one, not a third of it."""
        assert weighted_course_score(series(fx.S7)).value == Decimal("50.00")

    def test_weights_actually_weight(self) -> None:
        """Equal marks with FT1 weighted 2: the final test moves the score twice as much."""
        snapshot = b.build_snapshot({"s1": (100, 100, 40)}, weightages={"CT3": 2})
        assert weighted_course_score(series(b.student_id("s1"), snapshot)).value == Decimal(
            "70.00"
        ), "(100 + 100 + 80) / 4"

    def test_the_unweighted_average_is_reported_separately(self) -> None:
        """Different question, different number: 80.00 unweighted against 70.00 weighted."""
        snapshot = b.build_snapshot({"s1": (100, 100, 40)}, weightages={"CT3": 2})
        assert average_percentage(series(b.student_id("s1"), snapshot)).value == Decimal("80.00")

    def test_a_student_with_no_completed_assessment_has_no_score(self) -> None:
        withheld = weighted_course_score(series(b.student_id("s3"), b.missing_results()))
        assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
        assert withheld.value is None
        assert withheld.reason == "only 0 completed assessments available (minimum 1)"

    def test_all_weights_zero_is_refused_rather_than_averaged(self) -> None:
        """A configuration problem, not a number to smooth over."""
        snapshot = b.build_snapshot({"s1": (60, 80)}, weightages={"CT1": 0, "CT2": 0})
        withheld = weighted_course_score(series(b.student_id("s1"), snapshot))
        assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
        assert "weight of 0" in (withheld.reason or "")


class TestCompletion:
    @pytest.mark.parametrize(
        ("student", "expected", "denominator"),
        [
            (fx.S1, "100.00", 3),
            (fx.S6, "50.00", 2),
            (fx.S7, "33.33", 3),
        ],
        ids=["complete", "absent-and-exempt", "stopped-sitting"],
    )
    def test_canonical_completion(self, student: object, expected: str, denominator: int) -> None:
        completion = completion_percent(series(student))
        assert completion.value == Decimal(expected)
        assert completion.n == denominator

    def test_absent_and_exempt_are_not_the_same_thing(self) -> None:
        """Same two papers sat; the exempt student is at 100% and the absent one is not."""
        snapshot = b.absent_students()
        absent = completion_percent(series(b.student_id("s2"), snapshot))
        exempt = completion_percent(series(b.student_id("s3"), snapshot))
        assert absent.value == Decimal("66.67")
        assert exempt.value == Decimal("100.00")

    def test_a_wholly_absent_student_is_at_zero_completion_with_no_score(self) -> None:
        snapshot = b.absent_students()
        assert completion_percent(series(b.student_id("s4"), snapshot)).value == Decimal("0.00")
        assert weighted_course_score(series(b.student_id("s4"), snapshot)).value is None


class TestConsistency:
    @pytest.mark.parametrize(
        ("student", "sd", "spread"),
        [
            (fx.S1, "2.05", "5.00"),
            (fx.S2, "16.33", "40.00"),
            (fx.S3, "18.40", "40.00"),
            (fx.S4, "0.82", "2.00"),
            (fx.S5, "2.05", "5.00"),
        ],
        ids=["S1", "S2", "S3", "S4", "S5"],
    )
    def test_canonical_consistency(self, student: object, sd: str, spread: str) -> None:
        assert consistency(series(student), defaults()).value == Decimal(sd)
        assert volatility_range(series(student), defaults()).value == Decimal(spread)

    def test_consistency_needs_three_points(self) -> None:
        """Two numbers have a spread; two numbers do not make someone "volatile"."""
        withheld = consistency(series(fx.S6), defaults())
        assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
        assert withheld.minimum_n == 3
        assert withheld.unit is Unit.PERCENTAGE_POINTS

    def test_identical_scores_are_perfectly_consistent(self) -> None:
        snapshot = b.volatile_students()
        assert consistency(series(b.student_id("s2"), snapshot), defaults()).value == Decimal(
            "0.00"
        )
        assert volatility_range(series(b.student_id("s2"), snapshot), defaults()).value == Decimal(
            "0.00"
        )

    def test_consistency_is_what_qualifies_a_volatile_students_trend(self) -> None:
        """90, 30, 85, 35 fits a Declining slope; sd 27.61 says not to read much into it."""
        snapshot = b.volatile_students()
        assert consistency(series(b.student_id("s1"), snapshot), defaults()).value == Decimal(
            "27.61"
        )
        assert volatility_range(series(b.student_id("s1"), snapshot), defaults()).value == Decimal(
            "60.00"
        )

    def test_a_steady_series_is_not_an_identical_one(self) -> None:
        snapshot = b.volatile_students()
        assert consistency(series(b.student_id("s3"), snapshot), defaults()).value == Decimal(
            "1.58"
        )


class TestChangeAndDecline:
    def test_latest_change_is_between_the_two_most_recent_completed(self) -> None:
        """S2: FT1 40 against CT2 60."""
        assert latest_change(series(fx.S2)).value == Decimal("-20.00")
        assert latest_change(series(fx.S1)).value == Decimal("3.00")

    def test_latest_change_skips_over_an_absence(self) -> None:
        """ "Compared with last time" means the last time they were assessed."""
        snapshot = b.build_snapshot({"s1": (60, b.ABSENT, 75)})
        assert latest_change(series(b.student_id("s1"), snapshot)).value == Decimal("15.00")

    def test_a_single_assessment_has_no_change(self) -> None:
        withheld = latest_change(series(fx.S7))
        assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
        assert withheld.minimum_n == 2

    @pytest.mark.parametrize(
        ("student", "drop", "fires"),
        [
            (fx.S1, "4.00", False),
            (fx.S2, "-30.00", True),
            (fx.S3, "-39.00", True),
            (fx.S4, "0.00", False),
            (fx.S5, "4.00", False),
        ],
        ids=["S1", "S2", "S3", "S4", "S5"],
    )
    def test_decline_against_the_earlier_mean(
        self, student: object, drop: str, fires: bool
    ) -> None:
        """S3: 50 against a mean of (90 + 88) / 2 = 89, so -39 pp."""
        measured = decline_against_earlier_mean(series(student), defaults())
        assert measured.value == Decimal(drop)
        assert is_sharp_decline(series(student), defaults()) is fires

    def test_a_sharp_decline_is_not_the_same_as_a_declining_trend(self) -> None:
        """S2 has both; a cliff and a slope are different events with different rules."""
        assert is_sharp_decline(series(fx.S2), defaults()) is True
        assert is_sharp_decline(series(fx.S1), defaults()) is False

    def test_decline_cannot_be_known_from_one_assessment(self) -> None:
        assert is_sharp_decline(series(fx.S7), defaults()) is None
        assert decline_against_earlier_mean(series(fx.S7), defaults()).value is None

    def test_the_configured_magnitude_decides(self) -> None:
        strict = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"), offering_overrides={"decline_drop_pp": "3"}
        )
        assert is_sharp_decline(series(fx.S4), strict) is False, "S4's drop is 0.00"
        gentle = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"), offering_overrides={"decline_drop_pp": "50"}
        )
        assert is_sharp_decline(series(fx.S3), gentle) is False, "-39 does not reach -50"


class TestRepeatedLow:
    @pytest.mark.parametrize(
        ("student", "run", "fires"),
        [
            (fx.S5, 3, True),
            (fx.S4, 0, False),
            (fx.S2, 0, False),
            (fx.S1, 0, False),
        ],
        ids=["persistently-low", "borderline", "declining-but-passing", "high"],
    )
    def test_canonical_runs(self, student: object, run: int, fires: bool) -> None:
        assert repeated_low_run(series(student), defaults()).value == Decimal(run)
        assert is_repeated_low(series(student), defaults()) is fires

    def test_the_pass_mark_is_inclusive_so_exactly_forty_is_not_low(self) -> None:
        """S4 scored exactly 40 in CT2. Exactly the pass mark is a pass."""
        assert repeated_low_run(series(fx.S4), defaults()).value == Decimal(0)

    def test_the_run_is_the_trailing_one_not_the_longest(self) -> None:
        """Below pass three times, then recovered: not currently in that state."""
        snapshot = b.build_snapshot({"s1": (30, 30, 30, 70)})
        assert repeated_low_run(series(b.student_id("s1"), snapshot), defaults()).value == Decimal(
            0
        )

    def test_a_run_is_counted_over_completed_assessments_only(self) -> None:
        """An absence between two low scores does not break the run, and is not itself low."""
        snapshot = b.build_snapshot({"s1": (30, b.ABSENT, 35, 20)})
        assert repeated_low_run(series(b.student_id("s1"), snapshot), defaults()).value == Decimal(
            3
        )

    def test_a_higher_pass_mark_makes_more_students_repeatedly_low(self) -> None:
        """S4 (42, 40, 41) is fine at a pass mark of 40 and repeatedly low at 50."""
        assert repeated_low_run(series(fx.S4), defaults("50.00")).value == Decimal(3)

    def test_no_completed_assessment_means_no_run(self) -> None:
        assert is_repeated_low(series(b.student_id("s3"), b.missing_results()), defaults()) is None


class TestBorderline:
    @pytest.mark.parametrize(
        ("student", "distance", "borderline"),
        [
            (fx.S4, "1.00", True),
            (fx.S5, "-7.00", False),
            (fx.S7, "10.00", False),
            (fx.S1, "53.00", False),
        ],
        ids=["S4", "S5", "S7", "S1"],
    )
    def test_distance_from_the_pass_mark(
        self, student: object, distance: str, borderline: bool
    ) -> None:
        assert pass_mark_distance(series(student), defaults()).value == Decimal(distance)
        assert is_borderline(series(student), defaults()) is borderline

    def test_the_band_is_symmetrical_and_inclusive(self) -> None:
        """Exactly 5 pp below and exactly 5 pp above are both borderline."""
        snapshot = b.build_snapshot({"below": (35, 35), "above": (45, 45)})
        for key in ("below", "above"):
            assert is_borderline(series(b.student_id(key), snapshot), defaults()) is True

    def test_just_outside_the_band_is_not_borderline(self) -> None:
        snapshot = b.build_snapshot({"s1": (34, 34)})
        assert is_borderline(series(b.student_id("s1"), snapshot), defaults()) is False

    def test_borderline_moves_with_the_offerings_pass_mark(self) -> None:
        """Nothing here is anchored to 50%: S5 (33.00) is borderline at a pass mark of 35."""
        assert is_borderline(series(fx.S5), defaults("35.00")) is True

    def test_a_student_with_no_score_is_not_declared_not_borderline(self) -> None:
        assert is_borderline(series(b.student_id("s3"), b.missing_results()), defaults()) is None


class TestStudentAssessmentPerformance:
    def test_an_assessed_performance_carries_score_percentage_and_context(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S1, fx.CT1)
        assert performance.state is DerivedState.ASSESSED
        assert performance.score == Decimal("45.00")
        assert performance.max_marks == Decimal("50.00")
        assert performance.percentage.value == Decimal("90.00")
        assert performance.difference_from_class_mean.value == Decimal("26.33"), "90 - 63.67"
        assert performance.meets_pass_mark is True

    def test_a_student_below_the_class_mean_gets_a_negative_difference(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S5, fx.CT1)
        assert performance.difference_from_class_mean.value == Decimal("-33.67")

    def test_an_absent_performance_is_not_a_zero(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S6, fx.CT1)
        assert performance.state is DerivedState.ABSENT
        assert performance.score is None
        assert performance.percentage.status is MeasureStatus.INSUFFICIENT_DATA
        assert "not a score of 0" in (performance.percentage.reason or "")
        assert performance.meets_pass_mark is None

    def test_an_exempt_performance_says_exempt(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S6, fx.CT2)
        assert performance.state is DerivedState.EXEMPT
        assert "exempt from CT2" in (performance.percentage.reason or "")

    def test_a_missing_performance_says_no_result_was_recorded(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S7, fx.FT1)
        assert performance.state is DerivedState.MISSING
        assert "no result recorded for FT1" in (performance.percentage.reason or "")

    def test_exactly_the_pass_mark_meets_it(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S4, fx.CT2)
        assert performance.percentage.value == Decimal("40.00")
        assert performance.meets_pass_mark is True

    def test_the_explanation_shows_the_marks_behind_the_percentage(self) -> None:
        performance = student_assessment_performance(fx.snapshot(), fx.S1, fx.CT1)
        evidence = {item.name: item.value for item in performance.explanation.evidence}
        assert evidence["Score"] == "45.00"
        assert evidence["Maximum marks"] == "50.00"
        assert evidence["Class mean"] == "63.67"

    def test_a_precomputed_class_mean_gives_the_same_answer(self) -> None:
        """The optimisation for cohort-wide builds must not change a number."""
        from app.modules.analytics.core.policy import assessed_percentages
        from app.modules.analytics.core.statistics import mean_percent

        snapshot = fx.snapshot()
        shared = mean_percent(assessed_percentages(snapshot, fx.CT1))
        one = student_assessment_performance(snapshot, fx.S1, fx.CT1)
        other = student_assessment_performance(snapshot, fx.S1, fx.CT1, class_mean=shared)
        assert one.difference_from_class_mean.value == other.difference_from_class_mean.value


class TestStudentPerformanceHistory:
    def test_the_history_assembles_every_student_level_measure(self) -> None:
        history = student_performance_history(fx.snapshot(), fx.S2, defaults())
        assert history.weighted_course_score.value == Decimal("55.00")
        assert history.completion_percent.value == Decimal("100.00")
        assert history.consistency_std_dev.value == Decimal("16.33")
        assert history.volatility_range.value == Decimal("40.00")
        assert history.trend.label.value == "declining"
        assert history.latest is not None
        assert history.latest.assessment.code == "FT1"

    def test_the_series_keeps_its_gaps(self) -> None:
        history = student_performance_history(fx.snapshot(), fx.S6, defaults())
        assert [p.state for p in history.points] == [
            DerivedState.ABSENT,
            DerivedState.EXEMPT,
            DerivedState.ASSESSED,
        ]
        assert history.coverage.assessed == 1
        assert history.coverage.completion_denominator == 2

    def test_latest_is_the_most_recent_assessment_actually_sat(self) -> None:
        """S7 sat CT1 and nothing since; the latest performance is CT1, not "missing"."""
        history = student_performance_history(fx.snapshot(), fx.S7, defaults())
        assert history.latest is not None
        assert history.latest.assessment.code == "CT1"
        assert history.latest.percentage.value == Decimal("50.00")

    def test_a_student_with_no_results_has_a_history_of_absences(self) -> None:
        snapshot = b.missing_results()
        history = student_performance_history(snapshot, b.student_id("s3"), defaults())
        assert history.latest is None
        assert history.weighted_course_score.value is None
        assert history.completion_percent.value == Decimal("0.00")
        assert "no completed assessment" in history.explanation.narrative

    def test_the_explanation_shows_each_contribution_and_its_weight(self) -> None:
        history = student_performance_history(fx.snapshot(), fx.S1, defaults())
        assert "CT1 90.00% (weight 1)" in history.explanation.narrative
        assert "FT1 95.00% (weight 2)" in history.explanation.narrative
        assert history.explanation.pass_mark_percent == Decimal("40.00")

    def test_thresholds_resolved_for_another_offering_are_refused(self) -> None:
        """Quoting one pass mark and applying another is the worst thing this could do."""
        with pytest.raises(ValueError, match="pass mark"):
            student_performance_history(fx.snapshot(), fx.S1, defaults("50.00"))

    def test_the_cohort_build_covers_active_students_only(self) -> None:
        histories = cohort_histories(fx.snapshot(), defaults())
        assert len(histories) == 7, "S8 is inactive"
        assert [h.weighted_course_score.value for h in histories] == [
            Decimal("93.00"),
            Decimal("55.00"),
            Decimal("69.50"),
            Decimal("41.00"),
            Decimal("33.00"),
            Decimal("60.00"),
            Decimal("50.00"),
        ]
