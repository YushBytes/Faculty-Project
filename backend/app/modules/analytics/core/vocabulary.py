"""Every categorical label analytics may emit, and the name of the set it came from.

A :class:`~app.modules.analytics.core.results.Label` carries its value as a plain string
plus a ``vocabulary`` name. This module holds the enums behind those names, so a stored or
serialised label can always be traced back to the closed set it was drawn from, and so two
modules cannot invent two spellings of "declining".

**Insufficiency is a status, not a label.** The scope directive lists "Insufficient Data" as
a trend and as a segment, but expressing it as a *value* would mean every consumer had to
special-case one member of each vocabulary, and it would collide with contract C10, which
already says how an uncomputable result looks. So no vocabulary here contains an
``insufficient_data`` member: a trend that cannot be classified is
``Label(status=INSUFFICIENT_DATA, value=None, reason=...)``, and the API renders the words
"Insufficient data" from that status. See docs/ANALYTICS_SPEC.md, "Insufficient data".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class TrendLabel(StrEnum):
    """How a student's percentage series is moving. See :class:`TrendMethod` for how."""

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


TREND_VOCABULARY: Final[str] = "trend"


class TrendMethod(StrEnum):
    """Which arithmetic produced a trend, because the two are not equally strong.

    Quoting the method in the explanation stops a two-point difference being read as a
    fitted trend.
    """

    TWO_POINT_DELTA = "two_point_delta"
    """Exactly two completed assessments: ``P[-1] - P[-2]``."""

    LEAST_SQUARES = "least_squares"
    """Three or more: the least-squares slope in percentage points per assessment."""


class SegmentLabel(StrEnum):
    """Rule-derived student segments.

    A student may satisfy several. The API returns one primary actionable status plus the
    supporting factors, ordered by :data:`SEGMENT_PRIORITY`.
    """

    HIGH_PERFORMER = "high_performer"
    IMPROVING = "improving"
    STABLE = "stable"
    BORDERLINE = "borderline"
    DECLINING = "declining"
    PERSISTENTLY_LOW = "persistently_low"


SEGMENT_VOCABULARY: Final[str] = "segment"

SEGMENT_PRIORITY: Final[tuple[SegmentLabel, ...]] = (
    SegmentLabel.PERSISTENTLY_LOW,
    SegmentLabel.DECLINING,
    SegmentLabel.BORDERLINE,
    SegmentLabel.IMPROVING,
    SegmentLabel.HIGH_PERFORMER,
    SegmentLabel.STABLE,
)
"""Most actionable first: the primary segment is the earliest member a student satisfies.

Ordered by what a teacher would act on, not by how good the news is. Improving outranks
high performer because it is the one a teacher can reinforce; stable is last because it is
the absence of anything to do.
"""


class ChangeDirection(StrEnum):
    """Which way a measured quantity moved between two points."""

    UP = "up"
    DOWN = "down"
    UNCHANGED = "unchanged"


CHANGE_VOCABULARY: Final[str] = "change_direction"


class OutcomeLabel(StrEnum):
    """An intervention's **observed** outcome against the peer baseline.

    Never a causal claim: the label describes what the numbers did, not what the
    intervention achieved. See :data:`app.modules.analytics.core.outputs.OBSERVATIONAL_CAVEAT`.
    """

    TARGET_IMPROVED_MORE = "target_improved_more"
    TARGET_IMPROVED_LESS = "target_improved_less"
    NO_MEASURABLE_DIFFERENCE = "no_measurable_difference"


OUTCOME_VOCABULARY: Final[str] = "intervention_outcome"


class StudentFindingCode(StrEnum):
    """Conditions a single student's series can satisfy.

    These are *observations*, not flags: a finding says "the numbers do this", and nothing
    about whether anyone should act. Raising a flag, with its severity and lifecycle, is the
    attention engine's job and reads the same measures through
    :data:`app.modules.analytics.core.rules.ATTENTION_RULES`.
    """

    SHARP_DECLINE = "sharp_decline"
    """F10: the latest result is far below the mean of the earlier ones."""

    REPEATED_LOW = "repeated_low"
    """F11: a trailing run of completed assessments below the pass mark."""

    IMPROVEMENT = "improvement"
    """F14: the latest completed assessment is up on the previous one by enough to count."""


FINDING_VOCABULARY: Final[str] = "student_finding"


