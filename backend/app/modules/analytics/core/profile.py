"""Student performance intelligence: Phase 2's measures, composed into one answer.

Phase 2 answers "what is this student's standard deviation?". This module answers the
question a teacher actually asks — *how is this student doing over time?* — and it does so
**without computing anything of its own**. Every number in a
:class:`StudentPerformanceProfile` comes from a Phase 2 function, so a profile and a bare
measure can never disagree; what is added here is composition, comparison and wording.

The shape of the answer::

    history      the whole series, with its gaps, plus the course score, completion,
                 consistency, volatility and trend
    latest       the most recent assessment the student was assessed in
    previous     the one before that, skipping absences
    change       latest - previous, in percentage POINTS
    baseline     the mean of the work before the latest one, and the change against it
    findings     the conditions this series satisfies, each with its evidence

Two distinctions the module exists to keep straight.

*Percentage points, not percent.* A move from 40% to 44% is +4 pp. Calling it "+10%" is a
different, true, and unhelpful statement, and mixing the two is how a report ends up wrong.

*A finding is not a flag.* :class:`StudentFinding` says what the numbers do. Whether anyone
should act on it — with a severity, a message and a lifecycle — is the attention engine's
decision, and it reads these same measures. Keeping them apart means a profile can show
"below the pass mark three times running" without asserting that it is an emergency.

Nothing here classifies on thin data. Where a comparison needs two completed assessments and
there is one, the profile says so, with the count: ``detected`` is ``None``, never ``False``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import AssessmentRef, OfferingSnapshot, StudentRef
from app.modules.analytics.core.outputs import (
    EvidenceItem,
    Explanation,
    StudentAssessmentPerformance,
    StudentFinding,
    StudentPerformanceHistory,
    StudentPerformanceProfile,
)
from app.modules.analytics.core.policy import SeriesPoint, StudentSeries, build_student_series
from app.modules.analytics.core.results import Measure, Unit
from app.modules.analytics.core.student import (
    assessment_for,
    decline_against_earlier_mean,
    latest_change,
    prior_average,
    repeated_low_run,
    student_assessment_performance,
    student_performance_history,
    student_ref,
)
from app.modules.analytics.core.thresholds import ResolvedThreshold, ThresholdKey, ThresholdSet
from app.modules.analytics.core.vocabulary import StudentFindingCode


def _series_evidence(series: StudentSeries) -> tuple[EvidenceItem, ...]:
    """The completed series, as evidence. The same list under every finding."""
    return tuple(
        EvidenceItem(name=point.assessment_code, value=str(point.percentage), unit=Unit.PERCENT)
        for point in series.assessed_points
    )


def _undetermined(
    code: StudentFindingCode,
    measure: Measure,
    *,
    threshold: ResolvedThreshold | None,
    pass_mark_percent: Decimal | None,
    series: StudentSeries,
    what: str,
) -> StudentFinding:
    """A finding that could not be evaluated, saying what it would have needed."""
    return StudentFinding(
        code=code,
        detected=None,
        measure=measure,
        threshold=threshold,
        pass_mark_percent=pass_mark_percent,
        explanation=Explanation(
            narrative=f"{what} cannot be assessed: {measure.reason}.",
            evidence=_series_evidence(series),
            thresholds=(threshold,) if threshold else (),
            pass_mark_percent=pass_mark_percent,
            assessments_used=tuple(p.assessment_code for p in series.assessed_points),
        ),
    )


# ------------------------------------------------------------------------------- findings


def sharp_decline_finding(series: StudentSeries, thresholds: ThresholdSet) -> StudentFinding:
    """F10 as a finding: is the latest result far below the student's earlier work?

    The comparison is against the mean of the *earlier* assessments, not against the whole
    series. It fires only when the fall reaches the configured magnitude — being a little
    below your own average is ordinary, and calling that a decline would flag most of a class
    most of the time.
    """
    drop = decline_against_earlier_mean(series, thresholds)
    threshold = thresholds.resolved[ThresholdKey.DECLINE_DROP_PP]
    if not drop.is_ok or drop.value is None:
        return _undetermined(
            StudentFindingCode.SHARP_DECLINE,
            drop,
            threshold=threshold,
            pass_mark_percent=None,
            series=series,
            what="A sharp decline",
        )

    baseline = prior_average(series, thresholds)
    latest = series.percentages[-1]
    detected = drop.value <= -threshold.value
    earlier = tuple(p.assessment_code for p in series.assessed_points[:-1])
    narrative = (
        f"Latest {series.assessed_points[-1].assessment_code} {latest}% against a mean of "
        f"{baseline.value}% across {baseline.n} earlier "
        f"{'assessment' if baseline.n == 1 else 'assessments'} "
        f"({', '.join(earlier)}): {drop.value} pp. "
        + (
            f"That reaches the configured drop of {threshold.value} pp."
            if detected
            else f"That does not reach the configured drop of {threshold.value} pp."
        )
    )
    return StudentFinding(
        code=StudentFindingCode.SHARP_DECLINE,
        detected=detected,
        measure=drop,
        threshold=threshold,
        explanation=Explanation(
            narrative=narrative,
            formula="drop = P_latest - mean(P over earlier completed assessments)",
            evidence=(
                *_series_evidence(series),
                EvidenceItem(
                    name="Mean of earlier assessments",
                    value=str(baseline.value),
                    unit=Unit.PERCENT,
                    note=f"over {baseline.n} completed, excluding the latest",
                ),
            ),
            thresholds=(threshold,),
            assessments_used=tuple(p.assessment_code for p in series.assessed_points),
        ),
    )


def repeated_low_finding(series: StudentSeries, thresholds: ThresholdSet) -> StudentFinding:
    """F11 as a finding: how many assessments in a row, up to now, are below the pass mark.

    The run is the trailing one, so a student who has recovered is not reported as still in
    it. Absent, exempt and missing assessments are not low scores; they are simply not part
    of the run, and they do not break it either.
    """
    run = repeated_low_run(series, thresholds)
    threshold = thresholds.resolved[ThresholdKey.REPEATED_LOW_COUNT]
    pass_mark = thresholds.pass_mark_percent
    if not run.is_ok or run.value is None:
        return _undetermined(
            StudentFindingCode.REPEATED_LOW,
            run,
            threshold=threshold,
            pass_mark_percent=pass_mark,
            series=series,
            what="A run below the pass mark",
        )

    length = int(run.value)
    detected = run.value >= threshold.value
    recent = series.assessed_points[len(series.assessed_points) - length :] if length else ()
    if length:
        listed = ", ".join(f"{p.assessment_code} {p.percentage}%" for p in recent)
        narrative = (
            f"Below the {pass_mark}% pass mark in the last {length} completed "
            f"{'assessment' if length == 1 else 'assessments'} ({listed}). "
            f"The configured run length is {int(threshold.value)}."
        )
    else:
        latest_point = series.assessed_points[-1]
        narrative = (
            f"Not currently below the {pass_mark}% pass mark: the latest completed "
            f"assessment, {latest_point.assessment_code}, is {latest_point.percentage}%."
        )
    return StudentFinding(
        code=StudentFindingCode.REPEATED_LOW,
        detected=detected,
        measure=run,
        threshold=threshold,
        pass_mark_percent=pass_mark,
        explanation=Explanation(
            narrative=narrative,
            formula="count back from the latest completed assessment while P < pass_mark",
            evidence=_series_evidence(series),
            thresholds=(threshold,),
            pass_mark_percent=pass_mark,
            assessments_used=tuple(p.assessment_code for p in recent),
        ),
    )


def improvement_finding(series: StudentSeries, thresholds: ThresholdSet) -> StudentFinding:
    """F14 for one student: is the latest completed assessment up on the previous one?

    Measured between the two most recent **completed** assessments, so an absence in between
    does not count as a collapse and then a recovery. It is a fact about one student, not a
    ranking: comparing students' improvements against each other is the cohort's business
    (most improved), and belongs to a later phase.
    """
    change = latest_change(series)
    threshold = thresholds.resolved[ThresholdKey.IMPROVEMENT_DELTA_PP]
    if not change.is_ok or change.value is None:
        return _undetermined(
            StudentFindingCode.IMPROVEMENT,
            change,
            threshold=threshold,
            pass_mark_percent=None,
            series=series,
            what="An improvement",
        )

    latest_point, previous_point = series.assessed_points[-1], series.assessed_points[-2]
    detected = change.value >= threshold.value
    narrative = (
        f"{previous_point.assessment_code} {previous_point.percentage}% to "
        f"{latest_point.assessment_code} {latest_point.percentage}%: "
        f"{'+' if change.value > 0 else ''}{change.value} pp. "
        + (
            f"That reaches the configured improvement of {threshold.value} pp."
            if detected
            else f"That does not reach the configured improvement of {threshold.value} pp."
        )
    )
    return StudentFinding(
        code=StudentFindingCode.IMPROVEMENT,
        detected=detected,
        measure=change,
        threshold=threshold,
        explanation=Explanation(
            narrative=narrative,
            formula="change = P_latest - P_previous over completed assessments",
            evidence=(
                EvidenceItem(
                    name=previous_point.assessment_code,
                    value=str(previous_point.percentage),
                    unit=Unit.PERCENT,
                ),
                EvidenceItem(
                    name=latest_point.assessment_code,
                    value=str(latest_point.percentage),
                    unit=Unit.PERCENT,
                ),
            ),
            thresholds=(threshold,),
            assessments_used=(previous_point.assessment_code, latest_point.assessment_code),
        ),
    )


def student_findings(series: StudentSeries, thresholds: ThresholdSet) -> tuple[StudentFinding, ...]:
    """Every condition, evaluated in a fixed order so two profiles are comparable."""
    return (
        sharp_decline_finding(series, thresholds),
        repeated_low_finding(series, thresholds),
        improvement_finding(series, thresholds),
    )


# -------------------------------------------------------------------------------- profile


def _performance_for(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    point: SeriesPoint | None,
    *,
    active_only: bool,
    stamp: datetime,
) -> StudentAssessmentPerformance | None:
    if point is None:
        return None
    assessment: AssessmentRef = assessment_for(snapshot, point.assessment_id)
    return student_assessment_performance(
        snapshot, student_id, assessment, active_only=active_only, generated_at=stamp
    )


def student_profile(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    published_only: bool = True,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> StudentPerformanceProfile:
    """**Contract 12.** One student's performance intelligence for one offering."""
    stamp = generated_at or datetime.now(UTC)
    student: StudentRef = student_ref(snapshot, student_id)
    series = build_student_series(snapshot, student_id, published_only=published_only)
    history = student_performance_history(
        snapshot,
        student_id,
        thresholds,
        published_only=published_only,
        active_only=active_only,
        generated_at=stamp,
    )

    assessed = series.assessed_points
    latest = _performance_for(
        snapshot,
        student_id,
        assessed[-1] if assessed else None,
        active_only=active_only,
        stamp=stamp,
    )
    previous = _performance_for(
        snapshot,
        student_id,
        assessed[-2] if len(assessed) >= 2 else None,
        active_only=active_only,
        stamp=stamp,
    )

    change = latest_change(series)
    baseline = prior_average(series, thresholds)
    against_baseline = decline_against_earlier_mean(series, thresholds)
    findings = student_findings(series, thresholds)

    return StudentPerformanceProfile(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        student=student,
        history=history,
        latest=latest,
        previous=previous,
        change_from_previous=change,
        historical_average=baseline,
        change_from_historical_average=against_baseline,
        findings=findings,
        explanation=_profile_explanation(
            series=series,
            thresholds=thresholds,
            history=history,
            change=change,
            baseline=baseline,
            findings=findings,
        ),
    )


