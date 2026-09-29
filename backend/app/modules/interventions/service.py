"""Recording interventions, and handing the stored ones to the Phase 6 outcome engine.

Layering follows the house rules: the router never touches the session, this service owns the
transaction (one ``commit()`` per operation), the repository never commits.

**Scope is the platform's.** Every entry point resolves the offering through
``OfferingAccess`` — an offering the user may not see is a 404 and its existence is not
disclosed — and the roster comes from the platform's own read through ``AnalyticsRepository``.
There is no second RBAC system here.

**Who may record one.** Anyone who can *view* the offering, which is the faculty assigned to it,
their HOD and an admin. Recording what you did for your own students is not administration of
the offering (that is the pass mark and faculty assignment), and requiring ADMINISTER would lock
faculty out of the one table that exists to hold their own actions.

**No outcome is stored.** ``intervention_outcomes`` measures them from the current snapshot every
time it is asked. An outcome changes the moment a new assessment lands, so a stored copy would be
a second answer that disagrees with the engine — and the engine is the source of truth for
baseline, follow-up, observed change and the peer comparison.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.core.pagination import Page, PageParams
from app.db.repository import write_guard
from app.modules.analytics.core.contracts import Intervention as InterventionContract
from app.modules.analytics.core.outputs import GeneratedInsight, InterventionOutcome
from app.modules.analytics.core.vocabulary import InterventionStatus
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.service import AnalyticsService
from app.modules.attention.models import AttentionFlag
from app.modules.attention.repository import AttentionFlagRepository
from app.modules.interventions.models import Intervention, InterventionReason
from app.modules.interventions.repository import (
    InterventionRepository,
    observed_measure,
    resolved_threshold,
)
from app.modules.interventions.schemas import (
    InterventionCreate,
    InterventionRead,
    InterventionReasonIn,
    InterventionReasonRead,
)
from app.modules.organization.scope import Access, OfferingAccess
from app.modules.users.models import User


class InterventionOutcomes(BaseModel):
    """Observed outcomes for an offering's stored interventions, plus their insight sentences."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    offering_id: uuid.UUID
    generated_at: datetime
    outcomes: tuple[InterventionOutcome, ...] = ()
    insights: tuple[GeneratedInsight, ...] = ()


class InterventionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = OfferingAccess(session)
        self._interventions = InterventionRepository(session)
        self._flags = AttentionFlagRepository(session)
        self._analytics = AnalyticsRepository(session)

    # ------------------------------------------------------------------ writes

    def create(
        self, offering_id: uuid.UUID, payload: InterventionCreate, *, actor: User
    ) -> InterventionRead:
        """Record one intervention. All of it or none of it.

        Validation order is deliberate: the offering first (so an out-of-scope id never learns
        anything from a later error), then the targets, then the flags each reason points at.
        """
        self._access.get(actor, offering_id, Access.VIEW)
        self._require_enrolled(offering_id, payload.student_ids, actor=actor)
        flags = self._resolve_flags(offering_id, payload.reasons)

        intervention = Intervention(
            offering_id=offering_id,
            kind=payload.kind,
            status=payload.status,
            after_sequence_no=payload.after_sequence_no,
            recorded_on=payload.recorded_on,
            note=payload.note,
            recorded_by_id=actor.id,
        )
        with write_guard(
            self._session,
            conflict="This intervention conflicts with an existing one.",
            in_use="The intervention references a record that no longer exists.",
            invalid="The intervention violates a data rule.",
        ):
            self._interventions.add(intervention)
            self._session.flush()
            for student_id in payload.student_ids:
                self._interventions.add_target(intervention.id, student_id)
            self._session.flush()
            for reason in payload.reasons:
                self._interventions.add_reason(
                    self._reason_row(intervention.id, reason, flags.get(reason.flag_id))
                )
        self._session.commit()
        return self._read_one(intervention)

    # ------------------------------------------------------------------ reads

    def list_for_offering(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        page: PageParams,
        student_id: uuid.UUID | None = None,
        status: InterventionStatus | None = None,
    ) -> Page[InterventionRead]:
        self._access.get(actor, offering_id, Access.VIEW)
        if student_id is not None:
            self._require_enrolled(offering_id, (student_id,), actor=actor)
        rows, total = self._interventions.page_for_offering(
            offering_id,
            limit=page.limit,
            offset=page.offset,
            student_id=student_id,
            status=status,
        )
        return Page(
            items=list(self._read_many(rows)),
            total=total,
            limit=page.limit,
            offset=page.offset,
        )

    def outcomes(
        self, offering_id: uuid.UUID, *, actor: User, generated_at: datetime | None = None
    ) -> InterventionOutcomes:
        """Measure every stored intervention of this offering with the Phase 6 engine."""
        self._access.get(actor, offering_id, Access.VIEW)
        stamp = generated_at or datetime.now(UTC)
        contracts = self.contracts_for_offering(offering_id)
        outcomes, insights = AnalyticsService(self._session).intervention_outcomes(
            offering_id, contracts, actor=actor, generated_at=stamp
        )
        return InterventionOutcomes(
            offering_id=offering_id,
            generated_at=stamp,
            outcomes=outcomes,
            insights=insights,
        )

    def contracts_for_offering(self, offering_id: uuid.UUID) -> tuple[InterventionContract, ...]:
        """Stored interventions as the analytics input contract. No access check: internal use.

        Callers serving a request must have resolved the offering through ``OfferingAccess``
        first; :meth:`outcomes` and the report path both do.
        """
        return self._interventions.contracts_for_offering(offering_id)

    # ------------------------------------------------------------------ validation

    def _require_enrolled(
        self, offering_id: uuid.UUID, student_ids: Sequence[uuid.UUID], *, actor: User
    ) -> None:
        """Every target must be an active enrolment of this offering.

        Read through the platform's own scoped read, so "enrolled here" means exactly what it
        means everywhere else. A student who exists but is not on this offering is a data rule
        violation (422), not a 404: the offering was found and the request is simply wrong about
        who is in it.
        """
        snapshot = self._analytics.snapshot_for_offering(offering_id, actor=actor)
        enrolled = {student.id for student in snapshot.students}
        stray = sorted(str(sid) for sid in student_ids if sid not in enrolled)
        if stray:
            raise BusinessRuleError(
                f"These students are not active enrolments of this offering: {', '.join(stray)}."
            )

    def _resolve_flags(
        self, offering_id: uuid.UUID, reasons: Sequence[InterventionReasonIn]
    ) -> dict[uuid.UUID | None, AttentionFlag]:
        """Load the flags the reasons point at, refusing any that is not this student's, here."""
        wanted = {reason.flag_id for reason in reasons if reason.flag_id is not None}
        if not wanted:
            return {}
        found = {
            row.id: row
            for row in self._flags.for_students(
                offering_id, [reason.student_id for reason in reasons]
            )
            if row.id in wanted
        }
        by_student = {(reason.student_id, reason.flag_id) for reason in reasons if reason.flag_id}
        for student_id, flag_id in sorted(by_student, key=lambda pair: str(pair[1])):
            row = found.get(flag_id)
            if row is None or row.student_id != student_id:
                raise BusinessRuleError(
                    f"Attention flag {flag_id} is not a live flag of this offering for student "
                    f"{student_id}."
                )
        return dict(found)

    # ------------------------------------------------------------------ mapping

    @staticmethod
    def _reason_row(
        intervention_id: uuid.UUID, reason: InterventionReasonIn, flag: AttentionFlag | None
    ) -> InterventionReason:
        """Freeze a reason. Where it names a flag, the flag supplies the analytics content.

        The flag's own message becomes the reason's note when the client did not write one, so a
        reason drawn from analytics always reads as a sentence and never as a bare code.
        """
        row = InterventionReason(
            intervention_id=intervention_id,
            student_id=reason.student_id,
            finding=reason.finding,
            note=reason.note,
        )
        if flag is None:
            return row
        row.rule_code = flag.rule_code
        row.observed_value = flag.actual_value
        row.observed_unit = flag.actual_unit
        row.observed_n = flag.actual_n
        row.threshold_key = flag.threshold_key
        row.threshold_value = flag.threshold_value
        row.threshold_source = flag.threshold_source
        row.assessments = list(flag.reference_assessments)
        row.note = reason.note or flag.message
        row.source_flag_id = flag.id
        return row

    def _read_one(self, row: Intervention) -> InterventionRead:
        return next(iter(self._read_many([row])))

    def _read_many(self, rows: Sequence[Intervention]) -> tuple[InterventionRead, ...]:
        ids = [row.id for row in rows]
        targets = self._interventions.targets_for(ids)
        reasons = self._interventions.reasons_for(ids)
        return tuple(
            InterventionRead(
                id=row.id,
                offering_id=row.offering_id,
                student_ids=tuple(targets.get(row.id, ())),
                kind=row.kind,
                status=row.status,
                after_sequence_no=row.after_sequence_no,
                recorded_on=row.recorded_on,
                note=row.note,
                reasons=tuple(_reason_read(r) for r in reasons.get(row.id, ())),
                recorded_by_id=row.recorded_by_id,
                created_at=row.created_at,
            )
            for row in rows
        )


def _reason_read(row: InterventionReason) -> InterventionReasonRead:
    return InterventionReasonRead(
        student_id=row.student_id,
        rule_code=row.rule_code,
        finding=row.finding,
        observed=observed_measure(row),
        threshold=resolved_threshold(row),
        assessments=tuple(row.assessments),
        note=row.note,
        source_flag_id=row.source_flag_id,
    )
