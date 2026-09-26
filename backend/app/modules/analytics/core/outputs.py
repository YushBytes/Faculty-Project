"""The eleven analytics output contracts, and the explainability payload they all share.

Every model here is what an analytics function *returns* and what a router serialises. They
are plain typed data: no session, no ORM, no I/O, so each can be built in a test from
hand-computed numbers and compared field by field.

The rule that shapes all of them: **a derived number must arrive with enough beside it to
explain itself.** In practice that means four things travel with every output.

``Measure`` / ``Label``
    The value, its unit or vocabulary, the ``n`` it was computed over, and — when it could
    not be computed — ``status="insufficient_data"`` with a reason instead of a fabricated
    zero (contract C10).
``DataCoverage``
    How many students or assessments were assessed, absent, exempt or missing. This is what
    makes "mean 62%" honest: it says who was not in it.
``ResolvedThreshold``
    The threshold the rule compared against *and where that number came from*, so an
    explanation can say "50%, set for this offering" rather than just "50%".
``Explanation``
    The formula, the evidence, and any caveat that must be read with the number.

Two caveats are enforced rather than documented, because they are the two places this
system could most easily mislead a teacher: comparisons across assessments carry
:data:`DIFFICULTY_CAVEAT` (a harder paper looks like a declining class), and intervention
outcomes carry :data:`OBSERVATIONAL_CAVEAT` (a change observed after an action is not a
change caused by it). Messages and insight text are additionally screened for predictive
and causal wording; see :data:`FORBIDDEN_PHRASES`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import JsonDecimal, Percent
from app.modules.analytics.core.contracts import AssessmentRef, StudentRef
from app.modules.analytics.core.policy import DerivedState, SeriesPoint
from app.modules.analytics.core.results import Label, Measure, Unit
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity, FlagStatus
from app.modules.analytics.core.thresholds import ResolvedThreshold
from app.modules.analytics.core.vocabulary import (
    ChangeDirection,
    InsightCode,
    InsightScope,
    SegmentLabel,
    StudentFindingCode,
    TrendMethod,
)

DIFFICULTY_CAVEAT: Final[str] = (
    "Assessments are not equated for difficulty: a harder paper lowers percentages across "
    "the cohort, so a change between assessments is not by itself evidence about the students."
)
"""RISK-10. Required on any output that compares one assessment against another."""

OBSERVATIONAL_CAVEAT: Final[str] = (
    "Observed change only. Students were not randomly assigned and no control was held, so "
    "this comparison does not show that the intervention caused the change."
)
"""CONFLICT-3 / section 10. Required on every intervention outcome."""

FORBIDDEN_PHRASES: Final[tuple[str, ...]] = (
    "will fail",
    "will pass",
    "at risk of failing",
    "high risk",
    "risk score",
    "likely to fail",
    "predicts",
    "prediction",
    "forecast",
    "caused by",
    "because the student",
    "due to lack of",
)
"""Wording analytics may never emit: prediction, risk scoring, or an invented cause.

