"""F21: the analytics, said in sentences. Deterministic templates, no model of any kind.

One code, one template, one set of numbers. There is no language model here and no scoring:
each rule is an ``if`` over facts the engine already computed, and the sentence it produces
is a formatting of those facts. Run it twice on the same snapshot and you get the same
words, in the same order, every time.

    existing analytics  ->  insight rules  ->  GeneratedInsight (contract 11)

**Nothing is recalculated.** Every number comes from a Phase 2-6 contract:

=============================  ==================================================
insight                        the fact behind it
=============================  ==================================================
class mean / pass rate moved   ``ChangeAnalysis`` and its ``AssessmentComparison``
completion moved               ``AssessmentComparison.completion_change``
decline / trend / repeated     ``rule_counts`` from the attention engine, which has
low / completion / borderline  already applied R3-R7 with their thresholds
clusters
improvement cluster            ``ChangeAnalysis.groups``
attention summary              ``cohort_attention`` counts
distribution peak              ``ClassHealth.course_score_distribution``
student insights               ``StudentPerformanceProfile`` and its findings
intervention                   ``InterventionOutcome``
=============================  ==================================================

The cluster insights are worth a word. They read ``rule_counts``, which counts the students
who fired each attention rule — so "5 students declined by at least 15 percentage points"
*is* R4's count, evaluated once, with R4's threshold. Re-deriving it here with a fresh loop
over students would be a second implementation of the same rule, free to disagree with the
first.

**A rule that cannot be supported produces nothing.** An offering with one assessment yields
no class-mean insight — not "the class average was stable", which is a claim about a change
that was never measured. A genuine zero is different and *is* reported: "unchanged at
70.00%" is a fact. The two are never conflated, which is the same line the rest of this
layer draws between insufficient data and zero.

Wording is neutral and observational. The contract screens every sentence against
:data:`~app.modules.analytics.core.outputs.FORBIDDEN_PHRASES`, so a template that reached
for "caused", "effectiveness" or "at risk of failing" would fail at construction rather than
in front of a teacher.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.attention import (
    cohort_attention,
    flagged_students,
    rule_counts,
    students_requiring_attention,
)
from app.modules.analytics.core.class_health import class_health
from app.modules.analytics.core.comparison import change_analysis, latest_published
from app.modules.analytics.core.contracts import Intervention, OfferingSnapshot
from app.modules.analytics.core.interventions import intervention_outcomes
from app.modules.analytics.core.outputs import (
    OBSERVATIONAL_CAVEAT,
    AttentionFlag,
    ChangeAnalysis,
    ClassHealth,
    EvidenceItem,
    Explanation,
    GeneratedInsight,
    InterventionOutcome,
    StudentAttention,
    StudentPerformanceProfile,
)
from app.modules.analytics.core.profile import student_profile
from app.modules.analytics.core.results import Measure, Unit
from app.modules.analytics.core.rules import ATTENTION_RULES, AttentionRuleCode
from app.modules.analytics.core.thresholds import ResolvedThreshold, ThresholdKey, ThresholdSet
from app.modules.analytics.core.vocabulary import (
    INSIGHT_ORDER,
    InsightCode,
    InsightScope,
    StudentFindingCode,
)

_ORDER = {code: index for index, code in enumerate(INSIGHT_ORDER)}


def _direction(value: Decimal) -> str:
    """The verb for a signed movement. Neutral words only: no "improved", no "worsened"."""
    if value > 0:
        return "increased"
    if value < 0:
        return "decreased"
    return "remained unchanged"


def _students(number: int) -> str:
    return "1 student" if number == 1 else f"{number} students"


def _were(number: int) -> str:
    """Verb agreement, so a cohort of one does not read as broken English."""
    return "was" if number == 1 else "were"


def _are(number: int) -> str:
    return "is" if number == 1 else "are"


def _insight(
    *,
    code: InsightCode,
    offering_id: uuid.UUID,
    scope: InsightScope,
    text: str,
    evidence: Sequence[EvidenceItem],
    formula: str,
    subject_id: uuid.UUID | None = None,
    thresholds: Sequence[ResolvedThreshold] = (),
    pass_mark_percent: Decimal | None = None,
    assessments: Sequence[str] = (),
    caveats: Sequence[str] = (),
    generated_at: datetime,
) -> GeneratedInsight:
    """Build one insight. Every rule goes through here, so none can skip its evidence."""
    return GeneratedInsight(
        generated_at=generated_at,
        offering_id=offering_id,
        scope=scope,
        subject_id=subject_id,
        code=code,
        text=text,
        severity=None,
        # Deliberately unset. The contract allows a severity, but attaching one would invite
        # ranking insights by it, and an ordering of findings is a judgement for the person
        # who knows the students. Presentation order is INSIGHT_ORDER; see the module docs.
        explanation=Explanation(
            narrative=text,
            formula=formula,
            evidence=tuple(evidence),
            thresholds=tuple(thresholds),
            pass_mark_percent=pass_mark_percent,
            assessments_used=tuple(assessments),
            caveats=tuple(caveats),
        ),
    )


def _movement_evidence(
    before: Measure, after: Measure, change: Measure, *, before_name: str, after_name: str
) -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(name=before_name, value=str(before.value), unit=before.unit),
        EvidenceItem(name=after_name, value=str(after.value), unit=after.unit),
        EvidenceItem(
            name="Change",
            value=str(change.value),
            unit=Unit.PERCENTAGE_POINTS,
            note=f"over {change.n} students",
        ),
    )


# ------------------------------------------------------------------- cohort movement


def _class_mean_insight(
    analysis: ChangeAnalysis, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§7/§8. The class average, between the two most recent published assessments."""
    change = analysis.class_mean_change
    comparison = analysis.comparison
    if not change.is_ok or change.value is None or comparison is None:
        return None
    if comparison.from_mean is None or comparison.to_mean is None:
        return None
    if not comparison.from_mean.is_ok or not comparison.to_mean.is_ok:
        return None
    from_mean = comparison.from_mean.value
    to_mean = comparison.to_mean.value

    moved = _direction(change.value)
    text = (
        f"Class average {moved} from {from_mean}% to {to_mean}% "
        f"({_signed(change.value)} percentage points) between "
        f"{comparison.from_assessment.code} and {comparison.to_assessment.code}, "
        f"across the {comparison.intersection_n} students assessed in both."
        if change.value != 0
        else (
            f"Class average remained unchanged at {to_mean}% between "
            f"{comparison.from_assessment.code} and {comparison.to_assessment.code}, "
            f"across the {comparison.intersection_n} students assessed in both."
        )
    )
    return _insight(
        code=InsightCode.CLASS_MEAN_MOVED,
        offering_id=analysis.offering_id,
        scope=InsightScope.OFFERING,
        text=text,
        formula="mean over students assessed in both assessments, latest minus earlier",
        evidence=(
            EvidenceItem(
                name=f"{comparison.from_assessment.code} mean",
                value=str(from_mean),
                unit=Unit.PERCENT,
                note="over the students assessed in both",
            ),
            EvidenceItem(
                name=f"{comparison.to_assessment.code} mean",
                value=str(to_mean),
                unit=Unit.PERCENT,
                note="over the students assessed in both",
            ),
            EvidenceItem(
                name="Change",
                value=str(change.value),
                unit=Unit.PERCENTAGE_POINTS,
            ),
            EvidenceItem(
                name="Students compared",
                value=str(comparison.intersection_n),
                unit=Unit.COUNT,
            ),
        ),
        assessments=(comparison.from_assessment.code, comparison.to_assessment.code),
        caveats=comparison.explanation.caveats,
        generated_at=generated_at,
    )


