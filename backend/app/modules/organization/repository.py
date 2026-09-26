import uuid

from sqlalchemy import ColumnElement, select

from app.db.repository import BaseRepository
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)


class DepartmentRepository(BaseRepository[Department]):
    model = Department

    def list(self, *, limit: int, offset: int) -> tuple[list[Department], int]:
        return self.page(select(Department), limit=limit, offset=offset, order_by=[Department.code])


class TermRepository(BaseRepository[AcademicTerm]):
    model = AcademicTerm

    def list(
        self, *, limit: int, offset: int, is_current: bool | None
    ) -> tuple[list[AcademicTerm], int]:
        query = select(AcademicTerm)
        if is_current is not None:
            query = query.where(AcademicTerm.is_current.is_(is_current))
        return self.page(
            query,
            limit=limit,
            offset=offset,
            order_by=[AcademicTerm.start_date.desc(), AcademicTerm.code],
        )

    def clear_current(self) -> None:
        for term in self.session.scalars(select(AcademicTerm).where(AcademicTerm.is_current)):
            term.is_current = False
        self.session.flush()


class CourseRepository(BaseRepository[Course]):
    model = Course

    def list(
        self, *, limit: int, offset: int, department_id: uuid.UUID | None, q: str | None
    ) -> tuple[list[Course], int]:
        query = select(Course)
        if department_id is not None:
            query = query.where(Course.department_id == department_id)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.where(Course.code.ilike(pattern) | Course.name.ilike(pattern))
        return self.page(query, limit=limit, offset=offset, order_by=[Course.code])


class SectionRepository(BaseRepository[Section]):
    model = Section

    def list(
        self,
        *,
        limit: int,
        offset: int,
        department_id: uuid.UUID | None,
        batch_year: int | None,
    ) -> tuple[list[Section], int]:
        query = select(Section)
        if department_id is not None:
            query = query.where(Section.department_id == department_id)
        if batch_year is not None:
            query = query.where(Section.batch_year == batch_year)
        return self.page(
            query,
            limit=limit,
            offset=offset,
            order_by=[Section.batch_year.desc(), Section.name],
        )


class OfferingRepository(BaseRepository[CourseOffering]):
    model = CourseOffering

    def list(
        self,
        *,
        limit: int,
        offset: int,
        scope: ColumnElement[bool],
        term_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        section_id: uuid.UUID | None = None,
        faculty_id: uuid.UUID | None = None,
    ) -> tuple[list[CourseOffering], int]:
        query = select(CourseOffering).where(scope)
        if term_id is not None:
            query = query.where(CourseOffering.term_id == term_id)
        if course_id is not None:
            query = query.where(CourseOffering.course_id == course_id)
        if section_id is not None:
            query = query.where(CourseOffering.section_id == section_id)
        if faculty_id is not None:
            query = query.where(
                CourseOffering.id.in_(
                    select(OfferingFaculty.offering_id).where(OfferingFaculty.user_id == faculty_id)
                )
            )
        return self.page(
            query,
            limit=limit,
            offset=offset,
            order_by=[CourseOffering.created_at.desc(), CourseOffering.id],
        )

    def get_visible(
        self, offering_id: uuid.UUID, scope: ColumnElement[bool]
    ) -> CourseOffering | None:
        return self.session.scalar(
            select(CourseOffering).where(CourseOffering.id == offering_id, scope)
        )

    def assignment(self, offering_id: uuid.UUID, user_id: uuid.UUID) -> OfferingFaculty | None:
        return self.session.get(OfferingFaculty, (offering_id, user_id))
