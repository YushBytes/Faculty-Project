"""The scenario fixtures must actually contain the condition they are named for.

A fixture that has drifted is worse than no fixture: every test built on it still passes
while proving something else. These tests read the built snapshots back through the policy
layer and assert the shape each builder's docstring claims.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.contracts import OfferingSnapshot, ResultStatus
from app.modules.analytics.core.policy import (
    DerivedState,
    assessed_percentages,
    build_student_series,
)
from tests.analytics import builders as b


def series_percentages(snapshot: OfferingSnapshot, key: str) -> tuple[Decimal, ...]:
    return build_student_series(snapshot, b.student_id(key)).percentages


def states(snapshot: OfferingSnapshot, key: str) -> tuple[DerivedState, ...]:
    return tuple(p.state for p in build_student_series(snapshot, b.student_id(key)).points)


class TestBuilderMechanics:
    def test_percentages_in_are_percentages_out(self) -> None:
        """A cell of 60 is 60.00%, exactly, with no rounding anywhere in between."""
        snapshot = b.build_snapshot({"s1": (60, 33, 100)})
        assert series_percentages(snapshot, "s1") == (
            Decimal("60.00"),
            Decimal("33.00"),
            Decimal("100.00"),
        )

    def test_percentages_survive_a_different_maximum(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 90)}, max_marks=50)
        assert series_percentages(snapshot, "s1") == (Decimal("60.00"), Decimal("90.00"))

    def test_a_missing_cell_creates_no_row_at_all(self) -> None:
        """Missing is the absence of data, so there must be nothing to read."""
        snapshot = b.build_snapshot({"s1": (70, b.MISSING, 80)})
        assert len(snapshot.results) == 2
        assert states(snapshot, "s1") == (
            DerivedState.ASSESSED,
            DerivedState.MISSING,
            DerivedState.ASSESSED,
        )

    def test_a_short_row_is_padded_with_missing_not_with_zero(self) -> None:
        snapshot = b.build_snapshot({"s1": (70, 80, 90), "s2": (60,)})
        assert states(snapshot, "s2") == (
            DerivedState.ASSESSED,
            DerivedState.MISSING,
            DerivedState.MISSING,
        )
        assert series_percentages(snapshot, "s2") == (Decimal("60.00"),)

    def test_absent_and_exempt_rows_exist_and_carry_no_score(self) -> None:
        snapshot = b.build_snapshot({"s1": (b.ABSENT, b.EXEMPT)})
        statuses = {r.status: r.score for r in snapshot.results}
        assert statuses == {ResultStatus.ABSENT: None, ResultStatus.EXEMPT: None}

    def test_ids_are_stable_across_builds(self) -> None:
        """Two runs of the same scenario must be comparable."""
        assert b.small_class().students[0].id == b.small_class().students[0].id
        assert b.student_id("s1") != b.student_id("s2")

    def test_the_pass_mark_is_the_offerings_own(self) -> None:
        assert b.build_snapshot({"s1": (40,)}).pass_mark_percent == Decimal("40.00")
        assert b.build_snapshot({"s1": (40,)}, pass_mark=50).pass_mark_percent == Decimal("50")

    def test_a_percentage_outside_zero_to_one_hundred_is_refused(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            b.build_snapshot({"s1": (101,)})


class TestScenarioShapes:
    def test_single_student_has_one_student_and_no_group(self) -> None:
        snapshot = b.single_student()
        assert len(snapshot.active_students()) == 1
        assert series_percentages(snapshot, "s1") == (
            Decimal("70.00"),
            Decimal("74.00"),
            Decimal("78.00"),
        )

    def test_small_class_is_below_the_group_minimum_but_has_two_points(self) -> None:
        snapshot = b.small_class()
        assert len(snapshot.active_students()) == 3
        assert all(len(series_percentages(snapshot, key)) == 2 for key in ("s1", "s2", "s3"))

    def test_multi_assessment_class_hides_its_unpublished_assessment(self) -> None:
        snapshot = b.multi_assessment_class()
        assert len(snapshot.assessments) == 4
        assert tuple(a.code for a in snapshot.ordered_assessments()) == ("CT1", "CT2", "CT3")
        assert series_percentages(snapshot, "s1") == (
            Decimal("88.00"),
            Decimal("90.00"),
            Decimal("92.00"),
        )

    def test_multi_assessment_class_carries_an_absence_and_a_dropout(self) -> None:
        snapshot = b.multi_assessment_class()
        assert states(snapshot, "s5")[1] is DerivedState.ABSENT
        assert states(snapshot, "s6")[2] is DerivedState.MISSING

    def test_missing_results_includes_a_student_with_no_data_anywhere(self) -> None:
        snapshot = b.missing_results()
        s3 = build_student_series(snapshot, b.student_id("s3"))
        assert not s3.has_any_result
        assert s3.percentages == ()
        assert s3.completion_denominator == 3, "a student with no rows is still expected to sit"

    def test_absent_and_exempt_produce_different_denominators(self) -> None:
        """The pair the fixture exists for: same papers sat, different completion."""
        snapshot = b.absent_students()
        absent = build_student_series(snapshot, b.student_id("s2"))
        exempt = build_student_series(snapshot, b.student_id("s3"))
        assert absent.completed_count == exempt.completed_count == 2
        assert absent.completion_denominator == 3
        assert exempt.completion_denominator == 2

    def test_a_wholly_absent_student_has_no_percentages_rather_than_zeroes(self) -> None:
        snapshot = b.absent_students()
        s4 = build_student_series(snapshot, b.student_id("s4"))
        assert s4.percentages == ()
        assert s4.latest_assessed is None
        assert s4.has_any_result, "absence is recorded data, unlike a missing row"

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("s1", ("40.00", "50.00", "60.00")),
            ("s2", ("55.00", "60.00", "65.00")),
            ("s3", ("50.00", "52.00", "54.00")),
            ("s4", ("30.00", "70.00")),
        ],
    )
    def test_improving_students_span_the_trend_threshold(
        self, key: str, expected: tuple[str, ...]
    ) -> None:
        snapshot = b.improving_students()
        assert series_percentages(snapshot, key) == tuple(Decimal(v) for v in expected)

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("s1", ("80.00", "70.00", "60.00")),
            ("s2", ("65.00", "60.00", "55.00")),
            ("s3", ("54.00", "52.00", "50.00")),
            ("s4", ("90.00", "88.00", "50.00")),
        ],
    )
    def test_declining_students_span_the_trend_threshold(
        self, key: str, expected: tuple[str, ...]
    ) -> None:
        snapshot = b.declining_students()
        assert series_percentages(snapshot, key) == tuple(Decimal(v) for v in expected)

    def test_declining_students_include_a_cliff_not_just_a_slope(self) -> None:
        """s4's drop is against its own earlier mean of 89, which is a different rule."""
        percentages = series_percentages(b.declining_students(), "s4")
        earlier_mean = (percentages[0] + percentages[1]) / 2
        assert earlier_mean == Decimal("89.00")
        assert percentages[-1] - earlier_mean == Decimal("-39.00")

    def test_borderline_students_sit_on_the_pass_mark(self) -> None:
        snapshot = b.borderline_students()
        assert snapshot.pass_mark_percent == Decimal("40.00")
        latest = {key: series_percentages(snapshot, key)[-1] for key in ("s1", "s4", "s5")}
        assert latest["s1"] == Decimal("40.00"), "exactly on the mark"
        assert latest["s4"] == Decimal("45.00"), "the upper edge of a 5 pp band"
        assert latest["s5"] == Decimal("50.00"), "clear of the band"

    def test_volatile_students_share_a_mean_and_differ_in_spread(self) -> None:
        snapshot = b.volatile_students()
        for key in ("s1", "s2", "s3"):
            percentages = series_percentages(snapshot, key)
            assert sum(percentages) / len(percentages) == Decimal("60.00")
        assert max(series_percentages(snapshot, "s1")) - min(
            series_percentages(snapshot, "s1")
        ) == Decimal("60.00")
        assert len(set(series_percentages(snapshot, "s2"))) == 1


class TestEveryScenario:
    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_scenario_builds_and_is_internally_consistent(self, name: str) -> None:
        snapshot = b.SCENARIOS[name]()
        assert isinstance(snapshot, OfferingSnapshot)
        for assessment in snapshot.ordered_assessments():
            # Every percentage the cohort exposes is a real, in-range number.
            for percentage in assessed_percentages(snapshot, assessment):
                assert Decimal("0") <= percentage <= Decimal("100")

    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_no_scenario_records_a_score_without_a_present_status(self, name: str) -> None:
        """The one property every fixture must have: absence is never a number."""
        snapshot = b.SCENARIOS[name]()
        for result in snapshot.results:
            if result.status is not ResultStatus.PRESENT:
                assert result.score is None

    def test_the_empty_offering_is_buildable(self) -> None:
        empty = b.empty_offering()
        assert empty.students == ()
        assert empty.assessments == ()
