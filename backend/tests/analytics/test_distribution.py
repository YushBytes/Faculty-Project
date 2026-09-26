"""F8: the histogram, and the students who must stay out of it.

The failure this guards against is subtle and would look fine on a chart: an absent student
binned into ``0-9``. Every assertion about who is *not* binned is there for that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.distribution import (
    bin_index,
    bin_percentages,
    distribution_of,
    score_distribution,
)
from app.modules.analytics.core.outputs import HISTOGRAM_BINS, DataCoverage
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def counts(distribution: object) -> dict[str, int]:
    return {f"{b_.lower}-{b_.upper}": b_.count for b_ in distribution.bins if b_.count}  # type: ignore[attr-defined]


class TestBinning:
    @pytest.mark.parametrize(
        ("percentage", "expected"),
        [
            ("0", 0),
            ("9.99", 0),
            ("10", 1),
            ("39.99", 3),
            ("40", 4),
            ("89.99", 8),
            ("90", 9),
            ("99.99", 9),
            ("100", 9),
        ],
    )
    def test_boundaries_land_in_the_bin_above(self, percentage: str, expected: int) -> None:
        assert bin_index(Decimal(percentage)) == expected

    def test_a_perfect_score_is_in_the_top_bin_not_off_the_end(self) -> None:
        assert HISTOGRAM_BINS[bin_index(Decimal("100"))] == (90, 100)

    def test_a_percentage_outside_the_range_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="outside 0-100"):
            bin_index(Decimal("101"))

    def test_shares_are_computed_per_bin(self) -> None:
        bins = bin_percentages([Decimal(v) for v in ("5", "15", "15", "95")])
        assert bins[0].count == 1
        assert bins[0].share_percent == Decimal("25.00")
        assert bins[1].count == 2
        assert bins[1].share_percent == Decimal("50.00")

    def test_thirds_round_to_two_places(self) -> None:
        bins = bin_percentages([Decimal(v) for v in ("5", "15", "25")])
        assert {b_.share_percent for b_ in bins if b_.count} == {Decimal("33.33")}

    def test_an_empty_set_produces_ten_empty_bins(self) -> None:
        bins = bin_percentages([])
        assert len(bins) == 10
        assert all(b_.count == 0 and b_.share_percent == Decimal("0.00") for b_ in bins)


class TestCanonicalDistribution:
    def test_ct1_bins(self) -> None:
        """CT1 assessed: 90, 80, 90, 42, 30, 50."""
        distribution = score_distribution(fx.snapshot(), fx.CT1)
        assert counts(distribution) == {"30-39": 1, "40-49": 1, "50-59": 1, "80-89": 1, "90-100": 2}
        assert distribution.n == 6

    def test_the_absent_student_is_not_in_the_bottom_bin(self) -> None:
        """S6 was absent for CT1. The 0-9 bin must be empty, and coverage must say why."""
        distribution = score_distribution(fx.snapshot(), fx.CT1)
        assert distribution.bins[0].count == 0
        assert distribution.coverage.absent == 1
        assert distribution.n == distribution.coverage.assessed == 6

    def test_exempt_and_missing_students_are_not_binned_either(self) -> None:
        distribution = score_distribution(fx.snapshot(), fx.CT2)
        assert distribution.n == 5
        assert (distribution.coverage.exempt, distribution.coverage.missing) == (1, 1)
        assert sum(b_.count for b_ in distribution.bins) == 5

    def test_counts_always_sum_to_n(self) -> None:
        for assessment in (fx.CT1, fx.CT2, fx.FT1):
            distribution = score_distribution(fx.snapshot(), assessment)
            assert sum(b_.count for b_ in distribution.bins) == distribution.n

    def test_the_explanation_says_how_many_were_left_out(self) -> None:
        distribution = score_distribution(fx.snapshot(), fx.CT2)
        evidence = {item.name: item.value for item in distribution.explanation.evidence}
        assert evidence["Binned"] == "5"
        assert evidence["Not binned"] == "2"


class TestEmptyAndDerivedDistributions:
    def test_nothing_assessed_gives_empty_bins_and_says_so(self) -> None:
        """A whole cohort absent is not a cohort of zeroes stacked in the bottom bin."""
        snapshot = b.build_snapshot({"s1": (b.ABSENT,), "s2": (b.ABSENT,), "s3": (b.MISSING,)})
        distribution = score_distribution(snapshot, snapshot.assessments[0])
        assert distribution.n == 0
        assert all(b_.count == 0 for b_ in distribution.bins)
        assert "nothing to bin" in distribution.explanation.narrative
        assert "0-9" in distribution.explanation.narrative

    def test_a_derived_series_may_be_binned_without_an_assessment(self) -> None:
        """Weighted course scores across a cohort, for example."""
        distribution = distribution_of(
            [Decimal("93.00"), Decimal("55.00"), Decimal("41.00")],
            offering_id=fx.OFFERING_ID,
            coverage=DataCoverage(assessed=3, absent=0, exempt=0, missing=0, basis="test"),
            label="weighted course score",
        )
        assert distribution.assessment is None
        assert counts(distribution) == {"40-49": 1, "50-59": 1, "90-100": 1}
        assert "weighted course score" in distribution.explanation.narrative

    def test_a_coverage_that_disagrees_with_the_values_is_refused(self) -> None:
        """The contract will not let a student go missing between the filter and the chart."""
        with pytest.raises(ValidationError, match="only assessed students are binned"):
            distribution_of(
                [Decimal("50.00")],
                offering_id=fx.OFFERING_ID,
                coverage=DataCoverage(assessed=4, absent=0, exempt=0, missing=0, basis="test"),
            )
