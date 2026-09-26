import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.pagination import Page, PageParams
from app.core.security import hash_password
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserRead, UserUpdate


def normalise_email(email: str) -> str:
    return email.strip().lower()


class UserService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    def create_user(self, data: UserCreate) -> User:
        email = normalise_email(data.email)
        if self._users.get_by_email(email) is not None:
            raise ConflictError(f"A user with email '{email}' already exists.")
        user = User(
            email=email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            role=data.role,
            is_active=True,
        )
        try:
            self._users.add(user)
        except IntegrityError as exc:  # concurrent insert of the same email
            self._session.rollback()
            raise ConflictError(f"A user with email '{email}' already exists.") from exc
        self._session.commit()
        return user

    def get_user(self, user_id: uuid.UUID) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    def list_users(
        self, page: PageParams, *, role: Role | None, is_active: bool | None
    ) -> Page[UserRead]:
        items, total = self._users.list(
            limit=page.limit, offset=page.offset, role=role, is_active=is_active
        )
        return Page[UserRead](
            items=[UserRead.model_validate(u) for u in items],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )

    def update_user(self, user_id: uuid.UUID, data: UserUpdate, *, actor: User) -> User:
        user = self.get_user(user_id)
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.role is not None and data.role != user.role:
            self._guard_last_admin(user, actor, action="change the role of")
            user.role = data.role
        if data.password is not None:
            user.password_hash = hash_password(data.password)
            self._tokens.revoke_all_for_user(user.id, datetime.now(UTC))
        self._session.commit()
        return user

    def deactivate_user(self, user_id: uuid.UUID, *, actor: User) -> User:
        user = self.get_user(user_id)
        if user.id == actor.id:
            raise BusinessRuleError("You cannot deactivate your own account.")
        if user.is_active:
            self._guard_last_admin(user, actor, action="deactivate")
            user.is_active = False
            self._tokens.revoke_all_for_user(user.id, datetime.now(UTC))
            self._session.commit()
        return user

    def activate_user(self, user_id: uuid.UUID) -> User:
        user = self.get_user(user_id)
        if not user.is_active:
            user.is_active = True
            self._session.commit()
        return user

    def _guard_last_admin(self, user: User, actor: User, *, action: str) -> None:
        if user.role is not Role.ADMIN:
            return
        if user.id == actor.id:
            raise BusinessRuleError(f"You cannot {action} your own administrator account.")
        if user.is_active and self._users.count_active_admins() <= 1:
            raise BusinessRuleError(f"Cannot {action} the last active administrator.")
