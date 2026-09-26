"""The analytics service boundary: the two ports, declared before anything implements them.

Phase 1 fixes the shape of the layering, not its behaviour::

    router.py            thin; auth, scope, serialisation
        |
        v
    services.py          orchestration: fetch a snapshot, call the engine, assemble a response
        |
        +--> core/       pure functions over OfferingSnapshot -> the contracts in core.outputs
        |
        v
    repository.py        all SQL/ORM access (Phase 4)
        |
        v
    PostgreSQL

Only the two *ports* live here now, because they are the parts other people have to build
against:

:class:`SnapshotSource`
    How the engine gets its data. Everything the core computes comes from one
    :class:`~app.modules.analytics.core.contracts.OfferingSnapshot`, so this single method
    is the whole read surface of analytics. Making it an explicit protocol means the
    repository can be swapped for a hand-built snapshot in a test without a database, and it
    is what dependency D8 must ultimately satisfy.

:class:`RecomputeHook`
    Contract C4 / requirement U1, the hard handoff to Agent 1. Agent 1 calls it inside the
    import-confirm transaction and after a results edit; the signature is agreed in Phase 1
    so Agent 1 can ship a no-op stub in its Phase 3 and never be blocked by analytics. It
    takes the caller's ``Session`` and **must not commit** (decision D-003): the results
    write and the recomputed flags land in one transaction or neither does.

Implementations are Phase 4 (repository, services) and Phase 5 (recompute). Nothing is
stubbed here: an empty method that returns a plausible value is worse than no method, since
a caller cannot tell the difference between "not built yet" and "no flags fired".
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.modules.analytics.core.contracts import OfferingSnapshot


@runtime_checkable
class SnapshotSource(Protocol):
    """Supplies the one input every analytic reads.

    The implementation reads through the platform's own services/repositories (README rule
    4), so faculty scope and PII rules are enforced once, where the data lives, rather than
    re-derived here.
    """

    def snapshot_for_offering(
        self,
        session: Session,
        offering_id: uuid.UUID,
        *,
        published_only: bool = True,
        active_only: bool = True,
    ) -> OfferingSnapshot:
        """Build the snapshot for one offering.

        ``published_only`` excludes assessments faculty have created but not published;
        ``active_only`` excludes withdrawn students from the cohort. Both are the defaults
        every analytic uses, and both are stated rather than assumed because they change
        every denominator in the module.
        """
        ...


class RecomputeSummary(BaseModel):
    """What a recompute did, for the audit trail and for tests.

    Counts only: the point is to make an invisible write-path side effect observable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    offering_id: uuid.UUID
    assessment_id: uuid.UUID
    students_evaluated: int = Field(ge=0)
    flags_raised: int = Field(ge=0)
    flags_resolved: int = Field(ge=0)


@runtime_checkable
class RecomputeHook(Protocol):
    """Contract C4: re-derive analytics for one assessment, inside the caller's transaction."""

    def __call__(self, session: Session, assessment_id: uuid.UUID) -> RecomputeSummary:
        """Recompute derived rows and attention flags for ``assessment_id``'s offering.

        Must not commit, must not open its own session, and must be idempotent: calling it
        twice on unchanged data produces the same flags, because Agent 1's import confirm
        may be retried.
        """
        ...
