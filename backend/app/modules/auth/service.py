import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.service import normalise_email

INVALID_CREDENTIALS = "Invalid email or password."
INVALID_REFRESH = "Invalid or expired refresh token."


class AuthService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    def login(self, email: str, password: str) -> TokenPair:
        user = self._users.get_by_email(normalise_email(email))
        # verify_password always runs (against a dummy hash when user is None) to keep
        # timing uniform; inactive accounts get the same generic message.
        password_ok = verify_password(password, user.password_hash if user else None)
        if user is None or not password_ok or not user.is_active:
            raise AuthenticationError(INVALID_CREDENTIALS)

        now = datetime.now(UTC)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = now
        pair = self._issue(user, family_id=uuid.uuid4(), now=now)[0]
        self._session.commit()
        return pair

    def refresh(self, refresh_token: str) -> TokenPair:
        now = datetime.now(UTC)
        current = self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if current is None:
            raise AuthenticationError(INVALID_REFRESH)

        if current.revoked_at is not None:
            # A rotated/revoked token was replayed: assume theft, kill the whole session.
            self._tokens.revoke_family(current.family_id, now)
            self._session.commit()
            raise AuthenticationError("Refresh token reuse detected; the session was revoked.")

        if current.expires_at <= now:
            raise AuthenticationError(INVALID_REFRESH)

        user = self._users.get(current.user_id)
        if user is None or not user.is_active:
            self._tokens.revoke_family(current.family_id, now)
            self._session.commit()
            raise AuthenticationError(INVALID_REFRESH)

        pair, new_token = self._issue(user, family_id=current.family_id, now=now)
        current.revoked_at = now
        current.replaced_by_id = new_token.id
        self._session.commit()
        return pair

    def logout(self, refresh_token: str) -> None:
        """Revoke the session this refresh token belongs to. Idempotent; never reveals
        whether the token existed."""
        current = self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if current is not None:
            self._tokens.revoke_family(current.family_id, datetime.now(UTC))
            self._session.commit()

    def authenticate(self, access_token: str) -> User:
        try:
            claims = decode_access_token(access_token)
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid or expired access token.") from exc
        user = self._users.get(claims.user_id)
        # Checked on every request so deactivation takes effect immediately.
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid or expired access token.")
        return user

    def _issue(
        self, user: User, *, family_id: uuid.UUID, now: datetime
    ) -> tuple[TokenPair, RefreshToken]:
        settings = get_settings()
        access_token, access_exp = create_access_token(user.id, user.role.value)
        raw_refresh = generate_refresh_token()
        refresh_exp = now + timedelta(days=settings.refresh_token_expire_days)
        token = self._tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh),
                family_id=family_id,
                expires_at=refresh_exp,
            )
        )
        pair = TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            access_token_expires_at=access_exp,
            refresh_token_expires_at=refresh_exp,
        )
        return pair, token
