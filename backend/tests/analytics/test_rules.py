"""Contract C9: the attention-rule registry is frozen and internally consistent.

These tests exist to catch renumbering. The blueprint used the same R-numbers for different
rules, so if someone "corrects" a code here to match it, stored flags stop meaning what they
say. The explicit code-to-meaning assertions below are the guard.
"""

from __future__ import annotations

import pytest

from app.modules.analytics.core.rules import (
    ATTENTION_RULES,
    AttentionRuleCode,
    FlagSeverity,
    FlagStatus,
    requires_attention,
)
from app.modules.analytics.core.thresholds import ThresholdKey


class TestRegistryShape:
    def test_every_code_has_exactly_one_rule(self) -> None:
        assert set(ATTENTION_RULES) == set(AttentionRuleCode)
        assert len(ATTENTION_RULES) == 7

    def test_each_rule_is_keyed_by_its_own_code(self) -> None:
        for code, rule in ATTENTION_RULES.items():
            assert rule.code is code

    def test_every_rule_states_its_condition(self) -> None:
        for rule in ATTENTION_RULES.values():
            assert rule.title
            assert rule.definition.strip().endswith(".")

    def test_every_rule_reads_a_threshold_or_the_pass_mark(self) -> None:
        """A rule with no comparison point could not explain itself."""
        for rule in ATTENTION_RULES.values():
            assert rule.threshold_key is not None or rule.uses_pass_mark

    def test_threshold_keys_are_real_keys(self) -> None:
        for rule in ATTENTION_RULES.values():
            if rule.threshold_key is not None:
                assert rule.threshold_key in set(ThresholdKey)
            if rule.minimum_points_key is not None:
                assert rule.minimum_points_key in set(ThresholdKey)

    def test_rules_are_immutable(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ATTENTION_RULES[AttentionRuleCode.R1_LOW_PERFORMANCE].severity = FlagSeverity.LOW  # type: ignore[misc]


class TestFrozenNumbering:
    """The canonical meaning of each code. Changing these values is a breaking change."""

    @pytest.mark.parametrize(
        ("code", "severity", "threshold_key"),
        [
            (
                AttentionRuleCode.R1_LOW_PERFORMANCE,
                FlagSeverity.HIGH,
                ThresholdKey.LOW_PERFORMANCE_PERCENT,
            ),
            (AttentionRuleCode.R2_FAILED_LATEST, FlagSeverity.MEDIUM, None),
            (
                AttentionRuleCode.R3_REPEATED_LOW,
                FlagSeverity.HIGH,
                ThresholdKey.REPEATED_LOW_COUNT,
            ),
            (
                AttentionRuleCode.R4_SHARP_DECLINE,
                FlagSeverity.MEDIUM,
                ThresholdKey.DECLINE_DROP_PP,
            ),
            (
                AttentionRuleCode.R5_DECLINING_TREND,
                FlagSeverity.LOW,
                ThresholdKey.TREND_DELTA_PP,
            ),
            (
                AttentionRuleCode.R6_LOW_COMPLETION,
                FlagSeverity.MEDIUM,
                ThresholdKey.LOW_COMPLETION_PERCENT,
            ),
            (
                AttentionRuleCode.R7_BORDERLINE,
                FlagSeverity.LOW,
                ThresholdKey.BORDERLINE_BAND_PP,
            ),
        ],
    )
    def test_code_severity_and_threshold(
        self, code: AttentionRuleCode, severity: FlagSeverity, threshold_key: ThresholdKey | None
    ) -> None:
        rule = ATTENTION_RULES[code]
        assert rule.severity is severity
        assert rule.threshold_key is threshold_key

    def test_stored_code_strings_are_the_enum_names(self) -> None:
        """The persisted value is the code itself, so it reads plainly in a database row."""
        assert AttentionRuleCode.R4_SHARP_DECLINE.value == "R4_SHARP_DECLINE"
        assert AttentionRuleCode.R2_FAILED_LATEST.value == "R2_FAILED_LATEST"

    def test_sharp_decline_is_r4_not_r3(self) -> None:
        """The blueprint called this R3. Ours is R4; R3 is repeated low performance."""
        assert ATTENTION_RULES[AttentionRuleCode.R4_SHARP_DECLINE].title == "Sharp decline"
        assert "Repeatedly below" in ATTENTION_RULES[AttentionRuleCode.R3_REPEATED_LOW].title

    def test_failed_latest_is_r2_not_r6(self) -> None:
        """The blueprint called this R6. Ours is R6 for low completion."""
        assert "latest assessment" in ATTENTION_RULES[AttentionRuleCode.R2_FAILED_LATEST].title
        assert ATTENTION_RULES[AttentionRuleCode.R6_LOW_COMPLETION].title == "Low completion"

    def test_there_is_no_topic_rule(self) -> None:
        """The blueprint's R2 was topic-based. We have no topic data, so it does not exist."""
        for rule in ATTENTION_RULES.values():
            assert "topic" not in rule.definition.lower()
            assert "topic" not in rule.title.lower()


class TestRulesUsingThePassMark:
    def test_pass_mark_rules_are_marked_as_such(self) -> None:
        using = {code for code, rule in ATTENTION_RULES.items() if rule.uses_pass_mark}
        assert using == {
            AttentionRuleCode.R2_FAILED_LATEST,
            AttentionRuleCode.R3_REPEATED_LOW,
            AttentionRuleCode.R7_BORDERLINE,
        }

    def test_multi_assessment_rules_declare_a_sample_size_gate(self) -> None:
        """Decline and trend are meaningless from a single assessment."""
        for code in (AttentionRuleCode.R4_SHARP_DECLINE, AttentionRuleCode.R5_DECLINING_TREND):
            assert ATTENTION_RULES[code].minimum_points_key is ThresholdKey.MIN_TREND_POINTS


class TestEscalation:
    def test_a_single_high_rule_requires_attention(self) -> None:
        assert requires_attention([FlagSeverity.HIGH])

    def test_two_medium_rules_require_attention(self) -> None:
        assert requires_attention([FlagSeverity.MEDIUM, FlagSeverity.MEDIUM])

    def test_one_medium_rule_does_not(self) -> None:
        assert not requires_attention([FlagSeverity.MEDIUM])

    def test_low_rules_alone_never_escalate(self) -> None:
        """Being borderline is worth showing a teacher, but it is not a call to act."""
        assert not requires_attention([FlagSeverity.LOW] * 5)

    def test_one_medium_and_any_number_of_low_rules_does_not_escalate(self) -> None:
        assert not requires_attention([FlagSeverity.MEDIUM, FlagSeverity.LOW, FlagSeverity.LOW])

    def test_no_rules_do_not_escalate(self) -> None:
        assert not requires_attention([])

    def test_high_wins_regardless_of_order(self) -> None:
        assert requires_attention([FlagSeverity.LOW, FlagSeverity.HIGH, FlagSeverity.LOW])


class TestFlagStatus:
    def test_lifecycle_values(self) -> None:
        assert [s.value for s in FlagStatus] == ["open", "acknowledged", "resolved"]
