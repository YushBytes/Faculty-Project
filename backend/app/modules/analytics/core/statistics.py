"""F1, F3-F7: group statistics over one assessment, and the primitives behind them.

This module owns the arithmetic every other analytic borrows: the mean, the median, the
standard deviation and the square root. Nothing recomputes them itself, so "the mean" means
one thing across statistics, trends, class health and reports.

Three decisions shape every function here.

*Assessed students only.* A mean is over the students who actually sat the paper. Absent,
exempt and missing students contribute nothing — not a zero — and are reported separately
through :class:`DataCoverage`, which is what makes the number honest rather than flattering.

*Population, not sample, standard deviation.* The cohort is not a sample drawn from a larger
population we want to infer about; it is the whole class. Dividing by ``n - 1`` would answer
a question nobody asked, and would be undefined at ``n = 1``.

*Exact arithmetic.* Everything is ``Decimal``. Percentages are quantized to two decimal
places with half-up rounding at the point they become an output, never mid-calculation, so
a mean of six exact percentages is not a float's approximation of one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.modules.analytics.core.contracts import AssessmentRef, OfferingSnapshot, StudentRef
from app.modules.analytics.core.outputs import (
    AssessmentAnalytics,
    DataCoverage,
    EvidenceItem,
    Explanation,
    ExtremeScore,
)
from app.modules.analytics.core.policy import PERCENT_PRECISION, assessed_scores, classify
from app.modules.analytics.core.results import (
    Measure,
    Unit,
    insufficient_measure,
    measure,
    shortfall,
)

MIN_STD_DEV_POINTS = 2
"""Fewest values before a spread means anything.

