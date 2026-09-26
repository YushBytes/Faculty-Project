"""Shared API value types."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer, StringConstraints

# Decimals are exact in Python and PostgreSQL (NUMERIC) and serialise as JSON numbers.
JsonDecimal = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
Percent = Annotated[JsonDecimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]

Code = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=32)
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
