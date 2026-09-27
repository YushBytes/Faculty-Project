"""The eleven output contracts: what each one refuses to be built as.

These are the guards that keep a wrong number from ever reaching a teacher — an absence
carrying a score, a trend with no method, a flag with nothing to compare against, an
insight with no evidence, a causal claim in a message. Each test names the thing that must
not happen.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.core.contracts import AssessmentRef, StudentRef
from app.modules.analytics.core.outputs import (
    ANALYTICS_CONTRACTS,
    DIFFICULTY_CAVEAT,
    HISTOGRAM_BINS,
    OBSERVATIONAL_CAVEAT,
    REQUIRED_CONTRACT_NAMES,
    AttentionFlag,
    ChangeAnalysis,
    ChangeGroup,
    DataCoverage,
    DistributionBin,
    EvidenceItem,
    Explanation,
    GeneratedInsight,
    InterventionOutcome,
    OutcomeGroup,
    ScoreDistribution,
    SegmentFactor,
    StudentAssessmentPerformance,
    StudentPerformanceHistory,
    StudentSegment,
    StudentTrend,
)
from app.modules.analytics.core.policy import DerivedState, SeriesPoint
from app.modules.analytics.core.results import (
    Unit,
    insufficient_label,
    insufficient_measure,
    label,
    measure,
)
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity
from app.modules.analytics.core.thresholds import ResolvedThreshold, ThresholdKey, ThresholdSource
from app.modules.analytics.core.vocabulary import (
    OUTCOME_VOCABULARY,
    SEGMENT_VOCABULARY,
    TREND_VOCABULARY,
    InsightCode,
    InsightScope,
    OutcomeLabel,
    SegmentLabel,
    TrendLabel,
    TrendMethod,
)

NOW = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)
OFFERING = uuid.uuid4()
STUDENT = StudentRef(id=uuid.uuid4(), register_no="RA0001", name="Student One")


def assessment(code: str = "CT1", sequence_no: int = 1) -> AssessmentRef:
    return AssessmentRef(
        id=uuid.uuid4(), code=code, sequence_no=sequence_no, max_marks=Decimal("100.00")
    )


def explanation(
    *, caveats: tuple[str, ...] = (), evidence: tuple[EvidenceItem, ...] = ()
) -> Explanation:
    return Explanation(narrative="Stated for the test.", caveats=caveats, evidence=evidence)


def threshold(key: ThresholdKey, value: str) -> ResolvedThreshold:
    return ResolvedThreshold(key=key, value=Decimal(value), source=ThresholdSource.SYSTEM_DEFAULT)


def coverage(assessed: int = 1, absent: int = 0, exempt: int = 0, missing: int = 0) -> DataCoverage:
    return DataCoverage(
        assessed=assessed,
        absent=absent,
        exempt=exempt,
        missing=missing,
        basis="active enrolled students",
    )


def trend(**overrides: object) -> StudentTrend:
    defaults: dict[str, object] = {
        "generated_at": NOW,
        "offering_id": OFFERING,
        "student_id": STUDENT.id,
        "label": label(TrendLabel.DECLINING, vocabulary=TREND_VOCABULARY, n=3),
        "slope": measure(Decimal("-10.00"), unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT, n=3),
        "method": TrendMethod.LEAST_SQUARES,
        "points_used": ("CT1", "CT2", "CT3"),
        "percentages_used": (Decimal("80"), Decimal("70"), Decimal("60")),
        "threshold": threshold(ThresholdKey.TREND_DELTA_PP, "5"),
        "explanation": explanation(caveats=(DIFFICULTY_CAVEAT,)),
    }
    return StudentTrend(**(defaults | overrides))  # type: ignore[arg-type]


def flag(**overrides: object) -> AttentionFlag:
    defaults: dict[str, object] = {
        "generated_at": NOW,
        "offering_id": OFFERING,
        "student_id": STUDENT.id,
        "rule_code": AttentionRuleCode.R1_LOW_PERFORMANCE,
        "severity": FlagSeverity.HIGH,
        "actual": measure(Decimal("41.00"), unit=Unit.PERCENT, n=3),
        "threshold": threshold(ThresholdKey.LOW_PERFORMANCE_PERCENT, "50"),
        "reference_assessments": ("CT1", "CT2", "CT3"),
        "message": "Weighted course score 41%. Configured low-performance threshold 50%.",
        "explanation": explanation(),
    }
    return AttentionFlag(**(defaults | overrides))  # type: ignore[arg-type]


def distribution(counts: tuple[int, ...] | None = None) -> ScoreDistribution:
    filled = counts or (0, 0, 0, 0, 1, 1, 0, 0, 0, 0)
    n = sum(filled)
    bins = tuple(
        DistributionBin(
            lower=lower,
            upper=upper,
            count=count,
            share_percent=(Decimal(100 * count) / n).quantize(Decimal("0.01"))
            if n
            else Decimal("0.00"),
        )
        for (lower, upper), count in zip(HISTOGRAM_BINS, filled, strict=True)
    )
    return ScoreDistribution(
        offering_id=OFFERING,
        assessment=assessment(),
        bins=bins,
        n=n,
        coverage=coverage(assessed=n),
        explanation=explanation(),
    )


class TestEveryContract:
    @pytest.mark.parametrize("contract", ANALYTICS_CONTRACTS, ids=lambda c: c.__name__)
    def test_contract_is_frozen_and_rejects_unknown_fields(self, contract: type) -> None:
        """A response model that accepts extras will quietly carry an un-reviewed number."""
        assert contract.model_config["frozen"] is True
        assert contract.model_config["extra"] == "forbid"

    @pytest.mark.parametrize("contract", ANALYTICS_CONTRACTS, ids=lambda c: c.__name__)
    def test_contract_carries_an_explanation(self, contract: type) -> None:
        assert "explanation" in contract.model_fields, (
            f"{contract.__name__} has no explanation: every derived output must be able to "
            "say how it was produced."
        )

    @pytest.mark.parametrize("contract", ANALYTICS_CONTRACTS, ids=lambda c: c.__name__)
    def test_contract_is_stamped_or_is_stamped_by_its_container(self, contract: type) -> None:
        stamped = "generated_at" in contract.model_fields
        assert stamped or contract is ScoreDistribution, (
            f"{contract.__name__} must record when it was computed"
        )

    def test_the_original_eleven_are_all_still_here(self) -> None:
        """Later phases may add contracts; they may never drop or rename the eleven."""
        present = {contract.__name__ for contract in ANALYTICS_CONTRACTS}
        assert set(REQUIRED_CONTRACT_NAMES) <= present
        assert len(REQUIRED_CONTRACT_NAMES) == 11
        assert len(set(ANALYTICS_CONTRACTS)) == len(ANALYTICS_CONTRACTS), "no duplicates"


class TestTimestamps:
    def test_a_naive_timestamp_is_rejected(self) -> None:
        """A naive stamp silently becomes whatever timezone the reader is in."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            trend(generated_at=datetime(2026, 9, 26, 10, 30))


