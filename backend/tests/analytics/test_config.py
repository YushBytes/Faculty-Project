"""Configuration: one name per threshold, one place for each default, one resolution order.

The failure this guards against is a threshold that is configurable in theory and
hard-coded in practice — an environment variable nobody reads, or a default written down
twice and changed once.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from app.modules.analytics.config import (
    AnalyticsSettings,
    get_analytics_settings,
    resolve_offering_thresholds,
    system_threshold_defaults,
)
from app.modules.analytics.core.thresholds import (
    THRESHOLD_DEFAULTS,
    ThresholdKey,
    ThresholdSource,
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    """Settings are cached like the platform's own, so each test starts from the environment."""
    get_analytics_settings.cache_clear()
    yield
    get_analytics_settings.cache_clear()


class TestKeyNames:
    def test_every_threshold_key_is_a_settings_field(self) -> None:
        """One word for the env var, the stored override key and the settings field."""
        assert {key.value for key in ThresholdKey} == set(AnalyticsSettings.model_fields)

    def test_no_settings_field_is_a_threshold_nobody_knows(self) -> None:
        unknown = set(AnalyticsSettings.model_fields) - {key.value for key in ThresholdKey}
        assert not unknown


class TestDefaults:
    def test_the_defaults_are_the_cores_defaults(self) -> None:
        """Written down once: the settings field defaults *are* THRESHOLD_DEFAULTS."""
        assert system_threshold_defaults() == dict(THRESHOLD_DEFAULTS)

    def test_a_resolved_set_with_no_overrides_matches_the_documented_numbers(self) -> None:
        resolved = resolve_offering_thresholds(pass_mark_percent=Decimal("40"))
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("50")
        assert resolved.value(ThresholdKey.HIGH_PERFORMANCE_PERCENT) == Decimal("75")
        assert resolved.value(ThresholdKey.TREND_DELTA_PP) == Decimal("5")
        assert resolved.value(ThresholdKey.DECLINE_DROP_PP) == Decimal("15")
        assert resolved.value(ThresholdKey.BORDERLINE_BAND_PP) == Decimal("5")
        assert resolved.value(ThresholdKey.IMPROVEMENT_DELTA_PP) == Decimal("5")
        assert resolved.value(ThresholdKey.COHORT_SHIFT_PP) == Decimal("5")
        assert resolved.count(ThresholdKey.REPEATED_LOW_COUNT) == 3
        assert resolved.count(ThresholdKey.MIN_OUTCOME_GROUP_N) == 3


class TestEnvironmentOverrides:
    def test_an_environment_variable_changes_the_system_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANALYTICS_LOW_PERFORMANCE_PERCENT", "55")
        get_analytics_settings.cache_clear()
        resolved = resolve_offering_thresholds(pass_mark_percent=Decimal("40"))
        assert resolved.value(ThresholdKey.LOW_PERFORMANCE_PERCENT) == Decimal("55")

    def test_a_deployment_value_is_still_reported_as_a_system_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """To a faculty member, "the system default" is one thing however it was set.

        What an explanation has to distinguish is whether *their* offering or department
        changed the number.
        """
        monkeypatch.setenv("ANALYTICS_TREND_DELTA_PP", "7")
        get_analytics_settings.cache_clear()
        resolved = resolve_offering_thresholds(pass_mark_percent=Decimal("40"))
        assert resolved.value(ThresholdKey.TREND_DELTA_PP) == Decimal("7")
        assert resolved.source(ThresholdKey.TREND_DELTA_PP) is ThresholdSource.SYSTEM_DEFAULT

    def test_stored_overrides_still_outrank_the_deployment_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANALYTICS_BORDERLINE_BAND_PP", "8")
        get_analytics_settings.cache_clear()
        resolved = resolve_offering_thresholds(
            pass_mark_percent=Decimal("40"),
            department_settings={"borderline_band_pp": "6"},
            offering_overrides={"borderline_band_pp": "4"},
        )
        assert resolved.value(ThresholdKey.BORDERLINE_BAND_PP) == Decimal("4")
        assert resolved.source(ThresholdKey.BORDERLINE_BAND_PP) is (
            ThresholdSource.OFFERING_OVERRIDE
        )

    def test_a_nonsensical_environment_value_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A misconfigured deployment must not silently run on a negative threshold."""
        monkeypatch.setenv("ANALYTICS_DECLINE_DROP_PP", "-15")
        get_analytics_settings.cache_clear()
        with pytest.raises(ValueError, match="must be positive"):
            resolve_offering_thresholds(pass_mark_percent=Decimal("40"))

    def test_an_out_of_range_environment_percentage_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANALYTICS_LOW_COMPLETION_PERCENT", "140")
        get_analytics_settings.cache_clear()
        with pytest.raises(ValueError, match="between 0 and 100"):
            resolve_offering_thresholds(pass_mark_percent=Decimal("40"))


class TestPassMark:
    def test_the_pass_mark_is_not_configurable_here(self) -> None:
        """It is the offering's own column: an institution-wide pass mark is not a thing."""
        assert "pass_mark_percent" not in AnalyticsSettings.model_fields
        assert resolve_offering_thresholds(
            pass_mark_percent=Decimal("33.50")
        ).pass_mark_percent == Decimal("33.50")
