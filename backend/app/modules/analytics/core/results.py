"""Contract C10: how a computed value is returned, including when it cannot be computed.

Two rules drive this module.

*Insufficient data is an outcome, not an error.* When a cohort is too small or a student has
too few assessments for a statement to mean anything, the analytic returns a value of
``None`` with ``status="insufficient_data"`` and a human-readable reason naming the actual
and required sample size. It is still a 200 response. It is never a fabricated ``0``, and
never a label the data does not support.

*No non-finite number ever leaves the core.* ``NaN`` and infinities are rejected at
construction, so they cannot reach an API response, a report or a chart. ``Decimal`` has its
own ``NaN``/``Infinity`` values, so the guard checks ``is_finite`` rather than trusting the
type.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import JsonDecimal


class MeasureStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


class Unit(StrEnum):
    """What a number means, so a caller never has to guess at its scale."""

    PERCENT = "percent"
    """A percentage of a maximum, 0-100."""

    PERCENTAGE_POINTS = "percentage_points"
    """A signed difference between two percentages."""

    PERCENTAGE_POINTS_PER_ASSESSMENT = "percentage_points_per_assessment"
    """A trend slope."""

    COUNT = "count"
    """A whole number of students, assessments or occurrences."""

    MARKS = "marks"
    """Raw marks, in the assessment's own scale."""


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: MeasureStatus
    n: int = Field(ge=0, description="Sample size actually used to compute this.")
    minimum_n: int | None = Field(
        default=None, ge=0, description="Sample size the rule requires, when one applies."
    )
    reason: str | None = Field(
        default=None, description="Why the value is absent. Required when insufficient."
    )

    @model_validator(mode="after")
    def _reason_present_when_insufficient(self) -> Self:
        if self.status is MeasureStatus.INSUFFICIENT_DATA and not self.reason:
            raise ValueError("an insufficient_data result must explain itself")
        return self

    @property
    def is_ok(self) -> bool:
        return self.status is MeasureStatus.OK


class Measure(_Result):
    """A single numeric analytics output, with the evidence needed to explain it."""

    value: JsonDecimal | None = None
    unit: Unit

    @model_validator(mode="after")
    def _value_matches_status(self) -> Self:
        if self.status is MeasureStatus.OK:
            if self.value is None:
                raise ValueError("an ok measure must carry a value")
        elif self.value is not None:
            raise ValueError("an insufficient_data measure must not carry a value")
        _reject_non_finite(self.value)
        return self


class Label(_Result):
    """A single categorical analytics output (a trend, a segment).

    ``value`` is a plain string so any module can supply its own vocabulary; the enum that
    produced it is named in ``vocabulary`` for traceability.
    """

    value: str | None = None
    vocabulary: str

    @model_validator(mode="after")
    def _value_matches_status(self) -> Self:
        if self.status is MeasureStatus.OK:
            if not self.value:
                raise ValueError("an ok label must carry a value")
        elif self.value is not None:
            raise ValueError("an insufficient_data label must not carry a value")
        return self


def _reject_non_finite(value: Any) -> None:
    """Guard against NaN and infinity, which must never reach a caller."""
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("value must be finite: NaN and infinity must never leave analytics")
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise ValueError("value must be finite: NaN and infinity must never leave analytics")


def measure(value: Decimal, *, unit: Unit, n: int, minimum_n: int | None = None) -> Measure:
    """A computed measure."""
    return Measure(status=MeasureStatus.OK, value=value, unit=unit, n=n, minimum_n=minimum_n)


def insufficient_measure(*, unit: Unit, n: int, minimum_n: int, reason: str) -> Measure:
    """A measure that cannot be computed, with the shortfall stated."""
    return Measure(
        status=MeasureStatus.INSUFFICIENT_DATA,
        value=None,
        unit=unit,
        n=n,
        minimum_n=minimum_n,
        reason=reason,
    )


def label(value: StrEnum | str, *, vocabulary: str, n: int, minimum_n: int | None = None) -> Label:
    """A computed categorical label."""
    return Label(
        status=MeasureStatus.OK,
        value=str(value),
        vocabulary=vocabulary,
        n=n,
        minimum_n=minimum_n,
    )


def insufficient_label(*, vocabulary: str, n: int, minimum_n: int, reason: str) -> Label:
    """A label that cannot be assigned, with the shortfall stated."""
    return Label(
        status=MeasureStatus.INSUFFICIENT_DATA,
        value=None,
        vocabulary=vocabulary,
        n=n,
        minimum_n=minimum_n,
        reason=reason,
    )


def shortfall(*, have: int, need: int, noun: str) -> str:
    """Standard wording for a sample-size shortfall, so every reason reads the same."""
    return f"only {have} {noun}{'' if have == 1 else 's'} available (minimum {need})"
