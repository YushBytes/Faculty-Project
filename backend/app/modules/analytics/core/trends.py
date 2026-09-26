"""F9: which way a student's percentages are moving, and how strongly we can say so.

The rule, from docs/ANALYTICS_SPEC.md:

* fewer than ``min_trend_points`` completed assessments -> **insufficient data**, never a label
* exactly two -> the plain difference ``P[-1] - P[-2]``
* three or more -> the least-squares slope, in percentage points per assessment

then ``slope >= +trend_delta_pp`` is Improving, ``slope <= -trend_delta_pp`` is Declining,
and anything between them is Stable. Both comparisons are inclusive: a slope sitting exactly
on the threshold is classified, not shrugged at.

Two things are deliberate and easy to get wrong.

*The method travels with the answer.* A two-point difference and a fitted slope are not the
same kind of evidence, and a reader who cannot tell them apart will over-read the first.
:class:`TrendMethod` is returned so the difference is visible.

*The index is the position in the student's completed series*, 1..n, not the assessment's
``sequence_no``. Two students with different absences would otherwise get slopes on
different x-axes, and a gap would change the slope of the points either side of it, which is
not something the data supports. The trade-off is that the slope is "per completed
assessment" rather than per calendar assessment — which is what the unit says.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import OfferingSnapshot
from app.modules.analytics.core.outputs import (
    DIFFICULTY_CAVEAT,
    EvidenceItem,
    Explanation,
    StudentTrend,
)
from app.modules.analytics.core.policy import StudentSeries, build_student_series
from app.modules.analytics.core.results import (
    Label,
    Measure,
    Unit,
    insufficient_label,
    insufficient_measure,
    label,
    measure,
    shortfall,
)
from app.modules.analytics.core.statistics import POINT_NOUN, arithmetic_mean, quantize_percent
from app.modules.analytics.core.thresholds import (
    ResolvedThreshold,
    ThresholdKey,
    ThresholdSet,
)
from app.modules.analytics.core.vocabulary import TREND_VOCABULARY, TrendLabel, TrendMethod

TWO_POINT_SERIES = 2


def least_squares_slope(values: Sequence[Decimal]) -> Decimal:
    """Slope of the best-fit line through ``(1, P_1) … (n, P_n)``.

    ``slope = sum((i - i_mean) * (P_i - P_mean)) / sum((i - i_mean)^2)``

    The denominator is zero only when every index is the same, which cannot happen for
    ``n >= 2`` distinct positions, so there is no division-by-zero case to guard.
    """
    if len(values) < TWO_POINT_SERIES:
        raise ValueError("a slope needs at least two points")
    indices = [Decimal(i) for i in range(1, len(values) + 1)]
    index_mean = arithmetic_mean(indices)
    value_mean = arithmetic_mean(values)
    numerator = sum(
        ((i - index_mean) * (v - value_mean) for i, v in zip(indices, values, strict=True)),
        Decimal(0),
    )
    denominator = sum(((i - index_mean) ** 2 for i in indices), Decimal(0))
    return numerator / denominator


def trend_slope(values: Sequence[Decimal]) -> tuple[Decimal, TrendMethod]:
    """The slope and the method that produced it, for a series long enough to have one."""
    if len(values) < TWO_POINT_SERIES:
        raise ValueError("a trend needs at least two completed assessments")
    if len(values) == TWO_POINT_SERIES:
        return values[1] - values[0], TrendMethod.TWO_POINT_DELTA
    return least_squares_slope(values), TrendMethod.LEAST_SQUARES


def classify_slope(slope: Decimal, delta: Decimal) -> TrendLabel:
    """Improving / Stable / Declining, with both comparisons inclusive of the threshold."""
    if slope >= delta:
        return TrendLabel.IMPROVING
    if slope <= -delta:
        return TrendLabel.DECLINING
    return TrendLabel.STABLE


def student_trend(
    series: StudentSeries,
    thresholds: ThresholdSet,
    *,
    generated_at: datetime | None = None,
) -> StudentTrend:
    """**Contract 4.** Classify one student's direction of travel, or decline to.

    A single assessment yields no trend — not "stable", which would read as a finding, and
    certainly not "declining". It yields an insufficient-data label naming how many points
    were available and how many are needed.
    """
    stamp = generated_at or datetime.now(UTC)
    percentages = series.percentages
    codes = tuple(point.assessment_code for point in series.assessed_points)
    minimum = thresholds.count(ThresholdKey.MIN_TREND_POINTS)
    delta = thresholds.value(ThresholdKey.TREND_DELTA_PP)
    threshold = thresholds.resolved[ThresholdKey.TREND_DELTA_PP]

    if len(percentages) < minimum:
        reason = shortfall(have=len(percentages), need=minimum, noun=POINT_NOUN)
        return StudentTrend(
            generated_at=stamp,
            offering_id=series.offering_id,
            student_id=series.student_id,
            label=insufficient_label(
                vocabulary=TREND_VOCABULARY,
                n=len(percentages),
                minimum_n=minimum,
                reason=reason,
            ),
            slope=insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT,
                n=len(percentages),
                minimum_n=minimum,
                reason=reason,
            ),
            method=None,
            points_used=codes,
            percentages_used=percentages,
            threshold=threshold,
            explanation=_explanation(
                narrative=(
                    f"{reason.capitalize()}. A direction of travel cannot be read from this, "
                    "so none is reported."
                ),
                codes=codes,
                percentages=percentages,
                threshold=threshold,
                slope=None,
                method=None,
            ),
        )

    raw_slope, method = trend_slope(percentages)
    slope = quantize_percent(raw_slope)
    classification = classify_slope(slope, delta)

    return StudentTrend(
        generated_at=stamp,
        offering_id=series.offering_id,
        student_id=series.student_id,
        label=_label(classification, n=len(percentages), minimum_n=minimum),
        slope=_slope_measure(slope, n=len(percentages), minimum_n=minimum),
        method=method,
        points_used=codes,
        percentages_used=percentages,
        threshold=threshold,
        explanation=_explanation(
            narrative=_narrative(classification, slope, method, codes, percentages, delta),
            codes=codes,
            percentages=percentages,
            threshold=threshold,
            slope=slope,
            method=method,
        ),
    )


def _label(classification: TrendLabel, *, n: int, minimum_n: int) -> Label:
    return label(classification, vocabulary=TREND_VOCABULARY, n=n, minimum_n=minimum_n)


def _slope_measure(slope: Decimal, *, n: int, minimum_n: int) -> Measure:
    return measure(slope, unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT, n=n, minimum_n=minimum_n)


def _narrative(
    classification: TrendLabel,
    slope: Decimal,
    method: TrendMethod,
    codes: Sequence[str],
    percentages: Sequence[Decimal],
    delta: Decimal,
) -> str:
    series = ", ".join(f"{code} {value}%" for code, value in zip(codes, percentages, strict=True))
    how = (
        "Difference between the two completed assessments"
        if method is TrendMethod.TWO_POINT_DELTA
        else f"Least-squares slope across {len(percentages)} completed assessments"
    )
    return (
        f"{how}: {slope} pp per assessment ({series}). "
        f"Classified {classification.value} against a threshold of {delta} pp per assessment."
    )


def _explanation(
    *,
    narrative: str,
    codes: Sequence[str],
    percentages: Sequence[Decimal],
    threshold: ResolvedThreshold,
    slope: Decimal | None,
    method: TrendMethod | None,
) -> Explanation:
    evidence = [
        EvidenceItem(name=code, value=str(value), unit=Unit.PERCENT)
        for code, value in zip(codes, percentages, strict=True)
    ]
    if slope is not None and method is not None:
        evidence.append(
            EvidenceItem(
                name="Method",
                value=method.value,
                note=(
                    "a plain difference between two points, not a fitted line"
                    if method is TrendMethod.TWO_POINT_DELTA
                    else "least-squares fit over the completed series"
                ),
            )
        )
    return Explanation(
        narrative=narrative,
        formula=(
            "n < min_trend_points -> insufficient; n == 2 -> P[-1] - P[-2]; "
            "n >= 3 -> least-squares slope over positions 1..n"
        ),
        evidence=tuple(evidence),
        thresholds=(threshold,),
        assessments_used=tuple(codes),
        caveats=(DIFFICULTY_CAVEAT,),
    )


def trend_for(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> StudentTrend:
    """Convenience: build the student's series from a snapshot, then classify it."""
    series = build_student_series(snapshot, student_id, published_only=published_only)
    return student_trend(series, thresholds, generated_at=generated_at or datetime.now(UTC))
