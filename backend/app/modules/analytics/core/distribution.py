"""F8: the score distribution — ten fixed bins, and who is not in them.

The bins are fixed rather than derived from the data (``0-9, 10-19, … 90-100``), because a
histogram whose buckets move with the cohort cannot be compared between two assessments,
which is the main thing anyone wants to do with one.

Only **assessed** students are binned. An absent student has no percentage, so binning them
would mean putting them in ``0-9``, which is the exact mistake the whole missing-data policy
exists to prevent. They are reported alongside, in ``coverage``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from app.modules.analytics.core.contracts import AssessmentRef, OfferingSnapshot
from app.modules.analytics.core.outputs import (
    HISTOGRAM_BINS,
    DataCoverage,
    DistributionBin,
    EvidenceItem,
    Explanation,
    ScoreDistribution,
)
from app.modules.analytics.core.policy import assessed_scores
from app.modules.analytics.core.results import Unit
from app.modules.analytics.core.statistics import assessment_coverage, quantize_percent

BIN_WIDTH = 10


def bin_index(percentage: Decimal) -> int:
    """Which of the ten bins a percentage falls in.

    The top bin is ``90-100`` rather than ``90-99``: a perfect score is not an out-of-range
    value, and it must not fall off the end of the chart.
    """
    if not Decimal("0") <= percentage <= Decimal("100"):
        raise ValueError(f"percentage {percentage} is outside 0-100 and cannot be binned")
    return min(int(percentage // BIN_WIDTH), len(HISTOGRAM_BINS) - 1)


def bin_percentages(values: Sequence[Decimal]) -> tuple[DistributionBin, ...]:
    """Count the values into the canonical ten bins, with each bin's share of ``n``."""
    counts = [0] * len(HISTOGRAM_BINS)
    for value in values:
        counts[bin_index(value)] += 1

    total = len(values)
    return tuple(
        DistributionBin(
            lower=lower,
            upper=upper,
            count=count,
            share_percent=(
                quantize_percent(Decimal(100 * count) / Decimal(total))
                if total
                else Decimal("0.00")
            ),
        )
        for (lower, upper), count in zip(HISTOGRAM_BINS, counts, strict=True)
    )


def distribution_of(
    values: Sequence[Decimal],
    *,
    offering_id: uuid.UUID,
    coverage: DataCoverage,
    assessment: AssessmentRef | None = None,
    label: str | None = None,
) -> ScoreDistribution:
    """**Contract 6.** Bin a set of percentages that has already been filtered.

    ``assessment`` is ``None`` when the distribution is over a derived series — weighted
    course scores across a cohort, say — in which case ``label`` names what was binned.
    ``coverage.assessed`` must equal ``len(values)``; the contract enforces it, so a
    distribution cannot quietly lose or gain a student between the filter and the chart.
    """
    bins = bin_percentages(values)
    subject = str(assessment.code) if assessment else (label or "the cohort")
    occupied = [b for b in bins if b.count]

    if values:
        narrative = (
            f"{subject}: {len(values)} assessed "
            f"{'student' if len(values) == 1 else 'students'} across "
            f"{len(occupied)} of 10 bins ("
            + ", ".join(f"{b.lower}-{b.upper}: {b.count}" for b in occupied)
            + ")."
        )
    else:
        narrative = (
            f"{subject}: no student was assessed, so there is nothing to bin. "
            f"{coverage.absent} absent, {coverage.exempt} exempt, {coverage.missing} with no "
            "result recorded — none of which is a score in the 0-9 bin."
        )

    return ScoreDistribution(
        offering_id=offering_id,
        assessment=assessment,
        bins=bins,
        n=len(values),
        coverage=coverage,
        explanation=Explanation(
            narrative=narrative,
            formula="ten fixed bins of 10 percentage points; 90-100 inclusive of 100",
            evidence=(
                EvidenceItem(name="Binned", value=str(len(values)), unit=Unit.COUNT),
                EvidenceItem(
                    name="Not binned",
                    value=str(coverage.considered - coverage.assessed),
                    unit=Unit.COUNT,
                    note="absent, exempt or no result recorded: they have no percentage",
                ),
            ),
            assessments_used=(str(assessment.code),) if assessment else (),
        ),
    )


def score_distribution(
    snapshot: OfferingSnapshot,
    assessment: AssessmentRef,
    *,
    active_only: bool = True,
) -> ScoreDistribution:
    """**Contract 6** for one assessment, read straight from a snapshot."""
    scored = assessed_scores(snapshot, assessment, active_only=active_only)
    return distribution_of(
        tuple(percentage for _, percentage in scored),
        offering_id=snapshot.offering_id,
        coverage=assessment_coverage(snapshot, assessment, active_only=active_only),
        assessment=assessment,
    )
