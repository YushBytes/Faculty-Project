"""F19: how the class is doing, as one dashboard header.

An aggregation, not a calculation. Every KPI is a Phase 2 function applied to a cohort-level
list that Phase 3 already built, so the header and the detail behind it cannot disagree.

**Two different questions, kept apart.** ``class_mean`` is the mean of the students'
*weighted course scores* — how the class is doing in the course, over everything sat so far.
The latest paper's own mean lives in ``latest_assessment`` and is usually a different number
(in the canonical fixture, 57.36 against 53.50). Showing one where the other belongs is the
easiest way to make a dashboard quietly wrong, so they are named differently and computed
from different inputs.

**Attention is not evaluated here.** ``students_requiring_attention`` is ``None`` and
``flag_counts`` is empty, which the contract defines as "this build did not look" — not "we
looked and found none", and not insufficient data, which would be a claim about the
students. The attention engine fills both in a later phase.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import OfferingSnapshot, StudentRef
from app.modules.analytics.core.distribution import distribution_of
from app.modules.analytics.core.outputs import (
    AssessmentComparison,
    ClassFinding,
    ClassHealth,
    DataCoverage,
    EvidenceItem,
    Explanation,
    StudentPerformanceProfile,
)
from app.modules.analytics.core.policy import classify
from app.modules.analytics.core.profile import cohort_profiles
from app.modules.analytics.core.results import Measure, Unit
from app.modules.analytics.core.segmentation import cohort_segments, segment_counts
from app.modules.analytics.core.statistics import (
    assessment_analytics,
    completion_percent,
    mean_percent,
    median_percent,
    pass_percent,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet

ATTENTION_NOT_EVALUATED = (
    "Attention flags were not evaluated in this build, so no student is reported as "
    "requiring attention and no flag counts are given. This is not a finding that none do."
)

COURSE_SCORE_BASIS = "active enrolled students with a weighted course score"
MATRIX_BASIS = "every (student, published assessment) the active cohort was required to sit"


def matrix_coverage(
    snapshot: OfferingSnapshot, *, active_only: bool = True, published_only: bool = True
) -> DataCoverage:
    """Every cell of the cohort's result matrix, counted by state.

    Cohort completion is over cells, not students: a class where everyone missed one paper
    and a class where a quarter of the students sat nothing are different situations, and
    counting students would report them identically.
    """
    students = snapshot.active_students() if active_only else snapshot.students
    assessments = snapshot.ordered_assessments(published_only=published_only)
    states = [
        classify(
            result.status
            if (result := snapshot.result_for(student.id, assessment.id)) is not None
            else None
        )
        for student in students
        for assessment in assessments
    ]
    return DataCoverage.from_states(states, basis=MATRIX_BASIS)


def cohort_course_scores(
    profiles: Sequence[StudentPerformanceProfile],
) -> tuple[tuple[StudentRef, Decimal], ...]:
    """Each student's weighted course score, for those who have one.

    A student with no completed assessment has no score and contributes nothing — they are
    not a zero — but they stay in ``cohort_n``, so the gap between the two counts is visible.
    """
    return tuple(
        (profile.student, profile.history.weighted_course_score.value)
        for profile in profiles
        if profile.history.weighted_course_score.is_ok
        and profile.history.weighted_course_score.value is not None
    )


def _course_score_coverage(scored: int, cohort_n: int) -> DataCoverage:
    """Who is behind the course-score statistics, and how many have no score at all."""
    return DataCoverage(
        assessed=scored,
        absent=0,
        exempt=0,
        missing=max(cohort_n - scored, 0),
        basis=COURSE_SCORE_BASIS,
    )


def class_health(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> ClassHealth:
    """**F19, contract 5.** The offering's KPIs, aggregated from the contracts below it."""
    from app.modules.analytics.core.comparison import (
        class_findings,
        compare_assessments,
        latest_published,
        preceding_published,
    )

    stamp = generated_at or datetime.now(UTC)
    students = snapshot.active_students() if active_only else snapshot.students
    assessments = snapshot.ordered_assessments(published_only=published_only)

    profiles = cohort_profiles(
        snapshot,
        thresholds,
        active_only=active_only,
        published_only=published_only,
        generated_at=stamp,
    )
    scored = cohort_course_scores(profiles)
    scores = [score for _, score in scored]

    segments = cohort_segments(
        snapshot,
        thresholds,
        profiles=profiles,
        active_only=active_only,
        published_only=published_only,
        generated_at=stamp,
    )
    counts = segment_counts(segments)

    coverage = matrix_coverage(snapshot, active_only=active_only, published_only=published_only)
    score_coverage = _course_score_coverage(len(scored), len(students))

    latest = latest_published(snapshot)
    previous = preceding_published(snapshot, latest) if latest else None
    comparison: AssessmentComparison | None = None
    findings: tuple[ClassFinding, ...] = ()
    if latest is not None and previous is not None:
        comparison = compare_assessments(
            snapshot, previous, latest, active_only=active_only, generated_at=stamp
        )
        findings = class_findings(comparison, thresholds)

    class_mean = mean_percent(scores)
    median = median_percent(scores)
    passing = pass_percent(scores, snapshot.pass_mark_percent)
    completion = completion_percent(coverage)

    return ClassHealth(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        pass_mark_percent=snapshot.pass_mark_percent,
        cohort_n=len(students),
        published_assessments=len(assessments),
        class_mean=class_mean,
        median=median,
        pass_percent=passing,
        completion_percent=completion,
        students_requiring_attention=None,
        segment_counts=counts,
        flag_counts={},
        course_score_distribution=distribution_of(
            scores,
            offering_id=snapshot.offering_id,
            coverage=score_coverage,
            label="weighted course score",
        ),
        findings=findings,
        latest_assessment=(
            assessment_analytics(snapshot, latest, active_only=active_only, generated_at=stamp)
            if latest is not None
            else None
        ),
        latest_comparison=comparison,
        coverage=coverage,
        explanation=_health_explanation(
            snapshot=snapshot,
            thresholds=thresholds,
            cohort_n=len(students),
            assessments=len(assessments),
            scored=len(scored),
            class_mean=class_mean,
            passing=passing,
            completion=completion,
            coverage=coverage,
            counts=counts,
            findings=findings,
        ),
    )


