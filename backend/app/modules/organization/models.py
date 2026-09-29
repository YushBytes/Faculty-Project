"""Academic structure: departments, terms, courses, sections and course offerings.

A course offering (course x term x section) is the unit of teaching, of faculty
assignment and therefore of faculty data-access scope.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.users.models import User


class Semester(StrEnum):
    """SRM's two semesters per academic year; a full-year view is the union of both."""

    ODD = "ODD"
    EVEN = "EVEN"


class CourseType(StrEnum):
    """SRM regulation 2021 course category, the last letter of the course code
    (21CSC201**J**). It decides the internal assessment scheme (see assessments/schemes.py)."""

    THEORY = "T"
    JOINT = "J"  # theory + lab
    PROJECT = "P"  # project based learning
    PRACTICAL = "L"
    NON_CREDIT = "M"


def course_type_from_code(code: str) -> CourseType | None:
    """``21DCS201P`` -> PROJECT. None when the code does not follow the SRM pattern."""
    last = code.strip().upper()[-1:] if code else ""
    try:
        return CourseType(last)
    except ValueError:
        return None


def _values(enum: type[StrEnum]) -> list[str]:
    return [m.value for m in enum]


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        CheckConstraint("code = upper(code) AND length(code) > 0", name="code_upper"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class AcademicTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "academic_terms"
    __table_args__ = (
        CheckConstraint("code = upper(code) AND length(code) > 0", name="code_upper"),
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        # At most one current term.
        Index(
            "uq_academic_terms_single_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)  # e.g. 2026-27
    # ODD / EVEN. Nullable for terms that are neither (e.g. a summer term).
    semester: Mapped[Semester | None] = mapped_column(
        Enum(Semester, name="semester", values_callable=_values)
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class Course(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("code = upper(code) AND length(code) > 0", name="code_upper"),
        CheckConstraint(
            "credits IS NULL OR (credits >= 0 AND credits <= 30)", name="credits_range"
        ),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    course_type: Mapped[CourseType | None] = mapped_column(
        Enum(CourseType, name="course_type", values_callable=_values)
    )

    department: Mapped[Department] = relationship(lazy="joined")
    coordinators: Mapped[list["CourseCoordinator"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", back_populates="course"
    )


class Section(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A cohort of students taught together (e.g. CSE 2025 batch, section A1)."""

    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("department_id", "batch_year", "name"),
        CheckConstraint("batch_year BETWEEN 2000 AND 2100", name="batch_year_range"),
        CheckConstraint("length(name) > 0", name="name_not_blank"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_year: Mapped[int] = mapped_column(Integer, nullable=False)  # admission year
    program: Mapped[str | None] = mapped_column(String(100))  # e.g. "B.Tech CSE"

    department: Mapped[Department] = relationship(lazy="joined")


class CourseOffering(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_offerings"
    __table_args__ = (
        UniqueConstraint("course_id", "term_id", "section_id"),
        CheckConstraint("pass_percent >= 0 AND pass_percent <= 100", name="pass_percent_range"),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="config_is_object"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    term_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_terms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pass_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("50.00"), server_default=text("50.00")
    )
    # Per-offering threshold overrides for analytics. Keys are defined by the analytics
    # layer; the platform only stores a JSON object.
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    course: Mapped[Course] = relationship(lazy="joined")
    term: Mapped[AcademicTerm] = relationship(lazy="joined")
    section: Mapped[Section] = relationship(lazy="joined")
    faculty_assignments: Mapped[list["OfferingFaculty"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", back_populates="offering"
    )


class OfferingFaculty(Base):
    """Faculty member assigned to teach an offering. Drives faculty data-access scope."""

    __tablename__ = "offering_faculty"

    offering_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_offerings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    offering: Mapped[CourseOffering] = relationship(back_populates="faculty_assignments")
    user: Mapped["User"] = relationship(lazy="joined")


class CourseCoordinator(Base):
    """A Course Coordinator owns a course across every section and term it is offered in.

    Assignment never touches results: changing the coordinator changes who can see and
    manage the course from now on, and the history of who did what stays in the audit log.
    """

    __tablename__ = "course_coordinators"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    course: Mapped[Course] = relationship(back_populates="coordinators")
    user: Mapped["User"] = relationship(lazy="joined", foreign_keys=[user_id])


class DepartmentSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Department-level key/value settings (e.g. analytics threshold defaults).

    The analytics layer defines the keys and interprets the values (contract C5:
    offering.config -> department setting -> built-in default). The platform only
    stores them.
    """

    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("department_id", "key"),
        CheckConstraint("key ~ '^[A-Za-z0-9_.-]{1,100}$'", name="key_format"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
