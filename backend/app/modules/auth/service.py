import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    AuthenticationError,
    BusinessRuleError,
    RoleMismatchError,
    TooManyAttemptsError,
)
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
from app.core.throttle import login_throttle
from app.modules.audit.service import AuditService
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.service import normalise_email

INVALID_CREDENTIALS = "Invalid email or password."
INVALID_REFRESH = "Invalid or expired refresh token."
ROLE_MISMATCH = "The selected role does not match your account. Please choose your assigned role."


class AuthService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    def login(self, email: str, password: str, role: Role | None = None) -> TokenPair:
        """Sign in. ``role`` is an optional confirmation from the sign-in page: when given, it
        must equal the stored role, checked only after the password, and a mismatch issues no
        tokens. It is never used for anything else; the tokens and every permission come from
        the stored user."""
        key = normalise_email(email)
        wait = login_throttle.retry_after(key)
        if wait is not None:
            # Refused before the password is checked, so guessing cannot continue.
            raise TooManyAttemptsError(
                f"Too many failed sign-in attempts for this account. Try again in "
                f"{(wait + 59) // 60} minute(s), or ask an administrator to reset the password.",
                retry_after=wait,
            )
        user = self._users.get_by_email(key)
        # verify_password always runs (against a dummy hash when user is None) to keep
        # timing uniform; inactive accounts get the same generic message.
        password_ok = verify_password(password, user.password_hash if user else None)
        if user is None or not password_ok or not user.is_active:
            login_throttle.failed(key)
            raise AuthenticationError(INVALID_CREDENTIALS)
        if role is not None and role != user.role:
            # Counted like a wrong password, so it cannot be used to probe without limit.
            login_throttle.failed(key)
            raise RoleMismatchError(ROLE_MISMATCH)
        login_throttle.succeeded(key)

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
            if self._is_concurrent_rotation(current, now):
                # Two tabs (or a reload) refreshed with the same cookie at the same moment.
                # The loser gets its own token in the same, still-live session.
                user = self._users.get(current.user_id)
                if user is not None and user.is_active:
                    pair = self._issue(user, family_id=current.family_id, now=now)[0]
                    self._session.commit()
                    return pair
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

    def _is_concurrent_rotation(self, token: RefreshToken, now: datetime) -> bool:
        """A token rotated moments ago, in a session that is still live, is a benign race
        between concurrent refreshes rather than a replay. Logged-out or killed sessions
        (no live token left) and anything older than the grace window stay a replay."""
        grace = get_settings().refresh_reuse_grace_seconds
        return (
            grace > 0
            and token.replaced_by_id is not None
            and token.revoked_at is not None
            and now - token.revoked_at <= timedelta(seconds=grace)
            and self._tokens.family_is_live(token.family_id)
        )

    def logout(self, refresh_token: str) -> None:
        """Revoke the session this refresh token belongs to. Idempotent; never reveals
        whether the token existed."""
        current = self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if current is not None:
            self._tokens.revoke_family(current.family_id, datetime.now(UTC))
            self._session.commit()

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        """Self-service password change. Signs the person out of every session (all refresh
        tokens are revoked), so a password that leaked stops working everywhere at once."""
        if not verify_password(current_password, user.password_hash):
            raise BusinessRuleError(
                "The current password is not correct.",
                details=[{"loc": ["body", "current_password"], "message": "Incorrect password."}],
            )
        if new_password == current_password:
            raise BusinessRuleError(
                "The new password must be different from the current one.",
                details=[{"loc": ["body", "new_password"], "message": "Same as current."}],
            )
        user.password_hash = hash_password(new_password)
        self._tokens.revoke_all_for_user(user.id, datetime.now(UTC))
        AuditService(self._session).record(
            actor_id=user.id, entity="user", entity_id=user.id, action="password_change"
        )
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
