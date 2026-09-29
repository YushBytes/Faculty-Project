"""All SQL for persisted attention flags. Never commits (README rule 1)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db.repository import BaseRepository
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.attention.models import LIVE_FLAG_STATUSES, AttentionFlag


class AttentionFlagRepository(BaseRepository[AttentionFlag]):
    model = AttentionFlag

    def live_for_offering(self, offering_id: uuid.UUID) -> list[AttentionFlag]:
        """Every flag of this offering that still stands, open or acknowledged.

        One query per recompute: the synchroniser needs the whole live set to decide what to
        update and what to resolve, and asking per student would be one round trip per student.
        """
        return list(
            self.session.scalars(
                select(AttentionFlag)
                .where(
                    AttentionFlag.offering_id == offering_id,
                    AttentionFlag.status.in_(LIVE_FLAG_STATUSES),
                )
                .order_by(AttentionFlag.student_id, AttentionFlag.rule_code)
            ).all()
        )

    def live_index(
        self, offering_id: uuid.UUID
    ) -> dict[tuple[uuid.UUID, AttentionRuleCode], AttentionFlag]:
        """``(student, rule) -> live flag``. The key the unique index also enforces."""
        return {(row.student_id, row.rule_code): row for row in self.live_for_offering(offering_id)}

    def for_students(
        self, offering_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
    ) -> list[AttentionFlag]:
        """Live flags for named students of one offering, for freezing intervention reasons."""
        if not student_ids:
            return []
        return list(
            self.session.scalars(
                select(AttentionFlag).where(
                    AttentionFlag.offering_id == offering_id,
                    AttentionFlag.student_id.in_(student_ids),
                    AttentionFlag.status.in_(LIVE_FLAG_STATUSES),
                )
            ).all()
        )
