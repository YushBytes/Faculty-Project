"""F18: the R1-R7 engine — what fires, what does not, and what refuses to answer.

Every fixture below was computed by hand and verified against the engine, and the numbers
are quoted in the test so a failure is a disagreement about arithmetic rather than about
what the code used to do.

Isolating fixtures (pass mark 40 unless stated):

=========================  ==========================  =====================================
series                     fires                       why it isolates the rule
=========================  ==========================  =====================================
20, 25, 45                 R1 only                     W 30.00; latest clears the pass mark
54, 54, 54, 39.5           R2 only                     W 50.38 (no R1); drop -14.50 (no R4)
30, 30, 30                 R1, R2, R3                  a run of three; see the R3 note
60, 90, 55                 R4 only                     drop -20.00; slope -2.50 (stable)
80, 75, 70                 R5 only                     slope -5.00; drop -7.50 (no R4)
60, 60, missing, missing   R6 only                     completion 50.00%
52, 52, 52 (pass 50)       R7 only                     W 52.00, 2.00 pp from the mark
=========================  ==========================  =====================================

**R3 cannot fire alone.** A trailing run below the pass mark means the latest completed
assessment is below it, so R2 always fires with R3. That is a property of the definitions in
contract C9, not of this implementation, and `test_r3_always_brings_r2` pins it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.core.attention import (
    evaluate_rule,
    student_attention,
    student_flags,
)
from app.modules.analytics.core.outputs import AttentionFlag
from app.modules.analytics.core.policy import build_student_series, series_up_to
from app.modules.analytics.core.results import Unit
from app.modules.analytics.core.rules import (
    ATTENTION_RULES,
    AttentionRuleCode,
    FlagSeverity,
    FlagStatus,
)
from app.modules.analytics.core.student import (
    completion_percent,
    decline_against_earlier_mean,
    pass_mark_distance,
    repeated_low_run,
    weighted_course_score,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.trends import trend_for
from tests.analytics import builders as b
from tests.analytics import canonical as fx

R1, R2, R3, R4, R5, R6, R7 = AttentionRuleCode


def defaults(pass_mark: str = "40.00") -> ThresholdSet:
    return resolve_thresholds(pass_mark_percent=Decimal(pass_mark))


def series_for(rows: dict, *, pass_mark: str = "40.00", key: str = "s1"):  # noqa: ANN201
    snapshot = b.build_snapshot(rows, pass_mark=pass_mark)
    return build_student_series(snapshot, b.student_id(key))


def codes(rows: dict, *, pass_mark: str = "40.00") -> list[AttentionRuleCode]:
    return [
        flag.rule_code
        for flag in student_flags(series_for(rows, pass_mark=pass_mark), defaults(pass_mark))
    ]


def flag_for(rows: dict, code: AttentionRuleCode, *, pass_mark: str = "40.00") -> AttentionFlag:
    found = [
        f
        for f in student_flags(series_for(rows, pass_mark=pass_mark), defaults(pass_mark))
        if f.rule_code is code
    ]
    assert len(found) == 1, f"expected {code.value} to fire, got {found}"
    return found[0]


class TestEachRuleFires:
    def test_r1_low_performance(self) -> None:
        """W 30.00% against a low-performance threshold of 50%."""
        assert codes({"s1": (20, 25, 45)}) == [R1]
        flag = flag_for({"s1": (20, 25, 45)}, R1)
        assert flag.actual.value == Decimal("30.00")
        assert flag.actual.unit is Unit.PERCENT
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.LOW_PERFORMANCE_PERCENT
        assert flag.severity is FlagSeverity.HIGH
        assert flag.reference_assessments == ("CT1", "CT2", "CT3")

    def test_r2_failed_latest(self) -> None:
        """Latest 39.50% below the 40% pass mark, with no other rule reaching its threshold."""
        assert codes({"s1": (54, 54, 54, 39.5)}) == [R2]
        flag = flag_for({"s1": (54, 54, 54, 39.5)}, R2)
        assert flag.actual.value == Decimal("39.50")
        assert flag.threshold is None, "R2 compares against the offering's pass mark"
        assert flag.pass_mark_percent == Decimal("40.00")
        assert flag.severity is FlagSeverity.MEDIUM
        assert flag.reference_assessments == ("CT4",)

    def test_r3_repeated_low(self) -> None:
        flag = flag_for({"s1": (30, 30, 30)}, R3)
        assert flag.actual.value == Decimal(3)
        assert flag.actual.unit is Unit.COUNT
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.REPEATED_LOW_COUNT
        assert flag.pass_mark_percent == Decimal("40.00")
        assert flag.severity is FlagSeverity.HIGH
        assert flag.reference_assessments == ("CT1", "CT2", "CT3")

    def test_r3_always_brings_r2(self) -> None:
        """A run below the pass mark means the latest is below it. A property of C9."""
        fired = codes({"s1": (30, 30, 30)})
        assert R3 in fired
        assert R2 in fired

    def test_r4_sharp_decline(self) -> None:
        """55% against a mean of 75% over CT1-CT2: -20.00 pp. Slope is only -2.50, so no R5."""
        assert codes({"s1": (60, 90, 55)}) == [R4]
        flag = flag_for({"s1": (60, 90, 55)}, R4)
        assert flag.actual.value == Decimal("-20.00")
        assert flag.actual.unit is Unit.PERCENTAGE_POINTS
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.DECLINE_DROP_PP
        assert flag.severity is FlagSeverity.MEDIUM

    def test_r5_declining_trend(self) -> None:
        assert codes({"s1": (80, 75, 70)}) == [R5]
        flag = flag_for({"s1": (80, 75, 70)}, R5)
        assert flag.actual.value == Decimal("-5.00")
        assert flag.actual.unit is Unit.PERCENTAGE_POINTS_PER_ASSESSMENT
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.TREND_DELTA_PP
        assert flag.severity is FlagSeverity.LOW

    def test_r6_low_completion(self) -> None:
        rows = {"s1": (60, 60, b.MISSING, b.MISSING)}
        assert codes(rows) == [R6]
        flag = flag_for(rows, R6)
        assert flag.actual.value == Decimal("50.00")
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.LOW_COMPLETION_PERCENT
        assert flag.severity is FlagSeverity.MEDIUM
        assert flag.reference_assessments == ("CT3", "CT4"), "the ones not completed"

    def test_r7_borderline(self) -> None:
        """Pass mark 50, W 52.00: inside the band and clear of the low threshold."""
        rows = {"s1": (52, 52, 52)}
        assert codes(rows, pass_mark="50") == [R7]
        flag = flag_for(rows, R7, pass_mark="50")
        assert flag.actual.value == Decimal("2.00")
        assert flag.actual.unit is Unit.PERCENTAGE_POINTS
        assert flag.threshold is not None
        assert flag.threshold.key is ThresholdKey.BORDERLINE_BAND_PP
        assert flag.pass_mark_percent == Decimal("50")
        assert flag.severity is FlagSeverity.LOW

    @pytest.mark.parametrize("code", list(AttentionRuleCode))
    def test_every_flag_carries_its_registered_severity(self, code: AttentionRuleCode) -> None:
        """Severity comes from the frozen registry, never from the evaluator."""
        by_rule = {
            R1: ({"s1": (20, 25, 45)}, "40.00"),
            R2: ({"s1": (54, 54, 54, 39.5)}, "40.00"),
            R3: ({"s1": (30, 30, 30)}, "40.00"),
            R4: ({"s1": (60, 90, 55)}, "40.00"),
            R5: ({"s1": (80, 75, 70)}, "40.00"),
            R6: ({"s1": (60, 60, b.MISSING, b.MISSING)}, "40.00"),
            R7: ({"s1": (52, 52, 52)}, "50"),
        }
        rows, pass_mark = by_rule[code]
        assert flag_for(rows, code, pass_mark=pass_mark).severity is ATTENTION_RULES[code].severity


class TestBoundaries:
    def test_r1_is_strict_at_the_threshold(self) -> None:
        """A course score of exactly 50.00 does **not** raise R1 — C9 says "below".

        The Persistently Low *segment* is inclusive on the same threshold (F17 is `<=`), so
        this student is segmented low and unflagged. The difference is deliberate; see
        test_the_r1_flag_and_the_persistently_low_segment_disagree_at_the_boundary.
        """
        assert codes({"s1": (50, 50)}) == []
        assert codes({"s1": (49, 49)}) == [R1]

    def test_the_r1_flag_and_the_persistently_low_segment_disagree_at_the_boundary(self) -> None:
        from app.modules.analytics.core.segmentation import student_segment

        snapshot = b.build_snapshot({"s1": (50, 50)})
        thresholds = defaults()
        student = b.student_id("s1")
        assert student_flags(build_student_series(snapshot, student), thresholds) == ()
        assert student_segment(snapshot, student, thresholds).primary.value == "persistently_low"

    def test_r2_is_strict_at_the_pass_mark(self) -> None:
        """Exactly the pass mark is a pass."""
        assert R2 not in codes({"s1": (60, 40)})
        assert R2 in codes({"s1": (60, 39.99)})

    def test_r3_fires_at_exactly_the_configured_run(self) -> None:
        assert R3 in codes({"s1": (30, 30, 30)})
        assert R3 not in codes({"s1": (60, 30, 30)}), "a run of two"

    def test_r4_fires_at_exactly_the_configured_drop(self) -> None:
        """70, 70, 55 is a drop of exactly -15.00; 55.01 makes it -14.99."""
        assert R4 in codes({"s1": (70, 70, 55)})
        assert R4 not in codes({"s1": (70, 70, 55.01)})

    def test_r5_fires_at_exactly_the_configured_slope(self) -> None:
        assert R5 in codes({"s1": (65, 60, 55)}), "slope exactly -5.00"
        assert R5 not in codes({"s1": (64, 60, 56)}), "slope -4.00"

    def test_r6_is_strict_at_the_completion_threshold(self) -> None:
        """Three of four required assessments is exactly 75.00% — not below it."""
        assert R6 not in codes({"s1": (60, 60, 60, b.MISSING)})
        assert R6 in codes({"s1": (60, 60, b.MISSING, b.MISSING)})

    def test_r7_includes_both_edges_of_the_band(self) -> None:
        assert R7 in codes({"s1": (45, 45)}), "exactly 5 pp above the mark"
        assert R7 in codes({"s1": (35, 35)}), "exactly 5 pp below"
        assert R7 not in codes({"s1": (46, 46)}), "6 pp above"

    def test_a_configured_threshold_moves_the_boundary(self) -> None:
        strict = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"),
            offering_overrides={"low_performance_percent": "55"},
        )
        series = series_for({"s1": (52, 52)})
        assert student_flags(series, defaults()) == ()
        fired = [f.rule_code for f in student_flags(series, strict)]
        assert R1 in fired


class TestInsufficientData:
    def test_a_student_with_no_completed_assessment_raises_only_what_is_knowable(self) -> None:
        """No W, no latest, no trend — but completion is 0% and knowable, so R6 fires."""
        fired = codes({"s1": (b.ABSENT, b.ABSENT)})
        assert fired == [R6]

    def test_a_student_with_no_rows_at_all_is_not_a_student_who_scored_zero(self) -> None:
        series = build_student_series(b.missing_results(), b.student_id("s3"))
        fired = [f.rule_code for f in student_flags(series, defaults())]
        assert fired == [R6], "completion 0%; nothing else can be computed"
        assert R1 not in fired and R2 not in fired

    def test_one_assessment_cannot_produce_a_decline_or_a_trend(self) -> None:
        fired = codes({"s1": (30, b.MISSING, b.MISSING)})
        assert R4 not in fired, "a drop needs an earlier mean"
        assert R5 not in fired, "a trend needs two points"
        assert R1 in fired, "the course score is knowable from one assessment"

    @pytest.mark.parametrize("code", [R4, R5])
    def test_an_unevaluable_rule_returns_none_rather_than_a_verdict(
        self, code: AttentionRuleCode
    ) -> None:
        series = series_for({"s1": (30, b.MISSING)})
        assert evaluate_rule(code, series, defaults()) is None

    def test_an_all_exempt_student_has_no_completion_to_judge(self) -> None:
        """Completion has no denominator, so R6 must not fire on a null."""
        fired = codes({"s1": (b.EXEMPT, b.EXEMPT)})
        assert fired == []

    def test_an_empty_offering_produces_no_flags(self) -> None:
        snapshot = b.empty_offering()
        assert snapshot.students == ()

    def test_an_unpublished_assessment_is_not_a_missed_one(self) -> None:
        """QUIZ1 is unpublished, so it is not part of anyone's completion denominator."""
        series = build_student_series(fx.snapshot(), fx.S1)
        assert [p.assessment_code for p in series.points] == ["CT1", "CT2", "FT1"]
        assert student_flags(series, defaults()) == ()