class TestExplanation:
    def test_a_missing_mandatory_caveat_is_reported_with_the_caveat_text(self) -> None:
        with pytest.raises(ValidationError, match="must carry the caveat"):
            trend(explanation=explanation())

    def test_with_caveat_does_not_duplicate(self) -> None:
        once = explanation().with_caveat(DIFFICULTY_CAVEAT)
        assert once.with_caveat(DIFFICULTY_CAVEAT).caveats == (DIFFICULTY_CAVEAT,)


class TestDataCoverage:
    def test_states_are_counted_separately(self) -> None:
        counted = DataCoverage.from_states(
            [
                DerivedState.ASSESSED,
                DerivedState.ASSESSED,
                DerivedState.ABSENT,
                DerivedState.EXEMPT,
                DerivedState.MISSING,
            ],
            basis="published assessments",
        )
        assert (counted.assessed, counted.absent, counted.exempt, counted.missing) == (2, 1, 1, 1)
        assert counted.considered == 5

    def test_exempt_leaves_the_completion_denominator_and_absent_does_not(self) -> None:
        counted = coverage(assessed=2, absent=1, exempt=1, missing=1)
        assert counted.completion_denominator == 4
        assert counted.excluded_states[DerivedState.EXEMPT] == 1


class TestScoreDistribution:
    def test_the_canonical_bins_are_required(self) -> None:
        bins = distribution().bins[:9]
        with pytest.raises(ValidationError, match="canonical ten"):
            ScoreDistribution(
                offering_id=OFFERING,
                bins=bins,
                n=2,
                coverage=coverage(assessed=2),
                explanation=explanation(),
            )

    def test_a_lost_student_is_caught(self) -> None:
        with pytest.raises(ValidationError, match="bin counts sum to"):
            ScoreDistribution(
                offering_id=OFFERING,
                bins=distribution().bins,
                n=5,
                coverage=coverage(assessed=5),
                explanation=explanation(),
            )

    def test_n_must_be_the_assessed_count_not_the_cohort(self) -> None:
        """Binning absent students would put them in the 0-9 bin. They are not zeroes."""
        with pytest.raises(ValidationError, match="only assessed students are binned"):
            ScoreDistribution(
                offering_id=OFFERING,
                bins=distribution().bins,
                n=2,
                coverage=coverage(assessed=4, absent=2),
                explanation=explanation(),
            )

    def test_the_top_bin_includes_one_hundred(self) -> None:
        assert HISTOGRAM_BINS[-1] == (90, 100)
        assert distribution().bins[-1].label == "90-100"


