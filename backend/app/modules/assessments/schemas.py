import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import JsonDecimal
from app.modules.assessments.models import AssessmentType, ResultSource, ResultStatus
from app.modules.students.models import EnrollmentStatus
from app.modules.students.schemas import StudentSummary

AssessmentName = Annotated[str, Field(min_length=1, max_length=100)]
Marks = Annotated[JsonDecimal, Field(gt=0, max_digits=6, decimal_places=2)]
Score = Annotated[JsonDecimal, Field(ge=0, max_digits=6, decimal_places=2)]
Weightage = Annotated[JsonDecimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]

ResultState = Literal["present", "absent", "exempt", "missing"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ assessments


class AssessmentCreate(_In):
    name: AssessmentName
    assessment_type: AssessmentType
    assessment_date: date | None = None
    max_marks: Marks
    weightage: Weightage = Decimal("0")
    sequence_no: int | None = Field(
        default=None, gt=0, description="Order within the offering; next free number if omitted"
    )
    is_published: bool = False


class AssessmentUpdate(_In):
    """Partial update. ``max_marks`` cannot change once results exist."""

    name: AssessmentName | None = None
    assessment_type: AssessmentType | None = None
    assessment_date: date | None = None
    max_marks: Marks | None = None
    weightage: Weightage | None = None
    sequence_no: int | None = Field(default=None, gt=0)
    is_published: bool | None = None


class ResultCounts(BaseModel):
    """Counts over the offering's active cohort. ``missing`` = enrolled, no result row."""

    present: int = 0
    absent: int = 0
    exempt: int = 0
    missing: int = 0
    enrolled: int = 0


class AssessmentRead(_Out):
    id: uuid.UUID
    offering_id: uuid.UUID
    name: str
    assessment_type: AssessmentType
    assessment_date: date | None
    max_marks: JsonDecimal
    weightage: JsonDecimal
    sequence_no: int
    is_published: bool
    created_at: datetime
    updated_at: datetime


class AssessmentDetail(AssessmentRead):
    result_counts: ResultCounts


class AssessmentList(BaseModel):
    items: list[AssessmentDetail]
    weightage_total: JsonDecimal
    warnings: list[str]


# ------------------------------------------------------------------ results


class ResultEntry(_In):
    """One cell. Identify the student by ``student_id`` or ``register_number``.

    status=present needs a score; absent/exempt must not have one. If status is omitted a
    score means present; a blank entry (no score, no status) is rejected — blanks are
    never turned into 0 or absent silently.
    """

    student_id: uuid.UUID | None = None
    register_number: str | None = Field(default=None, max_length=20)
    status: ResultStatus | None = None
    score: Score | None = None

    @model_validator(mode="after")
    def _one_identifier(self) -> "ResultEntry":
        if (self.student_id is None) == (self.register_number is None):
            raise ValueError("Give exactly one of student_id or register_number.")
        return self


class ResultsUpsert(_In):
    results: list[ResultEntry] = Field(min_length=1, max_length=2000)


class ResultRead(_Out):
    score: JsonDecimal | None
    status: ResultStatus
    max_marks_snapshot: JsonDecimal
    percentage: JsonDecimal | None = Field(
        description="100 * score / max_marks_snapshot, 2 dp; null unless present"
    )
    source: ResultSource
    recorded_at: datetime
    updated_at: datetime


class ResultRow(BaseModel):
    student: StudentSummary
    enrollment_status: EnrollmentStatus
    state: ResultState
    result: ResultRead | None


class ResultsGrid(BaseModel):
    assessment: AssessmentRead
    counts: ResultCounts
    rows: list[ResultRow]


class UpsertSummary(BaseModel):
    created: int
    updated: int
    unchanged: int


# ------------------------------------------------------------------ offering matrix (C3/D8)


class MatrixOffering(BaseModel):
    id: uuid.UUID
    course_code: str
    section_name: str
    term_code: str
    pass_percent: JsonDecimal
    config: dict[str, Any]
    department_id: uuid.UUID


class MatrixStudent(BaseModel):
    id: uuid.UUID
    register_number: str
    full_name: str
    enrollment_status: EnrollmentStatus
    is_active: bool


class MatrixResult(BaseModel):
    student_id: uuid.UUID
    assessment_id: uuid.UUID
    status: ResultStatus
    score: JsonDecimal | None
    max_marks_snapshot: JsonDecimal
    percentage: JsonDecimal | None


class OfferingResults(BaseModel):
    """Everything analytics needs for one offering, in one read."""

    offering: MatrixOffering
    assessments: list[AssessmentRead]  # ordered by sequence_no
    students: list[MatrixStudent]  # the cohort, ordered by register number
    results: list[MatrixResult]  # stored rows only; absence of a row = missing


# ------------------------------------------------------------------ settings


class SettingWrite(_In):
    value: Any = Field(description="Any JSON value")


class SettingRead(_Out):
    key: str
    value: Any
    updated_at: datetime
