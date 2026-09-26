import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.types import Code, JsonDecimal, Name, Percent

AcademicYear = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")]
Credits = Annotated[JsonDecimal, Field(ge=0, le=30, max_digits=4, decimal_places=1)]
Program = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def _check_academic_year(value: str | None) -> str | None:
    if value is None:
        return value
    start, end = value.split("-")
    if (int(start) + 1) % 100 != int(end):
        raise ValueError("academic_year must be consecutive years, e.g. 2026-27")
    return value


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ departments


class DepartmentCreate(_In):
    code: Code
    name: Name


class DepartmentUpdate(_In):
    code: Code | None = None
    name: Name | None = None


class DepartmentRead(_Out):
    id: uuid.UUID
    code: str
    name: str
    created_at: datetime
    updated_at: datetime


class DepartmentSummary(_Out):
    id: uuid.UUID
    code: str
    name: str


# ------------------------------------------------------------------ terms


class TermCreate(_In):
    code: Code
    name: Name
    academic_year: AcademicYear
    start_date: date
    end_date: date
    is_current: bool = False

    _year = field_validator("academic_year")(_check_academic_year)

    @model_validator(mode="after")
    def _dates(self) -> "TermCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class TermUpdate(_In):
    code: Code | None = None
    name: Name | None = None
    academic_year: AcademicYear | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None

    _year = field_validator("academic_year")(_check_academic_year)


class TermRead(_Out):
    id: uuid.UUID
    code: str
    name: str
    academic_year: str
    start_date: date
    end_date: date
    is_current: bool
    created_at: datetime
    updated_at: datetime


class TermSummary(_Out):
    id: uuid.UUID
    code: str
    name: str
    academic_year: str
    is_current: bool


# ------------------------------------------------------------------ courses


class CourseCreate(_In):
    department_id: uuid.UUID
    code: Code
    name: Name
    credits: Credits | None = None


class CourseUpdate(_In):
    code: Code | None = None
    name: Name | None = None
    credits: Credits | None = None


class CourseRead(_Out):
    id: uuid.UUID
    code: str
    name: str
    credits: JsonDecimal | None
    department: DepartmentSummary
    created_at: datetime
    updated_at: datetime


class CourseSummary(_Out):
    id: uuid.UUID
    code: str
    name: str
    department_id: uuid.UUID


# ------------------------------------------------------------------ sections

SectionName = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=32)
]
BatchYear = Annotated[int, Field(ge=2000, le=2100)]


class SectionCreate(_In):
    department_id: uuid.UUID
    name: SectionName
    batch_year: BatchYear
    program: Program | None = None


class SectionUpdate(_In):
    name: SectionName | None = None
    batch_year: BatchYear | None = None
    program: Program | None = None


class SectionRead(_Out):
    id: uuid.UUID
    name: str
    batch_year: int
    program: str | None
    department: DepartmentSummary
    created_at: datetime
    updated_at: datetime


class SectionSummary(_Out):
    id: uuid.UUID
    name: str
    batch_year: int
    department_id: uuid.UUID


# ------------------------------------------------------------------ offerings


class OfferingCreate(_In):
    course_id: uuid.UUID
    term_id: uuid.UUID
    section_id: uuid.UUID
    pass_percent: Percent = Decimal("50")
    config: dict[str, Any] = Field(default_factory=dict)
    faculty_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class OfferingUpdate(_In):
    """``pass_percent`` needs ADMINISTER access; ``config`` may also be set by the
    offering's assigned faculty. ``config`` replaces the whole object."""

    pass_percent: Percent | None = None
    config: dict[str, Any] | None = None


class FacultyAssign(_In):
    user_id: uuid.UUID


class FacultySummary(_Out):
    id: uuid.UUID
    full_name: str
    email: str


class OfferingRead(_Out):
    id: uuid.UUID
    course: CourseSummary
    term: TermSummary
    section: SectionSummary
    pass_percent: JsonDecimal
    config: dict[str, Any]
    faculty: list[FacultySummary]
    created_at: datetime
    updated_at: datetime
