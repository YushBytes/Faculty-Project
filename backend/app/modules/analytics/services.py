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
from app.modules.users.models import User


@runtime_checkable
class SnapshotSource(Protocol):
    """Supplies the one input every analytic reads.

    The implementation reads through the platform's own services/repositories (README rule
    4), so faculty scope and PII rules are enforced once, where the data lives, rather than
    re-derived here. :class:`app.modules.analytics.repository.AnalyticsRepository` is it.

    The signature changed in Phase 3, when the platform's read interface (contract C3) was
    delivered, for two reasons worth stating:

    * the session belongs to the implementation, not the call — every platform service in
      this codebase takes it in ``__init__`` (decision D-001), so analytics matches;
    * scope needs the **actor**. ``OfferingResultsService.for_user`` turns an offering the
      user may not see into a 404, which is the behaviour contract C6 requires, and a port
      with nowhere to put the user would have quietly pushed that decision upwards.
    """

    def snapshot_for_offering(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User | None = None,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingSnapshot:
        """Build the snapshot for one offering.

        ``actor`` is the user the read is for: out of their scope is a 404. ``None`` means
        **no access check** and is only for system work with no user — the recompute hook.
        Never pass ``None`` with an id that came from a request.

        ``published_only`` excludes assessments faculty have created but not published;
        ``include_dropped`` brings withdrawn enrolments back into the cohort (with
        ``is_active`` false, so the engine still leaves them out of class statistics). Both
        are stated rather than assumed because they change every denominator in the module.
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

    def __call__(self, session: Session, assessment_id: uuid.UUID) -> None:
        """Recompute derived rows and attention flags for ``assessment_id``'s offering.

        Returns ``None``, matching the platform's installed type
        (``app.core.recompute.RecomputeFn``): the write path ignores any value, and agreeing
        with the signature it is installed against is worth more than a return nobody reads.
        An implementation that wants the counts computes a :class:`RecomputeSummary`
        internally and logs or discards it.

        Must not commit, must not open its own session, and must be idempotent: calling it
        twice on unchanged data produces the same flags, because Agent 1's import confirm
        may be retried.
        """
        ...