class InterventionKind(StrEnum):
    """What a faculty member actually did. Deliberately small.

    Six kinds, because an intervention's *type* is not what the measurement turns on — the
    pre/post windows and the peer comparison are identical whichever it is. A longer list
    would be a workflow taxonomy nobody analyses, and every extra value is one more thing a
    report has to render and a teacher has to choose between.

    ``OTHER`` exists so a real action is never forced into the wrong box; the intervention's
    note says what it was.
    """

    ACADEMIC_SUPPORT = "academic_support"
    REMEDIAL_SESSION = "remedial_session"
    FACULTY_MEETING = "faculty_meeting"
    PEER_SUPPORT = "peer_support"
    ADDITIONAL_PRACTICE = "additional_practice"
    COUNSELLING_REFERRAL = "counselling_referral"
    OTHER = "other"


INTERVENTION_KIND_VOCABULARY: Final[str] = "intervention_kind"


class InterventionStatus(StrEnum):
    """Where an intervention is in its short life.

    Analytics reads this to decide whether an outcome can be measured at all: a cancelled
    intervention did not happen, so the change after it is not an outcome *of* it, and a
    planned one has not happened yet. Neither is insufficient data in the usual sense — the
    data may be perfectly good — so both are reported with their own reason.
    """

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def has_happened(self) -> bool:
        """Whether the action was actually taken, so a change after it can be reported."""
        return self in (InterventionStatus.ACTIVE, InterventionStatus.COMPLETED)


INTERVENTION_STATUS_VOCABULARY: Final[str] = "intervention_status"


class ClassFindingCode(StrEnum):
    """Cohort-level movements that reached the configured magnitude.

    The cohort counterpart of :class:`StudentFindingCode`, and the same kind of statement:
    what the numbers did, for a whole class, between two assessments. Not a significance
    test — assessments are not equated for difficulty, so "the mean fell 10 pp" is a fact
    about the marks and never a claim about the students.
    """

    CLASS_MEAN_MOVED = "class_mean_moved"
    PASS_RATE_MOVED = "pass_rate_moved"
    PARTICIPATION_MOVED = "participation_moved"
    SPREAD_MOVED = "spread_moved"


CLASS_FINDING_VOCABULARY: Final[str] = "class_finding"


class InsightCode(StrEnum):
    """The deterministic insight templates. No LLM: one code, one sentence template.

    Codes are stable identifiers, so a rendered sentence can always be traced to the
    template and the numbers that produced it.
    """

    CLASS_MEAN_MOVED = "class_mean_moved"
    CLASS_PASS_RATE_MOVED = "class_pass_rate_moved"
    CLASS_COMPLETION_MOVED = "class_completion_moved"
    COHORT_COMPLETION_LOW = "cohort_completion_low"
    DECLINE_CLUSTER = "decline_cluster"
    DECLINING_TREND_CLUSTER = "declining_trend_cluster"
    REPEATED_LOW_CLUSTER = "repeated_low_cluster"
    IMPROVEMENT_CLUSTER = "improvement_cluster"
    BORDERLINE_CLUSTER = "borderline_cluster"
    DISTRIBUTION_PEAK = "distribution_peak"
    ATTENTION_SUMMARY = "attention_summary"
    STUDENT_TREND = "student_trend"
    STUDENT_SHARP_DECLINE = "student_sharp_decline"
    STUDENT_REPEATED_LOW = "student_repeated_low"
    STUDENT_MOST_IMPROVED = "student_most_improved"
    STUDENT_LATEST_CHANGE = "student_latest_change"
    STUDENT_COMPLETION_LOW = "student_completion_low"
    STUDENT_BORDERLINE = "student_borderline"
    INTERVENTION_OBSERVED_CHANGE = "intervention_observed_change"


INSIGHT_VOCABULARY: Final[str] = "insight_code"


class InsightCategory(StrEnum):
    """What an insight is *about*, for grouping in a report.

    Derived from the code rather than stored on the insight: every code belongs to exactly
    one category, so carrying both would be two spellings of one fact.
    """

    PERFORMANCE = "performance"
    COMPLETION = "completion"
    TREND = "trend"
    ATTENTION = "attention"
    DISTRIBUTION = "distribution"
    INTERVENTION = "intervention"