class TestStudentAssessmentPerformance:
    def performance(self, **overrides: object) -> StudentAssessmentPerformance:
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "offering_id": OFFERING,
            "student": STUDENT,
            "assessment": assessment(),
            "state": DerivedState.ASSESSED,
            "score": Decimal("62.00"),
            "max_marks": Decimal("100.00"),
            "percentage": measure(Decimal("62.00"), unit=Unit.PERCENT, n=1),
            "difference_from_class_mean": measure(
                Decimal("4.00"), unit=Unit.PERCENTAGE_POINTS, n=6
            ),
            "meets_pass_mark": True,
            "explanation": explanation(),
        }
        return StudentAssessmentPerformance(**(defaults | overrides))  # type: ignore[arg-type]

    def test_an_assessed_performance_carries_its_score(self) -> None:
        assert self.performance().percentage.value == Decimal("62.00")

    @pytest.mark.parametrize(
        "state", [DerivedState.ABSENT, DerivedState.EXEMPT, DerivedState.MISSING]
    )
    def test_a_non_assessed_performance_may_not_carry_a_score(self, state: DerivedState) -> None:
        with pytest.raises(ValidationError, match="not zero"):
            self.performance(state=state)

    def test_a_non_assessed_performance_reports_insufficient_data_not_zero(self) -> None:
        absent = self.performance(
            state=DerivedState.ABSENT,
            score=None,
            percentage=insufficient_measure(
                unit=Unit.PERCENT, n=0, minimum_n=1, reason="absent in CT1; absent is not zero"
            ),
            meets_pass_mark=None,
        )
        assert absent.percentage.value is None
        assert absent.percentage.reason is not None
        assert absent.meets_pass_mark is None

    def test_a_non_assessed_performance_may_not_claim_to_miss_the_pass_mark(self) -> None:
        with pytest.raises(ValidationError, match="meets_pass_mark"):
            self.performance(
                state=DerivedState.ABSENT,
                score=None,
                percentage=insufficient_measure(
                    unit=Unit.PERCENT, n=0, minimum_n=1, reason="absent in CT1"
                ),
                meets_pass_mark=False,
            )


class TestStudentTrend:
    def test_the_difficulty_caveat_is_mandatory(self) -> None:
        """RISK-10: a harder paper makes a whole cohort look like it is declining."""
        assert DIFFICULTY_CAVEAT in trend().explanation.caveats

    def test_a_classified_trend_must_name_its_method(self) -> None:
        with pytest.raises(ValidationError, match="name the method"):
            trend(method=None)

    def test_an_insufficient_trend_needs_no_method(self) -> None:
        withheld = trend(
            label=insufficient_label(
                vocabulary=TREND_VOCABULARY,
                n=1,
                minimum_n=2,
                reason="only 1 completed assessment (minimum 2)",
            ),
            slope=insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT,
                n=1,
                minimum_n=2,
                reason="only 1 completed assessment (minimum 2)",
            ),
            method=None,
            points_used=("CT1",),
            percentages_used=(Decimal("50"),),
        )
        assert withheld.label.value is None
        assert withheld.label.reason == "only 1 completed assessment (minimum 2)"

    def test_points_and_percentages_must_line_up(self) -> None:
        with pytest.raises(ValidationError, match="line up one to one"):
            trend(points_used=("CT1", "CT2"))

    def test_a_classified_trend_quotes_the_series_it_used(self) -> None:
        with pytest.raises(ValidationError, match="at least two percentages"):
            trend(points_used=("CT1",), percentages_used=(Decimal("80"),))


