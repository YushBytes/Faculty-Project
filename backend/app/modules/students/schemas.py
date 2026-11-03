import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.core.types import Name
from app.modules.organization.schemas import DepartmentSummary, SectionSummary
from app.modules.students.models import EnrollmentStatus


def _normalise_register_number(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"\s+", "", value).upper()
    return value


RegisterNumber = Annotated[
    str,
    BeforeValidator(_normalise_register_number),
    StringConstraints(pattern=r"^[A-Z0-9]{5,20}$"),
]
BatchYear = Annotated[int, Field(ge=2000, le=2100)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StudentCreate(_In):
    register_number: RegisterNumber
    full_name: Name
    email: EmailStr | None = None
    department_id: uuid.UUID
    batch_year: BatchYear
    section_id: uuid.UUID | None = None


class StudentUpdate(_In):
    """Partial update. Changing ``section_id`` records section history; past enrolments and
    results are untouched."""

    full_name: Name | None = None
    email: EmailStr | None = None
    batch_year: BatchYear | None = None
    section_id: uuid.UUID | None = None


class StudentRead(_Out):
    id: uuid.UUID
    register_number: str
    full_name: str
    email: str | None
    department: DepartmentSummary
    batch_year: int
    current_section: SectionSummary | None
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StudentSummary(_Out):
    id: uuid.UUID
    register_number: str
    full_name: str
    is_active: bool


class SectionHistoryRead(_Out):
    section: SectionSummary
    started_at: datetime
    ended_at: datetime | None


# ------------------------------------------------------------------ bulk


class StudentBulkRow(BaseModel):
    """One row of a bulk upsert. Rows are matched on ``register_number``: new numbers are
    created, existing ones updated."""

    model_config = ConfigDict(extra="forbid")

    register_number: RegisterNumber
    full_name: Name
    email: EmailStr | None = None
    department_code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)]
    batch_year: BatchYear
    section: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None


class StudentBulkRequest(_In):
    rows: list[dict] = Field(min_length=1, max_length=5000)
    dry_run: bool = False


class RowError(BaseModel):
    row: int
    field: str | None = None
    value: str | None = None
    message: str


class BulkResult(BaseModel):
    dry_run: bool
    valid: bool
    total_rows: int
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[RowError] = []


# ------------------------------------------------------------------ enrolments


class EnrollRequest(_In):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class EnrollmentRead(_Out):
    student: StudentSummary
    status: EnrollmentStatus
    enrolled_at: datetime
    dropped_at: datetime | None


class EnrollResult(BaseModel):
    enrolled: int
    reactivated: int
    already_enrolled: int
