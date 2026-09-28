"""The application-facing analytics service: one read, one computation, one response.

This is the seam between Agent 1's platform and Agent 2's pure engine.

    OfferingResultsService (platform, scoped)
            v
    AnalyticsRepository            adapter: rows -> OfferingSnapshot
            v
    OfferingContext                snapshot + resolved thresholds
            v
    analytics/core                 pure functions
            v
    AnalyticsService               this module
            v
    router                         serialisation only

**Scope is the platform's, not ours.** Every read goes through
``OfferingResultsService.for_user``, which returns 404 for an offering the user may not see
— so an unauthorised request cannot distinguish "not yours" from "does not exist", and there
is no second RBAC system to keep in step with the first.

**Analytics runs once per request.** ``class_health`` builds the cohort's profiles and
segments; ``class_insights`` needs the same health block, the same attention and the same
comparison. The service computes each fact once and passes it down, so a dashboard read does
not rebuild the cohort three times.

Nothing here calculates. Every number in a response came from ``analytics/core``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.analytics.core.attention import (
    cohort_attention,
    flag_counts,
    flagged_students,
    rule_counts,
    students_requiring_attention,
)
from app.modules.analytics.core.class_health import class_health
from app.modules.analytics.core.comparison import change_analysis, latest_published
from app.modules.analytics.core.contracts import Intervention, OfferingSnapshot, StudentRef
from app.modules.analytics.core.insights import (
    class_insights,
    intervention_insights,
    student_insights,
)
from app.modules.analytics.core.interventions import intervention_outcomes
from app.modules.analytics.core.outputs import (
    ChangeAnalysis,
    ClassHealth,
    GeneratedInsight,
    InterventionOutcome,
    StudentAttention,
    StudentPerformanceProfile,
    StudentSegment,
)
from app.modules.analytics.core.profile import student_profile
from app.modules.analytics.core.rules import AttentionRuleCode, FlagSeverity
from app.modules.analytics.core.segmentation import student_segment
from app.modules.analytics.repository import AnalyticsRepository, OfferingContext
from app.modules.reports.builders import (
    attention_report,
    class_report,
    comparison_report,
    intervention_report,
    student_report,
)
from app.modules.reports.exporters import to_csv, to_pdf, to_xlsx
from app.modules.reports.model import Report, ReportKind
from app.modules.users.models import User


class ExportFormat:
    """The three export formats, with the media type and extension each needs."""

    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"

    MEDIA_TYPES = {
        CSV: "text/csv; charset=utf-8",
        XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        PDF: "application/pdf",
    }

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (cls.CSV, cls.XLSX, cls.PDF)


_EXPORTERS = {
    ExportFormat.CSV: to_csv,
    ExportFormat.XLSX: to_xlsx,
    ExportFormat.PDF: to_pdf,
}


class AnalyticsService:
    """Everything the API needs from one offering, computed from one read."""

    def __init__(self, session: Session) -> None:
        self._repository = AnalyticsRepository(session)

    # ------------------------------------------------------------------ loading

    def context(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingContext:
        """The offering's snapshot and thresholds, scoped to ``actor``.

        One platform read per request. An offering the actor cannot see raises the
        platform's own ``NotFoundError``, which the API renders as a 404.
        """
        return self._repository.context_for_offering(
            offering_id,
            actor=actor,
            published_only=published_only,
            include_dropped=include_dropped,
        )

    def _student(self, snapshot: OfferingSnapshot, student_id: uuid.UUID) -> StudentRef:
        """Resolve a student *within this offering*.

        A student who exists but is not enrolled here is a 404 for this endpoint: the
        question "how is this student doing in this offering" has no answer, and saying so
        is better than returning an empty profile that reads like a real one.
        """
        for student in snapshot.students:
            if student.id == student_id:
                return student
        raise NotFoundError("Student not found in this offering.")

    # ------------------------------------------------------------------ cohort

    def class_analytics(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        generated_at: datetime | None = None,
    ) -> ClassAnalytics:
        """The offering dashboard: health, what changed, attention counts and insights.

        Each fact is computed once and threaded into the next, so the cohort is built once
        rather than once per block.
        """
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        snapshot, thresholds = loaded.snapshot, loaded.thresholds

        health = class_health(snapshot, thresholds, generated_at=stamp)
        attentions = cohort_attention(snapshot, thresholds, generated_at=stamp)
        analysis = (
            change_analysis(snapshot, thresholds, generated_at=stamp)
            if latest_published(snapshot) is not None
            else None
        )
        insights = class_insights(
            snapshot,
            thresholds,
            health=health,
            attentions=attentions,
            analysis=analysis,
            generated_at=stamp,
        )
        return ClassAnalytics(
            offering_id=offering_id,
            generated_at=stamp,
            health=health,
            change=analysis,
            attention=AttentionSummary.of(attentions),
            insights=insights,
        )

    def attention(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        generated_at: datetime | None = None,
    ) -> CohortAttention:
        """Every flag in the cohort, overlaps and ordering preserved."""
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        attentions = cohort_attention(loaded.snapshot, loaded.thresholds, generated_at=stamp)
        return CohortAttention(
            offering_id=offering_id,
            generated_at=stamp,
            summary=AttentionSummary.of(attentions),
            students=attentions,
        )

    def insights(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        generated_at: datetime | None = None,
    ) -> CohortInsights:
        """The cohort's deterministic sentences, in presentation order."""
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        return CohortInsights(
            offering_id=offering_id,
            generated_at=stamp,
            insights=class_insights(loaded.snapshot, loaded.thresholds, generated_at=stamp),
        )

    # ------------------------------------------------------------------ one student

    def student_analytics(
        self,
        offering_id: uuid.UUID,
        student_id: uuid.UUID,
        *,
        actor: User,
        generated_at: datetime | None = None,
    ) -> StudentAnalytics:
        """One student's profile, segment, flags and insights within this offering."""
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        snapshot, thresholds = loaded.snapshot, loaded.thresholds
        self._student(snapshot, student_id)

        profile = student_profile(snapshot, student_id, thresholds, generated_at=stamp)
        segment = student_segment(
            snapshot, student_id, thresholds, profile=profile, generated_at=stamp
        )
        attention = next(
            (
                entry
                for entry in cohort_attention(snapshot, thresholds, generated_at=stamp)
                if entry.student.id == student_id
            ),
            None,
        )
        return StudentAnalytics(
            offering_id=offering_id,
            student_id=student_id,
            generated_at=stamp,
            profile=profile,
            segment=segment,
            attention=attention,
            insights=student_insights(
                snapshot, student_id, thresholds, profile=profile, generated_at=stamp
            ),
        )

    # ------------------------------------------------------------------ interventions

    def intervention_outcomes(
        self,
        offering_id: uuid.UUID,
        interventions: Sequence[Intervention],
        *,
        actor: User,
        generated_at: datetime | None = None,
    ) -> tuple[tuple[InterventionOutcome, ...], tuple[GeneratedInsight, ...]]:
        """Observed outcomes for interventions **supplied by the caller**.

        Interventions are not stored yet (dependency D5), so there is no endpoint that lists
        them and none that creates one. This exists so the outcome analytics are reachable
        the moment that storage lands: the service takes the records, the engine measures
        them, and nothing here would change.
        """
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        outcomes = intervention_outcomes(
            loaded.snapshot, interventions, loaded.thresholds, generated_at=stamp
        )
        return outcomes, intervention_insights(outcomes, generated_at=stamp)

    # ------------------------------------------------------------------ reports

    def report(
        self,
        offering_id: uuid.UUID,
        kind: ReportKind,
        *,
        actor: User,
        student_id: uuid.UUID | None = None,
        generated_at: datetime | None = None,
    ) -> Report:
        """Build one report from a single offering read.

        The report builders take analytics contracts and lay them out; nothing is computed
        here that the engine does not already provide.
        """
        stamp = generated_at or datetime.now(UTC)
        loaded = self.context(offering_id, actor=actor)
        snapshot, thresholds = loaded.snapshot, loaded.thresholds

        match kind:
            case ReportKind.CLASS_SUMMARY:
                return class_report(snapshot, thresholds, generated_at=stamp)
            case ReportKind.ATTENTION:
                return attention_report(snapshot, thresholds, generated_at=stamp)
            case ReportKind.ASSESSMENT_COMPARISON:
                return comparison_report(snapshot, thresholds, generated_at=stamp)
            case ReportKind.STUDENT_PERFORMANCE:
                if student_id is None:
                    raise NotFoundError("A student report needs a student_id.")
                self._student(snapshot, student_id)
                return student_report(snapshot, student_id, thresholds, generated_at=stamp)
            case ReportKind.INTERVENTION_OUTCOME:
                # Interventions are not stored yet (D5); with none to measure, the report is
                # its own empty case rather than a fabricated one.
                return intervention_report(snapshot, (), thresholds, generated_at=stamp)
        raise NotFoundError(f"Unknown report type {kind}.")

    def export(self, report: Report, export_format: str) -> tuple[bytes, str, str]:
        """Serialise a report, returning its bytes, media type and filename."""
        exporter = _EXPORTERS.get(export_format)
        if exporter is None:
            raise NotFoundError(f"Unknown export format {export_format!r}.")
        stem = report.metadata.kind.value
        stamp = report.metadata.generated_at.date().isoformat()
        return (
            exporter(report),
            ExportFormat.MEDIA_TYPES[export_format],
            f"{stem}-{stamp}.{export_format}",
        )


