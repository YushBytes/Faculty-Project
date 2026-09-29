"""All SQL for interventions. Never commits (README rule 1).

Targets and reasons are read for a *batch* of interventions rather than per row: a list endpoint
is three queries whatever the page size, instead of one plus two per intervention.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Select, select

from app.db.repository import BaseRepository
from app.modules.analytics.core.contracts import Intervention as InterventionContract
from app.modules.analytics.core.contracts import InterventionReason as ReasonContract
from app.modules.analytics.core.results import Measure, MeasureStatus
from app.modules.analytics.core.thresholds import ResolvedThreshold
from app.modules.analytics.core.vocabulary import InterventionStatus
from app.modules.interventions.models import (
    Intervention,
    InterventionReason,
    InterventionStudent,
)

_ORDER = (Intervention.after_sequence_no, Intervention.created_at, Intervention.id)
"""Deterministic order: by the window they sit in, then by when they were recorded.

Two renderings of the same offering are identical, and the outcome engine receives them in an
order that does not depend on how PostgreSQL felt about the query plan.
"""


class InterventionRepository(BaseRepository[Intervention]):
    model = Intervention

    # ------------------------------------------------------------------ reads

    def _scoped(
        self,
        offering_id: uuid.UUID,
        *,
        student_id: uuid.UUID | None = None,
        status: InterventionStatus | None = None,
    ) -> Select[tuple[Intervention]]:
        query = select(Intervention).where(Intervention.offering_id == offering_id)
        if student_id is not None:
            query = query.where(
                Intervention.id.in_(
                    select(InterventionStudent.intervention_id).where(
                        InterventionStudent.student_id == student_id
                    )
                )
            )
        if status is not None:
            query = query.where(Intervention.status == status)
        return query

    def page_for_offering(
        self,
        offering_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        student_id: uuid.UUID | None = None,
        status: InterventionStatus | None = None,
    ) -> tuple[list[Intervention], int]:
        return self.page(
            self._scoped(offering_id, student_id=student_id, status=status),
            limit=limit,
            offset=offset,
            order_by=list(_ORDER),
        )

    def all_for_offering(
        self, offering_id: uuid.UUID, *, student_id: uuid.UUID | None = None
    ) -> list[Intervention]:
        """Every intervention of an offering, for the outcome engine (which measures them all)."""
        return list(
            self.session.scalars(
                self._scoped(offering_id, student_id=student_id).order_by(*_ORDER)
            ).all()
        )

    def get_in_offering(
        self, intervention_id: uuid.UUID, offering_id: uuid.UUID
    ) -> Intervention | None:
        return self.session.scalar(
            select(Intervention).where(
                Intervention.id == intervention_id, Intervention.offering_id == offering_id
            )
        )

    def targets_for(
        self, intervention_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """``intervention -> student ids``, in a stable order."""
        if not intervention_ids:
            return {}
        rows = self.session.execute(
            select(InterventionStudent.intervention_id, InterventionStudent.student_id)
            .where(InterventionStudent.intervention_id.in_(intervention_ids))
            .order_by(InterventionStudent.intervention_id, InterventionStudent.student_id)
        ).all()
        targets: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for intervention_id, student_id in rows:
            targets[intervention_id].append(student_id)
        return dict(targets)

    def reasons_for(
        self, intervention_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[InterventionReason]]:
        """``intervention -> reason rows``, in a stable order."""
        if not intervention_ids:
            return {}
        rows = self.session.scalars(
            select(InterventionReason)
            .where(InterventionReason.intervention_id.in_(intervention_ids))
            .order_by(
                InterventionReason.intervention_id,
                InterventionReason.student_id,
                InterventionReason.id,
            )
        ).all()
        reasons: dict[uuid.UUID, list[InterventionReason]] = defaultdict(list)
        for row in rows:
            reasons[row.intervention_id].append(row)
        return dict(reasons)

    def contracts_for_offering(
        self, offering_id: uuid.UUID, *, student_id: uuid.UUID | None = None
    ) -> tuple[InterventionContract, ...]:
        """Stored interventions as the analytics input contract, in deterministic order.

        Three queries whatever the count. An intervention with no surviving target is skipped
        rather than passed on: the contract requires at least one, and a targetless record is not
        something the outcome engine can measure.
        """
        rows = self.all_for_offering(offering_id, student_id=student_id)
        ids = [row.id for row in rows]
        targets = self.targets_for(ids)
        reasons = self.reasons_for(ids)
        return tuple(
            InterventionContract(
                id=row.id,
                offering_id=row.offering_id,
                student_ids=tuple(targets[row.id]),
                kind=row.kind,
                status=row.status,
                after_sequence_no=row.after_sequence_no,
                recorded_on=row.recorded_on,
                reasons=tuple(reason_contract(r) for r in reasons.get(row.id, ())),
                note=row.note,
            )
            for row in rows
            if targets.get(row.id)
        )

    # ------------------------------------------------------------------ writes

    def add_target(self, intervention_id: uuid.UUID, student_id: uuid.UUID) -> InterventionStudent:
        row = InterventionStudent(intervention_id=intervention_id, student_id=student_id)
        self.session.add(row)
        return row

    def add_reason(self, reason: InterventionReason) -> InterventionReason:
        self.session.add(reason)
        return reason


# ------------------------------------------------------------------ rows -> analytics contract
#
# The same adapter role AnalyticsRepository plays for OfferingSnapshot: stored rows mapped onto
# the input contract the pure engine consumes. It lives here, not in the service, so the report
# path can read stored interventions without importing the intervention service (which imports
# AnalyticsService, and would make the two modules circular).


def observed_measure(row: InterventionReason) -> Measure | None:
    """The value as it stood when the intervention was raised, rebuilt as a ``Measure``.

    ``None`` when the reason carried no number (a note-only or finding-only reason). A check
    constraint guarantees the unit and sample size are present whenever the value is.
    """
    if row.observed_value is None or row.observed_unit is None or row.observed_n is None:
        return None
    return Measure(
        status=MeasureStatus.OK,
        value=row.observed_value,
        unit=row.observed_unit,
        n=row.observed_n,
    )


def resolved_threshold(row: InterventionReason) -> ResolvedThreshold | None:
    """What the value was compared against, or ``None`` when the reason quoted no threshold."""
    if row.threshold_key is None or row.threshold_value is None or row.threshold_source is None:
        return None
    return ResolvedThreshold(
        key=row.threshold_key, value=row.threshold_value, source=row.threshold_source
    )


def reason_contract(row: InterventionReason) -> ReasonContract:
    return ReasonContract(
        student_id=row.student_id,
        rule_code=row.rule_code,
        finding=row.finding,
        observed=observed_measure(row),
        threshold=resolved_threshold(row),
        assessments=tuple(row.assessments),
        note=row.note,
    )