Screened in :class:`AttentionFlag` messages and :class:`GeneratedInsight` text, which are
the only free-text fields that reach a teacher. The list is deliberately about *claims*, not
tone: "below the pass mark in three consecutive assessments" is a fact and passes; "at risk
of failing" is a prediction this system is not allowed to make.
"""

_WORD_BOUNDARY = re.compile(r"[^a-z]+")


def _reject_forbidden_wording(text: str, *, field: str) -> str:
    """Reject predictive or causal claims in text that reaches a user."""
    normalised = " ".join(_WORD_BOUNDARY.split(text.lower())).strip()
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in normalised]
    if found:
        raise ValueError(
            f"{field} contains forbidden wording {found}: analytics states what the data "
            "shows, and never predicts an outcome or asserts a cause. Rephrase as an "
            "observation with its numbers."
        )
    return text


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Generated(_Frozen):
    """An output stamped with when it was computed.

    Timezone-aware only: these timestamps end up in reports and stored flags, where a naive
    one silently becomes whatever the reader's timezone is.
    """

    generated_at: datetime

    @model_validator(mode="after")
    def _timestamp_is_aware(self) -> Self:
        stamp = self.generated_at
        if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
            raise ValueError("generated_at must be timezone-aware")
        return self


# --------------------------------------------------------------------- explainability


class EvidenceItem(_Frozen):
    """One named fact behind a derived number, rendered for display.

    ``value`` is a string because evidence is heterogeneous — a percentage, a count, an
    assessment code, a status word — and it exists to be read, not recomputed.
    """

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: Unit | None = None
    note: str | None = None


class Explanation(_Frozen):
    """How one output was produced: the arithmetic, the inputs, the warnings.

    Present on every derived contract in this module. An explanation with no evidence is
    allowed only where the output is itself the evidence (a raw percentage, say); everything
    derived from more than one number must list what went into it.
    """

    narrative: str = Field(min_length=1)
    """One or two sentences of plain language, stating values and thresholds."""

    formula: str | None = None
    """The arithmetic in symbols, e.g. ``W = sum(P_a * w_a) / sum(w_a)``."""

    evidence: tuple[EvidenceItem, ...] = ()
    thresholds: tuple[ResolvedThreshold, ...] = ()
    pass_mark_percent: Percent | None = None
    assessments_used: tuple[str, ...] = ()
    """Assessment codes, in the order they contributed."""

    caveats: tuple[str, ...] = ()

    def with_caveat(self, caveat: str) -> Explanation:
        """A copy carrying one more caveat, if it is not already there."""
        if caveat in self.caveats:
            return self
        return self.model_copy(update={"caveats": (*self.caveats, caveat)})

    def requires(self, caveat: str, *, field: str) -> None:
        """Assert a mandatory caveat is present."""
        if caveat not in self.caveats:
            raise ValueError(f"{field} must carry the caveat: {caveat}")


class DataCoverage(_Frozen):
    """Who is behind a statistic, and who is not.

    Absent, exempt and missing are counted separately and never folded into a zero. Exempt
    is the one state excluded from the completion denominator: the student was not required
    to sit the assessment, so counting it against them would manufacture a problem.
    """

    assessed: int = Field(ge=0)
    absent: int = Field(ge=0)
    exempt: int = Field(ge=0)
    missing: int = Field(ge=0)
    basis: str = Field(min_length=1)
    """What the counts are over, e.g. "active enrolled students in this offering"."""

    @property
    def considered(self) -> int:
        """Every unit looked at, in any state."""
        return self.assessed + self.absent + self.exempt + self.missing

    @property
    def completion_denominator(self) -> int:
        """Everything the students were expected to sit: exempt excluded."""
        return self.assessed + self.absent + self.missing

    @property
    def excluded_states(self) -> Mapping[DerivedState, int]:
        """The non-assessed states and their counts, for an explanation's evidence."""
        return {
            DerivedState.ABSENT: self.absent,
            DerivedState.EXEMPT: self.exempt,
            DerivedState.MISSING: self.missing,
        }

    @classmethod
    def from_states(cls, states: Iterable[DerivedState], *, basis: str) -> DataCoverage:
        counts = dict.fromkeys(DerivedState, 0)
        for state in states:
            counts[state] += 1
        return cls(
            assessed=counts[DerivedState.ASSESSED],
            absent=counts[DerivedState.ABSENT],
            exempt=counts[DerivedState.EXEMPT],
            missing=counts[DerivedState.MISSING],
            basis=basis,
        )


class ExtremeScore(_Frozen):
    """A minimum or maximum, with the student it belongs to.

    Section 10 requires min/max to carry a student reference: a lowest score with no name
    cannot be acted on.
    """

    student: StudentRef
    percentage: Percent
    assessment_code: str | None = None


# ------------------------------------------------------------------ 6. ScoreDistribution

HISTOGRAM_BINS: Final[tuple[tuple[int, int], ...]] = (
    (0, 9),
    (10, 19),
    (20, 29),
    (30, 39),
    (40, 49),
    (50, 59),
    (60, 69),
    (70, 79),
    (80, 89),
    (90, 100),
)
"""Ten fixed bins. The last is 90-100 inclusive, so a perfect score has a home."""


class DistributionBin(_Frozen):
    """One histogram bin: its inclusive bounds, its count and its share."""

    lower: int = Field(ge=0, le=100)
    upper: int = Field(ge=0, le=100)
    count: int = Field(ge=0)
    share_percent: Percent
    """``100 * count / n``, so a chart can be drawn without recomputing it."""

    @property
    def label(self) -> str:
        return f"{self.lower}-{self.upper}"

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.upper < self.lower:
            raise ValueError(f"bin upper {self.upper} is below lower {self.lower}")
        return self


