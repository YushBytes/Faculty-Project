"""Departments, terms, courses, sections and course offerings.

Reference data (departments, terms, courses, sections) is readable by any signed-in user.
Offerings are filtered by the caller's scope (see scope.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.auth.dependencies import AdminUser, CurrentUser, require_roles
from app.modules.organization.schemas import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    FacultyAssign,
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
from app.modules.organization.service import (
    CourseService,
    DepartmentService,
    OfferingService,
    SectionService,
    TermService,
    offering_read,
)
from app.modules.users.models import Role, User

DB = Annotated[Session, Depends(get_db)]
Pages = Annotated[PageParams, Depends(page_params)]
Manager = Annotated[User, Depends(require_roles(Role.ADMIN, Role.HOD))]

_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Not permitted"},
}
_ONE = {**_COMMON, 404: {"model": ErrorResponse}}
_WRITE = {**_ONE, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
_NO_CONTENT = {"status_code": status.HTTP_204_NO_CONTENT, "response_class": Response}

# ------------------------------------------------------------------ departments

departments = APIRouter(prefix="/departments", tags=["organization"], responses=_COMMON)


@departments.get("", response_model=Page[DepartmentRead])
def list_departments(_: CurrentUser, db: DB, page: Pages) -> Page[DepartmentRead]:
    return DepartmentService(db).list(page)


@departments.post("", response_model=DepartmentRead, status_code=201, responses=_WRITE)
def create_department(body: DepartmentCreate, _: AdminUser, db: DB) -> DepartmentRead:
    return DepartmentRead.model_validate(DepartmentService(db).create(body))


@departments.get("/{department_id}", response_model=DepartmentRead, responses=_ONE)
def get_department(department_id: uuid.UUID, _: CurrentUser, db: DB) -> DepartmentRead:
    return DepartmentRead.model_validate(DepartmentService(db).get(department_id))


@departments.patch("/{department_id}", response_model=DepartmentRead, responses=_WRITE)
def update_department(
    department_id: uuid.UUID, body: DepartmentUpdate, _: AdminUser, db: DB
) -> DepartmentRead:
    return DepartmentRead.model_validate(DepartmentService(db).update(department_id, body))


@departments.delete("/{department_id}", responses=_WRITE, **_NO_CONTENT)
def delete_department(department_id: uuid.UUID, _: AdminUser, db: DB) -> None:
    DepartmentService(db).delete(department_id)


# ------------------------------------------------------------------ terms

terms = APIRouter(prefix="/terms", tags=["organization"], responses=_COMMON)


@terms.get("", response_model=Page[TermRead])
def list_terms(
    _: CurrentUser, db: DB, page: Pages, is_current: Annotated[bool | None, Query()] = None
) -> Page[TermRead]:
    return TermService(db).list(page, is_current=is_current)


@terms.post("", response_model=TermRead, status_code=201, responses=_WRITE)
def create_term(body: TermCreate, _: AdminUser, db: DB) -> TermRead:
    return TermRead.model_validate(TermService(db).create(body))


@terms.get("/{term_id}", response_model=TermRead, responses=_ONE)
def get_term(term_id: uuid.UUID, _: CurrentUser, db: DB) -> TermRead:
    return TermRead.model_validate(TermService(db).get(term_id))


@terms.patch("/{term_id}", response_model=TermRead, responses=_WRITE)
def update_term(term_id: uuid.UUID, body: TermUpdate, _: AdminUser, db: DB) -> TermRead:
    return TermRead.model_validate(TermService(db).update(term_id, body))


@terms.delete("/{term_id}", responses=_WRITE, **_NO_CONTENT)
def delete_term(term_id: uuid.UUID, _: AdminUser, db: DB) -> None:
    TermService(db).delete(term_id)


# ------------------------------------------------------------------ courses

courses = APIRouter(prefix="/courses", tags=["organization"], responses=_COMMON)


@courses.get("", response_model=Page[CourseRead])
def list_courses(
    _: CurrentUser,
    db: DB,
    page: Pages,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100, description="Code or name contains")] = None,
) -> Page[CourseRead]:
    return CourseService(db).list(page, department_id=department_id, q=q)


@courses.post("", response_model=CourseRead, status_code=201, responses=_WRITE)
def create_course(body: CourseCreate, actor: Manager, db: DB) -> CourseRead:
    return CourseRead.model_validate(CourseService(db).create(body, actor=actor))


@courses.get("/{course_id}", response_model=CourseRead, responses=_ONE)
def get_course(course_id: uuid.UUID, _: CurrentUser, db: DB) -> CourseRead:
    return CourseRead.model_validate(CourseService(db).get(course_id))


@courses.patch("/{course_id}", response_model=CourseRead, responses=_WRITE)
def update_course(course_id: uuid.UUID, body: CourseUpdate, actor: Manager, db: DB) -> CourseRead:
    return CourseRead.model_validate(CourseService(db).update(course_id, body, actor=actor))


@courses.delete("/{course_id}", responses=_WRITE, **_NO_CONTENT)
def delete_course(course_id: uuid.UUID, actor: Manager, db: DB) -> None:
    CourseService(db).delete(course_id, actor=actor)


# ------------------------------------------------------------------ sections

sections = APIRouter(prefix="/sections", tags=["organization"], responses=_COMMON)


@sections.get("", response_model=Page[SectionRead])
def list_sections(
    _: CurrentUser,
    db: DB,
    page: Pages,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> Page[SectionRead]:
    return SectionService(db).list(page, department_id=department_id, batch_year=batch_year)


@sections.post("", response_model=SectionRead, status_code=201, responses=_WRITE)
def create_section(body: SectionCreate, actor: Manager, db: DB) -> SectionRead:
    return SectionRead.model_validate(SectionService(db).create(body, actor=actor))


@sections.get("/{section_id}", response_model=SectionRead, responses=_ONE)
def get_section(section_id: uuid.UUID, _: CurrentUser, db: DB) -> SectionRead:
    return SectionRead.model_validate(SectionService(db).get(section_id))


@sections.patch("/{section_id}", response_model=SectionRead, responses=_WRITE)
def update_section(
    section_id: uuid.UUID, body: SectionUpdate, actor: Manager, db: DB
) -> SectionRead:
    return SectionRead.model_validate(SectionService(db).update(section_id, body, actor=actor))


@sections.delete("/{section_id}", responses=_WRITE, **_NO_CONTENT)
def delete_section(section_id: uuid.UUID, actor: Manager, db: DB) -> None:
    SectionService(db).delete(section_id, actor=actor)


# ------------------------------------------------------------------ offerings

offerings = APIRouter(prefix="/offerings", tags=["offerings"], responses=_COMMON)


@offerings.get(
    "",
    response_model=Page[OfferingRead],
    description="Only offerings within the caller's scope are returned.",
)
def list_offerings(
    actor: CurrentUser,
    db: DB,
    page: Pages,
    term_id: Annotated[uuid.UUID | None, Query()] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    section_id: Annotated[uuid.UUID | None, Query()] = None,
    faculty_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[OfferingRead]:
    return OfferingService(db).list(
        page,
        actor=actor,
        term_id=term_id,
        course_id=course_id,
        section_id=section_id,
        faculty_id=faculty_id,
    )


@offerings.post("", response_model=OfferingRead, status_code=201, responses=_WRITE)
def create_offering(body: OfferingCreate, actor: Manager, db: DB) -> OfferingRead:
    return offering_read(OfferingService(db).create(body, actor=actor))


@offerings.get("/{offering_id}", response_model=OfferingRead, responses=_ONE)
def get_offering(offering_id: uuid.UUID, actor: CurrentUser, db: DB) -> OfferingRead:
    return offering_read(OfferingService(db).get(offering_id, actor=actor))


@offerings.patch("/{offering_id}", response_model=OfferingRead, responses=_WRITE)
def update_offering(
    offering_id: uuid.UUID, body: OfferingUpdate, actor: CurrentUser, db: DB
) -> OfferingRead:
    return offering_read(OfferingService(db).update(offering_id, body, actor=actor))


@offerings.delete("/{offering_id}", responses=_WRITE, **_NO_CONTENT)
def delete_offering(offering_id: uuid.UUID, actor: Manager, db: DB) -> None:
    OfferingService(db).delete(offering_id, actor=actor)


@offerings.post("/{offering_id}/faculty", response_model=OfferingRead, responses=_WRITE)
def assign_faculty(
    offering_id: uuid.UUID, body: FacultyAssign, actor: Manager, db: DB
) -> OfferingRead:
    return offering_read(OfferingService(db).assign_faculty(offering_id, body.user_id, actor=actor))


@offerings.delete("/{offering_id}/faculty/{user_id}", response_model=OfferingRead, responses=_ONE)
def unassign_faculty(
    offering_id: uuid.UUID, user_id: uuid.UUID, actor: Manager, db: DB
) -> OfferingRead:
    return offering_read(OfferingService(db).unassign_faculty(offering_id, user_id, actor=actor))


ROUTERS = [departments, terms, courses, sections, offerings]
