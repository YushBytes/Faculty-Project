"""Materialising the engine's attention verdict into ``attention_flags``.

The engine decides; this synchronises. Given the flags that fire *now* for one offering, it
brings the stored live set into agreement with them:

======================================  ===========================================
fires now, no live row                  insert, ``status = open``
fires now, live row exists              update the value/threshold/message in place
live row exists, no longer fires        ``status = resolved``, stamp ``resolved_at``
======================================  ===========================================

Three properties this shape buys, each of which the alternatives lose:

*Idempotence.* Running it twice on unchanged data updates the same rows and inserts nothing,
so a retried import confirm cannot double-flag a student. The partial unique index on
``(offering_id, student_id, rule_code) WHERE status <> 'resolved'`` makes that a database
guarantee rather than a hope about interleaving.

*History.* A flag that stops firing is resolved, not deleted, which is what PROJECT_CONTEXT D6
asks for. Delete-and-reinsert would be less code and would erase the record that a student was
ever flagged.

*Acknowledgement survives.* A flag a faculty member has acknowledged and which still fires
stays ``acknowledged``; only the numbers move. Re-raising it as ``open`` would silently undo
their reading of it on the next results entry.

Never commits: the caller's transaction owns the boundary (decision D-003), so recomputed
flags land with the results that caused them or not at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.modules.analytics.core.outputs import AttentionFlag as FlagContract
from app.modules.analytics.core.outputs import StudentAttention
from app.modules.analytics.core.rules import AttentionRuleCode, FlagStatus
from app.modules.attention.models import AttentionFlag
from app.modules.attention.repository import AttentionFlagRepository


class SyncCounts(BaseModel):
    """What one synchronisation did. Makes an invisible write-path side effect observable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raised: int = Field(ge=0)
    """Flags that were not standing before and are now."""

    updated: int = Field(ge=0)
    """Flags that were already standing and still fire; their values were refreshed."""

    resolved: int = Field(ge=0)
    """Flags that were standing and no longer fire."""


class AttentionSyncService:
    """Writes the engine's verdict into ``attention_flags``. Does not evaluate, does not commit."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._flags = AttentionFlagRepository(session)

    def synchronize(
        self,
        offering_id: uuid.UUID,
        attentions: Sequence[StudentAttention],
        *,
        computed_at: datetime,
        triggered_by_assessment_id: uuid.UUID | None = None,
    ) -> SyncCounts:
        """Bring stored live flags into agreement with ``attentions``.

        ``attentions`` is the engine's output for **this offering only**; a flag for another
        offering is a programming error and is rejected rather than written somewhere odd.
        """
        current: dict[tuple[uuid.UUID, AttentionRuleCode], FlagContract] = {}
        for entry in attentions:
            for flag in entry.flags:
                if flag.offering_id != offering_id:
                    raise ValueError(
                        f"flag for offering {flag.offering_id} cannot be synchronised into "
                        f"offering {offering_id}"
                    )
                current[(flag.student_id, flag.rule_code)] = flag

        live = self._flags.live_index(offering_id)
        raised = updated = resolved = 0

        for key, row in live.items():
            flag = current.get(key)
            if flag is None:
                row.status = FlagStatus.RESOLVED
                row.resolved_at = computed_at
                resolved += 1
            else:
                self._refresh(row, flag, computed_at, triggered_by_assessment_id)
                updated += 1

        for key, flag in current.items():
            if key in live:
                continue
            self._flags.add(self._new_row(flag, computed_at, triggered_by_assessment_id))
            raised += 1

        # Flush inside the caller's transaction so a constraint violation surfaces here, at the
        # point that caused it, rather than at their commit.
        self._session.flush()
        return SyncCounts(raised=raised, updated=updated, resolved=resolved)

    # ------------------------------------------------------------------ mapping

    @staticmethod
    def _new_row(
        flag: FlagContract, computed_at: datetime, triggered_by_assessment_id: uuid.UUID | None
    ) -> AttentionFlag:
        row = AttentionFlag(
            offering_id=flag.offering_id,
            student_id=flag.student_id,
            rule_code=flag.rule_code,
            status=FlagStatus.OPEN,
        )
        AttentionSyncService._refresh(row, flag, computed_at, triggered_by_assessment_id)
        return row

    @staticmethod
    def _refresh(
        row: AttentionFlag,
        flag: FlagContract,
        computed_at: datetime,
        triggered_by_assessment_id: uuid.UUID | None,
    ) -> None:
        """Copy the decision onto a row. ``created_at`` and ``status`` are deliberately untouched.

        The contract guarantees ``flag.actual.is_ok`` and that either a threshold or the pass
        mark is quoted, so the not-null and check constraints on those columns cannot be reached
        from a valid flag.
        """
        row.severity = flag.severity
        row.actual_value = flag.actual.value
        row.actual_unit = flag.actual.unit
        row.actual_n = flag.actual.n
        row.threshold_key = flag.threshold.key if flag.threshold else None
        row.threshold_value = flag.threshold.value if flag.threshold else None
        row.threshold_source = flag.threshold.source if flag.threshold else None
        row.pass_mark_percent = flag.pass_mark_percent
        row.reference_assessments = list(flag.reference_assessments)
        row.message = flag.message
        row.computed_at = computed_at
        row.triggered_by_assessment_id = triggered_by_assessment_id
