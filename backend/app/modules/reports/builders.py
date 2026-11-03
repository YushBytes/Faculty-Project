"""Analytics contracts, arranged into reports. No arithmetic lives here.

Every number a report shows was computed by the analytics engine and is carried across
unchanged — a builder reads ``class_health(...)`` or ``cohort_attention(...)`` and lays the
result out in rows. If a builder ever needs a value the engine does not expose, the fix is a
function in ``analytics/core``, not a calculation in this file: a report that computes its
own average is a second analytics engine that will disagree with the first one eventually.

**Ordering is decided here and nowhere else**, so two renderings of the same data are
identical:

===================  =========================================================
students             the snapshot's cohort order (register-number order)
assessments          ``sequence_no``
attention flags      student order, then rule code R1 -> R7
attention rows       students holding flags, in cohort order
interventions        the order the caller supplied
outcomes             intervention order, then student order within each group
===================  =========================================================

Rule order is determinism, not priority: R1 is not more urgent than R2, and §12 of the
reporting brief requires that flags are never re-sorted by severity.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.modules.analytics.core.attention import (
    ATTENTION_NOT_EVALUATED,
    all_flags,
    cohort_attention,
    flag_counts,
    rule_counts,
    students_requiring_attention,
)
from app.modules.analytics.core.class_health import class_health
from app.modules.analytics.core.comparison import change_analysis, compare_assessments
from app.modules.analytics.core.contracts import (
    AssessmentRef,
    Intervention,
    OfferingSnapshot,
    StudentRef,
)
from app.modules.analytics.core.insights import (
    class_insights,
    intervention_insights,
    student_insights,
)
from app.modules.analytics.core.interventions import (
    intervention_outcomes,
    outcome_summary,
)
from app.modules.analytics.core.outputs import (
    OBSERVATIONAL_CAVEAT,
    AttentionFlag,
    DataCoverage,
    GeneratedInsight,
    InterventionOutcome,
)
from app.modules.analytics.core.profile import student_profile
from app.modules.analytics.core.segmentation import student_segment
from app.modules.analytics.core.statistics import assessment_analytics, format_marks
from app.modules.analytics.core.student import student_ref
from app.modules.analytics.core.thresholds import ThresholdSet
from app.modules.reports.model import (
    Cell,
    OfferingIdentity,
    Report,
    ReportKind,
    ReportMetadata,
    Section,
    Table,
    count,
    label,
    measure,
    missing,
    percent,
    text,
)

COVERAGE_HEADERS = ("Assessed", "Absent", "Exempt", "No result recorded", "Basis")


def _coverage_table(coverage: DataCoverage, *, name: str = "Data coverage") -> Table:
    """Who is behind the numbers, and who is not. On every report that has a cohort."""
    return Table(
        name=name,
        headers=COVERAGE_HEADERS,
        rows=(
            (
                count(coverage.assessed),
                count(coverage.absent),
                count(coverage.exempt),
                count(coverage.missing),
                text(coverage.basis),
            ),
        ),
    )


def _insight_table(insights: Sequence[GeneratedInsight], *, name: str = "Insights") -> Table:
    """The generated sentences, each beside the code and evidence that produced it.

    The code travels with the sentence so a reader can trace the wording back to its rule,
    and the evidence so they can check the arithmetic without leaving the page.
    """
    return Table(
        name=name,
        headers=("Insight", "Code", "Evidence"),
        rows=tuple(
            (
                text(insight.text),
                text(insight.code.value),
                text(
                    "; ".join(f"{item.name}: {item.value}" for item in insight.explanation.evidence)
                ),
            )
            for insight in insights
        ),
    )


def _metadata(
    snapshot: OfferingSnapshot,
    kind: ReportKind,
    title: str,
    *,
    subject: str | None = None,
    identity: OfferingIdentity | None = None,
    generated_at: datetime,
) -> ReportMetadata:
    """``identity`` is optional so the builders stay provable from a snapshot alone; when the
    service supplies it, the file names the course, section and term it is about."""
    named = identity or OfferingIdentity()
    return ReportMetadata(
        kind=kind,
        title=title,
        generated_at=generated_at,
        offering_id=str(snapshot.offering_id),
        subject=subject,
        course_code=named.course_code,
        section_name=named.section_name,
        term_code=named.term_code,
    )


def _student_label(student: StudentRef) -> str:
    return f"{student.register_no} {student.name}" if student.name else str(student.register_no)


# ------------------------------------------------------------------ A. class summary


def class_report(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    identity: OfferingIdentity | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> Report:
    """**A.** The offering at a glance: KPIs, each assessment, segments, attention."""
    stamp = generated_at or datetime.now(UTC)
    health = class_health(snapshot, thresholds, active_only=active_only, generated_at=stamp)

    summary = Table(
        name="Class summary",
        headers=("Metric", "Value", "Note"),
        rows=(
            (text("Students in cohort"), count(health.cohort_n), text("active enrolments")),
            (
                text("Students with a course score"),
                count(health.class_mean.n if health.class_mean.is_ok else 0),
                text("at least one completed assessment"),
            ),
            (text("Published assessments"), count(health.published_assessments), text("")),
            (
                text("Class mean (weighted course score)"),
                measure(health.class_mean),
                text("mean of students' weighted course scores"),
            ),
            (text("Median course score"), measure(health.median), text("")),
            (
                text("Pass rate"),
                measure(health.pass_percent),
                text(f"course scores at or above {health.pass_mark_percent}%"),
            ),
            (
                text("Completion"),
                measure(health.completion_percent),
                text("assessed sittings of those required; exempt excluded"),
            ),
            (
                text("Students requiring attention"),
                measure(health.students_requiring_attention),
                text("any High rule, or two Medium rules"),
            ),
        ),
    )

    assessments = Table(
        name="Assessments",
        headers=(
            "Assessment",
            "Max marks",
            "Weightage",
            "Assessed",
            "Mean",
            "Median",
            "Std dev",
            "Pass %",
            "Completion %",
            "Lowest",
            "Highest",
        ),
        rows=tuple(
            _assessment_row(snapshot, assessment, active_only=active_only, stamp=stamp)
            for assessment in snapshot.ordered_assessments()
        ),
    )

    segments = Table(
        name="Segments",
        headers=("Segment", "Students"),
        rows=tuple(
            (text(segment.value), count(number))
            for segment, number in health.segment_counts.items()
        )
        or ((text("none assigned"), count(0)),),
    )

    distribution = health.course_score_distribution
    bins = Table(
        name="Course score distribution",
        headers=("Band", "Students", "Share"),
        rows=tuple(
            (text(f"{b.lower}-{b.upper}"), count(b.count), percent(b.share_percent))
            for b in (distribution.bins if distribution else ())
        ),
    )

    # The narrative is already the section summary; notes carry only what it does not say.
    notes: list[str] = []
    if health.students_requiring_attention is None:
        notes.append(ATTENTION_NOT_EVALUATED)

    generated = class_insights(snapshot, thresholds, active_only=active_only, generated_at=stamp)

    sections = [
        Section(
            title="Summary",
            summary=health.explanation.narrative,
            tables=(summary, _coverage_table(health.coverage)),
            notes=tuple(notes),
        ),
    ]
    if generated:
        sections.append(
            Section(
                title="Insights",
                tables=(_insight_table(generated),),
                notes=tuple(
                    dict.fromkeys(
                        caveat for insight in generated for caveat in insight.explanation.caveats
                    )
                ),
            )
        )
    sections += [
        Section(title="Assessments", tables=(assessments,)),
        Section(title="Segments and distribution", tables=(segments, bins)),
    ]

    if health.students_requiring_attention is not None:
        sections.append(
            Section(
                title="Attention",
                tables=(
                    _severity_table(health.flag_counts),
                    _rule_table(health.rule_counts),
                ),
            )
        )

    return Report(
        metadata=_metadata(
            snapshot,
            ReportKind.CLASS_SUMMARY,
            "Class summary",
            identity=identity,
            generated_at=stamp,
        ),
        sections=tuple(sections),
    )


def _assessment_row(
    snapshot: OfferingSnapshot,
    assessment: AssessmentRef,
    *,
    active_only: bool,
    stamp: datetime,
) -> tuple[Cell, ...]:
    analytics = assessment_analytics(
        snapshot, assessment, active_only=active_only, generated_at=stamp
    )
    lowest = analytics.lowest
    highest = analytics.highest
    return (
        text(assessment.code),
        text(format_marks(assessment.max_marks)),
        text(format_marks(assessment.weightage)),
        count(analytics.coverage.assessed),
        measure(analytics.mean),
        measure(analytics.median),
        measure(analytics.std_dev),
        measure(analytics.pass_percent),
        measure(analytics.completion_percent),
        text(f"{lowest.percentage}% {_student_label(lowest.student)}")
        if lowest
        else missing("nobody was assessed"),
        text(f"{highest.percentage}% {_student_label(highest.student)}")
        if highest
        else missing("nobody was assessed"),
    )


def _severity_table(counts: object) -> Table:
    rows = tuple((text(severity.value), count(number)) for severity, number in counts.items())  # type: ignore[union-attr]
    return Table(
        name="Flags by severity",
        headers=("Severity", "Flags"),
        rows=rows or ((text("none"), count(0)),),
    )


def _rule_table(counts: object) -> Table:
    rows = tuple((text(code.value), count(number)) for code, number in counts.items())  # type: ignore[union-attr]
    return Table(
        name="Students by rule",
        headers=("Rule", "Students"),
        rows=rows or ((text("none"), count(0)),),
    )


# ------------------------------------------------------------- B. student performance


def student_report(
    snapshot: OfferingSnapshot,
    student_id: uuid.UUID,
    thresholds: ThresholdSet,
    *,
    identity: OfferingIdentity | None = None,
    interventions: Sequence[Intervention] = (),
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> Report:
    """**B.** One student: history, course score, trend, segment, flags, interventions."""
    stamp = generated_at or datetime.now(UTC)
    student = student_ref(snapshot, student_id)
    profile = student_profile(
        snapshot, student_id, thresholds, active_only=active_only, generated_at=stamp
    )
    segment = student_segment(
        snapshot,
        student_id,
        thresholds,
        profile=profile,
        active_only=active_only,
        generated_at=stamp,
    )
    attention = next(
        (
            entry
            for entry in cohort_attention(
                snapshot, thresholds, active_only=active_only, generated_at=stamp
            )
            if entry.student.id == student_id
        ),
        None,
    )

    history = Table(
        name="Assessment history",
        headers=("Assessment", "Status", "Score", "Max marks", "Percentage", "Weightage"),
        rows=tuple(
            (
                text(point.assessment_code),
                text(point.state.value),
                text(format_marks(point.score))
                if point.score is not None
                else missing(
                    f"{point.state.value}: no score was recorded, which is not a score of 0"
                ),
                text(format_marks(point.max_marks)),
                percent(point.percentage)
                if point.percentage is not None
                else missing(f"{point.state.value}: no percentage exists for this assessment"),
                text(format_marks(point.weightage)),
            )
            for point in profile.history.points
        ),
    )

    summary = Table(
        name="Student summary",
        headers=("Metric", "Value", "Note"),
        rows=(
            (
                text("Weighted course score"),
                measure(profile.history.weighted_course_score),
                text("over completed assessments only"),
            ),
            (
                text("Completion"),
                measure(profile.history.completion_percent),
                text("exempt assessments excluded from the denominator"),
            ),
            (
                text("Trend"),
                label(profile.trend.label),
                text(profile.trend.method.value if profile.trend.method else ""),
            ),
            (text("Trend slope"), measure(profile.trend.slope), text("")),
            (
                text("Consistency (population sd)"),
                measure(profile.history.consistency_std_dev),
                text(""),
            ),
            (text("Volatility (range)"), measure(profile.history.volatility_range), text("")),
            (
                text("Latest vs previous"),
                measure(profile.change_from_previous),
                text("between the two most recent completed assessments"),
            ),
            (
                text("Prior average"),
                measure(profile.historical_average),
                text("mean of completed assessments before the latest"),
            ),
            (
                text("Latest vs prior average"),
                measure(profile.change_from_historical_average),
                text(""),
            ),
            (
                text("Segment"),
                label(segment.primary),
                text(", ".join(f.segment.value for f in segment.factors)),
            ),
        ),
    )

    findings = Table(
        name="Findings",
        headers=("Finding", "Detected", "Value", "Explanation"),
        rows=tuple(
            (
                text(finding.code.value),
                text("yes" if finding.detected else "no")
                if finding.detected is not None
                else missing("could not be evaluated on the data available"),
                measure(finding.measure),
                text(finding.explanation.narrative),
            )
            for finding in profile.findings
        ),
    )

    generated = student_insights(
        snapshot,
        student_id,
        thresholds,
        profile=profile,
        active_only=active_only,
        generated_at=stamp,
    )

    sections = [
        Section(
            title="Summary",
            summary=profile.explanation.narrative,
            tables=(summary,),
            notes=profile.history.explanation.caveats,
        ),
    ]
    if generated:
        sections.append(Section(title="Insights", tables=(_insight_table(generated),)))
    sections += [
        Section(
            title="Assessment history",
            tables=(history, _coverage_table(profile.history.coverage)),
        ),
        Section(title="Findings", tables=(findings,)),
    ]

    if attention is not None:
        sections.append(
            Section(
                title="Attention",
                summary=attention.explanation.narrative,
                tables=(_flag_table(attention.flags),),
            )
        )

    mine = [i for i in interventions if student_id in i.targets]
    if mine:
        outcomes = intervention_outcomes(
            snapshot, mine, thresholds, active_only=active_only, generated_at=stamp
        )
        sections.append(
            Section(
                title="Interventions",
                tables=(_intervention_table(mine), _outcome_table(outcomes)),
                notes=(OBSERVATIONAL_CAVEAT,),
            )
        )

    return Report(
        metadata=_metadata(
            snapshot,
            ReportKind.STUDENT_PERFORMANCE,
            "Student performance",
            subject=_student_label(student),
            identity=identity,
            generated_at=stamp,
        ),
        sections=tuple(sections),
    )


# ----------------------------------------------------------------------- C. attention


def _flag_table(flags: Sequence[AttentionFlag], *, name: str = "Flags") -> Table:
    """Flags as rows, in the order given — rule code, never re-sorted by severity."""
    return Table(
        name=name,
        headers=(
            "Rule",
            "Severity",
            "Actual",
            "Threshold",
            "Threshold source",
            "Assessments",
            "Explanation",
        ),
        rows=tuple(
            (
                text(flag.rule_code.value),
                text(flag.severity.value),
                measure(flag.actual),
                text(f"{flag.threshold.value}")
                if flag.threshold
                else text(f"pass mark {flag.pass_mark_percent}%"),
                text(flag.threshold.source.value) if flag.threshold else text("offering"),
                text(", ".join(flag.reference_assessments)),
                text(flag.message),
            )
            for flag in flags
        ),
    )


def attention_report(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    identity: OfferingIdentity | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> Report:
    """**C.** Every flag in the cohort, with its evidence. Overlaps preserved."""
    stamp = generated_at or datetime.now(UTC)
    attentions = cohort_attention(snapshot, thresholds, active_only=active_only, generated_at=stamp)
    flagged = [entry for entry in attentions if entry.flags]
    requiring = students_requiring_attention(attentions)

    totals = Table(
        name="Attention summary",
        headers=("Metric", "Value", "Note"),
        rows=(
            (text("Total flags"), count(len(all_flags(attentions))), text("one per fired rule")),
            (
                text("Flagged students"),
                count(len(flagged)),
                text("students holding at least one flag"),
            ),
            (
                text("Students requiring attention"),
                count(len(requiring)),
                text("any High rule, or two Medium rules"),
            ),
            (text("Cohort"), count(len(attentions)), text("students evaluated")),
        ),
    )

    detail = Table(
        name="Flags by student",
        headers=(
            "Student",
            "Requires attention",
            "Rule",
            "Severity",
            "Actual",
            "Threshold",
            "Threshold source",
            "Assessments",
            "Explanation",
        ),
        rows=tuple(
            (
                text(_student_label(entry.student)),
                text("yes" if entry.requires_attention else "no"),
                text(flag.rule_code.value),
                text(flag.severity.value),
                measure(flag.actual),
                text(f"{flag.threshold.value}")
                if flag.threshold
                else text(f"pass mark {flag.pass_mark_percent}%"),
                text(flag.threshold.source.value) if flag.threshold else text("offering"),
                text(", ".join(flag.reference_assessments)),
                text(flag.message),
            )
            for entry in flagged
            for flag in entry.flags
        ),
    )

    unflagged = Table(
        name="Students with no flags",
        headers=("Student", "Note"),
        rows=tuple(
            (
                text(_student_label(entry.student)),
                text(entry.explanation.narrative),
            )
            for entry in attentions
            if not entry.flags
        ),
    )

    return Report(
        metadata=_metadata(
            snapshot, ReportKind.ATTENTION, "Attention", identity=identity, generated_at=stamp
        ),
        sections=(
            Section(
                title="Summary",
                tables=(
                    totals,
                    _severity_table(flag_counts(attentions)),
                    _rule_table(rule_counts(attentions)),
                ),
                notes=(
                    "Flags are listed in rule order R1 to R7. That is deterministic ordering, "
                    "not priority: no rule ranks above another.",
                ),
            ),
            Section(title="Flags", tables=(detail,)),
            Section(title="Students with no flags", tables=(unflagged,)),
        ),
    )


# ------------------------------------------------------- D. assessment comparison


def comparison_report(
    snapshot: OfferingSnapshot,
    thresholds: ThresholdSet,
    *,
    identity: OfferingIdentity | None = None,
    from_assessment: AssessmentRef | None = None,
    to_assessment: AssessmentRef | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> Report:
    """**D.** What moved between two assessments, over the students who sat both.

    With no assessments named, the latest published one is compared with the one before it —
    the same "what changed" question the dashboard asks.
    """
    stamp = generated_at or datetime.now(UTC)
    analysis = change_analysis(
        snapshot,
        thresholds,
        to_assessment=to_assessment,
        active_only=active_only,
        generated_at=stamp,
    )
    comparison = analysis.comparison
    if from_assessment is not None and to_assessment is not None:
        comparison = compare_assessments(
            snapshot, from_assessment, to_assessment, active_only=active_only, generated_at=stamp
        )

    movements = Table(
        name="Movements",
        headers=("Metric", "Change", "Note"),
        rows=(
            (
                text("Class mean"),
                measure(analysis.class_mean_change),
                text("over students assessed in both"),
            ),
            (
                text("Median"),
                measure(comparison.median_change) if comparison else measure(None),
                text(""),
            ),
            (text("Pass rate"), measure(analysis.pass_percent_change), text("")),
            (
                text("Spread (population sd)"),
                measure(comparison.spread_change) if comparison else measure(None),
                text(""),
            ),
            (
                text("Participation"),
                measure(comparison.completion_change) if comparison else measure(None),
                text("over the whole cohort, not the intersection"),
            ),
        ),
    )

    groups = Table(
        name="Students who moved",
        headers=("Group", "Students", "Members"),
        rows=tuple(
            (
                text(group.label),
                count(group.count),
                text(", ".join(_student_label(s) for s in group.students) or "none"),
            )
            for group in analysis.groups
        )
        or ((text("no comparison available"), count(0), text("")),),
    )

    findings = Table(
        name="Cohort findings",
        headers=("Finding", "Detected", "Direction", "Movement", "Explanation"),
        rows=tuple(
            (
                text(finding.code.value),
                text("yes" if finding.detected else "no")
                if finding.detected is not None
                else missing("cohort too small, or the movement could not be computed"),
                text(finding.direction.value) if finding.direction else text(""),
                measure(finding.measure),
                text(finding.explanation.narrative),
            )
            for finding in analysis.findings
        )
        or ((text("none"), text(""), text(""), measure(None), text("")),),
    )

    endpoints = Table(
        name="Assessments compared",
        headers=("Role", "Assessment", "Assessed", "Mean"),
        rows=_endpoint_rows(comparison),
    )

    return Report(
        metadata=_metadata(
            snapshot,
            ReportKind.ASSESSMENT_COMPARISON,
            "Assessment comparison",
            subject=(
                f"{analysis.from_assessment.code} to {analysis.to_assessment.code}"
                if analysis.from_assessment
                else analysis.to_assessment.code
            ),
            identity=identity,
            generated_at=stamp,
        ),
        sections=(
            Section(
                title="What changed",
                summary=analysis.explanation.narrative,
                tables=(endpoints, movements, _coverage_table(analysis.coverage)),
                notes=analysis.explanation.caveats,
            ),
            Section(title="Students who moved", tables=(groups,)),
            Section(title="Cohort findings", tables=(findings,)),
        ),
    )


def _endpoint_rows(comparison: object) -> tuple[tuple[Cell, ...], ...]:
    if comparison is None:
        return (
            (
                text("baseline"),
                missing("no earlier assessment to compare against"),
                count(0),
                measure(None),
            ),
        )
    rows = []
    for role, assessment, analytics in (
        ("baseline", comparison.from_assessment, comparison.from_analytics),  # type: ignore[attr-defined]
        ("comparison", comparison.to_assessment, comparison.to_analytics),  # type: ignore[attr-defined]
    ):
        rows.append(
            (
                text(role),
                text(assessment.code),
                count(analytics.coverage.assessed) if analytics else count(0),
                measure(analytics.mean) if analytics else measure(None),
            )
        )
    return tuple(rows)


# -------------------------------------------------------- E. intervention outcomes


def _intervention_table(interventions: Sequence[Intervention]) -> Table:
    return Table(
        name="Interventions",
        headers=("Intervention", "Kind", "Status", "After assessment", "Targets", "Reason"),
        rows=tuple(
            (
                text(str(intervention.id)),
                text(intervention.kind.value),
                text(intervention.status.value),
                count(intervention.after_sequence_no),
                count(len(intervention.student_ids)),
                text(
                    "; ".join(
                        reason.rule_code.value if reason.rule_code else (reason.note or "")
                        for reason in intervention.reasons
                    )
                    or (intervention.note or "")
                ),
            )
            for intervention in interventions
        ),
    )


def _outcome_table(outcomes: Sequence[InterventionOutcome]) -> Table:
    """Observed change per intervention. Never labelled effectiveness."""
    return Table(
        name="Observed outcomes",
        headers=(
            "Intervention",
            "Baseline",
            "Follow-up",
            "Target students",
            "Target before",
            "Target after",
            "Target change",
            "Comparison students",
            "Comparison change",
            "Observed difference in change",
            "Outcome",
        ),
        rows=tuple(
            (
                text(str(outcome.intervention_id)),
                text(", ".join(a.code for a in outcome.baseline_assessments) or "none"),
                text(outcome.follow_up_assessment.code)
                if outcome.follow_up_assessment
                else missing("no assessment has been held since the intervention"),
                count(outcome.target.n),
                measure(outcome.target.pre_mean),
                measure(outcome.target.post_mean),
                measure(outcome.target.change),
                count(outcome.peers.n),
                measure(outcome.peers.change),
                measure(outcome.net_change),
                label(outcome.label),
            )
            for outcome in outcomes
        ),
    )


def intervention_report(
    snapshot: OfferingSnapshot,
    interventions: Sequence[Intervention],
    thresholds: ThresholdSet,
    *,
    identity: OfferingIdentity | None = None,
    active_only: bool = True,
    generated_at: datetime | None = None,
) -> Report:
    """**E.** What was observed after each intervention, against its peers.

    Observational throughout: the caveat is on the section, on every outcome's own
    explanation, and the wording is screened by the analytics contracts before it reaches
    here.
    """
    stamp = generated_at or datetime.now(UTC)
    outcomes = intervention_outcomes(
        snapshot, interventions, thresholds, active_only=active_only, generated_at=stamp
    )
    summary = outcome_summary(outcomes, offering_id=snapshot.offering_id, generated_at=stamp)

    totals = Table(
        name="Outcome summary",
        headers=("Metric", "Value", "Note"),
        rows=(
            (text("Interventions"), count(summary.interventions), text("")),
            (
                text("With a measurable change"),
                count(summary.measurable),
                text("both windows populated and both groups above the minimum size"),
            ),
            (text("Mean observed change"), measure(summary.mean_observed_change), text("")),
            (text("Median observed change"), measure(summary.median_observed_change), text("")),
            (text("Target group rose"), count(summary.improved), text("not a success rate")),
            (text("Target group fell"), count(summary.declined), text("")),
            (text("Target group unchanged"), count(summary.unchanged), text("")),
        ),
    )

    reasons = Table(
        name="Intervention reasons",
        headers=("Intervention", "Student", "Rule", "Observed", "Threshold", "Assessments"),
        rows=tuple(
            (
                text(str(intervention.id)),
                text(str(reason.student_id)),
                text(reason.rule_code.value if reason.rule_code else "recorded note"),
                measure(reason.observed) if reason.observed else text(reason.note or ""),
                text(str(reason.threshold.value)) if reason.threshold else text(""),
                text(", ".join(reason.assessments)),
            )
            for intervention in interventions
            for reason in intervention.reasons
        )
        or ((text("none recorded"), text(""), text(""), text(""), text(""), text("")),),
    )

    coverage = outcomes[0].coverage if outcomes else None

    return Report(
        metadata=_metadata(
            snapshot,
            ReportKind.INTERVENTION_OUTCOME,
            "Intervention outcomes",
            identity=identity,
            generated_at=stamp,
        ),
        sections=(
            Section(
                title="Summary",
                summary=summary.explanation.narrative,
                tables=(totals,),
                notes=(OBSERVATIONAL_CAVEAT,),
            ),
            Section(
                title="Interventions",
                tables=(_intervention_table(interventions), reasons),
            ),
            Section(
                title="Observed outcomes",
                tables=(_outcome_table(outcomes),)
                + ((_coverage_table(coverage),) if coverage else ()),
                notes=(OBSERVATIONAL_CAVEAT,),
            ),
            Section(
                title="Insights",
                tables=(
                    _insight_table(
                        intervention_insights(outcomes, generated_at=stamp),
                        name="Intervention insights",
                    ),
                ),
                notes=(OBSERVATIONAL_CAVEAT,),
            ),
        ),
    )
