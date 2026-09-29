import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.types import JsonDecimal
from app.modules.assessments.models import ResultStatus
from app.modules.imports.models import ImportFormat, ImportStatus


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IssueRead(BaseModel):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    column: str | None = None


class ColumnRead(BaseModel):
    header: str
    role: str
    assessment_id: uuid.UUID | None
    assessment_name: str | None
    mapped_by: str
    issues: list[IssueRead]


class CellRead(BaseModel):
    column: str
    assessment_id: uuid.UUID | None
    assessment_name: str | None
    raw: str | None = Field(description="Value as uploaded")
    value: str | None = Field(description="Value after faculty fixes")
    fixed: bool
    status: ResultStatus | None
    score: JsonDecimal | None
    change: Literal["create", "update", "unchanged"] | None
    issues: list[IssueRead]


class RowRead(BaseModel):
    row: int = Field(description="Spreadsheet row number")
    register_number: str | None
    student_id: uuid.UUID | None
    student_name: str | None
    excluded: bool
    issues: list[IssueRead]
    cells: list[CellRead]


class MissingStudent(BaseModel):
    id: uuid.UUID
    register_number: str
    full_name: str


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    offering_id: uuid.UUID
    assessment_id: uuid.UUID | None
    status: ImportStatus
    file_name: str
    file_type: str
    file_format: ImportFormat
    sheet_name: str | None
    total_rows: int
    summary: dict[str, Any]
    uploaded_by_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    committed_at: datetime | None
    committed_by_id: uuid.UUID | None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    upload_group_id: uuid.UUID | None = None


class ImportPreview(BaseModel):
    batch: ImportBatchRead
    summary: dict[str, Any]
    file_issues: list[IssueRead]
    columns: list[ColumnRead]
    rows: list[RowRead]
    missing_students: list[MissingStudent]


class CellFix(_In):
    row: int = Field(gt=0)
    column: str = Field(min_length=1, max_length=255)
    value: str | None = Field(
        default=None, max_length=100, description="New raw value; null = blank"
    )
    reset: bool = Field(default=False, description="Drop the fix and use the uploaded value")


class FixRequest(_In):
    fixes: list[CellFix] = Field(min_length=1, max_length=1000)


class ExcludeRequest(_In):
    rows: list[int] = Field(min_length=1, max_length=5000)
    excluded: bool = True


class MappingRequest(_In):
    mappings: dict[str, uuid.UUID | Literal["ignore"] | None] = Field(
        min_length=1, description="header -> assessment id, 'ignore', or null for automatic"
    )


class ConfirmResult(BaseModel):
    batch_id: uuid.UUID
    status: ImportStatus
    created: int
    updated: int
    unchanged: int
    assessments: list[uuid.UUID]
    summary: dict[str, Any]


# ------------------------------------------------------------------ multi-file TLP uploads

TlpFileStatus = Literal[
    "valid", "warning", "error", "rejected", "duplicate", "skipped", "confirmed", "discarded"
]


class TlpFileResult(BaseModel):
    """One file of a multi-file upload.

    ``rejected``  could not be staged at all (unreadable, not routable); nothing was stored
    ``error``     staged, but has blocking errors to fix or exclude before confirming
    ``warning``   staged, confirmable, with warnings to review
    ``valid``     staged, confirmable, nothing to review
    ``duplicate`` staged, but this exact file was already imported into the offering
    ``skipped``   the same file appeared twice in this upload; the copy was not staged
    ``confirmed`` written to results
    ``discarded`` staged and then discarded
    """

    file_name: str
    status: TlpFileStatus
    message: str | None = None
    batch_id: uuid.UUID | None = None
    offering_id: uuid.UUID | None = None
    offering_label: str | None = None
    section_name: str | None = None
    assessment_id: uuid.UUID | None = None
    assessment_name: str | None = None
    routed_by: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[IssueRead] = Field(default_factory=list)


class TlpUploadRead(BaseModel):
    group_id: uuid.UUID
    files: list[TlpFileResult]
    counts: dict[str, int]