class ScoreDistribution(_Frozen):
    """**Contract 6.** How one assessment's percentages are spread across the cohort.

    Only assessed students are binned; ``coverage`` states who was left out and why. The
    bins must be the canonical ten and the counts must sum to ``n``, both checked here, so
    a distribution can never quietly lose a student.
    """

    offering_id: uuid.UUID
    assessment: AssessmentRef | None = None
    """``None`` when the distribution is over a derived series, e.g. weighted course scores."""

    bins: tuple[DistributionBin, ...]
    n: int = Field(ge=0)
    coverage: DataCoverage
    explanation: Explanation

    @model_validator(mode="after")
    def _bins_are_canonical_and_complete(self) -> Self:
        bounds = tuple((b.lower, b.upper) for b in self.bins)
        if bounds != HISTOGRAM_BINS:
            raise ValueError(
                f"distribution bins must be the canonical ten {HISTOGRAM_BINS}, got {bounds}"
            )
        total = sum(b.count for b in self.bins)
        if total != self.n:
            raise ValueError(f"bin counts sum to {total} but n is {self.n}")
        if self.n != self.coverage.assessed:
            raise ValueError(
                f"n is {self.n} but coverage reports {self.coverage.assessed} assessed; "
                "only assessed students are binned"
            )
        return self


# ---------------------------------------------------------------- 1. AssessmentAnalytics


class AssessmentAnalytics(_Generated):
    """**Contract 1.** Everything about one assessment across its cohort.

    The group statistics are over assessed students only. ``pass_percent`` is the share of
    *assessed* students at or above the offering's pass mark — not the share of the whole
    cohort, which would silently punish an absence — and ``completion_percent`` is the
    separate figure that reports the absences.
    """

    offering_id: uuid.UUID
    assessment: AssessmentRef
    pass_mark_percent: Percent

    mean: Measure
    median: Measure
    std_dev: Measure
    lowest: ExtremeScore | None = None
    highest: ExtremeScore | None = None
    pass_percent: Measure
    completion_percent: Measure
    distribution: ScoreDistribution

    coverage: DataCoverage
    explanation: Explanation


# -------------------------------------------------------- 2. StudentAssessmentPerformance


class StudentAssessmentPerformance(_Generated):
    """**Contract 2.** One student in one assessment.

    ``state`` is authoritative. When it is not ``ASSESSED`` there is no score and no
    percentage: ``percentage`` arrives as an insufficient-data measure naming the state, and
    ``score`` is ``None``. That is the contract that keeps an absence from becoming a zero
    two layers further up.
    """

    offering_id: uuid.UUID
    student: StudentRef
    assessment: AssessmentRef
    state: DerivedState

    score: JsonDecimal | None = Field(default=None, ge=0)
    max_marks: JsonDecimal = Field(gt=0)
    percentage: Measure
    difference_from_class_mean: Measure
    """Signed percentage points against the assessment's mean, over assessed students."""

    meets_pass_mark: bool | None = None
    """``None`` when the student was not assessed: unknown, not false."""

    explanation: Explanation

    @model_validator(mode="after")
    def _non_assessed_carries_no_score(self) -> Self:
        if self.state is DerivedState.ASSESSED:
            if self.score is None:
                raise ValueError("an assessed performance must carry a score")
            return self
        if self.score is not None:
            raise ValueError(
                f"a {self.state.value} performance must not carry a score; "
                "absent, exempt and missing are not zero"
            )
        if self.percentage.is_ok:
            raise ValueError(
                f"a {self.state.value} performance must not carry a percentage; "
                "report it as insufficient_data naming the state"
            )
        if self.meets_pass_mark is not None:
            raise ValueError(
                f"a {self.state.value} performance cannot be said to meet or miss the pass "
                "mark; leave meets_pass_mark null"
            )
        return self


# ------------------------------------------------------------------------ 4. StudentTrend


