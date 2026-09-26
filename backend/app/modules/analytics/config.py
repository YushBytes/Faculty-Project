"""Deployment-level analytics configuration: the system defaults, as settings.

This is the adapter between the project's settings architecture
(:mod:`app.core.config` — ``pydantic-settings``, environment-driven, ``lru_cache``-d) and
the pure resolver in :mod:`app.modules.analytics.core.thresholds`. It lives outside
``core`` on purpose: the core must stay importable and testable with nothing but plain
data, so it never reads an environment variable itself.

Why a separate settings class rather than fields on :class:`app.core.config.Settings`:
``Settings`` is Agent 1's platform configuration and analytics owns the threshold key names
by contract C5. Keeping the analytics block in the module that owns it means one agent's
new threshold is not an edit to the other agent's file, while the mechanism — the same
``BaseSettings``, the same ``.env``, the same cached accessor — stays identical.

Every field defaults to the built-in value in
:data:`~app.modules.analytics.core.thresholds.THRESHOLD_DEFAULTS`, so there is exactly one
place a default number is written down. Environment variables are prefixed ``ANALYTICS_``::

    ANALYTICS_LOW_PERFORMANCE_PERCENT=55
    ANALYTICS_REPEATED_LOW_COUNT=2

Values from here are reported as ``SYSTEM_DEFAULT``: a deployment-wide setting is still the
system's number, not this offering's or this department's. Per-offering and per-department
overrides are stored data and outrank it; see contract C5.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.analytics.core.thresholds import (
    THRESHOLD_DEFAULTS,
    ThresholdKey,
    ThresholdSet,
    resolve_thresholds,
)


def _default(key: ThresholdKey) -> Decimal:
    return THRESHOLD_DEFAULTS[key]


class AnalyticsSettings(BaseSettings):
    """System defaults for every configurable analytics threshold.

    Field names are exactly the :class:`ThresholdKey` values, which is asserted by the test
    suite: the environment variable, the stored override key and the settings field are then
    always the same word, and a rename cannot leave three spellings behind.
    """

    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    low_performance_percent: Decimal = _default(ThresholdKey.LOW_PERFORMANCE_PERCENT)
    high_performance_percent: Decimal = _default(ThresholdKey.HIGH_PERFORMANCE_PERCENT)
    repeated_low_count: Decimal = _default(ThresholdKey.REPEATED_LOW_COUNT)
    decline_drop_pp: Decimal = _default(ThresholdKey.DECLINE_DROP_PP)
    trend_delta_pp: Decimal = _default(ThresholdKey.TREND_DELTA_PP)
    low_completion_percent: Decimal = _default(ThresholdKey.LOW_COMPLETION_PERCENT)
    borderline_band_pp: Decimal = _default(ThresholdKey.BORDERLINE_BAND_PP)
    improvement_delta_pp: Decimal = _default(ThresholdKey.IMPROVEMENT_DELTA_PP)
    min_group_n: Decimal = _default(ThresholdKey.MIN_GROUP_N)
    min_trend_points: Decimal = _default(ThresholdKey.MIN_TREND_POINTS)
    min_consistency_points: Decimal = _default(ThresholdKey.MIN_CONSISTENCY_POINTS)
    min_outcome_group_n: Decimal = _default(ThresholdKey.MIN_OUTCOME_GROUP_N)

    def as_threshold_defaults(self) -> Mapping[ThresholdKey, Decimal]:
        """This deployment's defaults, keyed for the resolver."""
        return {key: getattr(self, key.value) for key in ThresholdKey}


@lru_cache
def get_analytics_settings() -> AnalyticsSettings:
    """Cached settings, mirroring :func:`app.core.config.get_settings`.

    Tests that change the environment call ``get_analytics_settings.cache_clear()``, exactly
    as the platform's own settings fixture does.
    """
    return AnalyticsSettings()


def system_threshold_defaults() -> Mapping[ThresholdKey, Decimal]:
    """The system-default layer to hand to :func:`resolve_thresholds`."""
    return get_analytics_settings().as_threshold_defaults()


def resolve_offering_thresholds(
    *,
    pass_mark_percent: Decimal,
    offering_overrides: Mapping[str, object] | None = None,
    department_settings: Mapping[str, object] | None = None,
) -> ThresholdSet:
    """Resolve an offering's thresholds with this deployment's defaults underneath.

    The one call sites should use. It exists so no service ever assembles the resolution
    order itself, which is how a layer gets skipped.

    ``offering_overrides`` and ``department_settings`` are the stored layers from contract
    C5. Neither has storage yet (there is no ``course_offerings.config`` column and no
    ``settings`` table), so today both arrive empty and every value resolves to the system
    default; see docs/ANALYTICS_SPEC.md, "Pending platform dependencies".
    """
    return resolve_thresholds(
        pass_mark_percent=pass_mark_percent,
        offering_overrides=offering_overrides,
        department_settings=department_settings,
        system_defaults=system_threshold_defaults(),
    )
