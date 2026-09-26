"""Contract C5: every threshold analytics uses, where its value came from, and its default.

No academic threshold is hard-coded at a call site. A rule asks this module for a value and
gets back the number *and its provenance*, so an explanation can say "threshold 50%, set for
this offering" rather than just "threshold 50%".

Resolution order, most specific first::

    offering override  ->  department setting  ->  deployment setting  ->  built-in default

The last two are both reported as ``SYSTEM_DEFAULT``: from a faculty member's point of view
"the system default" is one thing, whether it was shipped in this table or set by an
environment variable in :mod:`app.modules.analytics.config`. The distinction that matters to
a reader of an explanation is whether *their* offering or department changed the number.

The pass mark is separate: it is a first-class column on the offering, so it is passed in
rather than resolved, and it is never defaulted here.

Storage for the two override layers does not exist yet. The platform has
``course_offerings.pass_mark_percent`` but no per-offering override document and no
department settings table, so today every value except the pass mark resolves to
``SYSTEM_DEFAULT``. This resolver already accepts both layers, so when that storage lands
only the adapter changes, not any rule. See docs/ANALYTICS_SPEC.md, "Pending platform
dependencies".
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.types import JsonDecimal


class ThresholdKey(StrEnum):
    """Configurable threshold names. These strings are the storage keys."""

    LOW_PERFORMANCE_PERCENT = "low_performance_percent"
    """R1: weighted course score at or below this is low performance."""

    HIGH_PERFORMANCE_PERCENT = "high_performance_percent"
    """Weighted course score at or above this earns the High Performer segment.

    Not a rule threshold — nothing is flagged for doing well — but configurable for the same
    reason the others are: what counts as a high performer differs by institution, and the
    alternative is a 75 hard-coded inside the segmentation module.
    """

    REPEATED_LOW_COUNT = "repeated_low_count"
    """R3: how many consecutive below-pass assessments count as repeated low performance."""

    DECLINE_DROP_PP = "decline_drop_pp"
    """R4: a fall of at least this many percentage points against the earlier mean."""

    TREND_DELTA_PP = "trend_delta_pp"
    """R5: slope, in percentage points per assessment, that separates a trend from stable."""

    LOW_COMPLETION_PERCENT = "low_completion_percent"
    """R6: completion below this is low."""

    BORDERLINE_BAND_PP = "borderline_band_pp"
    """R7: distance either side of the pass mark that counts as borderline."""

    COHORT_SHIFT_PP = "cohort_shift_pp"
    """Movement, in percentage points, that counts as a real shift for a whole cohort.

    One key for every cohort-level movement — class mean, pass rate, participation and
    spread — rather than four that would drift apart in configuration. It answers "is this
    worth telling a teacher about", and the answer should not depend on which of the four
    numbers moved.

    Deliberately separate from ``IMPROVEMENT_DELTA_PP``, which is about one student between
    two assessments: a 5 pp move by one student and a 5 pp move by a whole class are
    different events that a department may well want to tune independently.
    """

    IMPROVEMENT_DELTA_PP = "improvement_delta_pp"
    """Rise, in percentage points, that counts as a real improvement rather than noise.

    Used by most-improved, the Improving segment and the intervention-outcome label. Kept
    separate from ``TREND_DELTA_PP`` because one is a slope across a series and the other is
    a difference between two points; making them one key would silently couple them.
    """

    MIN_GROUP_N = "min_group_n"
    """Fewest assessed students before a group statistic is labelled rather than withheld."""

    MIN_TREND_POINTS = "min_trend_points"
    """Fewest completed assessments before a trend may be classified."""

    MIN_CONSISTENCY_POINTS = "min_consistency_points"
    """Fewest completed assessments before consistency/volatility may be reported."""

    MIN_OUTCOME_GROUP_N = "min_outcome_group_n"
    """Fewest students in *each* of the target and peer groups before an intervention
    outcome may be labelled. Both groups are gated, because a net change computed against a
    two-student peer baseline is not a baseline."""


THRESHOLD_DEFAULTS: Final[Mapping[ThresholdKey, Decimal]] = {
    ThresholdKey.LOW_PERFORMANCE_PERCENT: Decimal("50"),
    ThresholdKey.HIGH_PERFORMANCE_PERCENT: Decimal("75"),
    ThresholdKey.REPEATED_LOW_COUNT: Decimal("3"),
    ThresholdKey.DECLINE_DROP_PP: Decimal("15"),
    ThresholdKey.TREND_DELTA_PP: Decimal("5"),
    ThresholdKey.LOW_COMPLETION_PERCENT: Decimal("75"),
    ThresholdKey.BORDERLINE_BAND_PP: Decimal("5"),
    ThresholdKey.IMPROVEMENT_DELTA_PP: Decimal("5"),
    ThresholdKey.COHORT_SHIFT_PP: Decimal("5"),
    ThresholdKey.MIN_GROUP_N: Decimal("5"),
    ThresholdKey.MIN_TREND_POINTS: Decimal("2"),
    ThresholdKey.MIN_CONSISTENCY_POINTS: Decimal("3"),
    ThresholdKey.MIN_OUTCOME_GROUP_N: Decimal("3"),
}

_PERCENT_KEYS: Final[frozenset[ThresholdKey]] = frozenset(
    {
        ThresholdKey.LOW_PERFORMANCE_PERCENT,
        ThresholdKey.HIGH_PERFORMANCE_PERCENT,
        ThresholdKey.LOW_COMPLETION_PERCENT,
    }
)

_POSITIVE_INT_KEYS: Final[frozenset[ThresholdKey]] = frozenset(
    {
        ThresholdKey.REPEATED_LOW_COUNT,
        ThresholdKey.MIN_GROUP_N,
        ThresholdKey.MIN_TREND_POINTS,
        ThresholdKey.MIN_CONSISTENCY_POINTS,
        ThresholdKey.MIN_OUTCOME_GROUP_N,
    }
)

_POSITIVE_PP_KEYS: Final[frozenset[ThresholdKey]] = frozenset(
    {
        ThresholdKey.DECLINE_DROP_PP,
        ThresholdKey.TREND_DELTA_PP,
        ThresholdKey.BORDERLINE_BAND_PP,
        ThresholdKey.IMPROVEMENT_DELTA_PP,
        ThresholdKey.COHORT_SHIFT_PP,
    }
)


class ThresholdSource(StrEnum):
    OFFERING_OVERRIDE = "offering_override"
    DEPARTMENT_SETTING = "department_setting"
    SYSTEM_DEFAULT = "system_default"


class ResolvedThreshold(BaseModel):
    """One threshold value plus where it came from, for explanation text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ThresholdKey
    value: JsonDecimal
    """``JsonDecimal``, so a threshold quoted in an explanation serialises as a JSON number
    like every other analytics value rather than as a string."""

    source: ThresholdSource


