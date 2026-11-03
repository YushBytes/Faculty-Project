import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.users.models import Role, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._session.scalar(select(User).where(User.email == email))

    def add(self, user: User) -> User:
        self._session.add(user)
        return user

    def list(
        self,
        *,
        limit: int,
        offset: int,
        role: Role | None = None,
        is_active: bool | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
    ) -> tuple[list[User], int]:
        query = select(User)
        if q:
            like = f"%{q.strip().lower()}%"
            query = query.where(
                func.lower(User.full_name).like(like)
                | User.email.like(like)
                | func.lower(func.coalesce(User.employee_code, "")).like(like)
            )
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if department_id is not None:
            query = query.where(User.department_id == department_id)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self._session.scalars(
            query.order_by(User.full_name, User.id).limit(limit).offset(offset)
        ).all()
        return list(items), total

    def count_active_admins(self) -> int:
        query = select(func.count()).where(User.role == Role.ADMIN, User.is_active.is_(True))
        return self._session.scalar(query) or 0
