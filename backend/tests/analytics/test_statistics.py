"""F3-F7: group statistics, against numbers worked out by hand.

Every expected value in this file was computed by hand from the canonical fixture and is
shown in the test or its docstring, so a failure is a disagreement about arithmetic rather
than a disagreement with whatever the code happened to produce last time.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.outputs import DataCoverage
from app.modules.analytics.core.policy import assessed_percentages
from app.modules.analytics.core.results import MeasureStatus, Unit
from app.modules.analytics.core.statistics import (
    arithmetic_mean,
    assessment_analytics,
    assessment_coverage,
    completion_percent,
    extremes,
    mean_percent,
    median_of,
    median_percent,
    pass_percent,
    population_std_dev,
    quantize_percent,
    std_dev_percentage_points,
    value_range,
)
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def dec(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


class TestPrimitives:
    def test_mean_is_exact_not_floating(self) -> None:
        """0.1 + 0.2 arithmetic must not leak into an academic average."""
        assert arithmetic_mean(dec("0.1", "0.2")) == Decimal("0.15")

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (("50",), "50"),
            (("40", "60"), "50"),
            (("30", "42", "50", "80", "90", "90"), "65"),
            (("32", "40", "60", "88", "92"), "60"),
        ],
    )
    def test_median_of_odd_and_even_series(self, values: tuple[str, ...], expected: str) -> None:
        assert median_of(dec(*values)) == Decimal(expected)

    def test_standard_deviation_is_the_population_form(self) -> None:
        """Population sd of 80, 60, 40 is sqrt(800/3) = 16.3299...; the sample form is 20."""
        assert quantize_percent(population_std_dev(dec("80", "60", "40"))) == Decimal("16.33")

    def test_identical_values_have_no_spread(self) -> None:
        assert population_std_dev(dec("60", "60", "60")) == Decimal("0")
        assert value_range(dec("60", "60", "60")) == Decimal("0")

    def test_a_single_value_has_no_standard_deviation(self) -> None:
        """Not 0: one student is not a spread of zero, it is no spread at all."""
        with pytest.raises(ValueError, match="at least 2 values"):
            population_std_dev(dec("60"))

    def test_the_mean_of_nothing_is_an_error_not_a_zero(self) -> None:
        with pytest.raises(ValueError, match="mean of no values"):
            arithmetic_mean([])

    def test_rounding_is_half_up(self) -> None:
        """66.665 -> 66.67 every time, not "sometimes, depending on the bits"."""
        assert quantize_percent(Decimal("66.665")) == Decimal("66.67")
        assert quantize_percent(Decimal("66.675")) == Decimal("66.68")


class TestMeasuresOverACohort:
    def test_an_empty_cohort_returns_insufficient_data_not_zero(self) -> None:
        for withheld in (mean_percent([]), median_percent([]), pass_percent([], Decimal("40"))):
            assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
            assert withheld.value is None
            assert withheld.n == 0
            assert "0 assessed students" in (withheld.reason or "")

    def test_standard_deviation_needs_two_values(self) -> None:
        withheld = std_dev_percentage_points(dec("60"))
        assert withheld.status is MeasureStatus.INSUFFICIENT_DATA
        assert withheld.minimum_n == 2
        assert withheld.unit is Unit.PERCENTAGE_POINTS

    def test_the_pass_mark_is_inclusive(self) -> None:
        """A student who scores exactly the pass mark has passed."""
        assert pass_percent(dec("40"), Decimal("40")).value == Decimal("100.00")
        assert pass_percent(dec("39.99"), Decimal("40")).value == Decimal("0.00")

    def test_pass_rate_is_over_assessed_students_not_the_cohort(self) -> None:
        """Absence belongs in completion, not in the pass rate."""
        passing = pass_percent(dec("80", "80", "20"), Decimal("40"))
        assert passing.value == Decimal("66.67")
        assert passing.n == 3

    def test_completion_excludes_exempt_from_the_denominator(self) -> None:
        coverage = DataCoverage(assessed=2, absent=1, exempt=3, missing=1, basis="test")
        completion = completion_percent(coverage)
        assert completion.n == 4, "exempt assessments leave the denominator"
        assert completion.value == Decimal("50.00")

    def test_completion_of_an_entirely_exempt_cohort_is_not_zero_percent(self) -> None:
        coverage = DataCoverage(assessed=0, absent=0, exempt=4, missing=0, basis="test")
        completion = completion_percent(coverage)
        assert completion.status is MeasureStatus.INSUFFICIENT_DATA
        assert "no denominator" in (completion.reason or "")

    def test_extremes_carry_the_student(self) -> None:
        snapshot = b.small_class()
        scored = tuple(
            (student, percentage)
            for student, percentage in zip(snapshot.students, dec("60", "40", "80"), strict=True)
        )
        lowest, highest = extremes(scored, assessment_code="CT1")
        assert lowest is not None and highest is not None
        assert (lowest.percentage, lowest.student.register_no) == (Decimal("40"), "RA0002")
        assert (highest.percentage, highest.student.register_no) == (Decimal("80"), "RA0003")
        assert highest.assessment_code == "CT1"

    def test_a_tie_resolves_to_the_first_student_in_cohort_order(self) -> None:
        """Stable, so two runs of the same report name the same student."""
        snapshot = b.small_class()
        scored = tuple(zip(snapshot.students, dec("90", "90", "10"), strict=True))
        _, highest = extremes(scored)
        assert highest is not None
        assert highest.student.register_no == "RA0001"

    def test_extremes_of_nobody_are_none(self) -> None:
        assert extremes(()) == (None, None)


class TestCanonicalAssessments:
    """Hand-computed from tests/analytics/canonical.py, pass mark 40.

    CT1 assessed (active): 90, 80, 90, 42, 30, 50   -> sum 382, n 6
    CT2 assessed (active): 92, 60, 88, 40, 32       -> sum 312, n 5 (S6 exempt, S7 missing)
    FT1 assessed (active): 95, 40, 50, 41, 35, 60   -> sum 321, n 6 (S7 missing)
    """

    @pytest.mark.parametrize(
        ("assessment", "expected"),
        [
            (fx.CT1, ("63.67", "65.00", "23.96", "83.33", "85.71", 6)),
            (fx.CT2, ("62.40", "60.00", "24.34", "80.00", "83.33", 5)),
            (fx.FT1, ("53.50", "45.50", "20.24", "83.33", "85.71", 6)),
        ],
        ids=["CT1", "CT2", "FT1"],
    )
    def test_every_group_statistic(
        self, assessment: object, expected: tuple[str, str, str, str, str, int]
    ) -> None:
        mean, median, sd, passing, completion, n = expected
        analytics = assessment_analytics(fx.snapshot(), assessment)  # type: ignore[arg-type]
        assert analytics.mean.value == Decimal(mean)
        assert analytics.median.value == Decimal(median)
        assert analytics.std_dev.value == Decimal(sd)
        assert analytics.pass_percent.value == Decimal(passing)
        assert analytics.completion_percent.value == Decimal(completion)
        assert analytics.mean.n == n

    def test_ct1_mean_is_382_over_6(self) -> None:
        """Stated as the arithmetic, so the expected value above is reviewable."""
        assert quantize_percent(Decimal(382) / Decimal(6)) == Decimal("63.67")

    def test_ct1_extremes(self) -> None:
        analytics = assessment_analytics(fx.snapshot(), fx.CT1)
        assert analytics.lowest is not None and analytics.highest is not None
        assert analytics.lowest.percentage == Decimal("30.00")
        assert analytics.lowest.student.id == fx.S5
        assert analytics.highest.percentage == Decimal("90.00")
        assert analytics.highest.student.id == fx.S1, "S1 and S3 tie at 90; first wins"

    def test_ct1_coverage_counts_every_state(self) -> None:
        """S6 was absent; S1-S5 and S7 sat it; S8 is inactive and out of the cohort."""
        coverage = assessment_coverage(fx.snapshot(), fx.CT1)
        assert (coverage.assessed, coverage.absent, coverage.exempt, coverage.missing) == (
            6,
            1,
            0,
            0,
        )
        assert coverage.completion_denominator == 7

    def test_ct2_coverage_separates_exempt_from_missing(self) -> None:
        coverage = assessment_coverage(fx.snapshot(), fx.CT2)
        assert (coverage.assessed, coverage.absent, coverage.exempt, coverage.missing) == (
            5,
            0,
            1,
            1,
        )
        assert coverage.completion_denominator == 6, "the exempt student leaves the denominator"

    def test_inactive_students_are_outside_the_cohort(self) -> None:
        """S8 scored 60 in CT1; including them would move the mean."""
        active = assessment_analytics(fx.snapshot(), fx.CT1).mean.value
        everyone = assessment_analytics(fx.snapshot(), fx.CT1, active_only=False).mean.value
        assert active == Decimal("63.67")
        assert everyone == Decimal("63.14"), "(382 + 60) / 7"

    def test_the_unpublished_assessment_is_not_read_by_default(self) -> None:
        """S1 has a result for the unpublished quiz; it must not reach a statistic."""
        assert assessed_percentages(fx.snapshot(), fx.QUIZ1) == (Decimal("90.00"),)
        published = [a.code for a in fx.snapshot().ordered_assessments()]
        assert "QUIZ1" not in published

    def test_the_pass_mark_is_never_assumed(self) -> None:
        """The same data against a pass mark of 50 gives a different pass rate."""
        at_forty = assessment_analytics(fx.snapshot(), fx.CT1)
        at_fifty = assessment_analytics(fx.snapshot(pass_mark=Decimal("50")), fx.CT1)
        assert at_forty.pass_percent.value == Decimal("83.33"), "5 of 6 reach 40"
        assert at_fifty.pass_percent.value == Decimal("66.67"), "4 of 6 reach 50"
        assert at_fifty.pass_mark_percent == Decimal("50")

    def test_the_explanation_names_the_states_it_excluded(self) -> None:
        analytics = assessment_analytics(fx.snapshot(), fx.CT2)
        evidence = {item.name: item.value for item in analytics.explanation.evidence}
        assert evidence["Assessed"] == "5"
        assert evidence["Exempt"] == "1"
        assert evidence["No result recorded"] == "1"
        assert "62.40" in analytics.explanation.narrative
        assert analytics.explanation.pass_mark_percent == Decimal("40.00")

    def test_the_contract_carries_its_distribution(self) -> None:
        analytics = assessment_analytics(fx.snapshot(), fx.CT1)
        assert analytics.distribution.n == 6
        assert analytics.distribution.assessment is not None
        assert analytics.distribution.assessment.code == "CT1"
