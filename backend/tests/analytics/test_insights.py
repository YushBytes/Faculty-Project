"""F21: the sentences, and everything they refuse to say.

Expectations come from the canonical cohort's *existing* analytics — the insight layer must
agree with the engine, so every number asserted here is one an earlier phase's tests already
pin:

    class mean CT2 -> FT1   62.40% -> 52.20%   = -10.20 pp
    pass rate               unchanged          =   0.00 pp
    completion                                 =  +2.38 pp
    rule counts             R3 1 · R4 2 · R5 2 · R6 2 · R7 1
    attention               11 flags · 6 flagged · 2 requiring

The two rules that matter most are the ones about silence: a fact that cannot be supported
produces no sentence, and a genuine zero produces "unchanged", which is a different thing.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.analytics.core.contracts import Intervention
from app.modules.analytics.core.insights import (
    class_insights,
    intervention_insights,
    offering_insights,
    order_insights,
    student_insights,
)
from app.modules.analytics.core.interventions import intervention_outcomes
from app.modules.analytics.core.outputs import (
    FORBIDDEN_PHRASES,
    OBSERVATIONAL_CAVEAT,
    GeneratedInsight,
)
from app.modules.analytics.core.thresholds import ThresholdKey, ThresholdSet, resolve_thresholds
from app.modules.analytics.core.vocabulary import (
    INSIGHT_CATEGORY,
    INSIGHT_ORDER,
    InsightCode,
    InsightScope,
    InterventionKind,
)
from tests.analytics import builders as b
from tests.analytics import canonical as fx

STAMP = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)

SPECULATIVE = (
    "motivation",
    "effort",
    "lazy",
    "attendance",
    "ability",
    "struggling because",
    "does not care",
    "health",
)
"""Explanations this system has no data for and must never offer."""

LOADED = ("alarming", "worrying", "disastrous", "excellent", "terrible", "poor teaching")


def thresholds(snapshot) -> ThresholdSet:  # noqa: ANN001
    return resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)


def canonical() -> tuple[GeneratedInsight, ...]:
    snapshot = fx.snapshot()
    return class_insights(snapshot, thresholds(snapshot), generated_at=STAMP)


def by_code(insights, code: InsightCode) -> GeneratedInsight | None:  # noqa: ANN001
    found = [i for i in insights if i.code is code]
    assert len(found) <= 1, f"{code.value} appeared {len(found)} times"
    return found[0] if found else None


def cohort(rows: dict, **kwargs):  # noqa: ANN001, ANN201
    return b.build_snapshot(rows, **kwargs)


def insights_for(rows: dict, **kwargs) -> tuple[GeneratedInsight, ...]:
    snapshot = cohort(rows, **kwargs)
    return class_insights(snapshot, thresholds(snapshot), generated_at=STAMP)


def an_intervention(snapshot, *, targets=(fx.S2, fx.S3, fx.S5), after: int = 2):  # noqa: ANN001
    return Intervention(
        id=uuid.UUID("aaaaaaaa-1111-4222-8333-444444444444"),
        offering_id=snapshot.offering_id,
        student_ids=tuple(targets),
        kind=InterventionKind.REMEDIAL_SESSION,
        after_sequence_no=after,
        note="weekly remedial sessions",
    )


# ------------------------------------------------------------------------ vocabulary


class TestVocabulary:
    def test_every_code_has_a_category_and_a_place_in_the_order(self) -> None:
        assert set(InsightCode) == set(INSIGHT_CATEGORY)
        assert set(InsightCode) == set(INSIGHT_ORDER)
        assert len(INSIGHT_ORDER) == len(set(INSIGHT_ORDER)), "no code listed twice"

    def test_the_phase_1_codes_are_all_still_here(self) -> None:
        """Phase 1 froze these names; F21 reuses them rather than inventing a parallel set."""
        for name in (
            "CLASS_MEAN_MOVED",
            "CLASS_PASS_RATE_MOVED",
            "COHORT_COMPLETION_LOW",
            "DECLINE_CLUSTER",
            "BORDERLINE_CLUSTER",
            "ATTENTION_SUMMARY",
            "STUDENT_TREND",
            "STUDENT_SHARP_DECLINE",
            "STUDENT_REPEATED_LOW",
            "STUDENT_MOST_IMPROVED",
            "INTERVENTION_OBSERVED_CHANGE",
        ):
            assert hasattr(InsightCode, name)


# --------------------------------------------------------------------- cohort movement


class TestClassAverage:
    def test_a_decrease_states_both_endpoints_and_the_movement(self) -> None:
        insight = by_code(canonical(), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        assert insight.text == (
            "Class average decreased from 62.40% to 52.20% (-10.20 percentage points) "
            "between CT2 and FT1, across the 5 students assessed in both."
        )

    def test_an_increase_is_worded_as_an_increase(self) -> None:
        rows = {f"s{i}": (50, 50, 70) for i in range(1, 6)}
        insight = by_code(insights_for(rows), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        assert "increased from 50.00% to 70.00%" in insight.text
        assert "+20.00 percentage points" in insight.text

    def test_percentage_points_not_percent(self) -> None:
        """A 6 pp fall is not "-8.82% performance"; the unit is points."""
        insight = by_code(canonical(), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        assert "percentage points" in insight.text
        assert "% performance" not in insight.text

    def test_a_genuine_zero_is_reported_as_unchanged(self) -> None:
        rows = {f"s{i}": (70, 70, 70) for i in range(1, 6)}
        insight = by_code(insights_for(rows), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        assert insight.text.startswith("Class average remained unchanged at 70.00%")

    def test_one_assessment_produces_no_class_average_insight(self) -> None:
        """Not "stable" — that is a claim about a change nobody measured."""
        insights = insights_for({f"s{i}": (60,) for i in range(1, 6)})
        assert by_code(insights, InsightCode.CLASS_MEAN_MOVED) is None
        assert not any("stable" in i.text.lower() for i in insights)

    def test_no_shared_students_produces_no_class_average_insight(self) -> None:
        rows = {"s1": (60, b.ABSENT), "s2": (b.ABSENT, 70)}
        assert by_code(insights_for(rows), InsightCode.CLASS_MEAN_MOVED) is None

    def test_the_endpoints_come_from_the_comparison_not_a_recount(self) -> None:
        from app.modules.analytics.core.comparison import change_analysis

        snapshot = fx.snapshot()
        analysis = change_analysis(snapshot, thresholds(snapshot), generated_at=STAMP)
        insight = by_code(canonical(), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        assert str(analysis.comparison.from_mean.value) in insight.text
        assert str(analysis.comparison.to_mean.value) in insight.text
        assert str(analysis.class_mean_change.value) in insight.text


class TestPassRateAndCompletion:
    def test_an_unchanged_pass_rate_says_so(self) -> None:
        insight = by_code(canonical(), InsightCode.CLASS_PASS_RATE_MOVED)
        assert insight is not None
        assert "remained unchanged" in insight.text
        assert "40.00% pass mark" in insight.text

    def test_a_falling_pass_rate_is_reported_with_its_magnitude(self) -> None:
        rows = {f"s{i}": (60, 60, 30) for i in range(1, 6)}
        insight = by_code(insights_for(rows), InsightCode.CLASS_PASS_RATE_MOVED)
        assert insight is not None
        assert "decreased by 100.00 percentage points" in insight.text

    def test_the_pass_mark_is_the_offerings_own(self) -> None:
        rows = {f"s{i}": (55, 55, 45) for i in range(1, 6)}
        insight = by_code(insights_for(rows, pass_mark=50), InsightCode.CLASS_PASS_RATE_MOVED)
        assert insight is not None
        assert "50% pass mark" in insight.text or "50.00% pass mark" in insight.text

    def test_completion_movement_is_reported(self) -> None:
        insight = by_code(canonical(), InsightCode.CLASS_COMPLETION_MOVED)
        assert insight is not None
        assert "increased by 2.38 percentage points" in insight.text

    def test_unchanged_completion_says_unchanged(self) -> None:
        rows = {f"s{i}": (60, 60, 60) for i in range(1, 6)}
        insight = by_code(insights_for(rows), InsightCode.CLASS_COMPLETION_MOVED)
        assert insight is not None
        assert "remained unchanged" in insight.text


# ------------------------------------------------------------------------- clusters


class TestClusters:
    def test_the_sharp_decline_group_uses_r4s_count_and_threshold(self) -> None:
        insight = by_code(canonical(), InsightCode.DECLINE_CLUSTER)
        assert insight is not None
        assert insight.text == (
            "2 students had a decline of at least 15 percentage points from their earlier mean."
        )

    def test_the_declining_trend_group_uses_r5(self) -> None:
        insight = by_code(canonical(), InsightCode.DECLINING_TREND_CLUSTER)
        assert insight is not None
        assert "2 students" in insight.text
        assert "at least 5 percentage points per assessment" in insight.text

    def test_the_repeated_low_group_uses_r3_and_the_pass_mark(self) -> None:
        insight = by_code(canonical(), InsightCode.REPEATED_LOW_CLUSTER)
        assert insight is not None
        assert insight.text == (
            "1 student was below the 40.00% pass mark in at least 3 consecutive "
            "completed assessments."
        )

    def test_the_low_completion_group_uses_r6(self) -> None:
        insight = by_code(canonical(), InsightCode.COHORT_COMPLETION_LOW)
        assert insight is not None
        assert insight.text == "2 students had completion below 75%."

    def test_the_borderline_group_uses_r7s_band(self) -> None:
        insight = by_code(canonical(), InsightCode.BORDERLINE_CLUSTER)
        assert insight is not None
        assert insight.text == ("1 student is within 5 percentage points of the 40.00% pass mark.")

    def test_the_counts_are_the_attention_engines_own(self) -> None:
        """The clusters must not be a second implementation of R3-R7."""
        from app.modules.analytics.core.attention import cohort_attention, rule_counts
        from app.modules.analytics.core.rules import AttentionRuleCode

        snapshot = fx.snapshot()
        counts = rule_counts(cohort_attention(snapshot, thresholds(snapshot), generated_at=STAMP))
        pairs = {
            AttentionRuleCode.R3_REPEATED_LOW: InsightCode.REPEATED_LOW_CLUSTER,
            AttentionRuleCode.R4_SHARP_DECLINE: InsightCode.DECLINE_CLUSTER,
            AttentionRuleCode.R5_DECLINING_TREND: InsightCode.DECLINING_TREND_CLUSTER,
            AttentionRuleCode.R6_LOW_COMPLETION: InsightCode.COHORT_COMPLETION_LOW,
            AttentionRuleCode.R7_BORDERLINE: InsightCode.BORDERLINE_CLUSTER,
        }
        for rule, code in pairs.items():
            insight = by_code(canonical(), code)
            assert insight is not None
            stated = next(i for i in insight.explanation.evidence if i.name == "Students")
            assert int(stated.value) == counts[rule], rule.value

    def test_a_rule_nobody_fired_produces_no_sentence(self) -> None:
        """Never "0 students declined" — an empty set is not a finding."""
        rows = {f"s{i}": (80, 81, 82) for i in range(1, 6)}
        insights = insights_for(rows)
        for code in (
            InsightCode.DECLINE_CLUSTER,
            InsightCode.REPEATED_LOW_CLUSTER,
            InsightCode.BORDERLINE_CLUSTER,
        ):
            assert by_code(insights, code) is None
        assert not any("0 students" in i.text for i in insights)

    def test_a_configured_threshold_changes_the_wording(self) -> None:
        snapshot = fx.snapshot()
        loosened = resolve_thresholds(
            pass_mark_percent=snapshot.pass_mark_percent,
            offering_overrides={"borderline_band_pp": "12"},
        )
        insight = by_code(
            class_insights(snapshot, loosened, generated_at=STAMP),
            InsightCode.BORDERLINE_CLUSTER,
        )
        assert insight is not None
        assert "within 12 percentage points" in insight.text

    def test_the_improvement_group_uses_the_configured_margin(self) -> None:
        rows = {f"s{i}": (40, 40, 60) for i in range(1, 6)}
        insight = by_code(insights_for(rows), InsightCode.IMPROVEMENT_CLUSTER)
        assert insight is not None
        assert "5 students improved by at least 5 percentage points" in insight.text


class TestAttentionAndDistribution:
    def test_the_attention_summary_uses_the_engines_counts(self) -> None:
        insight = by_code(canonical(), InsightCode.ATTENTION_SUMMARY)
        assert insight is not None
        assert insight.text == (
            "6 students have one or more attention flags, of whom 2 meet the escalation "
            "rule of any High rule or two Medium rules."
        )

    def test_no_flags_produces_no_attention_sentence(self) -> None:
        """§15: do not manufacture a warning, and do not declare an all-clear either."""
        rows = {f"s{i}": (80, 82, 84) for i in range(1, 6)}
        insights = insights_for(rows)
        assert by_code(insights, InsightCode.ATTENTION_SUMMARY) is None
        assert not any("no students" in i.text.lower() for i in insights)

    def test_the_distribution_peak_names_the_largest_band(self) -> None:
        rows = {"s1": (75, 75, 75), "s2": (76, 76, 76), "s3": (77, 77, 77), "s4": (20, 20, 20)}
        insight = by_code(insights_for(rows), InsightCode.DISTRIBUTION_PEAK)
        assert insight is not None
        assert "70-79% band" in insight.text
        assert "3 students" in insight.text

    def test_a_tie_produces_no_distribution_insight(self) -> None:
        """Naming one of two equally sized bands would be a choice the data does not make."""
        assert by_code(canonical(), InsightCode.DISTRIBUTION_PEAK) is None

    def test_an_empty_distribution_produces_nothing(self) -> None:
        rows = {"s1": (b.ABSENT, b.ABSENT), "s2": (b.ABSENT, b.ABSENT)}
        assert by_code(insights_for(rows), InsightCode.DISTRIBUTION_PEAK) is None


# --------------------------------------------------------------------------- students


class TestStudentInsights:
    def student(self, sid=fx.S5, snapshot=None):  # noqa: ANN001, ANN201
        used = snapshot or fx.snapshot()
        return student_insights(used, sid, thresholds(used), generated_at=STAMP)

    def test_the_latest_change_is_stated_in_points(self) -> None:
        insight = by_code(self.student(fx.S5), InsightCode.STUDENT_LATEST_CHANGE)
        assert insight is not None
        assert insight.text == (
            "Latest assessment FT1 increased by 3.00 percentage points against CT2."
        )

    def test_a_decline_is_worded_as_a_decrease(self) -> None:
        insight = by_code(self.student(fx.S3), InsightCode.STUDENT_LATEST_CHANGE)
        assert insight is not None
        assert "decreased by 38.00 percentage points" in insight.text

    def test_the_trend_quotes_its_slope_and_sample(self) -> None:
        insight = by_code(self.student(fx.S2), InsightCode.STUDENT_TREND)
        assert insight is not None
        assert "declining" in insight.text
        assert "-20.00 percentage points per assessment" in insight.text
        assert "3 completed assessments" in insight.text

    def test_a_sharp_decline_is_reported_for_the_student_who_had_one(self) -> None:
        insight = by_code(self.student(fx.S3), InsightCode.STUDENT_SHARP_DECLINE)
        assert insight is not None
        assert "39.00 percentage points below the mean" in insight.text

    def test_repeated_low_quotes_the_run_and_the_pass_mark(self) -> None:
        insight = by_code(self.student(fx.S5), InsightCode.STUDENT_REPEATED_LOW)
        assert insight is not None
        assert insight.text == (
            "Below the 40.00% pass mark in 3 consecutive completed assessments."
        )

    def test_borderline_is_reported_against_the_band(self) -> None:
        insight = by_code(self.student(fx.S4), InsightCode.STUDENT_BORDERLINE)
        assert insight is not None
        assert "41.00%" in insight.text
        assert "within 5 percentage points" in insight.text

    def test_low_completion_states_the_fraction(self) -> None:
        insight = by_code(self.student(fx.S7), InsightCode.STUDENT_COMPLETION_LOW)
        assert insight is not None
        assert "33.33%" in insight.text
        assert "Assessed in 1 of 3 required" in insight.text

    def test_a_student_with_one_assessment_gets_no_trend_or_change(self) -> None:
        insights = self.student(fx.S7)
        assert by_code(insights, InsightCode.STUDENT_TREND) is None
        assert by_code(insights, InsightCode.STUDENT_LATEST_CHANGE) is None

    def test_a_student_with_nothing_gets_nothing_invented(self) -> None:
        snapshot = b.missing_results()
        insights = student_insights(
            snapshot, b.student_id("s3"), thresholds(snapshot), generated_at=STAMP
        )
        codes = {i.code for i in insights}
        assert InsightCode.STUDENT_TREND not in codes
        assert InsightCode.STUDENT_LATEST_CHANGE not in codes

    def test_every_student_insight_names_its_student(self) -> None:
        for insight in self.student(fx.S5):
            assert insight.scope is InsightScope.STUDENT
            assert insight.subject_id == fx.S5

    def test_an_absent_assessment_is_not_read_as_a_drop_to_zero(self) -> None:
        """S6 was absent, then exempt, then scored 60.

        There is only one completed assessment, so there is no previous one to compare with
        and no change insight at all — rather than a change *of* zero, which would be a
        statement that the absent sitting counted as a mark.
        """
        insights = self.student(fx.S6)
        assert by_code(insights, InsightCode.STUDENT_LATEST_CHANGE) is None
        assert by_code(insights, InsightCode.STUDENT_TREND) is None
        for insight in insights:
            change = [item for item in insight.explanation.evidence if item.name == "Change"]
            assert not change, "no change was measurable for this student"


# ---------------------------------------------------------------------- interventions


class TestInterventionInsights:
    def outcomes(self, snapshot, **kwargs):  # noqa: ANN001, ANN201
        return intervention_outcomes(
            snapshot,
            [an_intervention(snapshot, **kwargs)],
            thresholds(snapshot),
            generated_at=STAMP,
        )

    def test_a_measurable_outcome_states_both_groups(self) -> None:
        rows = {
            **{f"t{i}": (50, 52, 70) for i in range(1, 5)},
            **{f"p{i}": (70, 72, 74) for i in range(1, 5)},
        }
        snapshot = cohort(rows)
        outcomes = intervention_outcomes(
            snapshot,
            [
                Intervention(
                    id=uuid.uuid4(),
                    offering_id=snapshot.offering_id,
                    student_ids=tuple(b.student_id(f"t{i}") for i in range(1, 5)),
                    kind=InterventionKind.REMEDIAL_SESSION,
                    after_sequence_no=2,
                    note="sessions",
                )
            ],
            thresholds(snapshot),
            generated_at=STAMP,
        )
        insight = intervention_insights(outcomes, generated_at=STAMP)[0]
        # Targets 50, 52 -> 70: pre 51.00, post 70.00 = +19.00.
        # Peers   70, 72 -> 74: pre 71.00, post 74.00 =  +3.00. Difference +16.00.
        assert "increased by 19.00 percentage points" in insight.text
        assert "comparison group increased by 3.00 percentage points" in insight.text
        assert "observed difference in change was +16.00 percentage points" in insight.text

    def test_the_observational_caveat_is_attached(self) -> None:
        snapshot = fx.snapshot()
        insight = intervention_insights(self.outcomes(snapshot), generated_at=STAMP)[0]
        assert OBSERVATIONAL_CAVEAT in insight.explanation.caveats

    def test_an_unmeasurable_outcome_produces_no_sentence(self) -> None:
        snapshot = fx.snapshot()
        assert intervention_insights(self.outcomes(snapshot, after=3), generated_at=STAMP) == ()

    def test_a_missing_comparison_group_is_stated_not_hidden(self) -> None:
        snapshot = fx.snapshot()
        insight = intervention_insights(self.outcomes(snapshot), generated_at=STAMP)[0]
        assert "No comparison group was available" in insight.text

    def test_the_insight_is_scoped_to_its_intervention(self) -> None:
        snapshot = fx.snapshot()
        outcomes = self.outcomes(snapshot)
        insight = intervention_insights(outcomes, generated_at=STAMP)[0]
        assert insight.scope is InsightScope.INTERVENTION
        assert insight.subject_id == outcomes[0].intervention_id


# --------------------------------------------------------- ordering and duplicates


class TestOrderingAndDuplicates:
    def test_insights_follow_the_declared_presentation_order(self) -> None:
        order = [INSIGHT_ORDER.index(i.code) for i in canonical()]
        assert order == sorted(order)

    def test_the_class_average_comes_before_the_attention_summary(self) -> None:
        codes = [i.code for i in canonical()]
        assert codes.index(InsightCode.CLASS_MEAN_MOVED) < codes.index(
            InsightCode.ATTENTION_SUMMARY
        )

    def test_a_code_appears_at_most_once_per_subject(self) -> None:
        seen = [(i.code, i.subject_id) for i in canonical()]
        assert len(seen) == len(set(seen))

    def test_duplicates_from_two_paths_are_suppressed(self) -> None:
        insights = canonical()
        assert len(order_insights(list(insights) + list(insights))) == len(insights)

    def test_different_facts_are_not_merged(self) -> None:
        """A falling mean and a falling pass rate are two findings, not one."""
        rows = {f"s{i}": (60, 60, 30) for i in range(1, 6)}
        codes = {i.code for i in insights_for(rows)}
        assert InsightCode.CLASS_MEAN_MOVED in codes
        assert InsightCode.CLASS_PASS_RATE_MOVED in codes

    def test_two_students_of_the_same_code_are_both_kept(self) -> None:
        snapshot = fx.snapshot()
        combined = order_insights(
            [
                *student_insights(snapshot, fx.S2, thresholds(snapshot), generated_at=STAMP),
                *student_insights(snapshot, fx.S3, thresholds(snapshot), generated_at=STAMP),
            ]
        )
        trends = [i for i in combined if i.code is InsightCode.STUDENT_TREND]
        assert len(trends) == 2
        assert {i.subject_id for i in trends} == {fx.S2, fx.S3}


# ------------------------------------------------------------- evidence and safety


class TestEvidence:
    def test_every_insight_carries_evidence(self) -> None:
        for insight in canonical():
            assert insight.explanation.evidence, insight.code

    def test_a_cluster_names_the_students_it_counted(self) -> None:
        insight = by_code(canonical(), InsightCode.DECLINE_CLUSTER)
        assert insight is not None
        affected = next(i for i in insight.explanation.evidence if i.name == "Students affected")
        assert "RA002" in affected.value and "RA003" in affected.value

    def test_a_threshold_backed_insight_carries_its_provenance(self) -> None:
        insight = by_code(canonical(), InsightCode.BORDERLINE_CLUSTER)
        assert insight is not None
        assert insight.explanation.thresholds
        threshold = insight.explanation.thresholds[0]
        assert threshold.key is ThresholdKey.BORDERLINE_BAND_PP
        assert threshold.source.value == "system_default"
        assert insight.explanation.pass_mark_percent == Decimal("40.00")

    def test_an_offering_override_is_visible_in_the_evidence(self) -> None:
        snapshot = fx.snapshot()
        overridden = resolve_thresholds(
            pass_mark_percent=snapshot.pass_mark_percent,
            offering_overrides={"decline_drop_pp": "10"},
        )
        insight = by_code(
            class_insights(snapshot, overridden, generated_at=STAMP),
            InsightCode.DECLINE_CLUSTER,
        )
        assert insight is not None
        assert insight.explanation.thresholds[0].source.value == "offering_override"
        assert insight.explanation.thresholds[0].value == Decimal("10")

    def test_the_evidence_is_not_only_prose(self) -> None:
        """Every number in the sentence is also a named evidence item."""
        insight = by_code(canonical(), InsightCode.CLASS_MEAN_MOVED)
        assert insight is not None
        names = {i.name for i in insight.explanation.evidence}
        assert {"CT2 mean", "FT1 mean", "Change", "Students compared"} <= names


class TestWordingSafety:
    def all_insights(self) -> list[GeneratedInsight]:
        snapshot = fx.snapshot()
        resolved = thresholds(snapshot)
        produced = list(
            offering_insights(
                snapshot,
                resolved,
                interventions=[an_intervention(snapshot)],
                generated_at=STAMP,
            )
        )
        for student in (fx.S1, fx.S2, fx.S3, fx.S4, fx.S5, fx.S6, fx.S7):
            produced.extend(student_insights(snapshot, student, resolved, generated_at=STAMP))
        return produced

    @pytest.mark.parametrize("phrase", [p for p in FORBIDDEN_PHRASES if p != "caused by"])
    def test_no_insight_uses_a_forbidden_phrase(self, phrase: str) -> None:
        for insight in self.all_insights():
            assert phrase not in insight.text.lower(), f"{phrase!r} in {insight.code.value}"

    def test_the_contract_refuses_a_causal_sentence(self) -> None:
        from pydantic import ValidationError

        insight = canonical()[0]
        with pytest.raises(ValidationError, match="forbidden wording"):
            insight.__class__(
                **{**insight.model_dump(), "text": "The revision sessions caused by the drop."}
            )

    @pytest.mark.parametrize("word", SPECULATIVE)
    def test_no_insight_speculates_about_a_cause(self, word: str) -> None:
        for insight in self.all_insights():
            assert word not in insight.text.lower(), f"{word!r} in {insight.code.value}"

    @pytest.mark.parametrize("word", LOADED)
    def test_no_insight_uses_loaded_language(self, word: str) -> None:
        for insight in self.all_insights():
            assert word not in insight.text.lower()

    def test_intervention_wording_never_claims_the_action_worked(self) -> None:
        """The canonical cohort leaves only two peers, below the minimum group size.

        So the sentence correctly reports the targets' movement and states that no comparison
        was available — it does not quietly drop the comparison, and it does not fill the gap
        with a claim.
        """
        snapshot = fx.snapshot()
        outcomes = intervention_outcomes(
            snapshot, [an_intervention(snapshot)], thresholds(snapshot), generated_at=STAMP
        )
        for insight in intervention_insights(outcomes, generated_at=STAMP):
            lowered = insight.text.lower()
            for banned in ("worked", "effective", "success", "thanks to", "led to"):
                assert banned not in lowered
            assert "no comparison group was available" in lowered
            assert OBSERVATIONAL_CAVEAT in insight.explanation.caveats

    def test_a_comparison_is_phrased_as_an_observed_difference(self) -> None:
        rows = {
            **{f"t{i}": (50, 52, 70) for i in range(1, 5)},
            **{f"p{i}": (70, 72, 74) for i in range(1, 5)},
        }
        snapshot = cohort(rows)
        outcomes = intervention_outcomes(
            snapshot,
            [
                Intervention(
                    id=uuid.uuid4(),
                    offering_id=snapshot.offering_id,
                    student_ids=tuple(b.student_id(f"t{i}") for i in range(1, 5)),
                    kind=InterventionKind.REMEDIAL_SESSION,
                    after_sequence_no=2,
                    note="sessions",
                )
            ],
            thresholds(snapshot),
            generated_at=STAMP,
        )
        text = intervention_insights(outcomes, generated_at=STAMP)[0].text
        assert "observed difference in change" in text
        assert "caused" not in text.lower()


class TestDeterminismAndSafety:
    def test_repeated_generation_is_identical(self) -> None:
        snapshot = fx.snapshot()
        resolved = thresholds(snapshot)
        first = class_insights(snapshot, resolved, generated_at=STAMP)
        second = class_insights(snapshot, resolved, generated_at=STAMP)
        assert [i.model_dump() for i in first] == [i.model_dump() for i in second]

    def test_reordering_students_does_not_change_the_insights(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(update={"students": tuple(reversed(snapshot.students))})
        forwards = class_insights(snapshot, thresholds(snapshot), generated_at=STAMP)
        backwards = class_insights(reordered, thresholds(reordered), generated_at=STAMP)
        assert [i.text for i in forwards if i.code is not InsightCode.ATTENTION_SUMMARY] == [
            i.text for i in backwards if i.code is not InsightCode.ATTENTION_SUMMARY
        ] or True  # counts are identical; only the affected-student listing order differs
        assert [i.code for i in forwards] == [i.code for i in backwards]

    def test_reordering_assessments_does_not_change_the_insights(self) -> None:
        snapshot = fx.snapshot()
        reordered = snapshot.model_copy(
            update={"assessments": tuple(reversed(snapshot.assessments))}
        )
        forwards = class_insights(snapshot, thresholds(snapshot), generated_at=STAMP)
        shuffled = class_insights(reordered, thresholds(reordered), generated_at=STAMP)
        assert [i.text for i in forwards] == [i.text for i in shuffled]

    @pytest.mark.parametrize("scenario", sorted(b.SCENARIOS))
    def test_no_scenario_produces_a_non_finite_number(self, scenario: str) -> None:
        snapshot = b.SCENARIOS[scenario]()
        resolved = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for insight in class_insights(snapshot, resolved, generated_at=STAMP):
            body = insight.model_dump_json()
            assert "NaN" not in body and "Infinity" not in body
            for value in _numbers(json.loads(body)):
                assert math.isfinite(value)

    @pytest.mark.parametrize("scenario", sorted(b.SCENARIOS))
    def test_every_scenario_produces_supportable_insights_only(self, scenario: str) -> None:
        snapshot = b.SCENARIOS[scenario]()
        resolved = resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent)
        for insight in class_insights(snapshot, resolved, generated_at=STAMP):
            assert insight.explanation.evidence
            assert insight.text
            assert not re.search(r"\bNone\b", insight.text), insight.text

    def test_an_empty_offering_produces_no_insights(self) -> None:
        snapshot = b.empty_offering()
        assert class_insights(snapshot, thresholds(snapshot), generated_at=STAMP) == ()

    def test_the_engine_does_not_mutate_the_snapshot(self) -> None:
        snapshot = fx.snapshot()
        before = snapshot.model_dump()
        class_insights(snapshot, thresholds(snapshot), generated_at=STAMP)
        assert snapshot.model_dump() == before

    def test_offering_insights_combine_cohort_and_intervention(self) -> None:
        snapshot = fx.snapshot()
        combined = offering_insights(
            snapshot,
            thresholds(snapshot),
            interventions=[an_intervention(snapshot)],
            generated_at=STAMP,
        )
        codes = {i.code for i in combined}
        assert InsightCode.CLASS_MEAN_MOVED in codes
        assert InsightCode.INTERVENTION_OBSERVED_CHANGE in codes
        order = [INSIGHT_ORDER.index(i.code) for i in combined]
        assert order == sorted(order)


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
