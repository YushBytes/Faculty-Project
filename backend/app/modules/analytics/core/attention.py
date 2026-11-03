"""F18: the R1-R7 attention engine — which students need a teacher's time, and why.

This module **evaluates** the rules that :mod:`app.modules.analytics.core.rules` declares.
That file is contract C9 and is frozen; nothing here may change a code, a severity or the
escalation predicate.

It computes no statistics. Every rule reads a fact a Phase 2 function already owns:

=====  ==============================================  =================================
rule   fires when                                      fact it reads
=====  ==============================================  =================================
R1     ``W < low_performance_percent``                 ``student.weighted_course_score``
R2     latest completed ``P < pass_mark``              ``series.latest_assessed``
R3     trailing run ``>= repeated_low_count``          ``student.repeated_low_run``
R4     ``drop <= -decline_drop_pp``                    ``student.decline_against_earlier_mean``
R5     trend classified Declining                      ``trends.student_trend``
R6     ``completion < low_completion_percent``         ``student.completion_percent``
R7     ``|W - pass_mark| <= borderline_band_pp``       ``student.pass_mark_distance``
=====  ==============================================  =================================

so a flag and a student's profile can never disagree about a number — a test asserts each
flag's ``actual`` equals the Phase 2/3 measure it came from.

Three rules the code enforces rather than trusts.

*A rule that cannot be evaluated does not fire.* If the fact behind it is insufficient data
— one completed assessment for a decline, nothing sat at all for a course score — the rule
returns ``None``. It never fires "just in case", and it never reports a fabricated zero.
The contract refuses a flag whose ``actual`` is not computable.

*Every fired rule is kept.* A student who is low, failed the latest paper and has been below
the mark three times running holds three flags. Each names a different fact; collapsing them
would throw away exactly what a teacher needs.

*R1 is strict where the Persistently Low segment is inclusive.* A weighted course score of
exactly ``low_performance_percent`` segments as Persistently Low (F17 is ``<=``) and raises
no R1 flag (C9 says "below"). Both are as specified, the difference is deliberate, and
``tests/analytics/test_attention.py`` pins it so it cannot be "tidied up" later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.analytics.core.contracts import OfferingSnapshot, StudentRef
from app.modules.analytics.core.outputs import (
    SEVERITY_ORDER,
    AttentionFlag,
    EvidenceItem,
    Explanation,
    StudentAttention,
    highest_severity,
)
from app.modules.analytics.core.policy import DerivedState, StudentSeries, build_all_series
from app.modules.analytics.core.results import Measure, Unit, measure
from app.modules.analytics.core.rules import (
    ATTENTION_RULES,
    AttentionRule,
    AttentionRuleCode,
    FlagSeverity,
    requires_attention,
)
from app.modules.analytics.core.student import (
    completion_percent,
    decline_against_earlier_mean,
    pass_mark_distance,
    prior_average,
    repeated_low_run,
    weighted_course_score,
)
from app.modules.analytics.core.thresholds import ResolvedThreshold, ThresholdKey, ThresholdSet
from app.modules.analytics.core.trends import student_trend
from app.modules.analytics.core.vocabulary import TrendLabel

ATTENTION_NOT_EVALUATED = (
    "Attention was not evaluated in this build, so no student is reported as requiring it "
    "and no flags are counted. This is not a finding that none do."
)
"""The wording for the unevaluated state, so it reads the same wherever it appears."""


def _codes(points: Iterable[object]) -> tuple[str, ...]:
    return tuple(point.assessment_code for point in points)  # type: ignore[attr-defined]


def _flag(
    rule: AttentionRule,
    series: StudentSeries,
    *,
    actual: Measure,
    threshold: ResolvedThreshold | None,
    pass_mark_percent: Decimal | None,
    reference_assessments: Sequence[str],
    message: str,
    formula: str,
    evidence: Sequence[EvidenceItem],
    generated_at: datetime,
) -> AttentionFlag:
    """Assemble one flag. Every caller goes through here, so no flag can skip its evidence."""
    return AttentionFlag(
        generated_at=generated_at,
        offering_id=series.offering_id,
        student_id=series.student_id,
        rule_code=rule.code,
        severity=rule.severity,
        actual=actual,
        threshold=threshold,
        pass_mark_percent=pass_mark_percent,
        reference_assessments=tuple(reference_assessments),
        message=message,
        explanation=Explanation(
            narrative=message,
            formula=formula,
            evidence=tuple(evidence),
            thresholds=(threshold,) if threshold is not None else (),
            pass_mark_percent=pass_mark_percent,
            assessments_used=tuple(reference_assessments),
        ),
    )


def _series_evidence(series: StudentSeries) -> tuple[EvidenceItem, ...]:
    return tuple(
        EvidenceItem(name=point.assessment_code, value=str(point.percentage), unit=Unit.PERCENT)
        for point in series.assessed_points
    )


# ------------------------------------------------------------------------- the seven rules


def _r1_low_performance(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R1_LOW_PERFORMANCE]
    threshold = thresholds.resolved[ThresholdKey.LOW_PERFORMANCE_PERCENT]
    score = weighted_course_score(series)
    if not score.is_ok or score.value is None:
        return None
    if not score.value < threshold.value:
        return None

    completed = _codes(series.assessed_points)
    return _flag(
        rule,
        series,
        actual=score,
        threshold=threshold,
        pass_mark_percent=None,
        reference_assessments=completed,
        message=(
            f"Weighted course score {score.value}% across {score.n} completed "
            f"{'assessment' if score.n == 1 else 'assessments'} ({', '.join(completed)}). "
            f"Configured low-performance threshold {threshold.value}%."
        ),
        formula="W = sum(P_a * w_a) / sum(w_a) over completed assessments; W < threshold",
        evidence=_series_evidence(series),
        generated_at=stamp,
    )


def _r2_failed_latest(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R2_FAILED_LATEST]
    pass_mark = thresholds.pass_mark_percent
    latest = series.latest_assessed
    if latest is None or latest.percentage is None:
        return None
    if not latest.percentage < pass_mark:
        return None

    return _flag(
        rule,
        series,
        actual=measure(latest.percentage, unit=Unit.PERCENT, n=1, minimum_n=1),
        threshold=None,
        pass_mark_percent=pass_mark,
        reference_assessments=(latest.assessment_code,),
        message=(
            f"Latest completed assessment {latest.assessment_code} {latest.percentage}%, "
            f"below the offering's pass mark of {pass_mark}%."
        ),
        formula="P of the most recent completed assessment < pass_mark_percent",
        evidence=(
            EvidenceItem(
                name=latest.assessment_code,
                value=str(latest.percentage),
                unit=Unit.PERCENT,
                note=f"{latest.score} of {latest.max_marks} marks",
            ),
        ),
        generated_at=stamp,
    )


def _r3_repeated_low(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R3_REPEATED_LOW]
    threshold = thresholds.resolved[ThresholdKey.REPEATED_LOW_COUNT]
    pass_mark = thresholds.pass_mark_percent
    run = repeated_low_run(series, thresholds)
    if not run.is_ok or run.value is None:
        return None
    if not run.value >= threshold.value:
        return None

    length = int(run.value)
    involved = series.assessed_points[len(series.assessed_points) - length :]
    listed = ", ".join(f"{p.assessment_code} {p.percentage}%" for p in involved)
    return _flag(
        rule,
        series,
        actual=run,
        threshold=threshold,
        pass_mark_percent=pass_mark,
        reference_assessments=_codes(involved),
        message=(
            f"Below the {pass_mark}% pass mark in {length} consecutive completed "
            f"assessments ({listed}). Configured run length {int(threshold.value)}."
        ),
        formula="count back from the latest completed assessment while P < pass_mark",
        evidence=tuple(
            EvidenceItem(name=p.assessment_code, value=str(p.percentage), unit=Unit.PERCENT)
            for p in involved
        ),
        generated_at=stamp,
    )


def _r4_sharp_decline(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R4_SHARP_DECLINE]
    threshold = thresholds.resolved[ThresholdKey.DECLINE_DROP_PP]
    drop = decline_against_earlier_mean(series, thresholds)
    if not drop.is_ok or drop.value is None:
        return None
    if not drop.value <= -threshold.value:
        return None

    baseline = prior_average(series, thresholds)
    latest = series.assessed_points[-1]
    earlier = _codes(series.assessed_points[:-1])
    return _flag(
        rule,
        series,
        actual=drop,
        threshold=threshold,
        pass_mark_percent=None,
        reference_assessments=_codes(series.assessed_points),
        message=(
            f"Latest completed assessment {latest.assessment_code} {latest.percentage}% "
            f"against a mean of {baseline.value}% across {baseline.n} earlier "
            f"{'assessment' if baseline.n == 1 else 'assessments'} "
            f"({', '.join(earlier)}): {drop.value} pp. "
            f"Configured drop {threshold.value} pp."
        ),
        formula="drop = P_latest - mean(P over earlier completed assessments)",
        evidence=(
            *_series_evidence(series),
            EvidenceItem(
                name="Mean of earlier assessments",
                value=str(baseline.value),
                unit=Unit.PERCENT,
                note=f"over {baseline.n} completed, excluding the latest",
            ),
        ),
        generated_at=stamp,
    )


def _r5_declining_trend(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R5_DECLINING_TREND]
    threshold = thresholds.resolved[ThresholdKey.TREND_DELTA_PP]
    trend = student_trend(series, thresholds, generated_at=stamp)
    if not trend.label.is_ok or trend.slope.value is None:
        return None
    if trend.label.value != TrendLabel.DECLINING.value:
        return None

    two_point = trend.method is not None and trend.method.value == "two_point_delta"
    how = (
        "Difference between the two completed assessments"
        if two_point
        else f"Least-squares slope across {trend.slope.n} completed assessments"
    )
    listed = ", ".join(
        f"{code} {value}%"
        for code, value in zip(trend.points_used, trend.percentages_used, strict=True)
    )
    return _flag(
        rule,
        series,
        actual=trend.slope,
        threshold=threshold,
        pass_mark_percent=None,
        reference_assessments=trend.points_used,
        message=(
            f"{how}: {trend.slope.value} pp per assessment ({listed}). "
            f"Configured declining threshold {threshold.value} pp per assessment."
        ),
        formula="n == 2 -> P[-1] - P[-2]; n >= 3 -> least-squares slope; slope <= -threshold",
        evidence=(
            *_series_evidence(series),
            EvidenceItem(
                name="Method",
                value=trend.method.value if trend.method else "n/a",
                note="how the slope was produced",
            ),
        ),
        generated_at=stamp,
    )


def _r6_low_completion(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R6_LOW_COMPLETION]
    threshold = thresholds.resolved[ThresholdKey.LOW_COMPLETION_PERCENT]
    completion = completion_percent(series)
    if not completion.is_ok or completion.value is None:
        return None
    if not completion.value < threshold.value:
        return None

    missed = tuple(
        point
        for point in series.points
        if point.state in (DerivedState.ABSENT, DerivedState.MISSING)
    )
    listed = ", ".join(f"{p.assessment_code} ({p.state.value})" for p in missed)
    return _flag(
        rule,
        series,
        actual=completion,
        threshold=threshold,
        pass_mark_percent=None,
        reference_assessments=_codes(missed),
        message=(
            f"Assessed in {series.completed_count} of {completion.n} required "
            f"{'assessment' if completion.n == 1 else 'assessments'}: {completion.value}% "
            f"completion. Configured threshold {threshold.value}%. Not completed: {listed}."
        ),
        formula="completion% = 100 * assessed / (assessed + absent + missing); exempt excluded",
        evidence=(
            EvidenceItem(name="Assessed", value=str(series.completed_count), unit=Unit.COUNT),
            EvidenceItem(
                name="Required",
                value=str(completion.n),
                unit=Unit.COUNT,
                note="exempt assessments are not required and leave the denominator",
            ),
            *(
                EvidenceItem(
                    name=p.assessment_code,
                    value=p.state.value,
                    note="not a score of 0",
                )
                for p in missed
            ),
        ),
        generated_at=stamp,
    )


def _r7_borderline(
    series: StudentSeries, thresholds: ThresholdSet, stamp: datetime
) -> AttentionFlag | None:
    rule = ATTENTION_RULES[AttentionRuleCode.R7_BORDERLINE]
    threshold = thresholds.resolved[ThresholdKey.BORDERLINE_BAND_PP]
    pass_mark = thresholds.pass_mark_percent
    distance = pass_mark_distance(series, thresholds)
    if not distance.is_ok or distance.value is None:
        return None
    if not abs(distance.value) <= threshold.value:
        return None

    score = weighted_course_score(series)
    return _flag(
        rule,
        series,
        actual=distance,
        threshold=threshold,
        pass_mark_percent=pass_mark,
        reference_assessments=_codes(series.assessed_points),
        message=(
            f"Weighted course score {score.value}% is {distance.value} pp from the "
            f"{pass_mark}% pass mark, within the configured band of {threshold.value} pp."
        ),
        formula="abs(W - pass_mark_percent) <= borderline_band_pp",
        evidence=(
            EvidenceItem(
                name="Weighted course score",
                value=str(score.value),
                unit=Unit.PERCENT,
                note=f"over {score.n} completed",
            ),
            EvidenceItem(
                name="Distance from the pass mark",
                value=str(distance.value),
                unit=Unit.PERCENTAGE_POINTS,
            ),
        ),
        generated_at=stamp,
    )


_EVALUATORS = {
    AttentionRuleCode.R1_LOW_PERFORMANCE: _r1_low_performance,
    AttentionRuleCode.R2_FAILED_LATEST: _r2_failed_latest,
    AttentionRuleCode.R3_REPEATED_LOW: _r3_repeated_low,
    AttentionRuleCode.R4_SHARP_DECLINE: _r4_sharp_decline,
    AttentionRuleCode.R5_DECLINING_TREND: _r5_declining_trend,
    AttentionRuleCode.R6_LOW_COMPLETION: _r6_low_completion,
    AttentionRuleCode.R7_BORDERLINE: _r7_borderline,
}


def evaluate_rule(
    code: AttentionRuleCode,
    series: StudentSeries,
    thresholds: ThresholdSet,
    *,
    generated_at: datetime | None = None,
) -> AttentionFlag | None:
    """Evaluate one rule against one student's series.

    Returns the flag when the rule fires and ``None`` when it does not — including when the
    fact it needs could not be computed. The two are deliberately the same return: neither
    is a finding, and a flag is the only thing this function ever asserts.
    """
    return _EVALUATORS[code](series, thresholds, generated_at or datetime.now(UTC))


def student_flags(
    series: StudentSeries,
    thresholds: ThresholdSet,
    *,
    generated_at: datetime | None = None,
) -> tuple[AttentionFlag, ...]:
    """Every rule this student fires, in rule-code order."""
    stamp = generated_at or datetime.now(UTC)
    found = (
        evaluate_rule(code, series, thresholds, generated_at=stamp) for code in AttentionRuleCode
    )
    return tuple(flag for flag in found if flag is not None)


def student_attention(
    series: StudentSeries,
    student: StudentRef,
    thresholds: ThresholdSet,
    *,
    generated_at: datetime | None = None,
) -> StudentAttention:
    """**Contract 14.** One student's flags and the escalation verdict over them."""
    stamp = generated_at or datetime.now(UTC)
    flags = student_flags(series, thresholds, generated_at=stamp)
    verdict = requires_attention(flag.severity for flag in flags)

    if flags:
        summary = ", ".join(f"{flag.rule_code.value} ({flag.severity.value})" for flag in flags)
        narrative = f"{len(flags)} {'rule' if len(flags) == 1 else 'rules'} fired: {summary}. " + (
            "That meets the escalation rule — any High rule, or two Medium ones — so "
            "this student is listed as requiring academic attention."
            if verdict
            else "That does not meet the escalation rule (any High rule, or two Medium "
            "ones), so the flags are shown without listing the student as requiring "
            "academic attention."
        )
    else:
        narrative = (
            "No attention rule fired for this student. Every rule was put to the data "
            "available; where a rule needed more completed assessments than this student "
            "has, it was left unjudged rather than counted as passing."
        )

    return StudentAttention(
        generated_at=stamp,
        offering_id=series.offering_id,
        student=student,
        flags=flags,
        requires_attention=verdict,
        highest_severity=highest_severity(flags),
        explanation=Explanation(
            narrative=narrative,
            formula=(
                "requires attention when any High rule fires, or at least two Medium rules; "
                "Low rules are informational alone"
            ),
            evidence=tuple(
                EvidenceItem(
                    name=flag.rule_code.value,
                    value=str(flag.actual.value),
                    unit=flag.actual.unit,
                    note=flag.severity.value,
                )
                for flag in flags
            ),
            thresholds=tuple(flag.threshold for flag in flags if flag.threshold is not None),
            pass_mark_percent=thresholds.pass_mark_percent,
            assessments_used=_codes(series.assessed_points),
        ),
    )


