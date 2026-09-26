import uuid

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.pagination import Page, PageParams
from app.db.repository import write_guard
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.organization.repository import (
    CourseRepository,
    DepartmentRepository,
    OfferingRepository,
    SectionRepository,
    TermRepository,
)
from app.modules.organization.schemas import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    FacultySummary,
    OfferingCreate,
    OfferingRead,
    OfferingUpdate,
    SectionCreate,
    SectionRead,
    SectionUpdate,
    TermCreate,
    TermRead,
    TermUpdate,
)
from app.modules.organization.scope import (
    Access,
    OfferingAccess,
    can_manage_department,
    visible_offerings,
)
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository


def _apply(entity: object, changes: dict) -> None:
    for field, value in changes.items():
        setattr(entity, field, value)


def _require_department_manager(user: User, department_id: uuid.UUID) -> None:
    if not can_manage_department(user, department_id):
        raise PermissionDeniedError("You can only manage records of your own department.")


def offering_read(offering: CourseOffering) -> OfferingRead:
    faculty = sorted(
        (FacultySummary.model_validate(a.user) for a in offering.faculty_assignments),
        key=lambda f: f.full_name,
    )
    return OfferingRead.model_validate(
        {
            "id": offering.id,
            "course": offering.course,
            "term": offering.term,
            "section": offering.section,
            "pass_mark_percent": offering.pass_mark_percent,
            "faculty": faculty,
            "created_at": offering.created_at,
            "updated_at": offering.updated_at,
        }
    )


class DepartmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = DepartmentRepository(session)

    def get(self, department_id: uuid.UUID) -> Department:
        department = self._repo.get(department_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    def list(self, page: PageParams) -> Page[DepartmentRead]:
        items, total = self._repo.list(limit=page.limit, offset=page.offset)
        return Page[DepartmentRead](
            items=[DepartmentRead.model_validate(d) for d in items],
            total=total,
            **page.model_dump(),
        )

    def create(self, data: DepartmentCreate) -> Department:
        with write_guard(self._session, conflict=f"Department code '{data.code}' already exists."):
            department = self._repo.add(Department(**data.model_dump()))
        self._session.commit()
        return department

    def update(self, department_id: uuid.UUID, data: DepartmentUpdate) -> Department:
        department = self.get(department_id)
        with write_guard(self._session, conflict=f"Department code '{data.code}' already exists."):
            _apply(department, data.model_dump(exclude_unset=True, exclude_none=True))
        self._session.commit()
        return department

    def delete(self, department_id: uuid.UUID) -> None:
        department = self.get(department_id)
        with write_guard(
            self._session,
            in_use="Department still has courses, sections or users; reassign them first.",
        ):
            self._repo.delete(department)
        self._session.commit()


class TermService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = TermRepository(session)

    def get(self, term_id: uuid.UUID) -> AcademicTerm:
        term = self._repo.get(term_id)
        if term is None:
            raise NotFoundError("Academic term not found.")
        return term

    def list(self, page: PageParams, *, is_current: bool | None) -> Page[TermRead]:
        items, total = self._repo.list(limit=page.limit, offset=page.offset, is_current=is_current)
        return Page[TermRead](
            items=[TermRead.model_validate(t) for t in items], total=total, **page.model_dump()
        )

    def create(self, data: TermCreate) -> AcademicTerm:
        with write_guard(self._session, conflict=f"Term code '{data.code}' already exists."):
            if data.is_current:
                self._repo.clear_current()
            term = self._repo.add(AcademicTerm(**data.model_dump()))
        self._session.commit()
        return term

    def update(self, term_id: uuid.UUID, data: TermUpdate) -> AcademicTerm:
        term = self.get(term_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        start = changes.get("start_date", term.start_date)
        end = changes.get("end_date", term.end_date)
        if end <= start:
            raise BusinessRuleError("end_date must be after start_date.")
        with write_guard(self._session, conflict=f"Term code '{data.code}' already exists."):
            if changes.get("is_current") and not term.is_current:
                self._repo.clear_current()
            _apply(term, changes)
        self._session.commit()
        return term

    def delete(self, term_id: uuid.UUID) -> None:
        term = self.get(term_id)
        with write_guard(self._session, in_use="Term has course offerings; delete those first."):
            self._repo.delete(term)
        self._session.commit()


class CourseService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CourseRepository(session)
        self._departments = DepartmentService(session)

    def get(self, course_id: uuid.UUID) -> Course:
        course = self._repo.get(course_id)
        if course is None:
            raise NotFoundError("Course not found.")
        return course

    def list(
        self, page: PageParams, *, department_id: uuid.UUID | None, q: str | None
    ) -> Page[CourseRead]:
        items, total = self._repo.list(
            limit=page.limit, offset=page.offset, department_id=department_id, q=q
        )
        return Page[CourseRead](
            items=[CourseRead.model_validate(c) for c in items], total=total, **page.model_dump()
        )

    def create(self, data: CourseCreate, *, actor: User) -> Course:
        self._departments.get(data.department_id)
        _require_department_manager(actor, data.department_id)
        with write_guard(self._session, conflict=f"Course code '{data.code}' already exists."):
            course = self._repo.add(Course(**data.model_dump()))
        self._session.commit()
        self._session.refresh(course)
        return course

    def update(self, course_id: uuid.UUID, data: CourseUpdate, *, actor: User) -> Course:
        course = self.get(course_id)
        _require_department_manager(actor, course.department_id)
        with write_guard(self._session, conflict=f"Course code '{data.code}' already exists."):
            _apply(course, data.model_dump(exclude_unset=True, exclude_none=True))
        self._session.commit()
        return course

    def delete(self, course_id: uuid.UUID, *, actor: User) -> None:
        course = self.get(course_id)
        _require_department_manager(actor, course.department_id)
        with write_guard(self._session, in_use="Course has offerings; delete those first."):
            self._repo.delete(course)
        self._session.commit()


class SectionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = SectionRepository(session)
        self._departments = DepartmentService(session)

    def get(self, section_id: uuid.UUID) -> Section:
        section = self._repo.get(section_id)
        if section is None:
            raise NotFoundError("Section not found.")
        return section

    def list(
        self, page: PageParams, *, department_id: uuid.UUID | None, batch_year: int | None
    ) -> Page[SectionRead]:
        items, total = self._repo.list(
            limit=page.limit, offset=page.offset, department_id=department_id, batch_year=batch_year
        )
        return Page[SectionRead](
            items=[SectionRead.model_validate(s) for s in items], total=total, **page.model_dump()
        )

    @staticmethod
    def _duplicate_message(name: str, batch_year: int) -> str:
        return f"Section '{name}' already exists for batch {batch_year} in this department."

    def create(self, data: SectionCreate, *, actor: User) -> Section:
        self._departments.get(data.department_id)
        _require_department_manager(actor, data.department_id)
        with write_guard(
            self._session, conflict=self._duplicate_message(data.name, data.batch_year)
        ):
            section = self._repo.add(Section(**data.model_dump()))
        self._session.commit()
        self._session.refresh(section)
        return section

    def update(self, section_id: uuid.UUID, data: SectionUpdate, *, actor: User) -> Section:
        section = self.get(section_id)
        _require_department_manager(actor, section.department_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        message = self._duplicate_message(
            changes.get("name", section.name), changes.get("batch_year", section.batch_year)
        )
        with write_guard(self._session, conflict=message):
            _apply(section, changes)
        self._session.commit()
        return section

    def delete(self, section_id: uuid.UUID, *, actor: User) -> None:
        section = self.get(section_id)
        _require_department_manager(actor, section.department_id)
        with write_guard(
            self._session, in_use="Section has offerings or students; remove those first."
        ):
            self._repo.delete(section)
        self._session.commit()


class OfferingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = OfferingRepository(session)
        self._access = OfferingAccess(session)
        self._users = UserRepository(session)

    def list(
        self,
        page: PageParams,
        *,
        actor: User,
        term_id: uuid.UUID | None,
        course_id: uuid.UUID | None,
        section_id: uuid.UUID | None,
        faculty_id: uuid.UUID | None,
    ) -> Page[OfferingRead]:
        items, total = self._repo.list(
            limit=page.limit,
            offset=page.offset,
            scope=visible_offerings(actor),
            term_id=term_id,
            course_id=course_id,
            section_id=section_id,
            faculty_id=faculty_id,
        )
        return Page[OfferingRead](
            items=[offering_read(o) for o in items], total=total, **page.model_dump()
        )

    def get(self, offering_id: uuid.UUID, *, actor: User) -> CourseOffering:
        return self._access.get(actor, offering_id, Access.VIEW)

    def create(self, data: OfferingCreate, *, actor: User) -> CourseOffering:
        course = CourseService(self._session).get(data.course_id)
        TermService(self._session).get(data.term_id)
        SectionService(self._session).get(data.section_id)
        _require_department_manager(actor, course.department_id)
        teachers = [self._assignable_faculty(uid) for uid in dict.fromkeys(data.faculty_ids)]

        with write_guard(
            self._session,
            conflict="This course is already offered to this section in this term.",
        ):
            offering = self._repo.add(
                CourseOffering(
                    course_id=data.course_id,
                    term_id=data.term_id,
                    section_id=data.section_id,
                    pass_mark_percent=data.pass_mark_percent,
                    faculty_assignments=[OfferingFaculty(user_id=t.id) for t in teachers],
                )
            )
        self._session.commit()
        self._session.refresh(offering)
        return offering

    def update(
        self, offering_id: uuid.UUID, data: OfferingUpdate, *, actor: User
    ) -> CourseOffering:
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        _apply(offering, data.model_dump(exclude_unset=True, exclude_none=True))
        self._session.commit()
        return offering

    def delete(self, offering_id: uuid.UUID, *, actor: User) -> None:
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        with write_guard(
            self._session,
            in_use="Offering has enrolments, assessments or results; remove those first.",
        ):
            self._repo.delete(offering)
        self._session.commit()

    def assign_faculty(
        self, offering_id: uuid.UUID, user_id: uuid.UUID, *, actor: User
    ) -> CourseOffering:
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        faculty = self._assignable_faculty(user_id)
        if self._repo.assignment(offering.id, faculty.id) is None:
            offering.faculty_assignments.append(OfferingFaculty(user_id=faculty.id))
            self._session.commit()
            self._session.refresh(offering)
        return offering

    def unassign_faculty(
        self, offering_id: uuid.UUID, user_id: uuid.UUID, *, actor: User
    ) -> CourseOffering:
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        assignment = self._repo.assignment(offering.id, user_id)
        if assignment is None:
            raise NotFoundError("That user is not assigned to this offering.")
        offering.faculty_assignments.remove(assignment)
        self._session.commit()
        self._session.refresh(offering)
        return offering

    def _assignable_faculty(self, user_id: uuid.UUID) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found.")
        if not user.is_active or user.role not in (Role.FACULTY, Role.HOD):
            raise BusinessRuleError("Only active FACULTY or HOD users can be assigned to teach.")
        return user