class StudentTrend(_Generated):
    """**Contract 4.** The direction of one student's percentage series.

    Deliberately explicit about its own weakness: ``method`` distinguishes a two-point
    difference from a fitted slope, ``points_used`` names the assessments, and the
    difficulty caveat is mandatory, because a class-wide "decline" is at least as likely to
    be a harder paper as a change in the students.
    """

    offering_id: uuid.UUID
    student_id: uuid.UUID
    label: Label
    """Vocabulary ``trend``; ``status=insufficient_data`` below the minimum points."""

    slope: Measure
    """Percentage points per assessment. Signed: negative is a fall."""

    method: TrendMethod | None = None
    """``None`` when there were too few points to classify."""

    points_used: tuple[str, ...] = ()
    percentages_used: tuple[JsonDecimal, ...] = ()
    threshold: ResolvedThreshold
    explanation: Explanation

    @model_validator(mode="after")
    def _explains_itself(self) -> Self:
        self.explanation.requires(DIFFICULTY_CAVEAT, field="StudentTrend.explanation")
        if self.label.is_ok and self.method is None:
            raise ValueError("a classified trend must name the method that produced it")
        if len(self.points_used) != len(self.percentages_used):
            raise ValueError("points_used and percentages_used must line up one to one")
        if self.label.is_ok and len(self.percentages_used) < 2:
            raise ValueError("a classified trend must quote at least two percentages")
        return self


# ------------------------------------------------------------ 3. StudentPerformanceHistory


class StudentPerformanceHistory(_Generated):
    """**Contract 3.** One student's whole story within one offering.

    The weighted course score is over *completed* assessments only, so an assessment that
    has not happened yet cannot drag a student down. Consistency is the standard deviation
    of the same series, gated on its own minimum, because two points describe no spread.
    """

    offering_id: uuid.UUID
    student: StudentRef
    points: tuple[SeriesPoint, ...]
    """Every published assessment, including the ones with no result: a gap is information."""

    weighted_course_score: Measure
    completion_percent: Measure
    consistency_std_dev: Measure
    volatility_range: Measure
    trend: StudentTrend
    latest: StudentAssessmentPerformance | None = None
    coverage: DataCoverage
    explanation: Explanation

    @model_validator(mode="after")
    def _coverage_matches_the_series(self) -> Self:
        counted = DataCoverage.from_states(
            (p.state for p in self.points), basis=self.coverage.basis
        )
        if counted.model_dump() != self.coverage.model_dump():
            raise ValueError(
                "coverage does not match the series it describes: "
                f"series is {counted.model_dump()}, coverage says {self.coverage.model_dump()}"
            )
        return self


# ------------------------------------------- 12. StudentPerformanceProfile and its findings


class StudentFinding(_Frozen):
    """One condition a student's series either satisfies or does not, with the evidence.

    Deliberately *not* an :class:`AttentionFlag`. A finding states what the numbers do; a
    flag says someone should act, carries a severity and has a lifecycle. Keeping them
    separate means the attention engine can raise a flag from a finding, while a report can
    show the finding without implying a call to action.

    ``detected`` is three-valued on purpose. ``None`` means the condition could not be
    evaluated — too few completed assessments, usually — and is not the same answer as
    ``False``. Saying "no sharp decline" about a student with one result would be a claim the
    data does not support.
    """

    code: StudentFindingCode
    detected: bool | None
    measure: Measure
    """The value the condition was evaluated on: the drop, the run length, the change."""

    threshold: ResolvedThreshold | None = None
    pass_mark_percent: Percent | None = None
    explanation: Explanation

    @model_validator(mode="after")
    def _undetermined_findings_carry_no_verdict(self) -> Self:
        if self.detected is not None and not self.measure.is_ok:
            raise ValueError(
                f"{self.code.value} reports detected={self.detected} from a measure that "
                "could not be computed; an unevaluable condition is None, not False"
            )
        if self.detected is None and self.measure.is_ok:
            raise ValueError(
                f"{self.code.value} has a computed measure but no verdict; if the value "
                "exists the condition can be evaluated"
            )
        return self


