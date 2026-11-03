"""The edge-case matrix from docs/ANALYTICS_SPEC.md §11, in one readable place.

Each test is one row of that matrix. They overlap with the per-module tests on purpose:
those check a formula, these check that the *whole engine* survives a shape of data that a
real cohort will eventually contain. This is the file to read when asking "what happens if
nobody sat the paper?".

One rule runs through all of them: **an answer that cannot be computed is reported as
insufficient data with its ``n``, never as 0, never as NaN, never as a label.**
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.modules.analytics.core.class_health import class_health
from app.modules.analytics.core.comparison import (
    change_analysis,
    consecutive_comparisons,
    latest_published,
)
from app.modules.analytics.core.distribution import score_distribution
from app.modules.analytics.core.outputs import ANALYTICS_CONTRACTS
from app.modules.analytics.core.policy import build_student_series
from app.modules.analytics.core.results import Measure, MeasureStatus
from app.modules.analytics.core.segmentation import cohort_segments, segment_counts
from app.modules.analytics.core.statistics import assessment_analytics
from app.modules.analytics.core.student import (
    cohort_histories,
    student_assessment_performance,
    student_performance_history,
    weighted_course_score,
)
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from app.modules.analytics.core.trends import trend_for
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def measures(model: object) -> list[Measure]:
    """Every Measure anywhere inside a contract, however deeply nested."""
    found: list[Measure] = []

    def walk(value: object) -> None:
        if isinstance(value, Measure):
            found.append(value)
        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                walk(getattr(value, name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                walk(item)

    walk(model)
    return found


# 1. Empty dataset -----------------------------------------------------------------------


class TestEmptyDataset:
    def test_an_offering_with_no_students_and_no_assessments_computes_nothing_and_raises_nothing(
        self,
    ) -> None:
        snapshot = b.empty_offering()
        assert snapshot.ordered_assessments() == ()
        assert cohort_histories(snapshot, defaults()) == ()

    def test_an_assessment_nobody_sat_has_no_statistics(self) -> None:
        snapshot = b.build_snapshot({"s1": (b.ABSENT,), "s2": (b.MISSING,)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        for withheld in (
            analytics.mean,
            analytics.median,
            analytics.std_dev,
            analytics.pass_percent,
        ):
            assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
            assert withheld.value is None
        assert analytics.lowest is None and analytics.highest is None
        assert analytics.completion_percent.value == Decimal("0.00"), "0 of 2 sat it"


# 2-5. Cohort and series sizes -----------------------------------------------------------


class TestSizes:
    def test_one_student_gets_student_analytics_and_no_class_spread(self) -> None:
        snapshot = b.single_student()
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.mean.value == Decimal("70.00")
        assert analytics.mean.n == 1
        assert analytics.std_dev.status is MeasureStatus.INSUFFICIENT_DATA
        assert analytics.std_dev.minimum_n == 2

    def test_one_assessment_gives_a_score_but_never_a_trend(self) -> None:
        snapshot = b.build_snapshot({"s1": (62,), "s2": (48,)})
        history = student_performance_history(snapshot, b.student_id("s1"), defaults())
        assert history.weighted_course_score.value == Decimal("62.00")
        assert history.trend.label.status is MeasureStatus.INSUFFICIENT_DATA
        assert history.consistency_std_dev.status is MeasureStatus.INSUFFICIENT_DATA

    def test_two_assessments_give_a_two_point_trend_and_still_no_consistency(self) -> None:
        snapshot = b.small_class()
        history = student_performance_history(snapshot, b.student_id("s1"), defaults())
        assert history.trend.label.value is not None, "two points is enough for a direction"
        assert history.trend.method is not None
        assert history.consistency_std_dev.status is MeasureStatus.INSUFFICIENT_DATA, (
            "three points before calling someone consistent"
        )

    def test_multiple_assessments_use_the_fitted_slope(self) -> None:
        history = student_performance_history(fx.snapshot(), fx.S2, defaults())
        assert history.trend.method is not None
        assert history.trend.method.value == "least_squares"
        assert history.trend.slope.n == 3

    def test_a_very_small_cohort_still_reports_its_numbers_with_n(self) -> None:
        """n = 3 is below min_group_n; the mean is real, the *label* is what waits (Phase 3)."""
        snapshot = b.small_class()
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.mean.value == Decimal("60.00")
        assert analytics.mean.n == 3


# 6-8. The three not-a-zero states -------------------------------------------------------


class TestMissingAbsentExempt:
    def test_a_missing_result_is_not_a_zero(self) -> None:
        snapshot = b.build_snapshot({"s1": (80, b.MISSING), "s2": (60, 60)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[1])
        assert analytics.mean.value == Decimal("60.00"), "the mean is of the one student who sat"
        assert analytics.mean.n == 1
        assert analytics.coverage.missing == 1
        assert weighted_course_score(
            build_student_series(snapshot, b.student_id("s1"))
        ).value == Decimal("80.00")

    def test_an_absent_result_is_not_a_zero(self) -> None:
        snapshot = b.absent_students()
        performance = student_assessment_performance(
            snapshot, b.student_id("s2"), snapshot.assessments[1]
        )
        assert performance.score is None
        assert performance.percentage.value is None
        assert performance.meets_pass_mark is None
        assert weighted_course_score(
            build_student_series(snapshot, b.student_id("s2"))
        ).value == Decimal("62.00"), "(60 + 64) / 2, the absence excluded"

    def test_an_exempt_result_leaves_the_denominator_rather_than_scoring_zero(self) -> None:
        snapshot = b.absent_students()
        history = student_performance_history(snapshot, b.student_id("s3"), defaults())
        assert history.completion_percent.value == Decimal("100.00")
        assert history.completion_percent.n == 2, "the exempt assessment is not required"
        assert history.weighted_course_score.value == Decimal("62.00")

    def test_absent_and_exempt_differ_only_in_the_denominator(self) -> None:
        snapshot = b.absent_students()
        absent = student_performance_history(snapshot, b.student_id("s2"), defaults())
        exempt = student_performance_history(snapshot, b.student_id("s3"), defaults())
        assert absent.weighted_course_score.value == exempt.weighted_course_score.value
        assert absent.completion_percent.value != exempt.completion_percent.value


# 9-13. Value extremes -------------------------------------------------------------------


class TestValueExtremes:
    def test_all_students_passing(self) -> None:
        snapshot = b.build_snapshot({"s1": (90,), "s2": (75,), "s3": (41,)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.pass_percent.value == Decimal("100.00")

    def test_all_students_failing(self) -> None:
        """0% is a real answer here, computed from three real percentages."""
        snapshot = b.build_snapshot({"s1": (39,), "s2": (20,), "s3": (5,)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.pass_percent.value == Decimal("0.00")
        assert analytics.pass_percent.n == 3

    def test_identical_scores_have_no_spread_and_no_trend(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 60, 60), "s2": (60, 60, 60)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.std_dev.value == Decimal("0.00")
        assert analytics.mean.value == analytics.median.value == Decimal("60.00")
        trend = trend_for(snapshot, b.student_id("s1"), defaults())
        assert trend.slope.value == Decimal("0.00")
        assert trend.label.value == "stable"

    def test_a_maximum_score(self) -> None:
        snapshot = b.build_snapshot({"s1": (100, 100)})
        history = student_performance_history(snapshot, b.student_id("s1"), defaults())
        assert history.weighted_course_score.value == Decimal("100.00")
        distribution = score_distribution(snapshot, snapshot.assessments[0])
        assert distribution.bins[-1].count == 1, "100 belongs in the 90-100 bin"

    def test_a_genuine_zero_is_a_score_not_a_gap(self) -> None:
        """A student who sat the paper and scored 0 is assessed: they count everywhere."""
        snapshot = b.build_snapshot({"s1": (0, 0), "s2": (60, 60)})
        series = build_student_series(snapshot, b.student_id("s1"))
        assert series.completed_count == 2
        history = student_performance_history(snapshot, b.student_id("s1"), defaults())
        assert history.weighted_course_score.value == Decimal("0.00")
        assert history.completion_percent.value == Decimal("100.00")
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.mean.value == Decimal("30.00"), "0 and 60 average 30"
        assert analytics.coverage.assessed == 2

    def test_decimal_values_survive_intact(self) -> None:
        """33.33% of 45 marks is 14.99, and 14.99/45 is 33.31% — no float drift."""
        snapshot = b.build_snapshot({"s1": (Decimal("33.33"),)}, max_marks=45)
        performance = student_assessment_performance(
            snapshot, b.student_id("s1"), snapshot.assessments[0]
        )
        assert performance.score == Decimal("15.00")
        assert performance.percentage.value == Decimal("33.33")

    def test_thirds_round_half_up_rather_than_drifting(self) -> None:
        snapshot = b.build_snapshot({"s1": (1,), "s2": (2,), "s3": (2,)})
        analytics = assessment_analytics(snapshot, snapshot.assessments[0])
        assert analytics.mean.value == Decimal("1.67"), "5/3 = 1.666... -> 1.67"


# 15-19. Series shapes -------------------------------------------------------------------


class TestSeriesShapes:
    def test_insufficient_observations_never_become_a_trend(self) -> None:
        for snapshot, key in (
            (b.missing_results(), "s3"),
            (b.single_student(), "s1"),
        ):
            trend = trend_for(snapshot, b.student_id(key), defaults())
            if len(trend.percentages_used) < 2:
                assert trend.label.value is None
                assert trend.method is None

    def test_a_student_with_one_result_is_never_called_declining(self) -> None:
        trend = trend_for(fx.snapshot(), fx.S7, defaults())
        assert trend.label.value is None
        assert "minimum 2" in (trend.label.reason or "")

    def test_flat_performance(self) -> None:
        trend = trend_for(b.volatile_students(), b.student_id("s2"), defaults())
        assert trend.label.value == "stable"
        assert trend.slope.value == Decimal("0.00")

    def test_increasing_performance(self) -> None:
        trend = trend_for(b.improving_students(), b.student_id("s1"), defaults())
        assert trend.label.value == "improving"
        assert trend.slope.value == Decimal("10.00")

    def test_decreasing_performance(self) -> None:
        trend = trend_for(b.declining_students(), b.student_id("s1"), defaults())
        assert trend.label.value == "declining"
        assert trend.slope.value == Decimal("-10.00")

    def test_a_large_sudden_change_shows_up_as_a_drop_not_just_a_slope(self) -> None:
        """S3: 90, 88, then 50. The slope says declining; the drop says how suddenly."""
        history = student_performance_history(fx.snapshot(), fx.S3, defaults())
        assert history.trend.label.value == "declining"
        assert history.volatility_range.value == Decimal("40.00")


# Invariants that must hold everywhere ---------------------------------------------------


def cohort_payloads(snapshot: object, thresholds: ThresholdSet) -> list[object]:
    """Every contract the engine can produce for one offering, class intelligence included."""
    payloads: list[object] = [
        assessment_analytics(snapshot, assessment)  # type: ignore[arg-type]
        for assessment in snapshot.ordered_assessments()  # type: ignore[attr-defined]
    ]
    payloads.extend(cohort_histories(snapshot, thresholds))  # type: ignore[arg-type]
    payloads.extend(cohort_segments(snapshot, thresholds))  # type: ignore[arg-type]
    payloads.extend(consecutive_comparisons(snapshot))  # type: ignore[arg-type]
    payloads.append(class_health(snapshot, thresholds))  # type: ignore[arg-type]
    if latest_published(snapshot) is not None:  # type: ignore[arg-type]
        payloads.append(change_analysis(snapshot, thresholds))  # type: ignore[arg-type]
    return payloads


class TestInvariantsAcrossEveryScenario:
    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_no_scenario_produces_a_non_finite_number(self, name: str) -> None:
        """NaN and infinity must never reach a response, in any shape of data."""
        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        payloads = cohort_payloads(snapshot, thresholds)
        for payload in payloads:
            text = payload.model_dump_json()
            assert "NaN" not in text
            assert "Infinity" not in text
            for value in _numbers(json.loads(text)):
                assert math.isfinite(value)

    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_every_measure_carries_its_n_and_explains_any_absence(self, name: str) -> None:
        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for payload in cohort_payloads(snapshot, thresholds):
            for found in measures(payload):
                assert found.n >= 0
                if found.status is MeasureStatus.INSUFFICIENT_DATA:
                    assert found.value is None
                    assert found.reason, "an absent value must say why"

    def test_every_contract_the_engine_produces_is_a_declared_one(self) -> None:
        snapshot = fx.snapshot()
        produced = {
            type(assessment_analytics(snapshot, fx.CT1)),
            type(score_distribution(snapshot, fx.CT1)),
            type(student_performance_history(snapshot, fx.S1, defaults())),
            type(trend_for(snapshot, fx.S1, defaults())),
            type(student_assessment_performance(snapshot, fx.S1, fx.CT1)),
            type(class_health(snapshot, defaults())),
            type(change_analysis(snapshot, defaults())),
            type(cohort_segments(snapshot, defaults())[0]),
            type(consecutive_comparisons(snapshot)[0]),
        }
        assert produced <= set(ANALYTICS_CONTRACTS)


class TestClassIntelligenceEdgeCases:
    """The Phase 4 additions to the matrix."""

    def test_an_offering_with_one_assessment_reports_no_change(self) -> None:
        snapshot = b.build_snapshot({"s1": (60,), "s2": (70,)})
        analysis = change_analysis(snapshot, defaults())
        assert analysis.from_assessment is None
        assert analysis.groups == ()
        assert analysis.class_mean_change.value is None

    def test_an_offering_with_no_published_assessment_has_no_latest(self) -> None:
        snapshot = b.build_snapshot({"s1": (60,)}, unpublished=("CT1",))
        assert latest_published(snapshot) is None
        assert consecutive_comparisons(snapshot) == ()
        assert class_health(snapshot, defaults()).latest_assessment is None

    def test_a_cohort_of_one_gets_numbers_and_no_cohort_verdict(self) -> None:
        snapshot = b.single_student()
        health = class_health(snapshot, defaults())
        assert health.cohort_n == 1
        assert health.class_mean.value == Decimal("74.00")
        analysis = change_analysis(snapshot, defaults())
        assert all(f.detected is None for f in analysis.findings), "1 student is below n=5"

    def test_everyone_absent_in_the_latest_assessment(self) -> None:
        snapshot = b.build_snapshot(
            {"s1": (60, b.ABSENT), "s2": (70, b.ABSENT), "s3": (50, b.ABSENT)}
        )
        analysis = change_analysis(snapshot, defaults())
        assert analysis.intersection_n == 0
        assert analysis.class_mean_change.value is None, "nobody sat it: not a fall to zero"
        assert all(g.count == 0 for g in analysis.groups)

    def test_an_all_exempt_assessment_has_no_participation_denominator(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, b.EXEMPT), "s2": (70, b.EXEMPT)})
        comparison = consecutive_comparisons(snapshot)[0]
        assert comparison.completion_change.status is MeasureStatus.INSUFFICIENT_DATA
        assert "no denominator" in (comparison.completion_change.reason or "")

    def test_a_student_who_joined_late_is_in_neither_side_of_the_comparison(self) -> None:
        snapshot = b.build_snapshot({"early": (60, 65), "late": (b.MISSING, 80)})
        comparison = consecutive_comparisons(snapshot)[0]
        assert comparison.intersection_n == 1
        assert comparison.mean_change.value == Decimal("5.00"), "the late joiner cannot move"
        assert comparison.coverage.missing == 1

    def test_segments_and_counts_survive_every_scenario(self) -> None:
        for name, build in sorted(b.SCENARIOS.items()):
            snapshot = build()
            thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
            segments = cohort_segments(snapshot, thresholds)
            counts = segment_counts(segments)
            assert sum(counts.values()) <= len(segments), name

    def test_class_health_never_claims_attention_was_evaluated_when_it_was_not(self) -> None:
        for build in b.SCENARIOS.values():
            snapshot = build()
            thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
            health = class_health(snapshot, thresholds, evaluate_attention=False)
            assert health.students_requiring_attention is None
            assert health.flag_counts == {}
            assert health.rule_counts == {}

    def test_an_evaluated_build_always_reports_a_count_even_when_it_is_zero(self) -> None:
        for name, build in sorted(b.SCENARIOS.items()):
            snapshot = build()
            thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
            health = class_health(snapshot, thresholds)
            assert health.students_requiring_attention is not None, name
            assert health.students_requiring_attention.value is not None, name
            assert health.students_requiring_attention.value <= health.cohort_n, name

    def test_every_comparison_carries_the_difficulty_caveat(self) -> None:
        from app.modules.analytics.core.outputs import DIFFICULTY_CAVEAT

        for build in b.SCENARIOS.values():
            for comparison in consecutive_comparisons(build()):
                assert DIFFICULTY_CAVEAT in comparison.explanation.caveats

    def test_every_change_group_count_equals_its_members(self) -> None:
        for build in b.SCENARIOS.values():
            snapshot = build()
            thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
            if latest_published(snapshot) is None:
                continue
            for found in change_analysis(snapshot, thresholds).groups:
                assert found.count == len(found.students)

    def test_the_result_index_returns_what_a_scan_would(self) -> None:
        """D-4: the cached index must be indistinguishable from the scan it replaced."""
        for build in b.SCENARIOS.values():
            snapshot = build()
            for student in snapshot.students:
                for assessment in snapshot.assessments:
                    expected = next(
                        (
                            r
                            for r in snapshot.results
                            if r.student_id == student.id and r.assessment_id == assessment.id
                        ),
                        None,
                    )
                    assert snapshot.result_for(student.id, assessment.id) == expected

    def test_the_index_does_not_break_frozen_semantics(self) -> None:
        snapshot = fx.snapshot()
        assert snapshot.result_for(fx.S1, fx.CT1_ID) is not None
        assert hash(snapshot) == hash(fx.snapshot())
        assert snapshot == fx.snapshot()


def _numbers(payload: object) -> list[float]:
    """Every numeric leaf in a serialised payload."""
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [float(payload)]
    if isinstance(payload, dict):
        return [n for value in payload.values() for n in _numbers(value)]
    if isinstance(payload, list):
        return [n for value in payload for n in _numbers(value)]
    return []
