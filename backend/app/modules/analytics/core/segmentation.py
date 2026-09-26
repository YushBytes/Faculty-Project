"""F17: which one thing a teacher should do about this student.

Segmentation adds **no mathematics**. Every condition below is a Phase 2 measure or a Phase
3 finding that has already been computed for the student's profile; this module only asks
which of them are true and which one matters most.

The segments, and what each is made of::

    Persistently Low    weighted course score <= low_performance_percent, or a run below
                        the pass mark (F11)
    Declining           trend is Declining (F9), or a sharp decline (F10)
    Borderline          weighted course score within borderline_band_pp of the pass mark
    Improving           trend is Improving (F9)
    High Performer      weighted course score >= high_performance_percent
    Stable              none of the above, and the trend was classifiable

A student is usually several of these at once — borderline *and* improving is the common,
hopeful case — so all of them travel as ``factors`` and one is chosen as ``primary`` by
:data:`SEGMENT_PRIORITY`, which is ordered by what a teacher would act on rather than by how
good the news is.

**Stable is a claim, not a fallback.** It says "there is nothing here to act on", which
requires knowing the trend is flat. A student with one completed assessment and no other
segment satisfied is *not* stable: they are unclassified, and the label says so with its
reason. Letting them fall through to Stable would turn "we do not know" into "all is well",
which is the exact failure this system exists to avoid.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import OfferingSnapshot
from app.modules.analytics.core.outputs import (
    EvidenceItem,
    Explanation,
    SegmentFactor,
    StudentPerformanceProfile,
    StudentSegment,
)
from app.modules.analytics.core.policy import StudentSeries, build_student_series
from app.modules.analytics.core.profile import cohort_profiles, student_profile
from app.modules.analytics.core.results import (
    Label,
    Measure,
    Unit,
    insufficient_label,
    label,
    shortfall,
)
from app.modules.analytics.core.student import pass_mark_distance
from app.modules.analytics.core.thresholds import ResolvedThreshold, ThresholdKey, ThresholdSet
from app.modules.analytics.core.vocabulary import (
    SEGMENT_PRIORITY,
    SEGMENT_VOCABULARY,
    SegmentLabel,
    StudentFindingCode,
    TrendLabel,
)

POINT_NOUN = "completed assessment"


def _factor(
    segment: SegmentLabel,
    *,
    narrative: str,
    evidence: Sequence[EvidenceItem] = (),
    thresholds: Sequence[ResolvedThreshold] = (),
    pass_mark_percent: Decimal | None = None,
) -> SegmentFactor:
    return SegmentFactor(
        segment=segment,
        explanation=Explanation(
            narrative=narrative,
            evidence=tuple(evidence),
            thresholds=tuple(thresholds),
            pass_mark_percent=pass_mark_percent,
        ),
    )


def _score_evidence(score: Measure) -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            name="Weighted course score",
            value=str(score.value),
            unit=Unit.PERCENT,
            note=f"over {score.n} completed {'assessment' if score.n == 1 else 'assessments'}",
        ),
    )


def satisfied_segments(
    series: StudentSeries,
    profile: StudentPerformanceProfile,
    thresholds: ThresholdSet,
) -> tuple[SegmentFactor, ...]:
    """Every segment this student satisfies, each with the evidence for it.

    Order follows :data:`SEGMENT_PRIORITY`, so the first entry is the primary one.
    """
    score = profile.history.weighted_course_score
    trend = profile.trend
    low = thresholds.resolved[ThresholdKey.LOW_PERFORMANCE_PERCENT]
    high = thresholds.resolved[ThresholdKey.HIGH_PERFORMANCE_PERCENT]
    band = thresholds.resolved[ThresholdKey.BORDERLINE_BAND_PP]
    repeated = profile.finding(StudentFindingCode.REPEATED_LOW)
    decline = profile.finding(StudentFindingCode.SHARP_DECLINE)

    found: dict[SegmentLabel, SegmentFactor] = {}

    # Persistently low: a low course score, or a run below the pass mark.
    if score.is_ok and score.value is not None and score.value <= low.value:
        found[SegmentLabel.PERSISTENTLY_LOW] = _factor(
            SegmentLabel.PERSISTENTLY_LOW,
            narrative=(
                f"Weighted course score {score.value}% is at or below the low-performance "
                f"threshold of {low.value}%."
            ),
            evidence=_score_evidence(score),
            thresholds=(low,),
        )
    elif repeated is not None and repeated.detected:
        found[SegmentLabel.PERSISTENTLY_LOW] = _factor(
            SegmentLabel.PERSISTENTLY_LOW,
            narrative=repeated.explanation.narrative,
            evidence=repeated.explanation.evidence,
            thresholds=repeated.explanation.thresholds,
            pass_mark_percent=thresholds.pass_mark_percent,
        )

    # Declining: a downward trend, or a sharp fall against their own earlier work.
    if trend.label.is_ok and trend.label.value == TrendLabel.DECLINING.value:
        found[SegmentLabel.DECLINING] = _factor(
            SegmentLabel.DECLINING,
            narrative=trend.explanation.narrative,
            evidence=trend.explanation.evidence,
            thresholds=(trend.threshold,),
        )
    elif decline is not None and decline.detected:
        found[SegmentLabel.DECLINING] = _factor(
            SegmentLabel.DECLINING,
            narrative=decline.explanation.narrative,
            evidence=decline.explanation.evidence,
            thresholds=decline.explanation.thresholds,
        )

    # Borderline: sitting within the band either side of the pass mark.
    distance = pass_mark_distance(series, thresholds)
    if distance.is_ok and distance.value is not None and abs(distance.value) <= band.value:
        found[SegmentLabel.BORDERLINE] = _factor(
            SegmentLabel.BORDERLINE,
            narrative=(
                f"Weighted course score {score.value}% is {distance.value} pp from the "
                f"{thresholds.pass_mark_percent}% pass mark, within the configured band of "
                f"{band.value} pp."
            ),
            evidence=(
                *_score_evidence(score),
                EvidenceItem(
                    name="Distance from the pass mark",
                    value=str(distance.value),
                    unit=Unit.PERCENTAGE_POINTS,
                ),
            ),
            thresholds=(band,),
            pass_mark_percent=thresholds.pass_mark_percent,
        )

    if trend.label.is_ok and trend.label.value == TrendLabel.IMPROVING.value:
        found[SegmentLabel.IMPROVING] = _factor(
            SegmentLabel.IMPROVING,
            narrative=trend.explanation.narrative,
            evidence=trend.explanation.evidence,
            thresholds=(trend.threshold,),
        )

    if score.is_ok and score.value is not None and score.value >= high.value:
        found[SegmentLabel.HIGH_PERFORMER] = _factor(
            SegmentLabel.HIGH_PERFORMER,
            narrative=(
                f"Weighted course score {score.value}% is at or above the high-performance "
                f"threshold of {high.value}%."
            ),
            evidence=_score_evidence(score),
            thresholds=(high,),
        )

    if not found and trend.label.is_ok:
        found[SegmentLabel.STABLE] = _factor(
            SegmentLabel.STABLE,
            narrative=(
                f"No other segment applies: the trend is {trend.label.value} at "
                f"{trend.slope.value} pp per assessment, and the weighted course score of "
                f"{score.value}% is clear of the low, high and borderline thresholds."
            ),
            evidence=(*_score_evidence(score), *trend.explanation.evidence),
            thresholds=(trend.threshold, low, high, band),
            pass_mark_percent=thresholds.pass_mark_percent,
        )

    return tuple(found[segment] for segment in SEGMENT_PRIORITY if segment in found)


def _primary(
    factors: Sequence[SegmentFactor],
    profile: StudentPerformanceProfile,
    thresholds: ThresholdSet,
) -> Label:
    """The most actionable satisfied segment, or an honest refusal to label."""
    score = profile.history.weighted_course_score
    minimum_points = thresholds.count(ThresholdKey.MIN_TREND_POINTS)
    completed = score.n

    if factors:
        return label(
            factors[0].segment,
            vocabulary=SEGMENT_VOCABULARY,
            n=completed,
            minimum_n=1,
        )

    if not score.is_ok:
        return insufficient_label(
            vocabulary=SEGMENT_VOCABULARY,
            n=0,
            minimum_n=1,
            reason=score.reason or shortfall(have=0, need=1, noun=POINT_NOUN),
        )

    return insufficient_label(
        vocabulary=SEGMENT_VOCABULARY,
        n=completed,
        minimum_n=minimum_points,
        reason=(
            f"{shortfall(have=completed, need=minimum_points, noun=POINT_NOUN)} to classify a "
            "trend, and no other segment applies; calling this student stable would claim "
            "more than the data shows"
        ),
    )


def student_segment(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    profile: StudentPerformanceProfile | None = None,
    published_only: bool = True,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> StudentSegment:
    """**Contract 7.** One primary actionable status, plus everything else that is true.

    ``profile`` may be passed in when the caller already built one — a cohort build does —
    so the Phase 2 measures behind the segments are computed once, not twice.
    """
    stamp = generated_at or datetime.now(UTC)
    built = profile or student_profile(
        snapshot,
        student_id,
        thresholds,
        published_only=published_only,
        active_only=active_only,
        generated_at=stamp,
    )
    series = build_student_series(snapshot, student_id, published_only=published_only)
    factors = satisfied_segments(series, built, thresholds)
    primary = _primary(factors, built, thresholds)

    if primary.is_ok:
        others = [f.segment.value for f in factors[1:]]
        narrative = (
            f"Primary status {primary.value}"
            + (f", also {', '.join(others)}" if others else "")
            + f". {factors[0].explanation.narrative}"
        )
    else:
        narrative = f"No segment can be assigned: {primary.reason}."

    return StudentSegment(
        generated_at=stamp,
        offering_id=snapshot.offering_id,
        student=built.student,
        primary=primary,
        factors=factors if primary.is_ok else (),
        explanation=Explanation(
            narrative=narrative,
            formula=(
                "satisfied segments from the course score, trend and findings; primary is "
                "the first satisfied in SEGMENT_PRIORITY"
            ),
            evidence=(
                EvidenceItem(
                    name="Segments satisfied",
                    value=", ".join(f.segment.value for f in factors) or "none",
                ),
            ),
            pass_mark_percent=thresholds.pass_mark_percent,
            assessments_used=tuple(point.assessment_code for point in series.assessed_points),
            caveats=built.history.explanation.caveats,
        ),
    )


def cohort_segments(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    profiles: Sequence[StudentPerformanceProfile] | None = None,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[StudentSegment, ...]:
    """Every student's segment, in the snapshot's student order."""
    stamp = generated_at or datetime.now(UTC)
    built = profiles or cohort_profiles(
        snapshot,
        thresholds,
        active_only=active_only,
        published_only=published_only,
        generated_at=stamp,
    )
    return tuple(
        student_segment(
            snapshot,
            profile.student.id,
            thresholds,
            profile=profile,
            published_only=published_only,
            active_only=active_only,
            generated_at=stamp,
        )
        for profile in built
    )


def segment_counts(segments: Sequence[StudentSegment]) -> Mapping[SegmentLabel, int]:
    """How many students hold each **primary** segment.

    Primary only, so the counts sum to the number of students who could be segmented rather
    than double-counting the borderline-and-improving students. Students whose segment could
    not be assigned are in no bucket; the difference against the cohort size is visible in
    :class:`ClassHealth`.
    """
    counts: dict[SegmentLabel, int] = {}
    for segment in segments:
        if not segment.primary.is_ok or segment.primary.value is None:
            continue
        held = SegmentLabel(segment.primary.value)
        counts[held] = counts.get(held, 0) + 1
    return {segment: counts[segment] for segment in SEGMENT_PRIORITY if segment in counts}