class StudentPerformanceProfile(_Generated):
    """**Contract 12.** One student, read as a whole rather than as a list of numbers.

    Phase 2 computes the measures; this composes them into the answer to "how is this
    student doing over time?" — the history, the latest result beside the previous one, the
    comparison against their own earlier work, the trend, and the conditions their series
    satisfies. Nothing here recomputes a statistic: every number comes from the Phase 2
    functions, so the profile and a bare measure can never disagree.
    """

    offering_id: uuid.UUID
    student: StudentRef
    history: StudentPerformanceHistory

    latest: StudentAssessmentPerformance | None = None
    """The most recent assessment the student was assessed in. Same object the history
    carries, surfaced here so it reads beside ``previous``."""

    previous: StudentAssessmentPerformance | None = None
    """The one before that — the previous time there was a performance, skipping absences."""

    change_from_previous: Measure
    """``P_latest - P_previous``, in percentage **points**. Not a percentage change: a move
    from 40% to 44% is +4 pp, never "+10%"."""

    historical_average: Measure
    """Mean of the completed assessments **before** the latest one, per F10's definition of
    "prior history". The latest result is the thing being compared, not part of the baseline."""

    change_from_historical_average: Measure
    """``P_latest - historical_average``, signed. The same measure F10 evaluates."""

    findings: tuple[StudentFinding, ...] = ()
    explanation: Explanation

    @property
    def trend(self) -> StudentTrend:
        """The trend, from the history. There is only one, computed once."""
        return self.history.trend

    def finding(self, code: StudentFindingCode) -> StudentFinding | None:
        for found in self.findings:
            if found.code is code:
                return found
        return None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        codes = [found.code for found in self.findings]
        if len(codes) != len(set(codes)):
            raise ValueError(f"duplicate finding codes {sorted(c.value for c in codes)}")
        if self.previous is None and self.change_from_previous.is_ok:
            raise ValueError(
                "a change from the previous assessment was reported without a previous "
                "assessment to compare against"
            )
        if (
            self.latest is not None
            and self.history.latest is not None
            and self.latest.assessment.id != self.history.latest.assessment.id
        ):
            raise ValueError(
                "the profile's latest assessment disagrees with the history's; they must be "
                "the same performance"
            )
        if (self.latest is None) != (self.history.latest is None):
            raise ValueError("the profile and its history disagree about whether a latest exists")
        return self


# ---------------------------------------------------------------------- 7. StudentSegment


class SegmentFactor(_Frozen):
    """One segment a student satisfies, with the evidence for it."""

    segment: SegmentLabel
    explanation: Explanation


class StudentSegment(_Generated):
    """**Contract 7.** One primary actionable status, plus everything else that is true.

    A student is often several things at once — borderline *and* improving. Returning one
    label would hide half of that and returning an unordered set would give a teacher
    nothing to act on, so the primary is chosen by :data:`SEGMENT_PRIORITY` and the rest
    travel with it.
    """

    offering_id: uuid.UUID
    student: StudentRef
    primary: Label
    """Vocabulary ``segment``; ``status=insufficient_data`` when nothing can be said."""

    factors: tuple[SegmentFactor, ...] = ()
    explanation: Explanation

    @model_validator(mode="after")
    def _primary_is_one_of_the_factors(self) -> Self:
        if self.primary.is_ok:
            satisfied = {f.segment.value for f in self.factors}
            if self.primary.value not in satisfied:
                raise ValueError(
                    f"primary segment {self.primary.value!r} is not among the satisfied "
                    f"factors {sorted(satisfied)}"
                )
        elif self.factors:
            raise ValueError(
                "an insufficient-data segment must not list satisfied factors: "
                "if a factor was satisfied, something could be said"
            )
        return self


# ------------------------------------------------------------------------ 8. AttentionFlag


class AttentionFlag(_Generated):
    """**Contract 8.** One fired rule, for one student, with everything needed to justify it.

    Carries the fields dependency D6 persists (``rule_code``, ``severity``, ``threshold``,
    ``actual_value``, ``message``, ``status``, ``computed_at``) plus the reference
    assessments and ``n``. The message is screened for predictive and causal wording: this
    is the single field most likely to end up quoted to a student.
    """

    offering_id: uuid.UUID
    student_id: uuid.UUID
    rule_code: AttentionRuleCode
    severity: FlagSeverity
    status: FlagStatus = FlagStatus.OPEN

    actual: Measure
    threshold: ResolvedThreshold | None = None
    """``None`` for R2, which compares against the offering's pass mark instead."""

    pass_mark_percent: Percent | None = None
    reference_assessments: tuple[str, ...] = ()
    message: str = Field(min_length=1)
    explanation: Explanation

    @model_validator(mode="after")
    def _states_what_it_compared(self) -> Self:
        _reject_forbidden_wording(self.message, field="AttentionFlag.message")
        if self.threshold is None and self.pass_mark_percent is None:
            raise ValueError(
                f"{self.rule_code.value} must quote either a resolved threshold or the "
                "offering's pass mark; a flag with no stated comparison cannot be explained"
            )
        if not self.actual.is_ok:
            raise ValueError(
                "a raised flag must carry the value that fired it; if the value could not "
                "be computed the rule must not fire"
            )
        return self


