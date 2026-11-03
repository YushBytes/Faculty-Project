"""Contract C10: insufficient data is an outcome, and no non-finite number escapes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.results import (
    Label,
    Measure,
    MeasureStatus,
    Unit,
    insufficient_label,
    insufficient_measure,
    label,
    measure,
    shortfall,
)


class TestMeasure:
    def test_ok_measure_carries_value_unit_and_sample_size(self) -> None:
        result = measure(Decimal("62.50"), unit=Unit.PERCENT, n=42)
        assert result.is_ok
        assert result.value == Decimal("62.50")
        assert result.unit is Unit.PERCENT
        assert result.n == 42
        assert result.reason is None

    def test_insufficient_measure_has_no_value_and_explains_itself(self) -> None:
        result = insufficient_measure(
            unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT,
            n=1,
            minimum_n=2,
            reason=shortfall(have=1, need=2, noun="completed assessment"),
        )
        assert not result.is_ok
        assert result.status is MeasureStatus.INSUFFICIENT_DATA
        assert result.value is None
        assert result.n == 1
        assert result.minimum_n == 2
        assert result.reason == "only 1 completed assessment available (minimum 2)"

    def test_insufficient_measure_must_not_be_a_fabricated_zero(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a value"):
            Measure(
                status=MeasureStatus.INSUFFICIENT_DATA,
                value=Decimal("0"),
                unit=Unit.PERCENT,
                n=0,
                reason="no data",
            )

    def test_ok_measure_without_a_value_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must carry a value"):
            Measure(status=MeasureStatus.OK, value=None, unit=Unit.PERCENT, n=3)

    def test_insufficient_measure_without_a_reason_is_rejected(self) -> None:
        """A withheld number that does not say why is not explainable."""
        with pytest.raises(ValidationError, match="must explain itself"):
            Measure(status=MeasureStatus.INSUFFICIENT_DATA, unit=Unit.PERCENT, n=0)

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
    def test_non_finite_decimals_are_refused(self, bad: str) -> None:
        """Decimal has its own NaN and infinities; none may reach an API response."""
        with pytest.raises(ValidationError, match="finite"):
            measure(Decimal(bad), unit=Unit.PERCENT, n=5)

    def test_negative_sample_size_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            measure(Decimal("1"), unit=Unit.PERCENT, n=-1)

    def test_measures_are_immutable(self) -> None:
        result = measure(Decimal("1"), unit=Unit.COUNT, n=1)
        with pytest.raises(ValidationError):
            result.value = Decimal("2")  # type: ignore[misc]

    def test_signed_percentage_point_measures_are_allowed(self) -> None:
        """A decline is negative; only percentages themselves are bounded to 0-100."""
        result = measure(Decimal("-18.50"), unit=Unit.PERCENTAGE_POINTS, n=7)
        assert result.value == Decimal("-18.50")


class TestLabel:
    def test_ok_label_records_its_vocabulary(self) -> None:
        result = label("declining", vocabulary="TrendLabel", n=3)
        assert result.is_ok
        assert result.value == "declining"
        assert result.vocabulary == "TrendLabel"

    def test_insufficient_label_has_no_value(self) -> None:
        result = insufficient_label(
            vocabulary="TrendLabel",
            n=1,
            minimum_n=2,
            reason=shortfall(have=1, need=2, noun="completed assessment"),
        )
        assert result.value is None
        assert result.reason is not None

    def test_ok_label_without_a_value_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must carry a value"):
            Label(status=MeasureStatus.OK, value=None, vocabulary="TrendLabel", n=3)

    def test_insufficient_label_must_not_carry_a_value(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a value"):
            Label(
                status=MeasureStatus.INSUFFICIENT_DATA,
                value="stable",
                vocabulary="TrendLabel",
                n=1,
                reason="not enough data",
            )


class TestShortfall:
    @pytest.mark.parametrize(
        ("have", "need", "noun", "expected"),
        [
            (1, 2, "completed assessment", "only 1 completed assessment available (minimum 2)"),
            (3, 5, "assessed student", "only 3 assessed students available (minimum 5)"),
            (0, 5, "assessed student", "only 0 assessed students available (minimum 5)"),
        ],
    )
    def test_wording_is_consistent(self, have: int, need: int, noun: str, expected: str) -> None:
        assert shortfall(have=have, need=need, noun=noun) == expected


class TestJsonSerialisation:
    def test_measure_serialises_decimal_as_a_json_number(self) -> None:
        payload = measure(Decimal("62.50"), unit=Unit.PERCENT, n=42).model_dump(mode="json")
        assert payload == {
            "status": "ok",
            "value": 62.5,
            "unit": "percent",
            "n": 42,
            "minimum_n": None,
            "reason": None,
        }

    def test_insufficient_measure_serialises_value_as_null(self) -> None:
        payload = insufficient_measure(
            unit=Unit.PERCENT, n=2, minimum_n=5, reason="too few"
        ).model_dump(mode="json")
        assert payload["value"] is None
        assert payload["status"] == "insufficient_data"