Not a configurable threshold: the population standard deviation of one value is
mathematically 0, and reporting "spread: 0.00" for a single student would be true and
useless. Two is where the number starts describing something.
"""

STUDENT_NOUN = "assessed student"
POINT_NOUN = "completed assessment"


def quantize_percent(value: Decimal) -> Decimal:
    """Two decimal places, half-up.

    Half-up rather than banker's rounding, so 66.665 becomes 66.67 every time instead of
    depending on the binary representation underneath.
    """
    return value.quantize(PERCENT_PRECISION, rounding=ROUND_HALF_UP)


def format_marks(value: Decimal) -> str:
    """Marks as they should be read: always two decimal places.

    Stored marks arrive however the platform's ``NUMERIC(5, 2)`` and the import happened to
    quantize them, so "45" and "50.00" can appear in the same assessment. Display text
    normalises them, while the contract keeps the stored value untouched.
    """
    return str(value.quantize(PERCENT_PRECISION, rounding=ROUND_HALF_UP))


def arithmetic_mean(values: Sequence[Decimal]) -> Decimal:
    """The exact, unrounded mean. Callers quantize when they publish it."""
    if not values:
        raise ValueError("cannot take the mean of no values")
    return sum(values, Decimal(0)) / Decimal(len(values))


def median_of(values: Sequence[Decimal]) -> Decimal:
    """The middle value, or the mean of the middle two."""
    if not values:
        raise ValueError("cannot take the median of no values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def population_std_dev(values: Sequence[Decimal]) -> Decimal:
    """Population standard deviation: ``sqrt(sum((x - mean)^2) / n)``.

    See the module docstring for why the population form is the right one here.
    """
    if len(values) < MIN_STD_DEV_POINTS:
        raise ValueError(f"need at least {MIN_STD_DEV_POINTS} values for a standard deviation")
    mean = arithmetic_mean(values)
    variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(len(values))
    return _sqrt(variance)


def _sqrt(value: Decimal) -> Decimal:
    """Square root at extra precision, so the rounding happens once, at the end."""
    if value < 0:
        raise ValueError(f"cannot take the square root of {value}")
    with localcontext() as ctx:
        ctx.prec = 34
        return value.sqrt()


def value_range(values: Sequence[Decimal]) -> Decimal:
    """``max - min``: the plainest statement of spread, and the one a teacher reads first."""
    if not values:
        raise ValueError("cannot take the range of no values")
    return max(values) - min(values)


# ------------------------------------------------------------------ measures over a cohort


def mean_percent(values: Sequence[Decimal], *, noun: str = STUDENT_NOUN) -> Measure:
    """F3: the mean percentage, or insufficient data when nobody was assessed."""
    if not values:
        return insufficient_measure(
            unit=Unit.PERCENT, n=0, minimum_n=1, reason=shortfall(have=0, need=1, noun=noun)
        )
    return measure(
        quantize_percent(arithmetic_mean(values)), unit=Unit.PERCENT, n=len(values), minimum_n=1
    )


def median_percent(values: Sequence[Decimal], *, noun: str = STUDENT_NOUN) -> Measure:
    """F3: the median percentage."""
    if not values:
        return insufficient_measure(
            unit=Unit.PERCENT, n=0, minimum_n=1, reason=shortfall(have=0, need=1, noun=noun)
        )
    return measure(
        quantize_percent(median_of(values)), unit=Unit.PERCENT, n=len(values), minimum_n=1
    )


def std_dev_percentage_points(
    values: Sequence[Decimal], *, minimum_n: int = MIN_STD_DEV_POINTS, noun: str = STUDENT_NOUN
) -> Measure:
    """F4: population standard deviation, in percentage points.

    ``minimum_n`` is a parameter because the gate differs by context: a cohort spread needs
    two values to exist at all, while a *student's* consistency is gated higher by
    ``min_consistency_points`` — three points before "steady" or "volatile" is a fair thing
    to say about someone.
    """
    if len(values) < minimum_n:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=len(values),
            minimum_n=minimum_n,
            reason=shortfall(have=len(values), need=minimum_n, noun=noun),
        )
    return measure(
        quantize_percent(population_std_dev(values)),
        unit=Unit.PERCENTAGE_POINTS,
        n=len(values),
        minimum_n=minimum_n,
    )


def range_percentage_points(
    values: Sequence[Decimal], *, minimum_n: int = MIN_STD_DEV_POINTS, noun: str = STUDENT_NOUN
) -> Measure:
    """F13: ``max - min``, in percentage points."""
    if len(values) < minimum_n:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=len(values),
            minimum_n=minimum_n,
            reason=shortfall(have=len(values), need=minimum_n, noun=noun),
        )
    return measure(
        quantize_percent(value_range(values)),
        unit=Unit.PERCENTAGE_POINTS,
        n=len(values),
        minimum_n=minimum_n,
    )


def pass_percent(values: Sequence[Decimal], pass_mark_percent: Decimal) -> Measure:
    """F6: ``100 * #{P >= pass_mark} / assessed``.

    The denominator is the **assessed** students, not the cohort. Dividing by the cohort
    would fold absence into the pass rate and produce a number that means neither one thing
    nor the other; absence is reported by :func:`completion_percent` instead.

    The comparison is ``>=``: a student who scores exactly the pass mark has passed.
    """
    if not values:
        return insufficient_measure(
            unit=Unit.PERCENT,
            n=0,
            minimum_n=1,
            reason=shortfall(have=0, need=1, noun=STUDENT_NOUN),
        )
    passed = sum(1 for value in values if value >= pass_mark_percent)
    return measure(
        quantize_percent(Decimal(100 * passed) / Decimal(len(values))),
        unit=Unit.PERCENT,
        n=len(values),
        minimum_n=1,
    )


def completion_percent(coverage: DataCoverage) -> Measure:
    """F7: ``100 * assessed / (assessed + absent + missing)``.

    Exempt is excluded from the denominator entirely — the student was not required to sit
    the assessment, so counting it against them would manufacture a completion problem.
    A denominator of zero means everything was exempt, which is not 0% completion.
    """
    denominator = coverage.completion_denominator
    if denominator == 0:
        return insufficient_measure(
            unit=Unit.PERCENT,
            n=0,
            minimum_n=1,
            reason=(
                "no assessment was required of this cohort: every result is exempt, so a "
                "completion percentage has no denominator"
            ),
        )
    return measure(
        quantize_percent(Decimal(100 * coverage.assessed) / Decimal(denominator)),
        unit=Unit.PERCENT,
        n=denominator,
        minimum_n=1,
    )


def extremes(
    scored: Sequence[tuple[StudentRef, Decimal]], *, assessment_code: str | None = None
) -> tuple[ExtremeScore | None, ExtremeScore | None]:
    """F5: the lowest and highest percentage, each with the student who scored it.

    Ties resolve to the **first** student in the snapshot's order, which is stable across
    runs; an arbitrary winner would make two identical reports disagree.
    """
    if not scored:
        return None, None
    lowest = min(scored, key=lambda pair: pair[1])
    highest = max(scored, key=lambda pair: pair[1])
    return (
        ExtremeScore(student=lowest[0], percentage=lowest[1], assessment_code=assessment_code),
        ExtremeScore(student=highest[0], percentage=highest[1], assessment_code=assessment_code),
    )


# ------------------------------------------------------------- reading one assessment


def assessment_coverage(
    snapshot: OfferingSnapshot, assessment: AssessmentRef, *, active_only: bool = True
) -> DataCoverage:
    """Who was assessed, absent, exempt and missing in one assessment."""
    students = snapshot.active_students() if active_only else snapshot.students
    states = []
    for student in students:
        result = snapshot.result_for(student.id, assessment.id)
        states.append(classify(result.status if result else None))
    return DataCoverage.from_states(
        states,
        basis=(
            "active enrolled students in this offering"
            if active_only
            else "all enrolled students in this offering"
        ),
    )


def assessment_analytics(
    snapshot: OfferingSnapshot,
    assessment: AssessmentRef,
    *,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> AssessmentAnalytics:
    """**Contract 1.** Every group statistic for one assessment, with its coverage.

    The pass mark comes from the offering, never from a constant.
    """
    # Imported here, not at module scope: distribution builds on these primitives, so a
    # module-level import would be circular.
    from app.modules.analytics.core.distribution import distribution_of

    stamp = generated_at or datetime.now(UTC)
    pass_mark = snapshot.pass_mark_percent
    scored = assessed_scores(snapshot, assessment, active_only=active_only)
    percentages = tuple(percentage for _, percentage in scored)
    coverage = assessment_coverage(snapshot, assessment, active_only=active_only)

    mean = mean_percent(percentages)
    median = median_percent(percentages)
    spread = std_dev_percentage_points(percentages)
    lowest, highest = extremes(scored, assessment_code=str(assessment.code))
    passing = pass_percent(percentages, pass_mark)
    completion = completion_percent(coverage)
    distribution = distribution_of(
        percentages,
        offering_id=snapshot.offering_id,
        coverage=coverage,
        assessment=assessment,
    )

    return AssessmentAnalytics(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        assessment=assessment,
        pass_mark_percent=pass_mark,
        mean=mean,
        median=median,
        std_dev=spread,
        lowest=lowest,
        highest=highest,
        pass_percent=passing,
        completion_percent=completion,
        distribution=distribution,
        coverage=coverage,
        explanation=_assessment_explanation(
            assessment=assessment,
            coverage=coverage,
            mean=mean,
            passing=passing,
            completion=completion,
            pass_mark=pass_mark,
        ),
    )


def _assessment_explanation(
    *,
    assessment: AssessmentRef,
    coverage: DataCoverage,
    mean: Measure,
    passing: Measure,
    completion: Measure,
    pass_mark: Decimal,
) -> Explanation:
    if mean.is_ok:
        narrative = (
            f"{assessment.code}: mean {mean.value}% across {coverage.assessed} assessed "
            f"students, {passing.value}% of them at or above the offering's pass mark of "
            f"{pass_mark}%. Completion {completion.value}% of "
            f"{coverage.completion_denominator} students required to sit it."
        )
    else:
        narrative = (
            f"{assessment.code}: no student was assessed, so no statistic can be computed. "
            f"{coverage.absent} absent, {coverage.exempt} exempt, {coverage.missing} with no "
            "result recorded. None of these is a score of 0."
        )

    evidence = [
        EvidenceItem(name="Assessed", value=str(coverage.assessed), unit=Unit.COUNT),
        EvidenceItem(
            name="Absent",
            value=str(coverage.absent),
            unit=Unit.COUNT,
            note="excluded from the mean; counted as not completed",
        ),
        EvidenceItem(
            name="Exempt",
            value=str(coverage.exempt),
            unit=Unit.COUNT,
            note="excluded from the mean and from the completion denominator",
        ),
        EvidenceItem(
            name="No result recorded",
            value=str(coverage.missing),
            unit=Unit.COUNT,
            note="excluded from the mean; counted as not completed",
        ),
        EvidenceItem(
            name="Maximum marks", value=format_marks(assessment.max_marks), unit=Unit.MARKS
        ),
    ]

    return Explanation(
        narrative=narrative,
        formula=(
            "P = 100 * score / max_marks; mean/median/population sd over assessed students; "
            "pass% = 100 * #{P >= pass_mark} / assessed; "
            "completion% = 100 * assessed / (assessed + absent + missing)"
        ),
        evidence=tuple(evidence),
        pass_mark_percent=pass_mark,
        assessments_used=(str(assessment.code),),
    )


def assessment_by_id(
    snapshot: OfferingSnapshot, assessment_id: uuid.UUID, *, published_only: bool = True
) -> AssessmentRef:
    """Look one assessment up in a snapshot, or say which offering it is not in."""
    for assessment in snapshot.ordered_assessments(published_only=published_only):
        if assessment.id == assessment_id:
            return assessment
    raise ValueError(f"assessment {assessment_id} is not in this offering snapshot")