# ------------------------------------------------------------------------ cohort level


def cohort_attention(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[StudentAttention, ...]:
    """Every student's attention, in the snapshot's student order.

    One entry per student, whether or not anything fired: an empty ``flags`` tuple is the
    answer "evaluated, nothing fired", and it must be distinguishable from a student who was
    never looked at.
    """
    stamp = generated_at or datetime.now(UTC)
    students = snapshot.active_students() if active_only else snapshot.students
    series = build_all_series(snapshot, active_only=active_only, published_only=published_only)
    return tuple(
        student_attention(student_series, student, thresholds, generated_at=stamp)
        for student, student_series in zip(students, series, strict=True)
    )


def all_flags(attentions: Sequence[StudentAttention]) -> tuple[AttentionFlag, ...]:
    """Every flag in the cohort, student order then rule order."""
    return tuple(flag for attention in attentions for flag in attention.flags)


def flag_counts(attentions: Sequence[StudentAttention]) -> Mapping[FlagSeverity, int]:
    """How many **flags** carry each severity.

    Flags, not students: one student who is low and repeatedly low holds two High flags, and
    a dashboard that said "1 high" would be describing something else.
    """
    counts: dict[FlagSeverity, int] = {}
    for flag in all_flags(attentions):
        counts[flag.severity] = counts.get(flag.severity, 0) + 1
    return {severity: counts[severity] for severity in SEVERITY_ORDER if severity in counts}


def rule_counts(attentions: Sequence[StudentAttention]) -> Mapping[AttentionRuleCode, int]:
    """How many **students** fired each rule, in rule-code order.

    A rule holds at most one flag per student (the contract enforces it), so this counts
    students and flags alike — it is stated as students because that is what is acted on.
    """
    counts: dict[AttentionRuleCode, int] = {}
    for attention in attentions:
        for code in attention.flag_codes:
            counts[code] = counts.get(code, 0) + 1
    return {code: counts[code] for code in AttentionRuleCode if code in counts}


def flagged_students(attentions: Sequence[StudentAttention]) -> tuple[StudentRef, ...]:
    """The students with at least one flag, each once, in cohort order."""
    return tuple(attention.student for attention in attentions if attention.flags)


def students_requiring_attention(
    attentions: Sequence[StudentAttention],
) -> tuple[StudentRef, ...]:
    """The students the escalation rule lists, each once, in cohort order."""
    return tuple(attention.student for attention in attentions if attention.requires_attention)


def attention_measure(attentions: Sequence[StudentAttention], *, cohort_n: int) -> Measure:
    """How many students require attention, over the cohort they were counted in."""
    return measure(
        Decimal(len(students_requiring_attention(attentions))),
        unit=Unit.COUNT,
        n=cohort_n,
        minimum_n=0,
    )


def new_flags_between(
    snapshot: OfferingSnapshot,
    from_sequence_no: int,
    to_sequence_no: int,
    thresholds: ThresholdSet,
    *,
    active_only: bool = True,
    published_only: bool = True,
    generated_at: datetime | None = None,
) -> tuple[AttentionFlag, ...]:
    """Flags that hold at ``to`` and did not hold at ``from``.

    "New" is a claim about two states, so every rule is evaluated twice — against the series
    truncated at each assessment, the same way "newly declining" is decided in
    :mod:`app.modules.analytics.core.comparison`. A student whose earlier series was too
    short for a rule to be evaluated counts as new when the rule fires now: the flag has
    appeared, which is what the word means.
    """
    from app.modules.analytics.core.policy import series_up_to

    stamp = generated_at or datetime.now(UTC)
    new: list[AttentionFlag] = []
    for series in build_all_series(
        snapshot, active_only=active_only, published_only=published_only
    ):
        before = {
            flag.rule_code
            for flag in student_flags(
                series_up_to(series, from_sequence_no), thresholds, generated_at=stamp
            )
        }
        for flag in student_flags(
            series_up_to(series, to_sequence_no), thresholds, generated_at=stamp
        ):
            if flag.rule_code not in before:
                new.append(flag)
    return tuple(new)
