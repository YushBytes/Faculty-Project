"""Label vocabularies: closed sets, and insufficiency kept out of them.

The rule this file defends is the one most likely to be undone by a well-meaning addition:
``insufficient_data`` is a *status* on the result (contract C10), never a member of a
vocabulary. Adding it as a label would give every consumer two ways to ask the same
question and make "Declining" and "we don't know" the same kind of answer.
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from app.modules.analytics.core.vocabulary import (
    SEGMENT_PRIORITY,
    VOCABULARIES,
    SegmentLabel,
    TrendLabel,
    TrendMethod,
)


class TestVocabulariesAreClosedSets:
    @pytest.mark.parametrize("name", sorted(VOCABULARIES))
    def test_no_vocabulary_contains_insufficient_data(self, name: str) -> None:
        values = {member.value for member in VOCABULARIES[name]}
        assert "insufficient_data" not in values, (
            f"{name} must not carry insufficient_data as a label: it is a status on the "
            "result, per contract C10."
        )

    @pytest.mark.parametrize("name", sorted(VOCABULARIES))
    def test_vocabulary_values_are_unique_and_lowercase(self, name: str) -> None:
        members: type[StrEnum] = VOCABULARIES[name]
        values = [member.value for member in members]
        assert len(values) == len(set(values))
        assert all(value == value.lower() for value in values)

    def test_the_trend_vocabulary_is_the_three_documented_directions(self) -> None:
        assert {t.value for t in TrendLabel} == {"improving", "stable", "declining"}


class TestSegmentPriority:
    def test_every_segment_has_a_priority(self) -> None:
        """A student who satisfies a segment with no priority would have no primary status."""
        assert set(SEGMENT_PRIORITY) == set(SegmentLabel)
        assert len(SEGMENT_PRIORITY) == len(SegmentLabel)

    def test_the_most_actionable_segment_wins(self) -> None:
        satisfied = {SegmentLabel.IMPROVING, SegmentLabel.BORDERLINE, SegmentLabel.STABLE}
        primary = next(s for s in SEGMENT_PRIORITY if s in satisfied)
        assert primary is SegmentLabel.BORDERLINE

    def test_stable_is_the_fallback(self) -> None:
        assert SEGMENT_PRIORITY[-1] is SegmentLabel.STABLE


class TestTrendMethod:
    def test_a_two_point_difference_is_not_called_a_slope(self) -> None:
        """Quoting the method stops a two-point delta being read as a fitted trend."""
        assert {m.value for m in TrendMethod} == {"two_point_delta", "least_squares"}
