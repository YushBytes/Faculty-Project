import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.auth.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        self._session.flush()
        return token

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        # Row lock serialises concurrent refreshes of the same token, so it rotates once.
        query = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return self._session.scalar(query)

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def family_is_live(self, family_id: uuid.UUID) -> bool:
        """True while the session has an unrevoked token (it was not logged out or killed)."""
        query = select(RefreshToken.id).where(
            RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
        )
        return self._session.scalar(query.limit(1)) is not None