class TestStudentPerformanceHistory:
    def history(self, **overrides: object) -> StudentPerformanceHistory:
        points = (
            SeriesPoint(
                assessment_id=uuid.uuid4(),
                assessment_code="CT1",
                sequence_no=1,
                state=DerivedState.ASSESSED,
                percentage=Decimal("60.00"),
                score=Decimal("60.00"),
                max_marks=Decimal("100.00"),
            ),
            SeriesPoint(
                assessment_id=uuid.uuid4(),
                assessment_code="CT2",
                sequence_no=2,
                state=DerivedState.ABSENT,
                max_marks=Decimal("100.00"),
            ),
        )
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "offering_id": OFFERING,
            "student": STUDENT,
            "points": points,
            "weighted_course_score": measure(Decimal("60.00"), unit=Unit.PERCENT, n=1),
            "completion_percent": measure(Decimal("50.00"), unit=Unit.PERCENT, n=2),
            "consistency_std_dev": insufficient_measure(
                unit=Unit.PERCENT,
                n=1,
                minimum_n=3,
                reason="only 1 completed assessment (minimum 3)",
            ),
            "volatility_range": insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS,
                n=1,
                minimum_n=3,
                reason="only 1 completed assessment (minimum 3)",
            ),
            "trend": trend(),
            "coverage": DataCoverage(
                assessed=1, absent=1, exempt=0, missing=0, basis="published assessments"
            ),
            "explanation": explanation(),
        }
        return StudentPerformanceHistory(**(defaults | overrides))  # type: ignore[arg-type]

    def test_a_history_keeps_the_gaps_in_its_series(self) -> None:
        assert [p.state for p in self.history().points] == [
            DerivedState.ASSESSED,
            DerivedState.ABSENT,
        ]

    def test_coverage_must_describe_the_series_it_ships_with(self) -> None:
        """The one place a summary count could drift from the data under it."""
        with pytest.raises(ValidationError, match="coverage does not match"):
            self.history(
                coverage=DataCoverage(
                    assessed=2, absent=0, exempt=0, missing=0, basis="published assessments"
                )
            )


class TestStudentSegment:
    def segment(self, **overrides: object) -> StudentSegment:
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "offering_id": OFFERING,
            "student": STUDENT,
            "primary": label(SegmentLabel.BORDERLINE, vocabulary=SEGMENT_VOCABULARY, n=3),
            "factors": (
                SegmentFactor(segment=SegmentLabel.BORDERLINE, explanation=explanation()),
                SegmentFactor(segment=SegmentLabel.IMPROVING, explanation=explanation()),
            ),
            "explanation": explanation(),
        }
        return StudentSegment(**(defaults | overrides))  # type: ignore[arg-type]

    def test_supporting_factors_travel_with_the_primary(self) -> None:
        assert [f.segment for f in self.segment().factors] == [
            SegmentLabel.BORDERLINE,
            SegmentLabel.IMPROVING,
        ]

    def test_the_primary_must_be_one_of_the_satisfied_factors(self) -> None:
        with pytest.raises(ValidationError, match="not among the satisfied"):
            self.segment(primary=label(SegmentLabel.DECLINING, vocabulary=SEGMENT_VOCABULARY, n=3))

    def test_insufficient_data_means_no_factors_were_satisfied(self) -> None:
        with pytest.raises(ValidationError, match="must not list satisfied factors"):
            self.segment(
                primary=insufficient_label(
                    vocabulary=SEGMENT_VOCABULARY,
                    n=1,
                    minimum_n=2,
                    reason="only 1 completed assessment (minimum 2)",
                )
            )


