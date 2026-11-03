"""F2, F7, F10-F13: one student, read through the missing-data policy.

Everything here takes a :class:`StudentSeries` — the student's ordered points across the
offering's published assessments, gaps included — and returns a measure or a contract. The
series already knows which points are assessed, so no function in this module re-derives
"who counts"; that decision lives in :mod:`app.modules.analytics.core.policy` alone.

The recurring theme is that **a student who has not been assessed is not a student who
scored zero**, and the difference has to survive every formula:

* the weighted course score is over *completed* assessments only, so an assessment that has
  not happened yet cannot drag a student down, and an absence does not either;
* completion is the separate number that reports the absences, with exempt assessments out
  of the denominator;
* consistency, decline and the run of low scores all count over completed points, so a gap
  in the middle of a series does not read as a collapse.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import AssessmentRef, OfferingSnapshot, StudentRef
from app.modules.analytics.core.outputs import (
    DataCoverage,
    EvidenceItem,
    Explanation,
    StudentAssessmentPerformance,
    StudentPerformanceHistory,
)
from app.modules.analytics.core.policy import (
    DerivedState,
    SeriesPoint,
    StudentSeries,
    assessed_percentages,
    build_student_series,
)
from app.modules.analytics.core.results import (
    Measure,
    Unit,
    insufficient_measure,
    measure,
    shortfall,
)
from app.modules.analytics.core.statistics import (
    POINT_NOUN,
    arithmetic_mean,
    format_marks,
    mean_percent,
    quantize_percent,
    range_percentage_points,
    std_dev_percentage_points,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet
from app.modules.analytics.core.trends import student_trend

SERIES_BASIS = "published assessments in this offering"

UNWEIGHTED_CAVEAT = (
    "No weightage is configured for any completed assessment in this offering, so they are "
    "counted equally. Set weightages on the assessments to change how the course score is "
    "composed."
)
"""Said out loud whenever the course score falls back to a plain mean; see
:func:`weighted_course_score`."""


def student_ref(snapshot: OfferingSnapshot, student_id: uuid.UUID) -> StudentRef:
    """The student's reference, or a clear error naming the offering they are not in."""
    for student in snapshot.students:
        if student.id == student_id:
            return student
    raise ValueError(f"student {student_id} is not in this offering snapshot")


def series_coverage(series: StudentSeries) -> DataCoverage:
    """The four state counts across this student's published assessments."""
    return DataCoverage.from_states((point.state for point in series.points), basis=SERIES_BASIS)


# ------------------------------------------------------------------------ F2, F7 and friends


def weighted_course_score(series: StudentSeries) -> Measure:
    """F2: ``W = sum(P_a * w_a) / sum(w_a)`` over **completed** assessments only.

    Restricting the sum to completed assessments is what stops a mid-semester score being a
    prediction of the final one: a student who has sat two of four assessments is measured
    on the two they sat.

    Weights come from the assessments themselves and default to 1, which is ordinary equal
    weighting. If every completed assessment carries a weight of 0 there is no weighted
    score to compute — that is a configuration problem, and it is reported as insufficient
    data rather than smoothed over by pretending the weights were equal.
    """
    points = series.assessed_points
    if not points:
        return insufficient_measure(
            unit=Unit.PERCENT,
            n=0,
            minimum_n=1,
            reason=shortfall(have=0, need=1, noun=POINT_NOUN),
        )

    total_weight = sum((point.weightage for point in points), Decimal(0))
    if total_weight == 0:
        # No weighting configured at all: the platform's default weightage is 0, so this is
        # the ordinary state of an offering whose faculty never set them. Declining to answer
        # would withhold a course score from every such class; weighting the assessments
        # equally is the absence of a weighting, not an invented one. The explanation in
        # StudentPerformanceHistory names it, and unweighted_course_score is what it returns.
        return average_percentage(series)

    weighted = sum(
        ((point.percentage or Decimal(0)) * point.weightage for point in points), Decimal(0)
    )
    return measure(
        quantize_percent(weighted / total_weight),
        unit=Unit.PERCENT,
        n=len(points),
        minimum_n=1,
    )


def is_unweighted(series: StudentSeries) -> bool:
    """Whether no completed assessment carries a weight, so the course score is a plain mean."""
    points = series.assessed_points
    return bool(points) and sum((point.weightage for point in points), Decimal(0)) == 0


