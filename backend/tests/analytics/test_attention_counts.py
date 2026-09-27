"""Cohort attention: counting students without counting flags, and the invariants.

Canonical cohort (pass 40), hand-verified:

=====  ===================  =======================================  ==================
who    flags                severities                               requires attention
=====  ===================  =======================================  ==================
S1     none                 -                                        no
S2     R4, R5               medium, low                              no
S3     R4, R5               medium, low                              no
S4     R1, R7               high, low                                **yes** (a High)
S5     R1, R2, R3           high, medium, high                       **yes** (a High)
S6     R6                   medium                                   no (one Medium)
S7     R6                   medium                                   no (one Medium)
=====  ===================  =======================================  ==================

    11 flags · 6 flagged students · 2 requiring attention
    severities  high 3, medium 5, low 3
    rules       R1 2, R2 1, R3 1, R4 2, R5 2, R6 2, R7 1

Note the shape of it: 3 High **flags** across 2 students. Counting flags where students
belong, or the reverse, is the mistake these tests exist to catch.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.modules.analytics.core.attention import (
    all_flags,
    attention_measure,
    cohort_attention,
    flag_counts,
    flagged_students,
    new_flags_between,
    rule_counts,
    students_requiring_attention,
)
from app.modules.analytics.core.class_health import class_health
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity
from app.modules.analytics.core.thresholds import ThresholdSet, resolve_thresholds
from tests.analytics import builders as b
from tests.analytics import canonical as fx

R1, R2, R3, R4, R5, R6, R7 = AttentionRuleCode


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def canonical():  # noqa: ANN201
    return cohort_attention(fx.snapshot(), defaults())


class TestCanonicalCounts:
    def test_every_student_appears_exactly_once(self) -> None:
        built = canonical()
        assert len(built) == 7, "S8 is inactive"
        ids = [a.student.id for a in built]
        assert len(ids) == len(set(ids))
        assert ids == [fx.S1, fx.S2, fx.S3, fx.S4, fx.S5, fx.S6, fx.S7], "cohort order"

    def test_the_flags_each_student_holds(self) -> None:
        held = {a.student.register_no: [f.rule_code for f in a.flags] for a in canonical()}
        assert held == {
            "RA001": [],
            "RA002": [R4, R5],
            "RA003": [R4, R5],
            "RA004": [R1, R7],
            "RA005": [R1, R2, R3],
            "RA006": [R6],
            "RA007": [R6],
        }

    def test_total_flags(self) -> None:
        assert len(all_flags(canonical())) == 11

    def test_flagged_students_counts_students_not_flags(self) -> None:
        """S5 holds three flags and is one student."""
        built = canonical()
        assert len(flagged_students(built)) == 6
        assert len(all_flags(built)) == 11

    def test_students_requiring_attention(self) -> None:
        requiring = students_requiring_attention(canonical())
        assert [s.register_no for s in requiring] == ["RA004", "RA005"]
        assert len(requiring) == 2

    def test_severity_counts_are_over_flags(self) -> None:
        """3 High flags, held by 2 students — both numbers are true and different."""
        built = canonical()
        assert {k.value: v for k, v in flag_counts(built).items()} == {
            "high": 3,
            "medium": 5,
            "low": 3,
        }
        assert sum(flag_counts(built).values()) == len(all_flags(built))
        high_holders = {
            a.student.id for a in built if any(f.severity is FlagSeverity.HIGH for f in a.flags)
        }
        assert len(high_holders) == 2

    def test_rule_counts_are_over_students(self) -> None:
        assert {k.value: v for k, v in rule_counts(canonical()).items()} == {
            "R1_LOW_PERFORMANCE": 2,
            "R2_FAILED_LATEST": 1,
            "R3_REPEATED_LOW": 1,
            "R4_SHARP_DECLINE": 2,
            "R5_DECLINING_TREND": 2,
            "R6_LOW_COMPLETION": 2,
            "R7_BORDERLINE": 1,
        }

    def test_rule_counts_sum_to_the_flag_total(self) -> None:
        """A rule holds at most one flag per student, so the two totals meet."""
        built = canonical()
        assert sum(rule_counts(built).values()) == len(all_flags(built)) == 11

    def test_counts_are_ordered(self) -> None:
        built = canonical()
        assert list(rule_counts(built)) == [c for c in AttentionRuleCode if c in rule_counts(built)]
        assert [s.value for s in flag_counts(built)] == ["high", "medium", "low"]

    def test_the_measure_reports_students_over_the_cohort(self) -> None:
        built = canonical()
        measure = attention_measure(built, cohort_n=len(built))
        assert measure.value == Decimal(2)
        assert measure.n == 7
        assert measure.is_ok


class TestNoStudentIsCountedTwice:
    def test_a_rule_cannot_hold_two_flags_for_one_student(self) -> None:
        for attention in canonical():
            held = [f.rule_code for f in attention.flags]
            assert len(held) == len(set(held))

    def test_every_flag_belongs_to_the_student_carrying_it(self) -> None:
        for attention in canonical():
            for flag in attention.flags:
                assert flag.student_id == attention.student.id
                assert flag.offering_id == attention.offering_id

    def test_every_flagged_student_is_in_the_cohort(self) -> None:
        cohort = {s.id for s in fx.snapshot().active_students()}
        assert {s.id for s in flagged_students(canonical())} <= cohort

    def test_requiring_is_a_subset_of_flagged(self) -> None:
        built = canonical()
        assert {s.id for s in students_requiring_attention(built)} <= {
            s.id for s in flagged_students(built)
        }


class TestOrderingDoesNotChangeCounts:
    def test_reordering_students_changes_nothing_but_the_order(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(update={"students": tuple(reversed(snapshot.students))})
        original = canonical()
        shuffled = cohort_attention(reordered, defaults())
        assert rule_counts(original) == rule_counts(shuffled)
        assert flag_counts(original) == flag_counts(shuffled)
        assert {s.id for s in students_requiring_attention(original)} == {
            s.id for s in students_requiring_attention(shuffled)
        }

    def test_reordering_assessments_changes_nothing(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(
            update={"assessments": tuple(reversed(snapshot.assessments))}
        )
        assert rule_counts(canonical()) == rule_counts(cohort_attention(reordered, defaults()))


class TestEvaluatedVersusNotEvaluated:
    def test_a_cohort_where_nothing_fires_is_still_evaluated(self) -> None:
        snapshot = b.build_snapshot({"s1": (80, 82, 85), "s2": (78, 80, 84)})
        built = cohort_attention(snapshot, defaults())
        assert len(built) == 2
        assert all(a.flags == () for a in built)
        assert flag_counts(built) == {}
        assert rule_counts(built) == {}
        assert attention_measure(built, cohort_n=2).value == Decimal(0)

    def test_class_health_distinguishes_zero_from_unevaluated(self) -> None:
        snapshot = b.build_snapshot({"s1": (80, 82, 85), "s2": (78, 80, 84)})
        thresholds = defaults()
        evaluated = class_health(snapshot, thresholds)
        unevaluated = class_health(snapshot, thresholds, evaluate_attention=False)
        assert evaluated.students_requiring_attention is not None
        assert evaluated.students_requiring_attention.value == Decimal(0)
        assert unevaluated.students_requiring_attention is None
        assert evaluated.flag_counts == unevaluated.flag_counts == {}
        assert "no rule fired" in evaluated.explanation.narrative
        assert "not evaluated" in unevaluated.explanation.narrative

    def test_an_empty_cohort_evaluates_to_nothing(self) -> None:
        built = cohort_attention(b.empty_offering(), defaults())
        assert built == ()
        assert attention_measure(built, cohort_n=0).value == Decimal(0)


class TestNewFlagsBetweenAssessments:
    def test_only_flags_that_were_not_there_before_are_new(self) -> None:
        """S3 newly declines at FT1; S5 reaches a run of three. S2 already held both."""
        new = new_flags_between(fx.snapshot(), 2, 3, defaults())
        assert [(f.rule_code, f.student_id) for f in new] == [
            (R4, fx.S3),
            (R5, fx.S3),
            (R3, fx.S5),
        ]

    def test_a_rule_that_could_not_be_judged_before_counts_as_new_now(self) -> None:
        """One assessment cannot show a decline; three can. The flag has appeared."""
        snapshot = b.build_snapshot({"s1": (80, 90, 40)})
        new = new_flags_between(snapshot, 1, 3, defaults())
        assert R4 in [f.rule_code for f in new]

    def test_nothing_is_new_when_nothing_changed(self) -> None:
        snapshot = b.build_snapshot({"s1": (30, 30)})
        assert new_flags_between(snapshot, 2, 2, defaults()) == ()


class TestClassHealthIntegration:
    def test_the_header_carries_the_canonical_counts(self) -> None:
        built = class_health(fx.snapshot(), defaults())
        assert built.students_requiring_attention is not None
        assert built.students_requiring_attention.value == Decimal(2)
        assert sum(built.flag_counts.values()) == 11
        assert sum(built.rule_counts.values()) == 11

    def test_the_counts_come_from_the_engine_not_a_second_calculation(self) -> None:
        snapshot = fx.snapshot()
        thresholds = defaults()
        built = class_health(snapshot, thresholds)
        engine = cohort_attention(snapshot, thresholds)
        assert built.flag_counts == flag_counts(engine)
        assert built.rule_counts == rule_counts(engine)
        assert built.students_requiring_attention is not None
        assert built.students_requiring_attention.value == Decimal(
            len(students_requiring_attention(engine))
        )

    def test_counts_never_exceed_the_cohort(self) -> None:
        for name, build in sorted(b.SCENARIOS.items()):
            snapshot = build()
            thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
            built = class_health(snapshot, thresholds)
            assert built.students_requiring_attention is not None
            assert built.students_requiring_attention.value <= built.cohort_n, name
            for code, count in built.rule_counts.items():
                assert count <= built.cohort_n, f"{name} {code}"

    def test_segments_and_attention_are_independent_views(self) -> None:
        """S4 is segmented persistently low and flagged R1 + R7: both, not one or the other."""
        built = class_health(fx.snapshot(), defaults())
        assert {k.value: v for k, v in built.segment_counts.items()} == {
            "persistently_low": 3,
            "declining": 2,
            "high_performer": 1,
        }
        assert sum(built.rule_counts.values()) == 11


class TestInvariantsAcrossScenarios:
    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_no_attention_payload_contains_a_non_finite_number(self, name: str) -> None:
        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for attention in cohort_attention(snapshot, thresholds):
            text = attention.model_dump_json()
            assert "NaN" not in text and "Infinity" not in text
            for value in _numbers(json.loads(text)):
                assert math.isfinite(value)

    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_every_flag_can_justify_itself(self, name: str) -> None:
        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for attention in cohort_attention(snapshot, thresholds):
            for flag in attention.flags:
                assert flag.actual.is_ok, "a flag must carry the value that fired it"
                assert flag.threshold is not None or flag.pass_mark_percent is not None
                assert flag.message
                assert flag.explanation.evidence

    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_the_verdict_matches_the_escalation_rule(self, name: str) -> None:
        from app.modules.analytics.core.rules import requires_attention

        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for attention in cohort_attention(snapshot, thresholds):
            assert attention.requires_attention == requires_attention(
                f.severity for f in attention.flags
            )

    @pytest.mark.parametrize("name", sorted(b.SCENARIOS))
    def test_evaluating_attention_does_not_disturb_the_other_outputs(self, name: str) -> None:
        """Phase 1-4 numbers must be identical whether or not attention runs."""
        from datetime import UTC, datetime

        snapshot = b.SCENARIOS[name]()
        thresholds = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        stamp = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
        with_attention = class_health(snapshot, thresholds, generated_at=stamp).model_dump()
        without = class_health(
            snapshot, thresholds, evaluate_attention=False, generated_at=stamp
        ).model_dump()
        ignored = {
            "students_requiring_attention",
            "flag_counts",
            "rule_counts",
            "explanation",
        }
        assert {k: v for k, v in with_attention.items() if k not in ignored} == {
            k: v for k, v in without.items() if k not in ignored
        }

    def test_the_engine_does_not_mutate_its_input(self) -> None:
        snapshot = fx.snapshot()
        before = snapshot.model_dump()
        cohort_attention(snapshot, defaults())
        assert snapshot.model_dump() == before


def _numbers(payload: object) -> list[float]:
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [float(payload)]
    if isinstance(payload, dict):
        return [n for value in payload.values() for n in _numbers(value)]
    if isinstance(payload, list):
        return [n for value in payload for n in _numbers(value)]
    return []