class TestAttentionFlag:
    def test_a_flag_states_what_it_compared_against(self) -> None:
        assert flag().threshold is not None

    def test_a_flag_with_nothing_to_compare_against_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must quote either a resolved threshold"):
            flag(threshold=None)

    def test_r2_may_quote_the_offerings_pass_mark_instead(self) -> None:
        r2 = flag(
            rule_code=AttentionRuleCode.R2_FAILED_LATEST,
            severity=FlagSeverity.MEDIUM,
            threshold=None,
            pass_mark_percent=Decimal("40.00"),
            message="Latest assessment CT3 35%. Offering pass mark 40%.",
        )
        assert r2.pass_mark_percent == Decimal("40.00")

    def test_a_flag_cannot_fire_on_a_value_that_could_not_be_computed(self) -> None:
        with pytest.raises(ValidationError, match="must carry the value that fired it"):
            flag(
                actual=insufficient_measure(
                    unit=Unit.PERCENT, n=1, minimum_n=3, reason="only 1 completed assessment"
                )
            )

    @pytest.mark.parametrize(
        "message",
        [
            "This student will fail the course.",
            "Student is at risk of failing.",
            "Low score caused by poor attendance.",
            "Risk score 0.82.",
        ],
    )
    def test_predictive_or_causal_wording_is_refused(self, message: str) -> None:
        """Section 10: state the values and the rule, never a prediction or a cause."""
        with pytest.raises(ValidationError, match="forbidden wording"):
            flag(message=message)

    def test_the_documented_message_style_is_accepted(self) -> None:
        wording = (
            "Latest assessment 42%. Configured low-performance threshold 50%. "
            "Below 50% in 3 consecutive assessments (CT1 46%, CT2 48%, FT1 42%)."
        )
        assert flag(message=wording).message == wording


class TestChangeAnalysis:
    def change(self, **overrides: object) -> ChangeAnalysis:
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "offering_id": OFFERING,
            "from_assessment": assessment("CT1", 1),
            "to_assessment": assessment("CT2", 2),
            "intersection_n": 6,
            "class_mean_change": measure(Decimal("-4.50"), unit=Unit.PERCENTAGE_POINTS, n=6),
            "pass_percent_change": measure(Decimal("-16.67"), unit=Unit.PERCENTAGE_POINTS, n=6),
            "groups": (ChangeGroup(label="Crossed below the pass mark", students=(STUDENT,)),),
            "coverage": coverage(assessed=6, absent=1),
            "explanation": explanation(caveats=(DIFFICULTY_CAVEAT,)),
        }
        return ChangeAnalysis(**(defaults | overrides))  # type: ignore[arg-type]

    def test_every_count_carries_its_members(self) -> None:
        group = self.change().groups[0]
        assert group.count == len(group.students) == 1

    def test_the_difficulty_caveat_is_mandatory_on_a_comparison(self) -> None:
        with pytest.raises(ValidationError, match="must carry the caveat"):
            self.change(explanation=explanation())

    def test_nothing_changed_when_there_is_nothing_to_compare_against(self) -> None:
        """The first assessment of an offering has no predecessor; that is not a change of 0."""
        with pytest.raises(ValidationError, match="no earlier assessment"):
            self.change(from_assessment=None)