def cohort_profiles(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[StudentPerformanceProfile, ...]:
    """Every student's profile, in the snapshot's student order.

    Each student is read independently: one student's gaps never change another's numbers.
    """
    stamp = generated_at or datetime.now(UTC)
    students = snapshot.active_students() if active_only else snapshot.students
    return tuple(
        student_profile(
            snapshot,
            student.id,
            thresholds,
            published_only=published_only,
            active_only=active_only,
            generated_at=stamp,
        )
        for student in students
    )


def _profile_explanation(
    *,
    series: StudentSeries,
    thresholds: ThresholdSet,
    history: StudentPerformanceHistory,
    change: Measure,
    baseline: Measure,
    findings: tuple[StudentFinding, ...],
) -> Explanation:
    """The one-paragraph summary, built only from values that were actually computed."""
    score = history.weighted_course_score
    trend = history.trend
    assessed = series.assessed_points

    if not assessed:
        narrative = (
            "No completed assessment in this offering, so nothing can be said about this "
            "student's performance over time. Their results are absent, exempt or not yet "
            "recorded — none of which is a score of 0."
        )
    else:
        latest_point = assessed[-1]
        sentences = [
            f"Latest completed assessment {latest_point.assessment_code} "
            f"{latest_point.percentage}%, against a pass mark of "
            f"{thresholds.pass_mark_percent}%."
        ]
        if change.is_ok:
            sentences.append(
                f"That is {'+' if (change.value or 0) > 0 else ''}{change.value} pp on the "
                f"previous completed assessment, and "
                f"{'+' if (latest_point.percentage or 0) > (baseline.value or 0) else ''}"
                f"{(latest_point.percentage or Decimal(0)) - (baseline.value or Decimal(0))} pp "
                f"against their earlier mean of {baseline.value}%."
            )
        else:
            sentences.append(f"No comparison with earlier work: {change.reason}.")
        if trend.label.is_ok:
            sentences.append(
                f"Trend {trend.label.value} ({trend.slope.value} pp per assessment, "
                f"{trend.method.value if trend.method else 'n/a'}, "
                f"{trend.slope.n} completed assessments)."
            )
        else:
            sentences.append(f"No trend: {trend.label.reason}.")
        if score.is_ok:
            sentences.append(f"Course score {score.value}% over {score.n} completed.")
        detected = [f.code.value for f in findings if f.detected]
        sentences.append(
            f"Conditions met: {', '.join(detected)}." if detected else "No condition met."
        )
        narrative = " ".join(sentences)

    evidence = [
        EvidenceItem(
            name=point.assessment_code,
            value=str(point.percentage) if point.percentage is not None else point.state.value,
            unit=Unit.PERCENT if point.percentage is not None else None,
            note=None if point.percentage is not None else "no percentage: not assessed",
        )
        for point in series.points
    ]
    return Explanation(
        narrative=narrative,
        formula="composed from F2, F7, F9, F10, F11, F13 and F14; nothing recomputed here",
        evidence=tuple(evidence),
        thresholds=tuple(
            thresholds.resolved[key]
            for key in (
                ThresholdKey.TREND_DELTA_PP,
                ThresholdKey.DECLINE_DROP_PP,
                ThresholdKey.REPEATED_LOW_COUNT,
                ThresholdKey.IMPROVEMENT_DELTA_PP,
            )
        ),
        pass_mark_percent=thresholds.pass_mark_percent,
        assessments_used=tuple(point.assessment_code for point in series.assessed_points),
        caveats=history.explanation.caveats,
    )
