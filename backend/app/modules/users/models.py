import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    """The institutional hierarchy, highest first.

    ADMIN                one per institution; everything
    HOD                  one per department; the whole department
    ACADEMIC_HEAD        one per department; academic coordination across its courses
    COURSE_COORDINATOR   owns one or more courses (``course_coordinators``) across all sections
    FACULTY              teaches offerings (``offering_faculty``)

    Scope is resolved server-side in ``organization/scope.py``; nothing here is authorisation.
    """

    ADMIN = "ADMIN"
    HOD = "HOD"
    ACADEMIC_HEAD = "ACADEMIC_HEAD"
    COURSE_COORDINATOR = "COURSE_COORDINATOR"
    FACULTY = "FACULTY"


ROLE_RANK = {
    Role.ADMIN: 0,
    Role.HOD: 1,
    Role.ACADEMIC_HEAD: 2,
    Role.COURSE_COORDINATOR: 3,
    Role.FACULTY: 4,
}
DEPARTMENT_ROLES = frozenset(
    (Role.HOD, Role.ACADEMIC_HEAD, Role.COURSE_COORDINATOR)
)  # must belong to a department
TEACHING_ROLES = frozenset(
    (Role.FACULTY, Role.COURSE_COORDINATOR, Role.ACADEMIC_HEAD, Role.HOD)
)  # may be assigned to teach an offering


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are stored normalised so the unique index is case-insensitive in effect.
        CheckConstraint("email = lower(btrim(email))", name="email_normalised"),
        CheckConstraint("length(full_name) > 0", name="full_name_not_blank"),
        CheckConstraint("role <> 'HOD' OR department_id IS NOT NULL", name="hod_has_department"),
        CheckConstraint(
            "role NOT IN ('ACADEMIC_HEAD', 'COURSE_COORDINATOR') OR department_id IS NOT NULL",
            name="department_role_has_department",
        ),
        # Exactly one active HOD and one active Academic Head per department.
        Index(
            "uq_users_department_head",
            "department_id",
            "role",
            unique=True,
            postgresql_where=text("role IN ('HOD', 'ACADEMIC_HEAD') AND is_active"),
        ),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Institutional staff id (the faculty id printed on SRM TLP reports).
    employee_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    designation: Mapped[str | None] = mapped_column(String(100))
    # HOD / ACADEMIC_HEAD / COURSE_COORDINATOR: their department (required).
    # FACULTY: home department (optional).
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
