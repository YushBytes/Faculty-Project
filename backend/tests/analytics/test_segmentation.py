"""F17: which segments a student satisfies, and which one a teacher should act on.

Segmentation adds no arithmetic, so most of these tests are about *composition*: the
segments must fall out of the Phase 2/3 facts, and the primary must follow the priority
order rather than the order the conditions happen to be evaluated in.

Canonical cohort (pass 40, low 50, high 75, band 5 pp):

=====  ========================  =========================================================
who    W / trend                 segments
=====  ========================  =========================================================
S1     93.00 / stable            high performer
S2     55.00 / declining         declining
S3     69.50 / declining         declining (also a sharp decline)
S4     41.00 / stable            persistently low (W <= 50) **and** borderline (1 pp away)
S5     33.00 / stable            persistently low
S6     60.00 / insufficient      none satisfied, trend unclassifiable -> no segment
S7     50.00 / insufficient      persistently low (W is exactly the threshold)
=====  ========================  =========================================================
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.profile import cohort_profiles, student_profile
from app.modules.analytics.core.results import MeasureStatus
from app.modules.analytics.core.segmentation import (
    cohort_segments,
    segment_counts,
    student_segment,
)
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import SEGMENT_PRIORITY, SegmentLabel
from tests.analytics import builders as b
from tests.analytics import canonical as fx


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def segment(student: object, snapshot: object | None = None) -> object:
    used = snapshot or fx.snapshot()
    thresholds = resolve_thresholds(pass_mark_percent=used.pass_mark_percent)
    return student_segment(used, student, thresholds)  # type: ignore[arg-type]


def labels(built: object) -> list[str]:
    return [f.segment.value for f in built.factors]  # type: ignore[attr-defined]


class TestCanonicalSegments:
    @pytest.mark.parametrize(
        ("student", "primary", "factors"),
        [
            (fx.S1, "high_performer", ["high_performer"]),
            (fx.S2, "declining", ["declining"]),
            (fx.S3, "declining", ["declining"]),
            (fx.S4, "persistently_low", ["persistently_low", "borderline"]),
            (fx.S5, "persistently_low", ["persistently_low"]),
            (fx.S7, "persistently_low", ["persistently_low"]),
        ],
        ids=["S1", "S2", "S3", "S4", "S5", "S7"],
    )
    def test_primary_and_factors(self, student: object, primary: str, factors: list[str]) -> None:
        built = segment(student)
        assert built.primary.value == primary
        assert labels(built) == factors

    def test_a_student_may_hold_several_segments_at_once(self) -> None:
        """S4's course score is 41: low enough to worry about, close enough to the mark to fix."""
        built = segment(fx.S4)
        assert set(labels(built)) == {"persistently_low", "borderline"}
        assert built.primary.value == "persistently_low", "priority picks the actionable one"

    def test_the_primary_is_always_among_the_factors(self) -> None:
        for student in (fx.S1, fx.S2, fx.S3, fx.S4, fx.S5, fx.S7):
            built = segment(student)
            assert built.primary.value in labels(built)


class TestSegmentRules:
    def test_high_performer_uses_the_configured_threshold_inclusively(self) -> None:
        snapshot = b.build_snapshot({"at": (75, 75), "below": (74, 74)})
        assert labels(segment(b.student_id("at"), snapshot)) == ["high_performer"]
        assert "high_performer" not in labels(segment(b.student_id("below"), snapshot))

    def test_persistently_low_uses_the_low_threshold_inclusively(self) -> None:
        snapshot = b.build_snapshot({"at": (50, 50), "above": (51, 51)})
        assert labels(segment(b.student_id("at"), snapshot)) == ["persistently_low"]
        assert "persistently_low" not in labels(segment(b.student_id("above"), snapshot))

    def test_a_run_below_the_pass_mark_is_persistently_low_even_with_a_higher_score(
        self,
    ) -> None:
        """Course score 52 from an early high, but the last three are all below the mark."""
        snapshot = b.build_snapshot({"s1": (100, 30, 30, 30)})
        built = segment(b.student_id("s1"), snapshot)
        assert "persistently_low" in labels(built)

    def test_declining_comes_from_the_trend_or_from_a_sharp_fall(self) -> None:
        by_trend = segment(b.student_id("s1"), b.declining_students())
        assert "declining" in labels(by_trend)
        by_cliff = segment(b.student_id("s4"), b.declining_students())
        assert "declining" in labels(by_cliff)

    def test_improving_comes_from_the_trend(self) -> None:
        snapshot = b.build_snapshot({"s1": (60, 70, 80)})
        built = segment(b.student_id("s1"), snapshot)
        assert labels(built) == ["improving"]
        assert built.primary.value == "improving"

    def test_a_student_improving_from_a_low_base_is_shown_as_low_first(self) -> None:
        """40, 50, 60 is a real improvement and a course score of 50.00, which is still low.

        Both are true and both are reported; the primary is the one a teacher acts on.
        """
        built = segment(b.student_id("s1"), b.improving_students())
        assert set(labels(built)) == {"persistently_low", "improving"}
        assert built.primary.value == "persistently_low"

    def test_borderline_is_measured_against_the_offerings_pass_mark(self) -> None:
        snapshot = b.build_snapshot({"s1": (45, 45)}, pass_mark=50)
        assert "borderline" in labels(segment(b.student_id("s1"), snapshot))
        elsewhere = b.build_snapshot({"s1": (45, 45)}, pass_mark=80)
        assert "borderline" not in labels(segment(b.student_id("s1"), elsewhere))

    def test_stable_is_only_claimed_when_the_trend_was_classifiable(self) -> None:
        snapshot = b.build_snapshot({"s1": (65, 66, 67)})
        built = segment(b.student_id("s1"), snapshot)
        assert labels(built) == ["stable"]
        assert built.primary.value == "stable"

    def test_priority_decides_the_primary_not_evaluation_order(self) -> None:
        """Declining and borderline at once: the teacher sees declining.

        Pass mark 50 here, so a course score of 52.00 is borderline (within 5 pp) without
        also being low — see the threshold-interaction test below for why that matters.
        """
        snapshot = b.build_snapshot({"s1": (60, 52, 44)}, pass_mark=50)
        built = segment(b.student_id("s1"), snapshot)
        assert set(labels(built)) == {"declining", "borderline"}
        assert built.primary.value == "declining"
        assert SEGMENT_PRIORITY.index(SegmentLabel.DECLINING) < SEGMENT_PRIORITY.index(
            SegmentLabel.BORDERLINE
        )

    def test_borderline_can_be_primary_when_the_thresholds_leave_room(self) -> None:
        """A consequence of configuration, not of code, worth pinning down.

        With a pass mark of 40 and a low-performance threshold of 50, the borderline band
        (35-45) sits entirely inside the low band, so every borderline student is also
        persistently low and borderline is never the primary. Raise the pass mark to the
        platform's own default of 50 and the bands separate: 52.00 is borderline and not low.
        """
        narrow = b.build_snapshot({"s1": (44, 44, 44)})
        assert segment(b.student_id("s1"), narrow).primary.value == "persistently_low"

        roomy = b.build_snapshot({"s1": (52, 52, 52)}, pass_mark=50)
        built = segment(b.student_id("s1"), roomy)
        assert labels(built) == ["borderline"]
        assert built.primary.value == "borderline"