class TestInterventionOutcome:
    def outcome(self, **overrides: object) -> InterventionOutcome:
        baseline = assessment("CT1", 1)
        group = OutcomeGroup(
            name="target",
            n=4,
            pre_mean=measure(Decimal("38.00"), unit=Unit.PERCENT, n=4),
            post_mean=measure(Decimal("46.00"), unit=Unit.PERCENT, n=4),
            change=measure(Decimal("8.00"), unit=Unit.PERCENTAGE_POINTS, n=4),
        )
        peers = OutcomeGroup(
            name="peers",
            n=9,
            pre_mean=measure(Decimal("64.00"), unit=Unit.PERCENT, n=9),
            post_mean=measure(Decimal("66.00"), unit=Unit.PERCENT, n=9),
            change=measure(Decimal("2.00"), unit=Unit.PERCENTAGE_POINTS, n=9),
        )
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "intervention_id": uuid.uuid4(),
            "offering_id": OFFERING,
            "baseline_assessments": (baseline,),
            "follow_up_assessment": assessment("CT2", 2),
            "target": group,
            "peers": peers,
            "net_change": measure(Decimal("6.00"), unit=Unit.PERCENTAGE_POINTS, n=13),
            "label": label(OutcomeLabel.TARGET_IMPROVED_MORE, vocabulary=OUTCOME_VOCABULARY, n=13),
            "coverage": coverage(assessed=13, absent=2),
            "explanation": explanation(caveats=(OBSERVATIONAL_CAVEAT,)),
        }
        return InterventionOutcome(**(defaults | overrides))  # type: ignore[arg-type]

    def test_the_observational_caveat_is_mandatory(self) -> None:
        with pytest.raises(ValidationError, match="must carry the caveat"):
            self.outcome(explanation=explanation())

    def test_the_narrative_may_not_claim_causation(self) -> None:
        with pytest.raises(ValidationError, match="forbidden wording"):
            self.outcome(
                explanation=Explanation(
                    narrative="The 6 pp gain was caused by the revision sessions.",
                    caveats=(OBSERVATIONAL_CAVEAT,),
                )
            )

    def test_the_follow_up_may_not_also_be_the_baseline(self) -> None:
        baseline = assessment("CT1", 1)
        with pytest.raises(ValidationError, match="must not also be a baseline"):
            self.outcome(baseline_assessments=(baseline,), follow_up_assessment=baseline)

    def test_a_labelled_outcome_needs_both_windows(self) -> None:
        """Phase 6 widened this: an outcome with no baseline is *expressible*, but only as
        insufficient data — an intervention with nothing before it is a real state, and the
        engine has to be able to say so. What stays forbidden is labelling a change that had
        no window to be measured in.
        """
        with pytest.raises(ValidationError, match="without both windows"):
            self.outcome(baseline_assessments=())
        with pytest.raises(ValidationError, match="without both windows"):
            self.outcome(follow_up_assessment=None)

    def test_an_unmeasurable_outcome_may_report_no_window(self) -> None:
        withheld = insufficient_label(
            vocabulary=OUTCOME_VOCABULARY,
            n=0,
            minimum_n=1,
            reason="no published assessment has been held since this intervention",
        )
        built = self.outcome(follow_up_assessment=None, label=withheld)
        assert built.follow_up_assessment is None
        assert built.is_measured is False

    def test_both_groups_report_their_own_n(self) -> None:
        built = self.outcome()
        assert (built.target.n, built.peers.n) == (4, 9)


class TestGeneratedInsight:
    def insight(self, **overrides: object) -> GeneratedInsight:
        defaults: dict[str, object] = {
            "generated_at": NOW,
            "offering_id": OFFERING,
            "scope": InsightScope.OFFERING,
            "code": InsightCode.CLASS_MEAN_MOVED,
            "text": "Class mean fell 4.5 pp from CT1 (62.0%) to CT2 (57.5%), over 6 students.",
            "explanation": explanation(
                evidence=(EvidenceItem(name="CT1 mean", value="62.00", unit=Unit.PERCENT),)
            ),
        }
        return GeneratedInsight(**(defaults | overrides))  # type: ignore[arg-type]

    def test_an_insight_must_be_backed_by_evidence(self) -> None:
        with pytest.raises(ValidationError, match="carries no evidence"):
            self.insight(explanation=explanation())

    def test_a_student_insight_must_name_its_student(self) -> None:
        with pytest.raises(ValidationError, match="must name its subject_id"):
            self.insight(scope=InsightScope.STUDENT)

    def test_an_insight_may_not_predict(self) -> None:
        with pytest.raises(ValidationError, match="forbidden wording"):
            self.insight(text="Four students are at risk of failing this course.")


class TestSerialisation:
    def test_an_insufficient_measure_serialises_as_the_c10_payload(self) -> None:
        """Contract C10: value null, a status, a reason and n. Never NaN, never 0."""
        withheld = trend(
            label=insufficient_label(
                vocabulary=TREND_VOCABULARY,
                n=1,
                minimum_n=2,
                reason="only 1 completed assessment (minimum 2)",
            ),
            slope=insufficient_measure(
                unit=Unit.PERCENTAGE_POINTS_PER_ASSESSMENT,
                n=1,
                minimum_n=2,
                reason="only 1 completed assessment (minimum 2)",
            ),
            method=None,
            points_used=("CT1",),
            percentages_used=(Decimal("50"),),
        )
        payload = json.loads(withheld.model_dump_json())
        assert payload["slope"] == {
            "status": "insufficient_data",
            "n": 1,
            "minimum_n": 2,
            "reason": "only 1 completed assessment (minimum 2)",
            "value": None,
            "unit": "percentage_points_per_assessment",
        }

    def test_decimals_serialise_as_json_numbers(self) -> None:
        payload = json.loads(flag().model_dump_json())
        assert payload["actual"]["value"] == 41.0
        assert payload["threshold"]["value"] == 50.0
        assert payload["threshold"]["source"] == "system_default"
