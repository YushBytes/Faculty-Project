import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.students.schemas import (
    BulkResult,
    EnrollmentRead,
    EnrollRequest,
    EnrollResult,
    SectionHistoryRead,
    StudentBulkRequest,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)
from app.modules.students.service import EnrollmentService, StudentService
from app.modules.users.models import Role, User

DB = Annotated[Session, Depends(get_db)]
Manager = Annotated[User, Depends(require_roles(Role.ADMIN, Role.HOD))]
_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Not permitted"},
}
_ONE = {**_COMMON, 404: {"model": ErrorResponse, "description": "Not found or out of scope"}}
_WRITE = {**_ONE, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}

students = APIRouter(prefix="/students", tags=["students"], responses=_COMMON)


@students.get(
    "",
    response_model=Page[StudentRead],
    description="Only students within the caller's scope are returned.",
)
def list_students(
    actor: CurrentUser,
    db: DB,
    page: Annotated[PageParams, Depends(page_params)],
    department_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    section_id: Annotated[uuid.UUID | None, Query(description="Current section")] = None,
    offering_id: Annotated[uuid.UUID | None, Query(description="Enrolled in offering")] = None,
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100, description="Register no. or name")] = None,
) -> Page[StudentRead]:
    return StudentService(db).list(
        page,
        actor=actor,
        department_id=department_id,
        batch_year=batch_year,
        section_id=section_id,
        offering_id=offering_id,
        is_active=is_active,
        q=q,
    )


@students.post("", response_model=StudentRead, status_code=201, responses=_WRITE)
def create_student(body: StudentCreate, actor: Manager, db: DB) -> StudentRead:
    return StudentRead.model_validate(StudentService(db).create(body, actor=actor))


@students.post(
    "/bulk",
    response_model=BulkResult,
    responses=_WRITE,
    summary="Bulk create/update students (JSON)",
    description=(
        "Rows are matched on register_number: new ones are created, existing ones updated. "
        "Every row is validated first; if any row fails nothing is written and all row "
        "errors are returned (valid=false). dry_run=true validates without writing. "
        "Row fields: register_number, full_name, email?, department_code, batch_year, section?"
    ),
)
def bulk_students(body: StudentBulkRequest, actor: Manager, db: DB) -> BulkResult:
    return StudentService(db).bulk_upsert(body.rows, dry_run=body.dry_run, actor=actor)


@students.post(
    "/import",
    response_model=BulkResult,
    responses=_WRITE,
    summary="Bulk create/update students from a CSV or XLSX file",
    description=(
        "Same rules as /students/bulk. Header names are matched flexibly, e.g. "
        "'Reg No' / 'Register Number', 'Name', 'Email', 'Department' / 'Dept', "
        "'Batch' / 'Batch Year', 'Section'. Row numbers in errors are spreadsheet rows."
    ),
)
async def import_students(
    actor: Manager,
    db: DB,
    file: Annotated[UploadFile, File(description=".csv or .xlsx")],
    dry_run: Annotated[bool, Form()] = False,
) -> BulkResult:
    content = await file.read()
    return StudentService(db).import_file(file.filename, content, dry_run=dry_run, actor=actor)


@students.get("/{student_id}", response_model=StudentRead, responses=_ONE)
def get_student(student_id: uuid.UUID, actor: CurrentUser, db: DB) -> StudentRead:
    return StudentRead.model_validate(StudentService(db).get(student_id, actor=actor))


@students.patch("/{student_id}", response_model=StudentRead, responses=_WRITE)
def update_student(
    student_id: uuid.UUID, body: StudentUpdate, actor: Manager, db: DB
) -> StudentRead:
    return StudentRead.model_validate(StudentService(db).update(student_id, body, actor=actor))


@students.post("/{student_id}/deactivate", response_model=StudentRead, responses=_ONE)
def deactivate_student(student_id: uuid.UUID, actor: Manager, db: DB) -> StudentRead:
    return StudentRead.model_validate(StudentService(db).set_active(student_id, False, actor=actor))


@students.post("/{student_id}/activate", response_model=StudentRead, responses=_ONE)
def activate_student(student_id: uuid.UUID, actor: Manager, db: DB) -> StudentRead:
    return StudentRead.model_validate(StudentService(db).set_active(student_id, True, actor=actor))


@students.get("/{student_id}/sections", response_model=list[SectionHistoryRead], responses=_ONE)
def section_history(student_id: uuid.UUID, actor: CurrentUser, db: DB) -> list[SectionHistoryRead]:
    rows = StudentService(db).section_history(student_id, actor=actor)
    return [SectionHistoryRead.model_validate(r) for r in rows]


# ------------------------------------------------------------------ offering enrolments

enrollments = APIRouter(prefix="/offerings/{offering_id}", tags=["enrollments"], responses=_ONE)


@enrollments.get(
    "/students",
    response_model=list[EnrollmentRead],
    summary="Offering roster",
    description="Active enrolments of active students by default.",
)
def roster(
    offering_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    include_dropped: bool = False,
    include_inactive: bool = False,
) -> list[EnrollmentRead]:
    return EnrollmentService(db).roster(
        offering_id,
        actor=actor,
        include_dropped=include_dropped,
        include_inactive=include_inactive,
    )


@enrollments.post("/enrollments", response_model=EnrollResult, responses=_WRITE)
def enroll(offering_id: uuid.UUID, body: EnrollRequest, actor: Manager, db: DB) -> EnrollResult:
    return EnrollmentService(db).enroll(offering_id, body.student_ids, actor=actor)


@enrollments.post(
    "/enrollments/from-section",
    response_model=EnrollResult,
    responses=_WRITE,
    summary="Enrol the offering's section",
    description="Enrols every active student currently in the offering's section. Idempotent.",
)
def enroll_section(offering_id: uuid.UUID, actor: Manager, db: DB) -> EnrollResult:
    return EnrollmentService(db).enroll_section(offering_id, actor=actor)


@enrollments.delete(
    "/enrollments/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_ONE,
    summary="Drop a student",
    description="Marks the enrolment DROPPED; the row and any results are kept.",
)
def drop(offering_id: uuid.UUID, student_id: uuid.UUID, actor: Manager, db: DB) -> None:
    EnrollmentService(db).drop(offering_id, student_id, actor=actor)


ROUTERS = [students, enrollments]