def _health_explanation(
    *,
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    cohort_n: int,
    assessments: int,
    scored: int,
    class_mean: Measure,
    passing: Measure,
    completion: Measure,
    coverage: DataCoverage,
    counts: dict,
    findings: Sequence[ClassFinding],
) -> Explanation:
    minimum = thresholds.count(ThresholdKey.MIN_GROUP_N)

    if class_mean.is_ok:
        sentences = [
            f"Across {scored} of {cohort_n} students with a course score, the mean weighted "
            f"course score is {class_mean.value}% and {passing.value}% are at or above the "
            f"{snapshot.pass_mark_percent}% pass mark.",
            f"Completion is {completion.value}% of the "
            f"{coverage.completion_denominator} assessment sittings required across "
            f"{assessments} published "
            f"{'assessment' if assessments == 1 else 'assessments'}.",
        ]
        if scored < cohort_n:
            sentences.append(
                f"{cohort_n - scored} "
                f"{'student has' if cohort_n - scored == 1 else 'students have'} no completed "
                "assessment and so no course score; they are counted in the cohort, not as "
                "zeroes."
            )
        if counts:
            sentences.append(
                "Primary segments: "
                + ", ".join(f"{segment.value} {count}" for segment, count in counts.items())
                + "."
            )
        unsegmented = cohort_n - sum(counts.values())
        if unsegmented:
            sentences.append(
                f"{unsegmented} "
                f"{'student could' if unsegmented == 1 else 'students could'} not be "
                "segmented on the data available."
            )
        moved = [f.code.value for f in findings if f.detected]
        if moved:
            sentences.append("Since the previous assessment: " + ", ".join(moved) + ".")
        if cohort_n < minimum:
            sentences.append(
                f"This cohort of {cohort_n} is below the minimum of {minimum} for a "
                "cohort-level judgement, so the numbers are reported without one."
            )
    else:
        sentences = [
            f"No student in this offering has a completed assessment, so no course-level "
            f"statistic can be computed. The cohort is {cohort_n} "
            f"{'student' if cohort_n == 1 else 'students'} across {assessments} published "
            f"{'assessment' if assessments == 1 else 'assessments'}; "
            f"{coverage.absent} absent, {coverage.exempt} exempt, {coverage.missing} with no "
            "result recorded."
        ]
    sentences.append(ATTENTION_NOT_EVALUATED)

    return Explanation(
        narrative=" ".join(sentences),
        formula=(
            "class_mean = mean(weighted course scores); pass% = share at or above the pass "
            "mark; completion% = assessed cells / required cells"
        ),
        evidence=(
            EvidenceItem(name="Cohort", value=str(cohort_n), unit=Unit.COUNT),
            EvidenceItem(
                name="With a course score",
                value=str(scored),
                unit=Unit.COUNT,
                note="students with at least one completed assessment",
            ),
            EvidenceItem(name="Published assessments", value=str(assessments), unit=Unit.COUNT),
            EvidenceItem(
                name="Assessed sittings",
                value=str(coverage.assessed),
                unit=Unit.COUNT,
                note=f"of {coverage.completion_denominator} required",
            ),
            EvidenceItem(
                name="Exempt sittings",
                value=str(coverage.exempt),
                unit=Unit.COUNT,
                note="excluded from the completion denominator",
            ),
        ),
        thresholds=(
            thresholds.resolved[ThresholdKey.MIN_GROUP_N],
            thresholds.resolved[ThresholdKey.LOW_PERFORMANCE_PERCENT],
            thresholds.resolved[ThresholdKey.HIGH_PERFORMANCE_PERCENT],
        ),
        pass_mark_percent=snapshot.pass_mark_percent,
        assessments_used=tuple(a.code for a in snapshot.ordered_assessments(published_only=True)),
    )