def _signed(value: Decimal) -> str:
    return f"+{value}" if value > 0 else str(value)


def _pass_rate_insight(
    analysis: ChangeAnalysis, pass_mark: Decimal, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§9. The pass rate over the same paired students, against the offering's pass mark."""
    change = analysis.pass_percent_change
    comparison = analysis.comparison
    if not change.is_ok or change.value is None or comparison is None:
        return None

    moved = _direction(change.value)
    text = (
        f"Pass rate {moved} by {abs(change.value)} percentage points between "
        f"{comparison.from_assessment.code} and {comparison.to_assessment.code}, measured "
        f"against the {pass_mark}% pass mark over the {comparison.intersection_n} students "
        "assessed in both."
        if change.value != 0
        else (
            f"Pass rate remained unchanged between {comparison.from_assessment.code} and "
            f"{comparison.to_assessment.code}, measured against the {pass_mark}% pass mark "
            f"over the {comparison.intersection_n} students assessed in both."
        )
    )
    return _insight(
        code=InsightCode.CLASS_PASS_RATE_MOVED,
        offering_id=analysis.offering_id,
        scope=InsightScope.OFFERING,
        text=text,
        formula="share at or above the pass mark, over students assessed in both",
        evidence=(
            EvidenceItem(
                name="Pass-rate change", value=str(change.value), unit=Unit.PERCENTAGE_POINTS
            ),
            EvidenceItem(
                name="Students compared",
                value=str(comparison.intersection_n),
                unit=Unit.COUNT,
            ),
        ),
        pass_mark_percent=pass_mark,
        assessments=(comparison.from_assessment.code, comparison.to_assessment.code),
        caveats=comparison.explanation.caveats,
        generated_at=generated_at,
    )


def _completion_insight(
    analysis: ChangeAnalysis, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§17. Participation between the two assessments, over the whole cohort."""
    comparison = analysis.comparison
    if comparison is None:
        return None
    change = comparison.completion_change
    if not change.is_ok or change.value is None:
        return None

    moved = _direction(change.value)
    text = (
        f"Completion {moved} by {abs(change.value)} percentage points between "
        f"{comparison.from_assessment.code} and {comparison.to_assessment.code}."
        if change.value != 0
        else (
            f"Completion remained unchanged between {comparison.from_assessment.code} and "
            f"{comparison.to_assessment.code}."
        )
    )
    return _insight(
        code=InsightCode.CLASS_COMPLETION_MOVED,
        offering_id=analysis.offering_id,
        scope=InsightScope.OFFERING,
        text=text,
        formula="assessed of those required, over the whole cohort; exempt excluded",
        evidence=(
            EvidenceItem(
                name="Completion change", value=str(change.value), unit=Unit.PERCENTAGE_POINTS
            ),
            EvidenceItem(
                name="Required sittings",
                value=str(change.n),
                unit=Unit.COUNT,
                note="exempt assessments are not required",
            ),
        ),
        assessments=(comparison.from_assessment.code, comparison.to_assessment.code),
        caveats=comparison.explanation.caveats,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------- rule clusters

_CLUSTER_CODES: dict[AttentionRuleCode, InsightCode] = {
    AttentionRuleCode.R3_REPEATED_LOW: InsightCode.REPEATED_LOW_CLUSTER,
    AttentionRuleCode.R4_SHARP_DECLINE: InsightCode.DECLINE_CLUSTER,
    AttentionRuleCode.R5_DECLINING_TREND: InsightCode.DECLINING_TREND_CLUSTER,
    AttentionRuleCode.R6_LOW_COMPLETION: InsightCode.COHORT_COMPLETION_LOW,
    AttentionRuleCode.R7_BORDERLINE: InsightCode.BORDERLINE_CLUSTER,
}
"""Which rule's student count each cluster insight reports. §10-14 of the F21 brief.

R1 and R2 have no cluster insight: "2 students have a low course score" restates the
attention summary without adding a fact a teacher can act on differently, and §4 warns
against multiplying insights.
"""


def _cluster_text(
    rule: AttentionRuleCode, number: int, thresholds: ThresholdSet, flag: AttentionFlag | None
) -> str:
    """One sentence per cluster, quoting the threshold the rule actually used."""
    pass_mark = thresholds.pass_mark_percent
    match rule:
        case AttentionRuleCode.R3_REPEATED_LOW:
            run = thresholds.count(ThresholdKey.REPEATED_LOW_COUNT)
            return (
                f"{_students(number)} {_were(number)} below the {pass_mark}% pass mark "
                f"in at least "
                f"{run} consecutive completed assessments."
            )
        case AttentionRuleCode.R4_SHARP_DECLINE:
            drop = thresholds.value(ThresholdKey.DECLINE_DROP_PP)
            return (
                f"{_students(number)} had a decline of at least {drop} percentage points "
                "from their earlier mean."
            )
        case AttentionRuleCode.R5_DECLINING_TREND:
            delta = thresholds.value(ThresholdKey.TREND_DELTA_PP)
            return (
                f"{_students(number)} had a declining trend of at least {delta} percentage "
                "points per assessment."
            )
        case AttentionRuleCode.R6_LOW_COMPLETION:
            limit = thresholds.value(ThresholdKey.LOW_COMPLETION_PERCENT)
            return f"{_students(number)} had completion below {limit}%."
        case AttentionRuleCode.R7_BORDERLINE:
            band = thresholds.value(ThresholdKey.BORDERLINE_BAND_PP)
            return (
                f"{_students(number)} {_are(number)} within {band} percentage points of the "
                f"{pass_mark}% pass mark."
            )
    del flag
    raise ValueError(f"no cluster wording for {rule}")


def _cluster_insights(
    attentions: Sequence[StudentAttention],
    offering_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    generated_at: datetime,
) -> list[GeneratedInsight]:
    """§10-14. One insight per rule that fired for at least one student.

    The counts are the attention engine's own — the rules were evaluated once, with their
    thresholds and provenance, and this reports what they found.
    """
    counts = rule_counts(attentions)
    by_rule: dict[AttentionRuleCode, list[StudentAttention]] = {}
    for attention in attentions:
        for flag in attention.flags:
            by_rule.setdefault(flag.rule_code, []).append(attention)

    produced: list[GeneratedInsight] = []
    for rule, code in _CLUSTER_CODES.items():
        number = counts.get(rule, 0)
        if not number:
            continue  # nothing fired: no insight, rather than "0 students…"
        holders = by_rule.get(rule, [])
        example = next(
            (flag for holder in holders for flag in holder.flags if flag.rule_code is rule),
            None,
        )
        rule_thresholds = (example.threshold,) if example is not None and example.threshold else ()
        produced.append(
            _insight(
                code=code,
                offering_id=offering_id,
                scope=InsightScope.OFFERING,
                text=_cluster_text(rule, number, thresholds, example),
                formula=f"count of students for whom {rule.value} fired",
                evidence=(
                    EvidenceItem(name="Students", value=str(number), unit=Unit.COUNT),
                    EvidenceItem(
                        name="Rule",
                        value=rule.value,
                        note=ATTENTION_RULES[rule].title,
                    ),
                    *(
                        (
                            EvidenceItem(
                                name="Threshold",
                                value=str(example.threshold.value),
                                note=f"source: {example.threshold.source.value}",
                            ),
                        )
                        if example is not None and example.threshold
                        else ()
                    ),
                    EvidenceItem(
                        name="Students affected",
                        value=", ".join(h.student.register_no for h in holders),
                    ),
                ),
                thresholds=rule_thresholds,
                pass_mark_percent=(
                    thresholds.pass_mark_percent if ATTENTION_RULES[rule].uses_pass_mark else None
                ),
                generated_at=generated_at,
            )
        )
    return produced


def _improvement_insight(
    analysis: ChangeAnalysis, thresholds: ThresholdSet, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§18. Students who rose by the configured margin between the two assessments."""
    group = next((g for g in analysis.groups if "Improved" in g.label), None)
    if group is None or not group.count or analysis.comparison is None:
        return None
    delta = thresholds.value(ThresholdKey.IMPROVEMENT_DELTA_PP)
    comparison = analysis.comparison
    return _insight(
        code=InsightCode.IMPROVEMENT_CLUSTER,
        offering_id=analysis.offering_id,
        scope=InsightScope.OFFERING,
        text=(
            f"{_students(group.count)} improved by at least {delta} percentage points "
            f"between {comparison.from_assessment.code} and {comparison.to_assessment.code}."
        ),
        formula="count of paired students whose change is at or above improvement_delta_pp",
        evidence=(
            EvidenceItem(name="Students", value=str(group.count), unit=Unit.COUNT),
            EvidenceItem(
                name="Students affected",
                value=", ".join(s.register_no for s in group.students),
            ),
            EvidenceItem(
                name="Threshold",
                value=str(delta),
                note=f"source: {thresholds.source(ThresholdKey.IMPROVEMENT_DELTA_PP).value}",
            ),
        ),
        thresholds=(thresholds.resolved[ThresholdKey.IMPROVEMENT_DELTA_PP],),
        assessments=(comparison.from_assessment.code, comparison.to_assessment.code),
        caveats=comparison.explanation.caveats,
        generated_at=generated_at,
    )


# ----------------------------------------------------------- attention and distribution


def _attention_insight(
    attentions: Sequence[StudentAttention], offering_id: uuid.UUID, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§15. How many students hold flags, and how many the escalation rule lists.

    Produces nothing when nothing fired: §15 forbids a misleading warning, and a positive
    "all clear" is a stronger claim than this layer should make on its own.
    """
    flagged = flagged_students(attentions)
    if not flagged:
        return None
    requiring = students_requiring_attention(attentions)
    return _insight(
        code=InsightCode.ATTENTION_SUMMARY,
        offering_id=offering_id,
        scope=InsightScope.OFFERING,
        text=(
            f"{_students(len(flagged))} have one or more attention flags, of whom "
            f"{len(requiring)} meet the escalation rule of any High rule or two Medium rules."
        ),
        formula="students holding at least one flag; escalation per the R1-R7 registry",
        evidence=(
            EvidenceItem(name="Flagged students", value=str(len(flagged)), unit=Unit.COUNT),
            EvidenceItem(name="Requiring attention", value=str(len(requiring)), unit=Unit.COUNT),
            EvidenceItem(
                name="Students affected",
                value=", ".join(s.register_no for s in flagged),
            ),
        ),
        generated_at=generated_at,
    )


def _distribution_insight(
    health: ClassHealth, *, generated_at: datetime
) -> GeneratedInsight | None:
    """§16. The band holding the most students, from the existing ten-bin distribution.

    Silent on a tie: naming one of two equally sized bands would be a choice the data does
    not make.
    """
    distribution = health.course_score_distribution
    if distribution is None or not distribution.n:
        return None
    occupied = [b for b in distribution.bins if b.count]
    if not occupied:
        return None
    largest = max(b.count for b in occupied)
    leaders = [b for b in occupied if b.count == largest]
    if len(leaders) != 1:
        return None
    band = leaders[0]
    return _insight(
        code=InsightCode.DISTRIBUTION_PEAK,
        offering_id=health.offering_id,
        scope=InsightScope.OFFERING,
        text=(
            f"The largest group of students by course score is the {band.lower}-{band.upper}% "
            f"band, with {_students(band.count)} of the {distribution.n} scored."
        ),
        formula="largest of the ten fixed bands of the course-score distribution",
        evidence=(
            EvidenceItem(name="Band", value=f"{band.lower}-{band.upper}%"),
            EvidenceItem(name="Students", value=str(band.count), unit=Unit.COUNT),
            EvidenceItem(name="Scored students", value=str(distribution.n), unit=Unit.COUNT),
            EvidenceItem(name="Share", value=str(band.share_percent), unit=Unit.PERCENT),
        ),
        generated_at=generated_at,
    )


# --------------------------------------------------------------------------- students


def student_insights(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    profile: StudentPerformanceProfile | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[GeneratedInsight, ...]:
    """§21. What changed for one student, observed and never explained.

    Each sentence states a measurement. None of them says *why*: this system has no data
    about effort, attendance, health or circumstance, and a sentence that guessed would be
    fiction with a number attached.
    """
    stamp = generated_at or datetime.now(UTC)
    built = profile or student_profile(
        snapshot, student_id, thresholds, active_only=active_only, generated_at=stamp
    )
    produced: list[GeneratedInsight] = []

    change = built.change_from_previous
    if change.is_ok and change.value is not None and built.latest and built.previous:
        moved = _direction(change.value)
        text = (
            f"Latest assessment {built.latest.assessment.code} {moved} by "
            f"{abs(change.value)} percentage points against "
            f"{built.previous.assessment.code}."
            if change.value != 0
            else (
                f"Latest assessment {built.latest.assessment.code} was unchanged against "
                f"{built.previous.assessment.code}."
            )
        )
        produced.append(
            _insight(
                code=InsightCode.STUDENT_LATEST_CHANGE,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=text,
                formula="latest completed percentage minus the previous completed one",
                evidence=(
                    EvidenceItem(
                        name=built.previous.assessment.code,
                        value=str(built.previous.percentage.value),
                        unit=Unit.PERCENT,
                    ),
                    EvidenceItem(
                        name=built.latest.assessment.code,
                        value=str(built.latest.percentage.value),
                        unit=Unit.PERCENT,
                    ),
                    EvidenceItem(
                        name="Change", value=str(change.value), unit=Unit.PERCENTAGE_POINTS
                    ),
                ),
                assessments=(
                    built.previous.assessment.code,
                    built.latest.assessment.code,
                ),
                generated_at=stamp,
            )
        )

    trend = built.trend
    if trend.label.is_ok and trend.slope.value is not None:
        produced.append(
            _insight(
                code=InsightCode.STUDENT_TREND,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=(
                    f"Trend across {trend.slope.n} completed assessments is "
                    f"{trend.label.value}, at {trend.slope.value} percentage points per "
                    "assessment."
                ),
                formula="two-point difference below three points, least-squares slope above",
                evidence=(
                    *(
                        EvidenceItem(name=code, value=str(value), unit=Unit.PERCENT)
                        for code, value in zip(
                            trend.points_used, trend.percentages_used, strict=True
                        )
                    ),
                    EvidenceItem(
                        name="Threshold",
                        value=str(trend.threshold.value),
                        note=f"source: {trend.threshold.source.value}",
                    ),
                ),
                thresholds=(trend.threshold,),
                assessments=trend.points_used,
                caveats=trend.explanation.caveats,
                generated_at=stamp,
            )
        )

    decline = built.finding(StudentFindingCode.SHARP_DECLINE)
    if decline is not None and decline.detected and decline.measure.value is not None:
        produced.append(
            _insight(
                code=InsightCode.STUDENT_SHARP_DECLINE,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=(
                    f"Latest completed assessment is {abs(decline.measure.value)} percentage "
                    f"points below the mean of the earlier ones, at or beyond the configured "
                    f"{thresholds.value(ThresholdKey.DECLINE_DROP_PP)} percentage points."
                ),
                formula="latest minus the mean of earlier completed assessments",
                evidence=decline.explanation.evidence,
                thresholds=(thresholds.resolved[ThresholdKey.DECLINE_DROP_PP],),
                generated_at=stamp,
            )
        )

    repeated = built.finding(StudentFindingCode.REPEATED_LOW)
    if repeated is not None and repeated.detected and repeated.measure.value is not None:
        produced.append(
            _insight(
                code=InsightCode.STUDENT_REPEATED_LOW,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=(
                    f"Below the {thresholds.pass_mark_percent}% pass mark in "
                    f"{int(repeated.measure.value)} consecutive completed assessments."
                ),
                formula="trailing run of completed assessments below the pass mark",
                evidence=repeated.explanation.evidence,
                thresholds=(thresholds.resolved[ThresholdKey.REPEATED_LOW_COUNT],),
                pass_mark_percent=thresholds.pass_mark_percent,
                generated_at=stamp,
            )
        )

    from app.modules.analytics.core.student import is_borderline

    series_borderline = is_borderline(
        _series(snapshot, student_id, active_only=active_only), thresholds
    )
    score = built.history.weighted_course_score
    if series_borderline and score.is_ok and score.value is not None:
        band = thresholds.value(ThresholdKey.BORDERLINE_BAND_PP)
        produced.append(
            _insight(
                code=InsightCode.STUDENT_BORDERLINE,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=(
                    f"Course score {score.value}% is within {band} percentage points of the "
                    f"{thresholds.pass_mark_percent}% pass mark."
                ),
                formula="absolute distance of the weighted course score from the pass mark",
                evidence=(
                    EvidenceItem(
                        name="Weighted course score",
                        value=str(score.value),
                        unit=Unit.PERCENT,
                        note=f"over {score.n} completed",
                    ),
                    EvidenceItem(
                        name="Band",
                        value=str(band),
                        note=f"source: {thresholds.source(ThresholdKey.BORDERLINE_BAND_PP).value}",
                    ),
                ),
                thresholds=(thresholds.resolved[ThresholdKey.BORDERLINE_BAND_PP],),
                pass_mark_percent=thresholds.pass_mark_percent,
                generated_at=stamp,
            )
        )

    completion = built.history.completion_percent
    limit = thresholds.value(ThresholdKey.LOW_COMPLETION_PERCENT)
    completion_source = thresholds.source(ThresholdKey.LOW_COMPLETION_PERCENT).value
    if completion.is_ok and completion.value is not None and completion.value < limit:
        produced.append(
            _insight(
                code=InsightCode.STUDENT_COMPLETION_LOW,
                offering_id=built.offering_id,
                scope=InsightScope.STUDENT,
                subject_id=student_id,
                text=(
                    f"Completion is {completion.value}%, below the configured {limit}%. "
                    f"Assessed in {built.history.coverage.assessed} of {completion.n} "
                    "required assessments."
                ),
                formula="assessed of those required; exempt assessments are not required",
                evidence=(
                    EvidenceItem(name="Completion", value=str(completion.value), unit=Unit.PERCENT),
                    EvidenceItem(
                        name="Assessed",
                        value=str(built.history.coverage.assessed),
                        unit=Unit.COUNT,
                    ),
                    EvidenceItem(name="Required", value=str(completion.n), unit=Unit.COUNT),
                    EvidenceItem(
                        name="Threshold",
                        value=str(limit),
                        note=f"source: {completion_source}",
                    ),
                ),
                thresholds=(thresholds.resolved[ThresholdKey.LOW_COMPLETION_PERCENT],),
                generated_at=stamp,
            )
        )

    return order_insights(produced)


def _series(snapshot: OfferingSnapshot, student_id: uuid.UUID, *, active_only: bool):  # noqa: ANN202
    from app.modules.analytics.core.policy import build_student_series

    del active_only
    return build_student_series(snapshot, student_id)


# ----------------------------------------------------------------------- interventions


def intervention_insights(
    outcomes: Sequence[InterventionOutcome], *, generated_at: datetime | None = None
) -> tuple[GeneratedInsight, ...]:
    """§20. What was observed after each intervention, with the caveat attached.

    Nothing here claims the action worked, and the contract enforces it: the sentence is
    screened for causal wording, and the observational caveat is mandatory on the insight as
    it is on the outcome it came from.
    """
    stamp = generated_at or datetime.now(UTC)
    produced: list[GeneratedInsight] = []
    for outcome in outcomes:
        change = outcome.target.change
        if not change.is_ok or change.value is None:
            continue  # §23: nothing to report is not a report of nothing

        moved = _direction(change.value)
        sentence = (
            f"Targeted students' average {moved} by {abs(change.value)} percentage points "
            f"after the intervention"
            if change.value != 0
            else "Targeted students' average was unchanged after the intervention"
        )
        peers = outcome.peers.change
        net = outcome.net_change
        if peers.is_ok and peers.value is not None and net.is_ok and net.value is not None:
            sentence += (
                f", while the comparison group {_direction(peers.value)} by "
                f"{abs(peers.value)} percentage points; the observed difference in change "
                f"was {_signed(net.value)} percentage points."
            )
        else:
            sentence += (
                f". No comparison group was available: {peers.reason or 'insufficient data'}."
            )

        produced.append(
            _insight(
                code=InsightCode.INTERVENTION_OBSERVED_CHANGE,
                offering_id=outcome.offering_id,
                scope=InsightScope.INTERVENTION,
                subject_id=outcome.intervention_id,
                text=sentence,
                formula="group change = mean(post) - mean(pre); net = target minus peers",
                evidence=(
                    EvidenceItem(
                        name="Target before",
                        value=str(outcome.target.pre_mean.value),
                        unit=Unit.PERCENT,
                        note=f"{outcome.target.n} students assessed in both windows",
                    ),
                    EvidenceItem(
                        name="Target after",
                        value=str(outcome.target.post_mean.value),
                        unit=Unit.PERCENT,
                    ),
                    EvidenceItem(
                        name="Target change",
                        value=str(change.value),
                        unit=Unit.PERCENTAGE_POINTS,
                    ),
                    *(
                        (
                            EvidenceItem(
                                name="Comparison change",
                                value=str(peers.value),
                                unit=Unit.PERCENTAGE_POINTS,
                                note=f"{outcome.peers.n} students",
                            ),
                            EvidenceItem(
                                name="Observed difference in change",
                                value=str(net.value),
                                unit=Unit.PERCENTAGE_POINTS,
                            ),
                        )
                        if peers.is_ok and net.is_ok
                        else ()
                    ),
                ),
                assessments=(
                    *[a.code for a in outcome.baseline_assessments],
                    *([outcome.follow_up_assessment.code] if outcome.follow_up_assessment else []),
                ),
                caveats=(OBSERVATIONAL_CAVEAT,),
                generated_at=stamp,
            )
        )
    return tuple(produced)


# ----------------------------------------------------------------------- composition


def order_insights(insights: Sequence[GeneratedInsight]) -> tuple[GeneratedInsight, ...]:
    """Presentation order, and duplicate suppression.

    Sorted by :data:`INSIGHT_ORDER`, then by subject so two students' insights of the same
    code are stably ordered. One insight per (code, subject): a fact reached by two paths is
    one fact, while two different facts — a class mean and a pass rate both falling — are
    two insights and both survive.
    """
    seen: set[tuple[InsightCode, uuid.UUID | None]] = set()
    unique: list[GeneratedInsight] = []
    for insight in insights:
        key = (insight.code, insight.subject_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(insight)
    return tuple(sorted(unique, key=lambda i: (_ORDER[i.code], str(i.subject_id or ""))))


def class_insights(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[GeneratedInsight, ...]:
    """Every cohort-level insight the data supports, in presentation order.

    Analytics is computed once here and shared between the rules, rather than each rule
    rebuilding the cohort.
    """
    stamp = generated_at or datetime.now(UTC)
    if latest_published(snapshot) is None:
        return ()

    health = class_health(snapshot, thresholds, active_only=active_only, generated_at=stamp)
    attentions = cohort_attention(snapshot, thresholds, active_only=active_only, generated_at=stamp)
    analysis = change_analysis(snapshot, thresholds, active_only=active_only, generated_at=stamp)

    produced: list[GeneratedInsight | None] = [
        _class_mean_insight(analysis, generated_at=stamp),
        _pass_rate_insight(analysis, snapshot.pass_mark_percent, generated_at=stamp),
        _completion_insight(analysis, generated_at=stamp),
        _improvement_insight(analysis, thresholds, generated_at=stamp),
        _attention_insight(attentions, snapshot.offering_id, generated_at=stamp),
        _distribution_insight(health, generated_at=stamp),
    ]
    produced.extend(
        _cluster_insights(attentions, snapshot.offering_id, thresholds, generated_at=stamp)
    )
    return order_insights([insight for insight in produced if insight is not None])


def offering_insights(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    interventions: Sequence[Intervention] = (),
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[GeneratedInsight, ...]:
    """Cohort insights plus any intervention outcomes, in one ordered list."""
    stamp = generated_at or datetime.now(UTC)
    produced = list(
        class_insights(snapshot, thresholds, active_only=active_only, generated_at=stamp)
    )
    if interventions:
        outcomes = intervention_outcomes(
            snapshot, interventions, thresholds, active_only=active_only, generated_at=stamp
        )
        produced.extend(intervention_insights(outcomes, generated_at=stamp))
    return order_insights(produced)