class TestInsufficientData:
    def test_an_unclassifiable_student_is_not_quietly_called_stable(self) -> None:
        """S6 has one completed assessment at 60: no trend, and no other segment applies."""
        built = segment(fx.S6)
        assert built.primary.status is MeasureStatus.INSUFFICIENT_DATA
        assert built.primary.value is None
        assert built.factors == ()
        assert "would claim more than the data shows" in built.primary.reason

    def test_a_student_with_no_completed_assessment_has_no_segment(self) -> None:
        built = segment(b.student_id("s3"), b.missing_results())
        assert built.primary.value is None
        assert built.factors == ()
        assert "0 completed assessments" in built.primary.reason

    def test_one_assessment_can_still_satisfy_a_score_based_segment(self) -> None:
        """A thin series is not a reason to withhold a fact the score already settles."""
        built = segment(fx.S7)
        assert built.primary.value == "persistently_low"
        assert built.primary.n == 1


class TestExplainability:
    def test_every_factor_explains_itself_with_numbers(self) -> None:
        for factor in segment(fx.S4).factors:
            assert factor.explanation.narrative
            assert factor.explanation.evidence or factor.explanation.thresholds

    def test_the_summary_names_the_primary_and_the_others(self) -> None:
        narrative = segment(fx.S4).explanation.narrative
        assert "Primary status persistently_low" in narrative
        assert "also borderline" in narrative

    def test_the_borderline_factor_quotes_the_distance_and_the_band(self) -> None:
        factor = [f for f in segment(fx.S4).factors if f.segment is SegmentLabel.BORDERLINE][0]
        assert "1.00 pp from the 40.00% pass mark" in factor.explanation.narrative
        assert "within the configured band of 5 pp" in factor.explanation.narrative

    def test_an_unsegmented_student_says_why(self) -> None:
        assert "No segment can be assigned" in segment(fx.S6).explanation.narrative


class TestCohortSegments:
    def test_every_active_student_gets_a_segment_in_cohort_order(self) -> None:
        segments = cohort_segments(fx.snapshot(), defaults())
        assert len(segments) == 7, "S8 is inactive"
        assert [s.student.register_no for s in segments] == [f"RA00{i}" for i in range(1, 8)]

    def test_counts_are_over_primary_segments_only(self) -> None:
        """S4 is both persistently low and borderline; it is counted once."""
        counts = segment_counts(cohort_segments(fx.snapshot(), defaults()))
        assert {k.value: v for k, v in counts.items()} == {
            "persistently_low": 3,
            "declining": 2,
            "high_performer": 1,
        }
        assert sum(counts.values()) == 6, "S6 could not be segmented"

    def test_counts_are_ordered_by_priority(self) -> None:
        counts = segment_counts(cohort_segments(fx.snapshot(), defaults()))
        order = list(counts)
        assert order == sorted(order, key=SEGMENT_PRIORITY.index)

    def test_an_unsegmented_student_is_in_no_bucket(self) -> None:
        segments = cohort_segments(fx.snapshot(), defaults())
        counts = segment_counts(segments)
        assert sum(counts.values()) == len(segments) - 1

    def test_prebuilt_profiles_give_the_same_answer(self) -> None:
        """The cohort path reuses profiles; it must not change a single verdict."""
        snapshot = fx.snapshot()
        thresholds = defaults()
        shared = cohort_profiles(snapshot, thresholds)
        from_profiles = cohort_segments(snapshot, thresholds, profiles=shared)
        fresh = cohort_segments(snapshot, thresholds)
        assert [s.primary.value for s in from_profiles] == [s.primary.value for s in fresh]

    def test_a_passed_profile_is_the_one_used(self) -> None:
        snapshot = fx.snapshot()
        thresholds = defaults()
        profile = student_profile(snapshot, fx.S1, thresholds)
        built = student_segment(snapshot, fx.S1, thresholds, profile=profile)
        assert built.student.id == profile.student.id
        assert built.primary.value == "high_performer"

    def test_an_empty_cohort_has_no_segments(self) -> None:
        assert cohort_segments(b.empty_offering(), defaults()) == ()
        assert segment_counts(()) == {}
