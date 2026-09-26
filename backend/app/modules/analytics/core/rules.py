"""Contract C9: the frozen attention-rule registry.

These seven codes are the canonical numbering and **must not be renumbered**. The original
blueprint used the same R-numbers for different rules (its R3 was sharp decline, its R6 was
failed latest, and it had a topic rule we cannot support), so any drift here would produce
flags whose stored ``rule_code`` means one thing to one part of the system and something
else to another.

This module is declarative on purpose: it says what each rule is, which threshold it reads
and how severe it is. Evaluating the rules against a cohort belongs to the attention module
in a later phase.

Wording rules that apply to every message generated from these rules:

* State the value, the threshold and the assessments involved.
* Never predict. "Below 50% in 3 consecutive assessments" is a fact; "will fail" is not.
* Never invent a cause. We have no topic-level data, so we cannot know *why*.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.modules.analytics.core.thresholds import ThresholdKey


class AttentionRuleCode(StrEnum):
    """Canonical rule codes. Frozen: see the module docstring."""

    R1_LOW_PERFORMANCE = "R1_LOW_PERFORMANCE"
    R2_FAILED_LATEST = "R2_FAILED_LATEST"
    R3_REPEATED_LOW = "R3_REPEATED_LOW"
    R4_SHARP_DECLINE = "R4_SHARP_DECLINE"
    R5_DECLINING_TREND = "R5_DECLINING_TREND"
    R6_LOW_COMPLETION = "R6_LOW_COMPLETION"
    R7_BORDERLINE = "R7_BORDERLINE"


class FlagSeverity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FlagStatus(StrEnum):
    """Lifecycle of a raised flag. Faculty acknowledge or resolve; analytics only raises."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AttentionRule(BaseModel):
    """One rule's definition: what it means, what it reads, how loud it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: AttentionRuleCode
    severity: FlagSeverity
    title: str
    definition: str
    """Plain-language statement of the condition, for documentation and tooltips."""

    threshold_key: ThresholdKey | None
    """The configurable threshold this rule compares against.

    ``None`` for R2, which compares against the offering's own pass mark rather than a
    configurable analytics threshold.
    """

    uses_pass_mark: bool = False
    minimum_points_key: ThresholdKey | None = None
    """Sample-size gate, where the rule needs more than one assessment to mean anything."""


ATTENTION_RULES: Final[Mapping[AttentionRuleCode, AttentionRule]] = {
    rule.code: rule
    for rule in (
        AttentionRule(
            code=AttentionRuleCode.R1_LOW_PERFORMANCE,
            severity=FlagSeverity.HIGH,
            title="Low overall performance",
            definition=(
                "The student's weighted course score across completed assessments is below "
                "the configured low-performance threshold."
            ),
            threshold_key=ThresholdKey.LOW_PERFORMANCE_PERCENT,
        ),
        AttentionRule(
            code=AttentionRuleCode.R2_FAILED_LATEST,
            severity=FlagSeverity.MEDIUM,
            title="Below pass mark in the latest assessment",
            definition=(
                "The student's percentage in the most recent completed assessment is below "
                "the offering's pass mark."
            ),
            threshold_key=None,
            uses_pass_mark=True,
        ),
        AttentionRule(
            code=AttentionRuleCode.R3_REPEATED_LOW,
            severity=FlagSeverity.HIGH,
            title="Repeatedly below pass mark",
            definition=(
                "The student has been below the offering's pass mark in the configured "
                "number of consecutive completed assessments."
            ),
            threshold_key=ThresholdKey.REPEATED_LOW_COUNT,
            uses_pass_mark=True,
        ),
        AttentionRule(
            code=AttentionRuleCode.R4_SHARP_DECLINE,
            severity=FlagSeverity.MEDIUM,
            title="Sharp decline",
            definition=(
                "The latest assessment percentage is below the mean of the student's earlier "
                "assessments by at least the configured number of percentage points."
            ),
            threshold_key=ThresholdKey.DECLINE_DROP_PP,
            minimum_points_key=ThresholdKey.MIN_TREND_POINTS,
        ),
        AttentionRule(
            code=AttentionRuleCode.R5_DECLINING_TREND,
            severity=FlagSeverity.LOW,
            title="Declining trend",
            definition=(
                "The slope of the student's percentage series is at or below the negative "
                "trend threshold, in percentage points per assessment."
            ),
            threshold_key=ThresholdKey.TREND_DELTA_PP,
            minimum_points_key=ThresholdKey.MIN_TREND_POINTS,
        ),
        AttentionRule(
            code=AttentionRuleCode.R6_LOW_COMPLETION,
            severity=FlagSeverity.MEDIUM,
            title="Low completion",
            definition=(
                "The student has been assessed in a smaller share of the offering's published "
                "assessments than the configured completion threshold. Exempt assessments are "
                "excluded from the denominator; absent and missing ones count as not completed."
            ),
            threshold_key=ThresholdKey.LOW_COMPLETION_PERCENT,
        ),
        AttentionRule(
            code=AttentionRuleCode.R7_BORDERLINE,
            severity=FlagSeverity.LOW,
            title="Borderline at the pass mark",
            definition=(
                "The student's weighted course score is within the configured band either "
                "side of the offering's pass mark."
            ),
            threshold_key=ThresholdKey.BORDERLINE_BAND_PP,
            uses_pass_mark=True,
        ),
    )
}

ATTENTION_MEDIUM_RULES_FOR_ESCALATION: Final[int] = 2
"""How many Medium rules together escalate a student to requiring attention."""


def requires_attention(severities: Iterable[FlagSeverity]) -> bool:
    """Whether a student's fired rules amount to requiring academic attention.

    Any High rule, or at least two Medium rules. Low rules are informational on their own:
    being borderline is worth showing a teacher, but it is not by itself a call to act.
    """
    counts: dict[FlagSeverity, int] = {}
    for severity in severities:
        counts[severity] = counts.get(severity, 0) + 1
    if counts.get(FlagSeverity.HIGH, 0) >= 1:
        return True
    return counts.get(FlagSeverity.MEDIUM, 0) >= ATTENTION_MEDIUM_RULES_FOR_ESCALATION
