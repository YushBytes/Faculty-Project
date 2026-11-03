"""Contract C5: threshold resolution order, provenance and validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.thresholds import (
    THRESHOLD_DEFAULTS,
    ThresholdKey,
    ThresholdSource,
    resolve_thresholds,
)


class TestDefaults:
    def test_every_key_has_a_default(self) -> None:
        assert set(THRESHOLD_DEFAULTS) == set(ThresholdKey)

    def test_documented_default_values(self) -> None:
        """These are the numbers documented in docs/PROJECT_CONTEXT.md section 10."""
        resolved = resolve_thresholds(pass_mark_percent=Decimal("40"))
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("50")
        assert resolved.count(ThresholdKey.REPEATED_LOW_COUNT) == 3
        assert resolved.value(ThresholdKey.DECLINE_DROP_PP) == Decimal("15")
        assert resolved.value(ThresholdKey.TREND_DELTA_PP) == Decimal("5")
        assert resolved.value(ThresholdKey.LOW_COMPLETION_PERCENT) == Decimal("75")
        assert resolved.value(ThresholdKey.BORDERLINE_BAND_PP) == Decimal("5")
        assert resolved.value(ThresholdKey.COHORT_SHIFT_PP) == Decimal("5")
        assert resolved.count(ThresholdKey.MIN_GROUP_N) == 5
        assert resolved.count(ThresholdKey.MIN_TREND_POINTS) == 2
        assert resolved.count(ThresholdKey.MIN_CONSISTENCY_POINTS) == 3

    def test_all_defaults_report_themselves_as_defaults(self) -> None:
        resolved = resolve_thresholds(pass_mark_percent=Decimal("40"))
        for key in ThresholdKey:
            assert resolved.source(key) is ThresholdSource.SYSTEM_DEFAULT


class TestResolutionOrder:
    def test_offering_override_beats_department_setting_and_default(self) -> None:
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"),
            offering_overrides={"low_performance_percent": "55"},
            department_settings={"low_performance_percent": "45"},
        )
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("55")
        assert resolved.source(ThresholdKey.LOW_PERFORMANCE_PERCENT) is (
            ThresholdSource.OFFERING_OVERRIDE
        )

    def test_department_setting_beats_default(self) -> None:
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"),
            department_settings={"borderline_band_pp": "3"},
        )
        assert resolved.value(ThresholdKey.BORDERLINE_BAND_PP) == Decimal("3")
        assert resolved.source(ThresholdKey.BORDERLINE_BAND_PP) is (
            ThresholdSource.DEPARTMENT_SETTING
        )

    def test_sources_are_tracked_per_key_not_per_set(self) -> None:
        """An explanation names the origin of the one threshold it quotes."""
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"),
            offering_overrides={"decline_drop_pp": "20"},
            department_settings={"trend_delta_pp": "4"},
        )
        assert resolved.source(ThresholdKey.DECLINE_DROP_PP) is ThresholdSource.OFFERING_OVERRIDE
        assert resolved.source(ThresholdKey.TREND_DELTA_PP) is ThresholdSource.DEPARTMENT_SETTING
        assert resolved.source(ThresholdKey.MIN_GROUP_N) is ThresholdSource.SYSTEM_DEFAULT


class TestPassMark:
    def test_pass_mark_is_carried_not_defaulted(self) -> None:
        """The offering's pass mark is authoritative; analytics never supplies one."""
        assert resolve_thresholds(pass_mark_percent=Decimal("33.50")).pass_mark_percent == Decimal(
            "33.50"
        )

    @pytest.mark.parametrize("bad", ["-1", "101"])
    def test_out_of_range_pass_mark_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="pass_mark_percent must be between 0 and 100"):
            resolve_thresholds(pass_mark_percent=Decimal(bad))

    def test_pass_mark_is_independent_of_the_low_performance_threshold(self) -> None:
        """They are different questions: 'did they pass' and 'are they performing poorly'."""
        resolved = resolve_thresholds(pass_mark_percent=Decimal("40"))
        assert resolved.pass_mark_percent == Decimal("40")
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("50")


class TestValidation:
    def test_non_numeric_override_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a number"):
            resolve_thresholds(
                pass_mark_percent=Decimal("40"),
                offering_overrides={"low_performance_percent": "half"},
            )

    def test_percentage_threshold_outside_zero_to_one_hundred_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            resolve_thresholds(
                pass_mark_percent=Decimal("40"),
                offering_overrides={"low_completion_percent": "150"},
            )

    @pytest.mark.parametrize(
        "key", ["decline_drop_pp", "trend_delta_pp", "borderline_band_pp", "cohort_shift_pp"]
    )
    def test_magnitude_thresholds_must_be_positive(self, key: str) -> None:
        """Stored as positive magnitudes; the rule applies the direction."""
        with pytest.raises(ValueError, match="must be positive"):
            resolve_thresholds(pass_mark_percent=Decimal("40"), offering_overrides={key: "-15"})

    @pytest.mark.parametrize("bad", ["0", "2.5", "-1"])
    def test_count_thresholds_must_be_whole_numbers_of_at_least_one(self, bad: str) -> None:
        with pytest.raises(ValueError, match="whole number"):
            resolve_thresholds(
                pass_mark_percent=Decimal("40"),
                offering_overrides={"repeated_low_count": bad},
            )

    def test_non_finite_override_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be finite"):
            resolve_thresholds(
                pass_mark_percent=Decimal("40"),
                offering_overrides={"decline_drop_pp": "NaN"},
            )

    def test_integers_and_floats_are_accepted_as_stored_json_values(self) -> None:
        """Stored overrides arrive as JSON, so the types are whatever the document held."""
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"),
            offering_overrides={"repeated_low_count": 4, "decline_drop_pp": 12.5},
        )
        assert resolved.count(ThresholdKey.REPEATED_LOW_COUNT) == 4
        assert resolved.value(ThresholdKey.DECLINE_DROP_PP) == Decimal("12.5")


class TestUnknownKeys:
    def test_unknown_keys_are_ignored_and_reported(self) -> None:
        """A newer config document must not break an older deployment, but a typo must show."""
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"),
            offering_overrides={"low_performance_pct": "55", "future_rule_threshold": 1},
        )
        assert resolved.ignored_keys == ("future_rule_threshold", "low_performance_pct")
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("50")

    def test_no_unknown_keys_when_configuration_is_clean(self) -> None:
        resolved = resolve_thresholds(
            pass_mark_percent=Decimal("40"), offering_overrides={"trend_delta_pp": "6"}
        )
        assert resolved.ignored_keys == ()