# ------------------------------------------------------------------ response models
#
# Compositions of the analytics contracts, not new representations of them: every field
# below is a contract the engine already returns, so there is still exactly one definition
# of each number.


class AttentionSummary(BaseModel):
    """Counts over a cohort's flags. Students and flags are counted separately."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_flags: int = Field(ge=0)
    flagged_students: int = Field(ge=0)
    students_requiring_attention: int = Field(ge=0)
    cohort: int = Field(ge=0)
    by_severity: dict[FlagSeverity, int] = Field(default_factory=dict)
    by_rule: dict[AttentionRuleCode, int] = Field(default_factory=dict)

    @classmethod
    def of(cls, attentions: Sequence[StudentAttention]) -> AttentionSummary:
        return cls(
            total_flags=sum(len(entry.flags) for entry in attentions),
            flagged_students=len(flagged_students(attentions)),
            students_requiring_attention=len(students_requiring_attention(attentions)),
            cohort=len(attentions),
            by_severity=dict(flag_counts(attentions)),
            by_rule=dict(rule_counts(attentions)),
        )


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offering_id: uuid.UUID
    generated_at: datetime


class ClassAnalytics(_Response):
    """The offering dashboard."""

    health: ClassHealth
    change: ChangeAnalysis | None = None
    """``None`` when the offering has no published assessment to analyse."""

    attention: AttentionSummary
    insights: tuple[GeneratedInsight, ...] = ()


class StudentAnalytics(_Response):
    """One student within one offering."""

    student_id: uuid.UUID
    profile: StudentPerformanceProfile
    segment: StudentSegment
    attention: StudentAttention | None = None
    insights: tuple[GeneratedInsight, ...] = ()


class CohortAttention(_Response):
    """Every student's flags, in cohort order."""

    summary: AttentionSummary
    students: tuple[StudentAttention, ...] = ()


class CohortInsights(_Response):
    insights: tuple[GeneratedInsight, ...] = ()
