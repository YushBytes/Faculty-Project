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


class InsightCode(StrEnum):
    """The deterministic insight templates. No LLM: one code, one sentence template.

    Codes are stable identifiers, so a rendered sentence can always be traced to the
    template and the numbers that produced it.
    """

    CLASS_MEAN_MOVED = "class_mean_moved"
    CLASS_PASS_RATE_MOVED = "class_pass_rate_moved"
    COHORT_COMPLETION_LOW = "cohort_completion_low"
    DECLINE_CLUSTER = "decline_cluster"
    BORDERLINE_CLUSTER = "borderline_cluster"
    ATTENTION_SUMMARY = "attention_summary"
    STUDENT_TREND = "student_trend"
    STUDENT_SHARP_DECLINE = "student_sharp_decline"
    STUDENT_REPEATED_LOW = "student_repeated_low"
    STUDENT_MOST_IMPROVED = "student_most_improved"
    INTERVENTION_OBSERVED_CHANGE = "intervention_observed_change"


INSIGHT_VOCABULARY: Final[str] = "insight_code"


class InsightScope(StrEnum):
    """Whether an insight is about a cohort or one student."""

    OFFERING = "offering"
    ASSESSMENT = "assessment"
    STUDENT = "student"
    INTERVENTION = "intervention"


VOCABULARIES: Final[dict[str, type[StrEnum]]] = {
    FINDING_VOCABULARY: StudentFindingCode,
    TREND_VOCABULARY: TrendLabel,
    SEGMENT_VOCABULARY: SegmentLabel,
    CHANGE_VOCABULARY: ChangeDirection,
    OUTCOME_VOCABULARY: OutcomeLabel,
    INSIGHT_VOCABULARY: InsightCode,
}
"""Vocabulary name -> the enum it names, so a ``Label`` can be validated against its set."""