class TestFlagsAgreeWithTheFactsBehindThem:
    """Composition, not duplication: a flag's value is the Phase 2/3 measure it came from."""

    def test_r1_carries_the_weighted_course_score(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S4)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R1][0]
        assert flag.actual == weighted_course_score(series)

    def test_r3_carries_the_repeated_low_run(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S5)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R3][0]
        assert flag.actual == repeated_low_run(series, defaults())

    def test_r4_carries_the_decline_measure(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S3)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R4][0]
        assert flag.actual == decline_against_earlier_mean(series, defaults())

    def test_r5_carries_the_trend_slope(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S2)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R5][0]
        assert flag.actual == trend_for(fx.snapshot(), fx.S2, defaults()).slope

    def test_r6_carries_the_completion_measure(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S6)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R6][0]
        assert flag.actual == completion_percent(series)

    def test_r7_carries_the_distance_from_the_pass_mark(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S4)
        flag = [f for f in student_flags(series, defaults()) if f.rule_code is R7][0]
        assert flag.actual == pass_mark_distance(series, defaults())


class TestExplainabilityAndProvenance:
    def test_every_flag_quotes_its_value_threshold_and_assessments(self) -> None:
        series = build_student_series(fx.snapshot(), fx.S5)
        for flag in student_flags(series, defaults()):
            assert str(flag.actual.value) in flag.message
            quoted = flag.threshold.value if flag.threshold else flag.pass_mark_percent
            assert str(quoted) in flag.message
            assert flag.explanation.evidence
            assert flag.explanation.narrative == flag.message

    def test_a_threshold_carries_where_it_came_from(self) -> None:
        overridden = resolve_thresholds(
            pass_mark_percent=Decimal("40.00"),
            offering_overrides={"low_performance_percent": "55"},
        )
        flag = [
            f for f in student_flags(series_for({"s1": (52, 52)}), overridden) if f.rule_code is R1
        ][0]
        assert flag.threshold is not None
        assert flag.threshold.value == Decimal("55")
        assert flag.threshold.source.value == "offering_override"
        assert flag.explanation.thresholds == (flag.threshold,)

    def test_the_documented_message_style(self) -> None:
        flag = flag_for({"s1": (30, 30, 30)}, R3)
        assert flag.message == (
            "Below the 40.00% pass mark in 3 consecutive completed assessments "
            "(CT1 30.00%, CT2 30.00%, CT3 30.00%). Configured run length 3."
        )

    def test_r6_names_what_was_missed_and_does_not_call_it_zero(self) -> None:
        flag = flag_for({"s1": (60, b.ABSENT, b.MISSING)}, R6)
        assert "Not completed: CT2 (absent), CT3 (missing)" in flag.message
        notes = {item.name: item.note for item in flag.explanation.evidence}
        assert notes["CT2"] == "not a score of 0"

    @pytest.mark.parametrize(
        "rows",
        [
            {"s1": (20, 25, 45)},
            {"s1": (30, 30, 30)},
            {"s1": (60, 90, 55)},
            {"s1": (60, 60, b.MISSING, b.MISSING)},
        ],
    )
    def test_no_message_predicts_or_blames(self, rows: dict) -> None:
        """The contract screens for it; this proves real messages pass the screen."""
        for flag in student_flags(series_for(rows), defaults()):
            lowered = flag.message.lower()
            for banned in ("will fail", "at risk", "likely", "because", "caused"):
                assert banned not in lowered

    def test_a_flag_is_open_when_raised(self) -> None:
        assert flag_for({"s1": (30, 30, 30)}, R3).status is FlagStatus.OPEN


