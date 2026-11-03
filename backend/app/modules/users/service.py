"""User administration across the hierarchy.

Who may manage whom (server-side; the UI only mirrors it):

    ADMIN          everyone. There is exactly one active administrator.
    HOD            staff of their own department: Academic Head, Course Coordinators, Faculty
    ACADEMIC_HEAD  Course Coordinators and Faculty of their own department (role changes
                   between the two, i.e. appointing coordinators)
    others         nobody

Looking users up (to assign someone to teach or coordinate) is open to ADMIN, HOD,
ACADEMIC_HEAD and COURSE_COORDINATOR; FACULTY cannot browse staff.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.pagination import Page, PageParams
from app.core.security import hash_password
from app.db.repository import write_guard
from app.modules.audit.service import AuditService
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.organization.models import CourseCoordinator, Department
from app.modules.users.models import DEPARTMENT_ROLES, Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserRead, UserUpdate

MANAGEABLE_BY: dict[Role, frozenset[Role]] = {
    Role.HOD: frozenset((Role.ACADEMIC_HEAD, Role.COURSE_COORDINATOR, Role.FACULTY)),
    Role.ACADEMIC_HEAD: frozenset((Role.COURSE_COORDINATOR, Role.FACULTY)),
}
LOOKUP_ROLES = frozenset((Role.ADMIN, Role.HOD, Role.ACADEMIC_HEAD, Role.COURSE_COORDINATOR))
HEAD_CONFLICT = "That department already has an active {role}; deactivate or reassign them first."


def normalise_email(email: str) -> str:
    return email.strip().lower()


class UserService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)
        self._audit = AuditService(session)

    # ------------------------------------------------------------ permissions

    @staticmethod
    def can_look_up(actor: User) -> bool:
        return actor.role in LOOKUP_ROLES

    def _require_lookup(self, actor: User | None) -> None:
        if actor is not None and not self.can_look_up(actor):
            raise PermissionDeniedError("You do not have permission to perform this action.")

    def _require_manage(
        self,
        actor: User | None,
        *,
        target_role: Role,
        department_id: uuid.UUID | None,
        current: User | None = None,
    ) -> None:
        """Raise unless ``actor`` may create/modify a user with this role in this department.

        ``actor=None`` is the operator path (CLI), which is trusted.
        """
        if actor is None or actor.role is Role.ADMIN:
            return
        allowed = MANAGEABLE_BY.get(actor.role)
        if (
            allowed is None
            or target_role not in allowed
            or department_id != actor.department_id
            or (current is not None and current.role not in allowed)
            or (current is not None and current.department_id != actor.department_id)
        ):
            raise PermissionDeniedError(
                "You can only manage staff below you in your own department."
            )

    # ------------------------------------------------------------ writes

    def create_user(self, data: UserCreate, *, actor: User | None = None) -> User:
        email = normalise_email(data.email)
        department_id = data.department_id
        if actor is not None and actor.role is not Role.ADMIN and department_id is None:
            department_id = actor.department_id
        self._require_manage(actor, target_role=data.role, department_id=department_id)
        if self._users.get_by_email(email) is not None:
            raise ConflictError(f"A user with email '{email}' already exists.")
        self._check_department(data.role, department_id)
        self._check_single_admin(data.role)
        user = User(
            email=email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            role=data.role,
            department_id=department_id,
            employee_code=data.employee_code,
            designation=data.designation,
            is_active=True,
        )
        conflict = self._conflict_message(email, data.role, data.employee_code)
        with write_guard(self._session, conflict=conflict):
            self._users.add(user)
        if actor is not None:
            self._audit.record(
                actor_id=actor.id,
                entity="user",
                entity_id=user.id,
                action="create",
                new={"role": user.role, "department_id": user.department_id, "email": email},
            )
        self._session.commit()
        return user

    def get_user(self, user_id: uuid.UUID, *, actor: User | None = None) -> User:
        self._require_lookup(actor)
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    def list_users(
        self,
        page: PageParams,
        *,
        role: Role | None,
        is_active: bool | None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        actor: User | None = None,
    ) -> Page[UserRead]:
        self._require_lookup(actor)
        items, total = self._users.list(
            limit=page.limit,
            offset=page.offset,
            role=role,
            is_active=is_active,
            department_id=department_id,
            q=q,
        )
        return Page[UserRead](
            items=[UserRead.model_validate(u) for u in items],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )

    def update_user(self, user_id: uuid.UUID, data: UserUpdate, *, actor: User) -> User:
        user = self.get_user(user_id)
        # Validate the resulting state first; mutate only once everything is valid.
        new_role = data.role if data.role is not None else user.role
        new_department = (
            data.department_id if "department_id" in data.model_fields_set else user.department_id
        )
        self._require_manage(
            actor, target_role=new_role, department_id=new_department, current=user
        )
        if new_role != user.role:
            self._guard_last_admin(user, actor, action="change the role of")
            self._check_single_admin(new_role)
        self._check_department(new_role, new_department)
        before = {"role": user.role, "department_id": user.department_id}
        conflict = self._conflict_message(user.email, new_role, data.employee_code)
        # Every change happens inside the savepoint, so a second HOD / Academic Head or a
        # duplicate staff id is a clean 409 and leaves the session usable.
        with write_guard(self._session, conflict=conflict):
            if data.full_name is not None:
                user.full_name = data.full_name
            if "employee_code" in data.model_fields_set:
                user.employee_code = data.employee_code
            if "designation" in data.model_fields_set:
                user.designation = data.designation
            user.role = new_role
            user.department_id = new_department
            self._session.flush()
        after = {"role": user.role, "department_id": user.department_id}
        if before["role"] is Role.COURSE_COORDINATOR and new_role is not Role.COURSE_COORDINATOR:
            # A former coordinator no longer owns courses; the audit row keeps the history.
            self._session.execute(
                delete(CourseCoordinator).where(CourseCoordinator.user_id == user.id)
            )
        if after != before:
            self._audit.record(
                actor_id=actor.id,
                entity="user",
                entity_id=user.id,
                action="update",
                old=before,
                new=after,
            )
        if data.password is not None:
            user.password_hash = hash_password(data.password)
            self._tokens.revoke_all_for_user(user.id, datetime.now(UTC))
            self._audit.record(
                actor_id=actor.id, entity="user", entity_id=user.id, action="password_reset"
            )
        self._session.commit()
        return user

    def deactivate_user(self, user_id: uuid.UUID, *, actor: User) -> User:
        user = self.get_user(user_id)
        self._require_manage(
            actor, target_role=user.role, department_id=user.department_id, current=user
        )
        if user.id == actor.id:
            raise BusinessRuleError("You cannot deactivate your own account.")
        if user.is_active:
            self._guard_last_admin(user, actor, action="deactivate")
            user.is_active = False
            self._tokens.revoke_all_for_user(user.id, datetime.now(UTC))
            self._audit.record(
                actor_id=actor.id, entity="user", entity_id=user.id, action="deactivate"
            )
            self._session.commit()
        return user

    def activate_user(self, user_id: uuid.UUID, *, actor: User | None = None) -> User:
        user = self.get_user(user_id)
        self._require_manage(
            actor, target_role=user.role, department_id=user.department_id, current=user
        )
        if not user.is_active:
            self._check_single_admin(user.role)
            with write_guard(
                self._session,
                conflict=self._conflict_message(user.email, user.role, user.employee_code),
            ):
                user.is_active = True
                self._session.flush()
            self._audit.record(
                actor_id=actor.id if actor else None,
                entity="user",
                entity_id=user.id,
                action="activate",
            )
            self._session.commit()
        return user

    # ------------------------------------------------------------ rules

    def _check_department(self, role: Role, department_id: uuid.UUID | None) -> None:
        if department_id is not None and self._session.get(Department, department_id) is None:
            raise NotFoundError("Department not found.")
        if role in DEPARTMENT_ROLES and department_id is None:
            label = {Role.HOD: "An HOD"}.get(role, f"A {role.value.replace('_', ' ').title()}")
            raise BusinessRuleError(f"{label} must belong to a department.")

    def _check_single_admin(self, role: Role) -> None:
        if role is Role.ADMIN and self._users.count_active_admins() >= 1:
            raise ConflictError("There is exactly one administrator; transfer the role instead.")

    @staticmethod
    def _conflict_message(email: str, role: Role, employee_code: str | None) -> str:
        if role in (Role.HOD, Role.ACADEMIC_HEAD):
            name = "HOD" if role is Role.HOD else "Academic Head"
            return HEAD_CONFLICT.format(role=name) + (
                f" (or email '{email}' / staff id '{employee_code}' is already in use)"
                if employee_code
                else f" (or email '{email}' is already in use)"
            )
        if employee_code:
            return f"Email '{email}' or staff id '{employee_code}' is already in use."
        return f"A user with email '{email}' already exists."

    def _guard_last_admin(self, user: User, actor: User, *, action: str) -> None:
        if user.role is not Role.ADMIN:
            return
        if user.id == actor.id:
            raise BusinessRuleError(f"You cannot {action} your own administrator account.")
        if user.is_active and self._users.count_active_admins() <= 1:
            raise BusinessRuleError(f"Cannot {action} the last active administrator.")