class ThresholdSet(BaseModel):
    """The fully resolved thresholds for one offering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pass_mark_percent: JsonDecimal
    resolved: Mapping[ThresholdKey, ResolvedThreshold]
    ignored_keys: tuple[str, ...] = ()
    """Keys found in stored overrides that this version of analytics does not know.

    Ignored rather than rejected: a newer configuration document must not break an older
    deployment. They are reported so a typo is visible instead of silently inert.
    """

    def value(self, key: ThresholdKey) -> Decimal:
        return self.resolved[key].value

    def source(self, key: ThresholdKey) -> ThresholdSource:
        return self.resolved[key].source

    def count(self, key: ThresholdKey) -> int:
        """A threshold that is conceptually a whole number of items."""
        return int(self.value(key))


def _coerce(key: ThresholdKey, raw: object) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"threshold {key.value} must be a number, got {raw!r}") from exc

    if not value.is_finite():
        raise ValueError(f"threshold {key.value} must be finite, got {raw!r}")

    if key in _PERCENT_KEYS and not (Decimal("0") <= value <= Decimal("100")):
        raise ValueError(f"threshold {key.value} must be between 0 and 100, got {value}")
    if key in _POSITIVE_PP_KEYS and value <= 0:
        raise ValueError(
            f"threshold {key.value} must be positive, got {value}. "
            "Magnitudes are stored positive; the rule applies the direction."
        )
    if key in _POSITIVE_INT_KEYS and (value != value.to_integral_value() or value < 1):
        raise ValueError(f"threshold {key.value} must be a whole number >= 1, got {value}")
    return value


def resolve_thresholds(
    *,
    pass_mark_percent: Decimal,
    offering_overrides: Mapping[str, object] | None = None,
    department_settings: Mapping[str, object] | None = None,
    system_defaults: Mapping[ThresholdKey, object] | None = None,
) -> ThresholdSet:
    """Resolve every threshold for one offering, recording each value's source.

    ``pass_mark_percent`` is the offering's own column and is required: analytics must not
    assume an institutional pass mark.

    ``system_defaults`` lets the deployment override the built-in defaults for keys it
    supplies; :func:`app.modules.analytics.config.system_threshold_defaults` passes the
    settings-derived values in. Keys it omits fall back to :data:`THRESHOLD_DEFAULTS`, and
    every value is validated exactly as a stored override is, so a bad environment variable
    fails loudly rather than producing a nonsensical threshold.
    """
    if not Decimal("0") <= pass_mark_percent <= Decimal("100"):
        raise ValueError(f"pass_mark_percent must be between 0 and 100, got {pass_mark_percent}")

    offering = dict(offering_overrides or {})
    department = dict(department_settings or {})
    deployment = dict(system_defaults or {})
    known = {key.value for key in ThresholdKey}
    ignored = tuple(sorted((set(offering) | set(department)) - known))

    resolved: dict[ThresholdKey, ResolvedThreshold] = {}
    for key in ThresholdKey:
        if key.value in offering:
            source = ThresholdSource.OFFERING_OVERRIDE
            value = _coerce(key, offering[key.value])
        elif key.value in department:
            source = ThresholdSource.DEPARTMENT_SETTING
            value = _coerce(key, department[key.value])
        elif key in deployment:
            source = ThresholdSource.SYSTEM_DEFAULT
            value = _coerce(key, deployment[key])
        else:
            source = ThresholdSource.SYSTEM_DEFAULT
            value = THRESHOLD_DEFAULTS[key]
        resolved[key] = ResolvedThreshold(key=key, value=value, source=source)

    return ThresholdSet(
        pass_mark_percent=pass_mark_percent,
        resolved=resolved,
        ignored_keys=ignored,
    )
