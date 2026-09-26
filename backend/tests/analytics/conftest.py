"""Fixtures for the analytics suite: snapshots, thresholds and a fixed clock.

These wrap :mod:`tests.analytics.builders` so a test can ask for the condition it is about
(``declining``, ``absent``) instead of assembling an offering. Nothing here touches the
database; the root ``conftest.py`` fixtures are not used by this package.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.analytics.core.contracts import OfferingSnapshot
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from tests.analytics import builders, canonical

FIXED_NOW = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)
"""A fixed, timezone-aware instant. Outputs are stamped, so tests must not use ``now()``."""


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def snapshot() -> OfferingSnapshot:
    """The canonical eight-student cohort."""
    return canonical.snapshot()


@pytest.fixture
def thresholds(snapshot: OfferingSnapshot) -> ThresholdSet:
    """Defaults resolved against the canonical offering's own pass mark."""
    return resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)


@pytest.fixture
def single_student() -> OfferingSnapshot:
    return builders.single_student()


@pytest.fixture
def small_class() -> OfferingSnapshot:
    return builders.small_class()


@pytest.fixture
def multi_assessment_class() -> OfferingSnapshot:
    return builders.multi_assessment_class()


@pytest.fixture
def missing_results() -> OfferingSnapshot:
    return builders.missing_results()


@pytest.fixture
def absent_students() -> OfferingSnapshot:
    return builders.absent_students()


@pytest.fixture
def improving_students() -> OfferingSnapshot:
    return builders.improving_students()


@pytest.fixture
def declining_students() -> OfferingSnapshot:
    return builders.declining_students()


@pytest.fixture
def borderline_students() -> OfferingSnapshot:
    return builders.borderline_students()


@pytest.fixture
def volatile_students() -> OfferingSnapshot:
    return builders.volatile_students()