# --------------------------------------------------------------------------- 5. ClassHealth


class ClassHealth(_Generated):
    """**Contract 5.** Offering-level KPIs, as a dashboard header.

    Everything here is an aggregate of the contracts above; nothing is computed a second
    way. ``students_requiring_attention`` follows the escalation rule in
    :func:`~app.modules.analytics.core.rules.requires_attention` — any High rule, or two
    Medium ones — and is reported beside the per-severity counts so the number can be taken
    apart.
    """

    offering_id: uuid.UUID
    pass_mark_percent: Percent
    cohort_n: int = Field(ge=0)
    published_assessments: int = Field(ge=0)

    class_mean: Measure
    median: Measure
    pass_percent: Measure
    completion_percent: Measure
    students_requiring_attention: Measure

    segment_counts: Mapping[SegmentLabel, int] = Field(default_factory=dict)
    flag_counts: Mapping[FlagSeverity, int] = Field(default_factory=dict)
    latest_assessment: AssessmentAnalytics | None = None
    coverage: DataCoverage
    explanation: Explanation

    @model_validator(mode="after")
    def _counts_are_not_negative(self) -> Self:
        for name, counts in (
            ("segment_counts", self.segment_counts),
            ("flag_counts", self.flag_counts),
        ):
            bad = {k: v for k, v in counts.items() if v < 0}
            if bad:
                raise ValueError(f"{name} has negative entries {bad}")
        return self


# ------------------------------------------------------------------------ 9. ChangeAnalysis


class ChangeGroup(_Frozen):
    """A counted set of students, with its members named.

    Section 10 requires every "what changed" count to carry its member list: a teacher
    cannot act on "4 students crossed below the pass mark" without knowing which four.
    """

    label: str = Field(min_length=1)
    direction: ChangeDirection | None = None
    students: tuple[StudentRef, ...] = ()

    @property
    def count(self) -> int:
        return len(self.students)


class ChangeAnalysis(_Generated):
    """**Contract 9.** What the latest assessment changed, against the state before it.

    Comparisons are over the **cohort intersection** — students with an assessed result in
    both assessments — and ``intersection_n`` states its size, because a mean that moved
    because a different set of students sat the paper has not moved at all.
    """

    offering_id: uuid.UUID
    from_assessment: AssessmentRef | None = None
    """``None`` when the latest assessment is the first: there is nothing to compare to."""

    to_assessment: AssessmentRef
    intersection_n: int = Field(ge=0)
    class_mean_change: Measure
    pass_percent_change: Measure
    groups: tuple[ChangeGroup, ...] = ()
    """Crossed the pass mark upward/downward, newly declining, newly flagged, and so on."""

    new_flags: tuple[AttentionFlag, ...] = ()
    coverage: DataCoverage
    explanation: Explanation

    @model_validator(mode="after")
    def _comparisons_carry_the_difficulty_caveat(self) -> Self:
        self.explanation.requires(DIFFICULTY_CAVEAT, field="ChangeAnalysis.explanation")
        if self.from_assessment is None and (self.class_mean_change.is_ok or self.groups):
            raise ValueError(
                "there is no earlier assessment to compare against, so no change may be "
                "reported; return insufficient_data instead"
            )
        return self


# ------------------------------------------------------------------ 10. InterventionOutcome


class OutcomeGroup(_Frozen):
    """One side of an outcome comparison: the targeted students, or their peers.

    Only students with an assessed result in **both** the baseline and the follow-up are
    counted, so ``n`` is the size of that intersection, not of the group as recorded.
    """

    name: str = Field(min_length=1)
    n: int = Field(ge=0)
    pre_mean: Measure
    post_mean: Measure
    change: Measure
    students: tuple[StudentRef, ...] = ()