def average_percentage(series: StudentSeries) -> Measure:
    """The unweighted mean of the student's completed percentages.

    Kept beside the weighted score rather than instead of it: they answer different
    questions, and a report that quoted one as the other would be wrong by exactly the
    amount the weights matter.
    """
    return mean_percent(series.percentages, noun=POINT_NOUN)


def completion_percent(series: StudentSeries) -> Measure:
    """F7 for one student: ``100 * assessed / (assessed + absent + missing)``.

    Exempt assessments leave the denominator entirely.
    """
    denominator = series.completion_denominator
    if denominator == 0:
        return insufficient_measure(
            unit=Unit.PERCENT,
            n=0,
            minimum_n=1,
            reason=(
                "this student was not required to sit any published assessment, so "
                "completion has no denominator"
            ),
        )
    return measure(
        quantize_percent(Decimal(100 * series.completed_count) / Decimal(denominator)),
        unit=Unit.PERCENT,
        n=denominator,
        minimum_n=1,
    )


def consistency(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """F13: population standard deviation of the student's percentages.

    Gated at ``min_consistency_points`` (3 by default) rather than at 2: two points have a
    spread arithmetically, but calling a student "consistent" or "volatile" on the strength
    of two numbers is not something the data supports.
    """
    return std_dev_percentage_points(
        series.percentages,
        minimum_n=thresholds.count(ThresholdKey.MIN_CONSISTENCY_POINTS),
        noun=POINT_NOUN,
    )


def volatility_range(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """F13: ``max - min`` across the student's percentages, in percentage points."""
    return range_percentage_points(
        series.percentages,
        minimum_n=thresholds.count(ThresholdKey.MIN_CONSISTENCY_POINTS),
        noun=POINT_NOUN,
    )


def latest_change(series: StudentSeries) -> Measure:
    """The signed change between the two most recent **completed** assessments.

    Skipping over an absence is deliberate: the question "how did they do compared with last
    time" means the last time they were assessed.
    """
    percentages = series.percentages
    if len(percentages) < 2:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=len(percentages),
            minimum_n=2,
            reason=shortfall(have=len(percentages), need=2, noun=POINT_NOUN),
        )
    return measure(
        quantize_percent(percentages[-1] - percentages[-2]),
        unit=Unit.PERCENTAGE_POINTS,
        n=2,
        minimum_n=2,
    )


def prior_average(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """The mean of the completed assessments **before** the latest one.

    "Prior history" excludes the result being compared against it — otherwise the latest
    assessment is part of its own baseline, which flattens exactly the change anyone is
    looking for. This is the baseline F10 uses, and it is exposed on its own because a
    student profile shows the number as well as the comparison.
    """
    percentages = series.percentages
    minimum = thresholds.count(ThresholdKey.MIN_TREND_POINTS)
    if len(percentages) < minimum:
        return insufficient_measure(
            unit=Unit.PERCENT,
            n=len(percentages),
            minimum_n=minimum,
            reason=shortfall(have=len(percentages), need=minimum, noun=POINT_NOUN),
        )
    return measure(
        quantize_percent(arithmetic_mean(percentages[:-1])),
        unit=Unit.PERCENT,
        n=len(percentages) - 1,
        minimum_n=minimum - 1,
    )


def decline_against_earlier_mean(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """F10: ``drop = P_latest - mean(P over earlier completed assessments)``.

    Signed, and negative when the latest result is the weaker one. The rule that reads this
    (R4) fires when the drop is at or below ``-decline_drop_pp``; the sign convention keeps
    the threshold stored as a positive magnitude and the direction in the comparison.

    The baseline is :func:`prior_average`, so the profile's "historical average" and this
    comparison cannot drift apart.
    """
    percentages = series.percentages
    minimum = thresholds.count(ThresholdKey.MIN_TREND_POINTS)
    baseline = prior_average(series, thresholds)
    if not baseline.is_ok or baseline.value is None:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=len(percentages),
            minimum_n=minimum,
            reason=baseline.reason
            or shortfall(have=len(percentages), need=minimum, noun=POINT_NOUN),
        )
    return measure(
        quantize_percent(percentages[-1] - baseline.value),
        unit=Unit.PERCENTAGE_POINTS,
        n=len(percentages),
        minimum_n=minimum,
    )


def is_sharp_decline(series: StudentSeries, thresholds: ThresholdSet) -> bool | None:
    """Whether F10's drop reaches the configured magnitude. ``None`` when it cannot be known."""
    drop = decline_against_earlier_mean(series, thresholds)
    if not drop.is_ok or drop.value is None:
        return None
    return drop.value <= -thresholds.value(ThresholdKey.DECLINE_DROP_PP)


def repeated_low_run(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """F11: how many of the **most recent** consecutive completed assessments are below pass.

    The trailing run, not the longest run anywhere in the series. A student who was below
    the pass mark three times and has since recovered is not currently in that state, and a
    rule that said otherwise would keep raising a flag about a problem that has passed.
    """
    percentages = series.percentages
    if not percentages:
        return insufficient_measure(
            unit=Unit.COUNT,
            n=0,
            minimum_n=1,
            reason=shortfall(have=0, need=1, noun=POINT_NOUN),
        )
    pass_mark = thresholds.pass_mark_percent
    run = 0
    for percentage in reversed(percentages):
        if percentage >= pass_mark:
            break
        run += 1
    return measure(Decimal(run), unit=Unit.COUNT, n=len(percentages), minimum_n=1)


def is_repeated_low(series: StudentSeries, thresholds: ThresholdSet) -> bool | None:
    """Whether the trailing run reaches ``repeated_low_count``."""
    run = repeated_low_run(series, thresholds)
    if not run.is_ok or run.value is None:
        return None
    return run.value >= thresholds.value(ThresholdKey.REPEATED_LOW_COUNT)


def pass_mark_distance(series: StudentSeries, thresholds: ThresholdSet) -> Measure:
    """F12: signed distance of the weighted course score from the offering's pass mark.

    Positive is above the mark. The borderline band is applied to its magnitude, so a
    student just above and a student just below are both borderline — which is the point.
    """
    score = weighted_course_score(series)
    if not score.is_ok or score.value is None:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=score.n,
            minimum_n=score.minimum_n or 1,
            reason=score.reason or "no weighted course score to compare with the pass mark",
        )
    return measure(
        quantize_percent(score.value - thresholds.pass_mark_percent),
        unit=Unit.PERCENTAGE_POINTS,
        n=score.n,
        minimum_n=score.minimum_n,
    )


def is_borderline(series: StudentSeries, thresholds: ThresholdSet) -> bool | None:
    """Whether the weighted course score sits within the band either side of the pass mark."""
    distance = pass_mark_distance(series, thresholds)
    if not distance.is_ok or distance.value is None:
        return None
    return abs(distance.value) <= thresholds.value(ThresholdKey.BORDERLINE_BAND_PP)


# ------------------------------------------------------- contract 2: one student, one assessment


def student_assessment_performance(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    assessment: AssessmentRef,
    *,
    class_mean: Measure | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> StudentAssessmentPerformance:
    """**Contract 2.** One student in one assessment, with the cohort for context.

    ``class_mean`` may be passed in when a caller is building a whole cohort's worth of
    these, so the assessment's mean is computed once rather than once per student. It is the
    *published* (two-decimal) mean, so the difference quoted here is the difference between
    the two numbers a reader can see.
    """
    stamp = generated_at or datetime.now(UTC)
    student = student_ref(snapshot, student_id)
    series = build_student_series(snapshot, student_id, published_only=False)
    point = next((p for p in series.points if p.assessment_id == assessment.id), None)
    if point is None:
        raise ValueError(f"assessment {assessment.id} is not in this offering snapshot")

    if class_mean is None:
        class_mean = mean_percent(
            assessed_percentages(snapshot, assessment, active_only=active_only)
        )

    pass_mark = snapshot.pass_mark_percent
    if point.state is DerivedState.ASSESSED and point.percentage is not None:
        percentage = measure(point.percentage, unit=Unit.PERCENT, n=1, minimum_n=1)
        difference = _difference_from_mean(point.percentage, class_mean)
        meets_pass_mark: bool | None = point.percentage >= pass_mark
        narrative = (
            f"{assessment.code}: {format_marks(point.score)} of "
            f"{format_marks(assessment.max_marks)} marks "
            f"({point.percentage}%), against a pass mark of {pass_mark}%"
            + (
                f" and a class mean of {class_mean.value}% over {class_mean.n} assessed students."
                if class_mean.is_ok
                else " (no class mean: nobody else was assessed)."
            )
        )
    else:
        percentage = _no_percentage(point, assessment)
        difference = insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=0,
            minimum_n=1,
            reason=f"no percentage to compare: {_state_phrase(point.state, assessment)}",
        )
        meets_pass_mark = None
        narrative = (
            f"{assessment.code}: {_state_phrase(point.state, assessment).capitalize()}. "
            "This is not a score of 0, and it is excluded from every mean."
        )

    return StudentAssessmentPerformance(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        student=student,
        assessment=assessment,
        state=point.state,
        score=point.score,
        max_marks=assessment.max_marks,
        percentage=percentage,
        difference_from_class_mean=difference,
        meets_pass_mark=meets_pass_mark,
        explanation=Explanation(
            narrative=narrative,
            formula="P = 100 * score / max_marks; difference = P - class mean",
            evidence=_performance_evidence(point, class_mean),
            pass_mark_percent=pass_mark,
            assessments_used=(str(assessment.code),),
        ),
    )


def _state_phrase(state: DerivedState, assessment: AssessmentRef) -> str:
    match state:
        case DerivedState.ABSENT:
            return f"recorded absent for {assessment.code}"
        case DerivedState.EXEMPT:
            return f"exempt from {assessment.code}"
        case DerivedState.MISSING:
            return f"no result recorded for {assessment.code}"
        case _:
            return f"assessed in {assessment.code}"


def _no_percentage(point: SeriesPoint, assessment: AssessmentRef) -> Measure:
    return insufficient_measure(
        unit=Unit.PERCENT,
        n=0,
        minimum_n=1,
        reason=f"{_state_phrase(point.state, assessment)}; this is not a score of 0",
    )


def _difference_from_mean(percentage: Decimal, class_mean: Measure) -> Measure:
    if not class_mean.is_ok or class_mean.value is None:
        return insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS,
            n=class_mean.n,
            minimum_n=1,
            reason=class_mean.reason or "no class mean to compare against",
        )
    return measure(
        quantize_percent(percentage - class_mean.value),
        unit=Unit.PERCENTAGE_POINTS,
        n=class_mean.n,
        minimum_n=1,
    )


def _performance_evidence(point: SeriesPoint, class_mean: Measure) -> tuple[EvidenceItem, ...]:
    evidence = [
        EvidenceItem(name="Recorded status", value=point.state.value, note="stored, not derived")
        if point.state is not DerivedState.MISSING
        else EvidenceItem(
            name="Recorded status", value="missing", note="no result row exists for this student"
        ),
        EvidenceItem(name="Maximum marks", value=format_marks(point.max_marks), unit=Unit.MARKS),
    ]
    if point.score is not None:
        evidence.insert(
            0, EvidenceItem(name="Score", value=format_marks(point.score), unit=Unit.MARKS)
        )
    if class_mean.is_ok and class_mean.value is not None:
        evidence.append(
            EvidenceItem(
                name="Class mean",
                value=str(class_mean.value),
                unit=Unit.PERCENT,
                note=f"over {class_mean.n} assessed students",
            )
        )
    return tuple(evidence)


# ----------------------------------------------------- contract 3: one student, whole offering


def student_performance_history(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    published_only: bool = True,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> StudentPerformanceHistory:
    """**Contract 3.** One student's whole story in one offering.

    ``latest`` is the most recent assessment the student was actually **assessed** in, not
    simply the most recent assessment: "latest performance" means the last time there was a
    performance. The gaps are still visible — every published assessment is in ``points``,
    whatever its state.
    """
    _require_matching_pass_mark(snapshot, thresholds)
    stamp = generated_at or datetime.now(UTC)
    student = student_ref(snapshot, student_id)
    series = build_student_series(snapshot, student_id, published_only=published_only)

    score = weighted_course_score(series)
    completion = completion_percent(series)
    spread = consistency(series, thresholds)
    volatility = volatility_range(series, thresholds)
    trend = student_trend(series, thresholds, generated_at=stamp)

    latest_point = series.latest_assessed
    latest = (
        student_assessment_performance(
            snapshot,
            student_id,
            assessment_for(snapshot, latest_point.assessment_id),
            active_only=active_only,
            generated_at=stamp,
        )
        if latest_point is not None
        else None
    )

    return StudentPerformanceHistory(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        student=student,
        points=series.points,
        weighted_course_score=score,
        completion_percent=completion,
        consistency_std_dev=spread,
        volatility_range=volatility,
        trend=trend,
        latest=latest,
        coverage=series_coverage(series),
        explanation=_history_explanation(
            series=series,
            thresholds=thresholds,
            score=score,
            completion=completion,
            spread=spread,
        ),
    )


def assessment_for(snapshot: OfferingSnapshot, assessment_id: uuid.UUID) -> AssessmentRef:
    """The assessment's reference, by id, published or not."""
    for assessment in snapshot.assessments:
        if assessment.id == assessment_id:
            return assessment
    raise ValueError(f"assessment {assessment_id} is not in this offering snapshot")


def _require_matching_pass_mark(snapshot: OfferingSnapshot, thresholds: ThresholdSet) -> None:
    """Catch a threshold set resolved against a different offering's pass mark.

    Silent disagreement here would put one pass mark in the explanation and apply another in
    the arithmetic, which is the single most misleading thing this layer could do.
    """
    if thresholds.pass_mark_percent != snapshot.pass_mark_percent:
        raise ValueError(
            f"thresholds were resolved against a pass mark of {thresholds.pass_mark_percent}% "
            f"but this offering's is {snapshot.pass_mark_percent}%"
        )


def _history_explanation(
    *,
    series: StudentSeries,
    thresholds: ThresholdSet,
    score: Measure,
    completion: Measure,
    spread: Measure,
) -> Explanation:
    coverage = series_coverage(series)
    unweighted = is_unweighted(series)
    contributions = ", ".join(
        f"{point.assessment_code} {point.percentage}%"
        + ("" if unweighted else f" (weight {point.weightage})")
        for point in series.assessed_points
    )

    if score.is_ok:
        narrative = (
            f"{'Course score (unweighted)' if unweighted else 'Weighted course score'} "
            f"{score.value}% over {score.n} completed "
            f"{'assessment' if score.n == 1 else 'assessments'} ({contributions}). "
            f"Completion {completion.value}% of {completion.n} required "
            f"{'assessment' if completion.n == 1 else 'assessments'}. "
            f"Pass mark {thresholds.pass_mark_percent}%."
        )
    else:
        narrative = (
            "This student has no completed assessment in this offering, so no course score "
            f"can be computed. {coverage.absent} absent, {coverage.exempt} exempt, "
            f"{coverage.missing} with no result recorded — none of which is a score of 0."
        )

    evidence = [
        EvidenceItem(
            name=point.assessment_code,
            value=str(point.percentage) if point.percentage is not None else point.state.value,
            unit=Unit.PERCENT if point.percentage is not None else None,
            note=None if point.state is DerivedState.ASSESSED else "no percentage: not assessed",
        )
        for point in series.points
    ]
    evidence.append(
        EvidenceItem(
            name="Completion denominator",
            value=str(series.completion_denominator),
            unit=Unit.COUNT,
            note=f"{coverage.exempt} exempt assessment(s) excluded",
        )
    )
    if spread.is_ok:
        evidence.append(
            EvidenceItem(
                name="Consistency (population sd)",
                value=str(spread.value),
                unit=Unit.PERCENTAGE_POINTS,
            )
        )

    caveats: tuple[str, ...] = ()
    if is_unweighted(series):
        caveats = (UNWEIGHTED_CAVEAT,)

    return Explanation(
        narrative=narrative,
        formula=(
            "W = sum(P_a * w_a) / sum(w_a) over completed assessments; "
            "completion% = 100 * assessed / (assessed + absent + missing)"
        ),
        evidence=tuple(evidence),
        thresholds=(thresholds.resolved[ThresholdKey.MIN_CONSISTENCY_POINTS],),
        pass_mark_percent=thresholds.pass_mark_percent,
        assessments_used=tuple(point.assessment_code for point in series.assessed_points),
        caveats=caveats,
    )


def cohort_histories(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[StudentPerformanceHistory, ...]:
    """Every student's history, in the snapshot's student order."""
    stamp = generated_at or datetime.now(UTC)
    students: Sequence[StudentRef] = (
        snapshot.active_students() if active_only else snapshot.students
    )
    return tuple(
        student_performance_history(
            snapshot,
            student.id,
            thresholds,
            published_only=published_only,
            active_only=active_only,
            generated_at=stamp,
        )
        for student in students
    )