class TestStudentAttention:
    def attention(self, student: object, snapshot: object | None = None):  # noqa: ANN201
        used = snapshot or fx.snapshot()
        thresholds = resolve_thresholds(pass_mark_percent=used.pass_mark_percent)  # type: ignore[attr-defined]
        series = build_student_series(used, student)  # type: ignore[arg-type]
        ref = [s for s in used.students if s.id == student][0]  # type: ignore[attr-defined]
        return student_attention(series, ref, thresholds)

    def test_a_student_holds_every_rule_they_fire(self) -> None:
        built = self.attention(fx.S5)
        assert [f.rule_code for f in built.flags] == [R1, R2, R3]
        assert built.requires_attention is True
        assert built.highest_severity is FlagSeverity.HIGH

    def test_flags_are_ordered_by_rule_code(self) -> None:
        built = self.attention(fx.S4)
        assert [f.rule_code for f in built.flags] == [R1, R7]

    def test_two_mediums_escalate(self) -> None:
        """R2 and R6 together: neither is High, and two Mediums meet the rule.

        54, 54, 54, 39.5 then two never sat: W 50.38 clears R1, the drop of -14.50 clears
        R4, and completion of 4 in 6 is 66.67%.
        """
        snapshot = b.build_snapshot({"s1": (54, 54, 54, 39.5, b.MISSING, b.MISSING)})
        built = self.attention(b.student_id("s1"), snapshot)
        assert [f.severity for f in built.flags] == [FlagSeverity.MEDIUM, FlagSeverity.MEDIUM]
        assert built.requires_attention is True

    def test_one_medium_does_not_escalate(self) -> None:
        built = self.attention(fx.S6)
        assert [f.rule_code for f in built.flags] == [R6]
        assert built.requires_attention is False
        assert built.highest_severity is FlagSeverity.MEDIUM

    def test_lows_alone_never_escalate(self) -> None:
        built = self.attention(b.student_id("s1"), b.build_snapshot({"s1": (80, 75, 70)}))
        assert [f.severity for f in built.flags] == [FlagSeverity.LOW]
        assert built.requires_attention is False

    def test_a_medium_and_a_low_do_not_escalate(self) -> None:
        built = self.attention(fx.S2)
        assert [f.rule_code for f in built.flags] == [R4, R5]
        assert built.requires_attention is False

    def test_no_flags_is_an_answer_not_an_absence(self) -> None:
        built = self.attention(fx.S1)
        assert built.flags == ()
        assert built.requires_attention is False
        assert built.highest_severity is None
        assert "No attention rule fired" in built.explanation.narrative
        assert "not evaluated" not in built.explanation.narrative, (
            "that phrase means the build did not look, which is a different answer"
        )
        assert "left unjudged rather than counted as passing" in built.explanation.narrative

    def test_the_verdict_cannot_be_asserted_against_the_flags(self) -> None:
        """The contract derives it, so no caller can reach a different answer."""
        from pydantic import ValidationError

        built = self.attention(fx.S5)
        with pytest.raises(ValidationError, match="the verdict is derived"):
            built.__class__(**{**built.model_dump(), "requires_attention": False})

    def test_the_explanation_lists_the_rules_and_the_escalation(self) -> None:
        narrative = self.attention(fx.S5).explanation.narrative
        assert "3 rules fired" in narrative
        assert "R1_LOW_PERFORMANCE (high)" in narrative
        assert "requiring academic attention" in narrative


