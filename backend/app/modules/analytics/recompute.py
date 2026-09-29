"""The real C4 recompute (dependency D7 / requirement U1).

Installed into the platform's hook at import time. Agent 1 calls it inside the writer's
transaction, after the results are flushed and before commit, once per changed assessment:
``PUT /assessments/{id}/results``, ``DELETE .../results/{student_id}``,
``POST /imports/{id}/confirm``, ``POST /admin/recompute`` and the demo seed. **Those triggers
already exist** — nothing here adds one, and several of them can fire for the same offering in
one transaction, which is why the operation is idempotent.

    assessment_id
        |  one lookup
        v
    offering_id -------> AnalyticsRepository.context_for_offering(actor=None)
                                |  snapshot + resolved thresholds (contract C5)
                                v
                         cohort_attention()            the engine decides
                                |
                                v
                         AttentionSyncService          raise / refresh / resolve

Scope: exactly one offering, the one the changed assessment belongs to. Nothing scans other
offerings and nothing walks the whole table.

Transaction: the caller's. This never commits and never rolls back (decision D-003). If it
raises, the results write is rolled back with it, which is the intended coupling — flags and the
results they describe are never out of step.

Reads go through ``AnalyticsRepository`` with ``actor=None``, the unscoped system path. That is
correct *here and only here*: the hook has no user, and the offering id came from a row the
platform already wrote, never from a request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.recompute import install_recompute
from app.modules.analytics.core.attention import cohort_attention
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.services import RecomputeSummary
from app.modules.assessments.models import Assessment
from app.modules.attention.service import AttentionSyncService


def recompute_offering(
    session: Session,
    offering_id: uuid.UUID,
    assessment_id: uuid.UUID,
    *,
    computed_at: datetime | None = None,
) -> RecomputeSummary:
    """Re-evaluate one offering's attention and materialise it, returning what changed.

    ``assessment_id`` is the write that set this off. It is recorded on every row this touches
    as provenance, and it is what makes the returned :class:`RecomputeSummary` answerable; it is
    **not** an input to the calculation, which reads the whole offering.

    An offering with no active students is not an error: it evaluates to an empty cohort, which
    correctly resolves every flag it used to have.
    """
    stamp = computed_at or datetime.now(UTC)
    loaded = AnalyticsRepository(session).context_for_offering(offering_id, actor=None)
    attentions = cohort_attention(loaded.snapshot, loaded.thresholds, generated_at=stamp)
    counts = AttentionSyncService(session).synchronize(
        offering_id,
        attentions,
        computed_at=stamp,
        triggered_by_assessment_id=assessment_id,
    )
    return RecomputeSummary(
        offering_id=offering_id,
        assessment_id=assessment_id,
        students_evaluated=len(attentions),
        flags_raised=counts.raised,
        flags_resolved=counts.resolved,
    )


def recompute_assessment(session: Session, assessment_id: uuid.UUID) -> None:
    """Contract C4. Re-derive the offering's attention flags after its results changed.

    Returns ``None``, matching ``app.core.recompute.RecomputeFn``: the write path ignores any
    value, and agreeing with the signature it is installed against is worth more than a return
    nobody reads. A caller that wants the counts calls :func:`recompute_offering`.

    An assessment that no longer exists is a no-op rather than an error:
    ``POST /admin/recompute`` iterates an offering's assessments, and failing on a row that went
    away in the same transaction would roll back a write that was perfectly valid.
    """
    offering_id = session.scalar(
        select(Assessment.offering_id).where(Assessment.id == assessment_id)
    )
    if offering_id is None:
        return None
    recompute_offering(session, offering_id, assessment_id)
    return None


install_recompute(recompute_assessment)