INSIGHT_CATEGORY: Final[dict[InsightCode, InsightCategory]] = {
    InsightCode.CLASS_MEAN_MOVED: InsightCategory.PERFORMANCE,
    InsightCode.CLASS_PASS_RATE_MOVED: InsightCategory.PERFORMANCE,
    InsightCode.CLASS_COMPLETION_MOVED: InsightCategory.COMPLETION,
    InsightCode.COHORT_COMPLETION_LOW: InsightCategory.COMPLETION,
    InsightCode.DECLINE_CLUSTER: InsightCategory.TREND,
    InsightCode.DECLINING_TREND_CLUSTER: InsightCategory.TREND,
    InsightCode.REPEATED_LOW_CLUSTER: InsightCategory.PERFORMANCE,
    InsightCode.IMPROVEMENT_CLUSTER: InsightCategory.TREND,
    InsightCode.BORDERLINE_CLUSTER: InsightCategory.PERFORMANCE,
    InsightCode.DISTRIBUTION_PEAK: InsightCategory.DISTRIBUTION,
    InsightCode.ATTENTION_SUMMARY: InsightCategory.ATTENTION,
    InsightCode.STUDENT_TREND: InsightCategory.TREND,
    InsightCode.STUDENT_SHARP_DECLINE: InsightCategory.TREND,
    InsightCode.STUDENT_REPEATED_LOW: InsightCategory.PERFORMANCE,
    InsightCode.STUDENT_MOST_IMPROVED: InsightCategory.TREND,
    InsightCode.STUDENT_LATEST_CHANGE: InsightCategory.PERFORMANCE,
    InsightCode.STUDENT_COMPLETION_LOW: InsightCategory.COMPLETION,
    InsightCode.STUDENT_BORDERLINE: InsightCategory.PERFORMANCE,
    InsightCode.INTERVENTION_OBSERVED_CHANGE: InsightCategory.INTERVENTION,
}
"""Every code's category. A test asserts the mapping is total, so a new code cannot be
added without deciding where it belongs."""

INSIGHT_ORDER: Final[tuple[InsightCode, ...]] = (
    # Cohort performance first, then what it cost in participation, then movement,
    # then who needs a teacher, then the shape of the cohort, then one student, then actions.
    InsightCode.CLASS_MEAN_MOVED,
    InsightCode.CLASS_PASS_RATE_MOVED,
    InsightCode.CLASS_COMPLETION_MOVED,
    InsightCode.COHORT_COMPLETION_LOW,
    InsightCode.DECLINE_CLUSTER,
    InsightCode.DECLINING_TREND_CLUSTER,
    InsightCode.REPEATED_LOW_CLUSTER,
    InsightCode.IMPROVEMENT_CLUSTER,
    InsightCode.BORDERLINE_CLUSTER,
    InsightCode.ATTENTION_SUMMARY,
    InsightCode.DISTRIBUTION_PEAK,
    InsightCode.STUDENT_LATEST_CHANGE,
    InsightCode.STUDENT_TREND,
    InsightCode.STUDENT_SHARP_DECLINE,
    InsightCode.STUDENT_REPEATED_LOW,
    InsightCode.STUDENT_BORDERLINE,
    InsightCode.STUDENT_COMPLETION_LOW,
    InsightCode.STUDENT_MOST_IMPROVED,
    InsightCode.INTERVENTION_OBSERVED_CHANGE,
)
"""**Presentation order, not priority.** Insights are listed in this sequence so two
renderings of the same cohort read identically. It says nothing about which finding matters
most — that is a judgement for the person reading, who knows the students."""


class InsightScope(StrEnum):
    """Whether an insight is about a cohort or one student."""

    OFFERING = "offering"
    ASSESSMENT = "assessment"
    STUDENT = "student"
    INTERVENTION = "intervention"


VOCABULARIES: Final[dict[str, type[StrEnum]]] = {
    CLASS_FINDING_VOCABULARY: ClassFindingCode,
    INTERVENTION_KIND_VOCABULARY: InterventionKind,
    INTERVENTION_STATUS_VOCABULARY: InterventionStatus,
    FINDING_VOCABULARY: StudentFindingCode,
    TREND_VOCABULARY: TrendLabel,
    SEGMENT_VOCABULARY: SegmentLabel,
    CHANGE_VOCABULARY: ChangeDirection,
    OUTCOME_VOCABULARY: OutcomeLabel,
    INSIGHT_VOCABULARY: InsightCode,
}
"""Vocabulary name -> the enum it names, so a ``Label`` can be validated against its set."""