class InterventionOutcome(_Generated):
    """**Contract 10.** The observed change after an intervention, against a peer baseline.

    ``net_change = target.change - peers.change``. The peer group is what stops a
    cohort-wide effect (an easier follow-up paper) being read as the intervention working.
    The observational caveat is mandatory and the label vocabulary is deliberately worded as
    comparison, never as achievement.
    """

    intervention_id: uuid.UUID
    offering_id: uuid.UUID
    baseline_assessments: tuple[AssessmentRef, ...]
    follow_up_assessment: AssessmentRef
    target: OutcomeGroup
    peers: OutcomeGroup
    net_change: Measure
    label: Label
    """Vocabulary ``intervention_outcome``; insufficient below the minimum group size."""

    coverage: DataCoverage
    explanation: Explanation

    @model_validator(mode="after")
    def _never_claims_causation(self) -> Self:
        self.explanation.requires(OBSERVATIONAL_CAVEAT, field="InterventionOutcome.explanation")
        _reject_forbidden_wording(
            self.explanation.narrative, field="InterventionOutcome.explanation.narrative"
        )
        if not self.baseline_assessments:
            raise ValueError("an outcome needs at least one baseline assessment")
        if self.follow_up_assessment.id in {a.id for a in self.baseline_assessments}:
            raise ValueError(
                "the follow-up assessment must not also be a baseline assessment: "
                "comparing an assessment with itself measures nothing"
            )
        return self


# ----------------------------------------------------------------- 11. GeneratedInsight


class GeneratedInsight(_Generated):
    """**Contract 11.** One deterministic sentence, and the numbers that produced it.

    No LLM (section 11): a fixed template per :class:`InsightCode`, filled from analytics
    outputs. ``evidence`` must be non-empty, so a sentence can never be shown that nothing
    supports, and the text is screened for prediction and invented causes.
    """

    offering_id: uuid.UUID
    scope: InsightScope
    subject_id: uuid.UUID | None = None
    """The student, assessment or intervention the insight is about; ``None`` for offering."""

    code: InsightCode
    text: str = Field(min_length=1)
    severity: FlagSeverity | None = None
    explanation: Explanation

    @model_validator(mode="after")
    def _traceable_and_not_predictive(self) -> Self:
        _reject_forbidden_wording(self.text, field="GeneratedInsight.text")
        if self.scope is not InsightScope.OFFERING and self.subject_id is None:
            raise ValueError(f"a {self.scope.value}-scoped insight must name its subject_id")
        if not self.explanation.evidence:
            raise ValueError(
                f"insight {self.code.value} carries no evidence: every insight sentence must "
                "name the analytics values behind it"
            )
        return self


REQUIRED_CONTRACT_NAMES: Final[tuple[str, ...]] = (
    "AssessmentAnalytics",
    "StudentAssessmentPerformance",
    "StudentPerformanceHistory",
    "StudentTrend",
    "ClassHealth",
    "ScoreDistribution",
    "StudentSegment",
    "AttentionFlag",
    "ChangeAnalysis",
    "InterventionOutcome",
    "GeneratedInsight",
)
"""The eleven the Phase 1 brief named. They may never be dropped or renamed."""

ANALYTICS_CONTRACTS: Final[tuple[type[BaseModel], ...]] = (
    AssessmentAnalytics,
    StudentAssessmentPerformance,
    StudentPerformanceHistory,
    StudentTrend,
    ClassHealth,
    ScoreDistribution,
    StudentSegment,
    AttentionFlag,
    ChangeAnalysis,
    InterventionOutcome,
    GeneratedInsight,
    StudentPerformanceProfile,
)
"""Every analytics response contract: the eleven above, then what later phases compose.

:data:`REQUIRED_CONTRACT_NAMES` pins the original eleven; this tuple is what the structural
tests sweep, so a new analytic's contract gets the same guarantees (frozen, no extra fields,
carries an explanation, stamped) by being added here.

Deliberately a tuple of the public outputs: a new analytic adds its contract here so the
suite's structural checks (explainability payload, frozen, no extras) cover it too.
"""
