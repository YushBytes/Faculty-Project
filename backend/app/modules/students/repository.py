from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import ColumnElement, or_, select

from app.db.repository import BaseRepository
from app.modules.students.models import (
    Enrollment,
    EnrollmentStatus,
    Student,
    StudentSectionHistory,
)


class StudentRepository(BaseRepository[Student]):
    model = Student

    def get_visible(self, student_id: uuid.UUID, scope: ColumnElement[bool]) -> Student | None:
        return self.session.scalar(select(Student).where(Student.id == student_id, scope))

    def by_register_numbers(self, numbers: Iterable[str]) -> dict[str, Student]:
        rows = self.session.scalars(
            select(Student).where(Student.register_number.in_(list(numbers)))
        )
        return {s.register_number: s for s in rows.unique()}

    def emails_taken(self, emails: Iterable[str]) -> dict[str, str]:
        """email -> register_number for existing students holding those emails."""
        rows = self.session.execute(
            select(Student.email, Student.register_number).where(Student.email.in_(list(emails)))
        )
        return {e: r for e, r in rows}

    def list(
        self,
        *,
        limit: int,
        offset: int,
        scope: ColumnElement[bool],
        department_id: uuid.UUID | None = None,
        batch_year: int | None = None,
        section_id: uuid.UUID | None = None,
        offering_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        q: str | None = None,
    ) -> tuple[list[Student], int]:
        query = select(Student).where(scope)
        if department_id is not None:
            query = query.where(Student.department_id == department_id)
        if batch_year is not None:
            query = query.where(Student.batch_year == batch_year)
        if section_id is not None:
            query = query.where(Student.current_section_id == section_id)
        if offering_id is not None:
            query = query.where(
                Student.id.in_(
                    select(Enrollment.student_id).where(Enrollment.offering_id == offering_id)
                )
            )
        if is_active is not None:
            query = query.where(Student.is_active.is_(is_active))
        if q:
            pattern = f"%{q.strip()}%"
            query = query.where(
                or_(Student.register_number.ilike(pattern), Student.full_name.ilike(pattern))
            )
        return self.page(query, limit=limit, offset=offset, order_by=[Student.register_number])

    def active_in_section(self, section_id: uuid.UUID) -> list[Student]:
        return list(
            self.session.scalars(
                select(Student).where(
                    Student.current_section_id == section_id, Student.is_active.is_(True)
                )
            ).unique()
        )


class SectionHistoryRepository(BaseRepository[StudentSectionHistory]):
    model = StudentSectionHistory

    def open_entry(self, student_id: uuid.UUID) -> StudentSectionHistory | None:
        return self.session.scalar(
            select(StudentSectionHistory).where(
                StudentSectionHistory.student_id == student_id,
                StudentSectionHistory.ended_at.is_(None),
            )
        )

    def for_student(self, student_id: uuid.UUID) -> list[StudentSectionHistory]:
        return list(
            self.session.scalars(
                select(StudentSectionHistory)
                .where(StudentSectionHistory.student_id == student_id)
                .order_by(StudentSectionHistory.started_at)
            ).unique()
        )


class EnrollmentRepository(BaseRepository[Enrollment]):
    model = Enrollment

    def for_offering(
        self, offering_id: uuid.UUID, *, include_dropped: bool, include_inactive: bool
    ) -> list[Enrollment]:
        query = select(Enrollment).join(Student).where(Enrollment.offering_id == offering_id)
        if not include_dropped:
            query = query.where(Enrollment.status == EnrollmentStatus.ACTIVE)
        if not include_inactive:
            query = query.where(Student.is_active.is_(True))
        return list(self.session.scalars(query.order_by(Student.register_number)).unique())

    def by_student(self, offering_id: uuid.UUID) -> dict[uuid.UUID, Enrollment]:
        rows = self.session.scalars(select(Enrollment).where(Enrollment.offering_id == offering_id))
        return {e.student_id: e for e in rows.unique()}

    def get_pair(self, offering_id: uuid.UUID, student_id: uuid.UUID) -> Enrollment | None:
        return self.session.scalar(
            select(Enrollment).where(
                Enrollment.offering_id == offering_id, Enrollment.student_id == student_id
            )
        )