class TestOrderingIsIrrelevantToResults:
    def test_reordering_assessments_changes_nothing(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(
            update={"assessments": tuple(reversed(snapshot.assessments))}
        )
        for student in (fx.S2, fx.S4, fx.S5):
            original = student_flags(build_student_series(snapshot, student), defaults())
            shuffled = student_flags(build_student_series(reordered, student), defaults())
            assert [f.rule_code for f in original] == [f.rule_code for f in shuffled]
            assert [f.actual.value for f in original] == [f.actual.value for f in shuffled]

    def test_reordering_results_changes_nothing(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(update={"results": tuple(reversed(snapshot.results))})
        original = student_flags(build_student_series(snapshot, fx.S5), defaults())
        shuffled = student_flags(build_student_series(reordered, fx.S5), defaults())
        assert [f.rule_code for f in original] == [f.rule_code for f in shuffled]

    def test_evaluating_a_truncated_series_reads_the_state_at_that_point(self) -> None:
        """S5 had a run of two at CT2 and three at FT1."""
        series = build_student_series(fx.snapshot(), fx.S5)
        at_ct2 = [f.rule_code for f in student_flags(series_up_to(series, 2), defaults())]
        at_ft1 = [f.rule_code for f in student_flags(series, defaults())]
        assert R3 not in at_ct2
        assert R3 in at_ft1
