import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.imports.models import ImportStatus
from app.modules.imports.schemas import (
    ConfirmResult,
    ExcludeRequest,
    FixRequest,
    ImportBatchRead,
    ImportPreview,
    MappingRequest,
    TlpUploadRead,
)
from app.modules.imports.service import ImportService, preview_read
from app.modules.imports.tlp_service import TlpUploadService

DB = Annotated[Session, Depends(get_db)]
Only = Annotated[
    Literal["all", "issues", "errors"],
    Query(description="Filter preview rows: all, rows with any issue, or rows with errors"),
]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Not permitted"},
    404: {"model": ErrorResponse, "description": "Not found or out of scope"},
}
_WRITE = {
    **_COMMON,
    409: {"model": ErrorResponse, "description": "Already committed/discarded or expired"},
    422: {"model": ErrorResponse, "description": "Rejected file or blocking errors"},
}
_UPLOAD_DOC = (
    "Parses and validates the sheet and stages it; nothing is written to results. Accepts "
    "wide sheets (Register No | Name | CT1 | CT2 ...) and long sheets (Register No | "
    "Assessment | Score | [Max] | [Percentage] | [Status]). Blank cells become absent (with a "
    "warning), AB / A / - mean absent, EX means exempt. Returns the preview."
)


def _file_response(name: str, content: bytes) -> Response:
    return Response(
        content,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ------------------------------------------------------------------ uploads & templates

uploads = APIRouter(tags=["imports"], responses=_COMMON)


@uploads.post(
    "/offerings/{offering_id}/imports",
    response_model=ImportPreview,
    status_code=201,
    responses=_WRITE,
    summary="Upload marks for an offering",
    description=_UPLOAD_DOC,
)
async def upload_offering(
    offering_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File(description=".xlsx or .csv, at most 5 MB")],
) -> ImportPreview:
    content = await file.read()
    batch, preview = ImportService(db).upload_for_offering(
        offering_id, file.filename, content, actor=actor
    )
    return preview_read(batch, preview)


@uploads.post(
    "/assessments/{assessment_id}/import",
    response_model=ImportPreview,
    status_code=201,
    responses=_WRITE,
    summary="Upload marks for one assessment",
    description=_UPLOAD_DOC + " A single 'Score'/'Marks' column maps to this assessment.",
)
async def upload_assessment(
    assessment_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File(description=".xlsx or .csv, at most 5 MB")],
) -> ImportPreview:
    content = await file.read()
    batch, preview = ImportService(db).upload_for_assessment(
        assessment_id, file.filename, content, actor=actor
    )
    return preview_read(batch, preview)


@uploads.get(
    "/offerings/{offering_id}/imports/template",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}}, **_COMMON},
    summary="XLSX template with every assessment of the offering",
)
def offering_template(offering_id: uuid.UUID, actor: CurrentUser, db: DB) -> Response:
    return _file_response(*ImportService(db).template_for_offering(offering_id, actor=actor))


@uploads.get(
    "/assessments/{assessment_id}/import/template",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}}, **_COMMON},
    summary="XLSX template for one assessment",
)
def assessment_template(assessment_id: uuid.UUID, actor: CurrentUser, db: DB) -> Response:
    return _file_response(*ImportService(db).template_for_assessment(assessment_id, actor=actor))


# ------------------------------------------------------------------ batches

imports = APIRouter(prefix="/imports", tags=["imports"], responses=_COMMON)


@imports.get("", response_model=Page[ImportBatchRead], summary="Import history")
def history(
    actor: CurrentUser,
    db: DB,
    page: Annotated[PageParams, Depends(page_params)],
    offering_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[ImportStatus | None, Query()] = None,
) -> Page[ImportBatchRead]:
    return ImportService(db).history(page, actor=actor, offering_id=offering_id, status=status)


@imports.get("/history", response_model=Page[ImportBatchRead], include_in_schema=False)
def history_alias(
    actor: CurrentUser,
    db: DB,
    page: Annotated[PageParams, Depends(page_params)],
    offering_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[ImportStatus | None, Query()] = None,
) -> Page[ImportBatchRead]:
    return ImportService(db).history(page, actor=actor, offering_id=offering_id, status=status)


@imports.get("/{batch_id}", response_model=ImportBatchRead)
def get_batch(batch_id: uuid.UUID, actor: CurrentUser, db: DB) -> ImportBatchRead:
    return ImportBatchRead.model_validate(ImportService(db).get(batch_id, actor=actor))


@imports.get("/{batch_id}/preview", response_model=ImportPreview, summary="Revalidate and preview")
def preview(batch_id: uuid.UUID, actor: CurrentUser, db: DB, only: Only = "all") -> ImportPreview:
    batch, result = ImportService(db).preview(batch_id, actor=actor)
    return preview_read(batch, result, only=only)


@imports.post(
    "/{batch_id}/fix",
    response_model=ImportPreview,
    responses=_WRITE,
    summary="Correct cells",
    description="Sets (or resets) cell values; every change is audited. Returns the revalidated "
    "preview. Turning a blank (absent) cell into 0 is done here, explicitly.",
)
def fix(
    batch_id: uuid.UUID, body: FixRequest, actor: CurrentUser, db: DB, only: Only = "all"
) -> ImportPreview:
    batch, result = ImportService(db).fix(batch_id, body.fixes, actor=actor)
    return preview_read(batch, result, only=only)


@imports.post(
    "/{batch_id}/exclude",
    response_model=ImportPreview,
    responses=_WRITE,
    summary="Exclude or re-include rows",
)
def exclude(
    batch_id: uuid.UUID, body: ExcludeRequest, actor: CurrentUser, db: DB, only: Only = "all"
) -> ImportPreview:
    batch, result = ImportService(db).exclude(batch_id, body.rows, body.excluded, actor=actor)
    return preview_read(batch, result, only=only)


@imports.post(
    "/{batch_id}/mapping",
    response_model=ImportPreview,
    responses=_WRITE,
    summary="Map columns to assessments",
    description="header -> assessment id, 'ignore', or null to return to automatic matching.",
)
def mapping(
    batch_id: uuid.UUID, body: MappingRequest, actor: CurrentUser, db: DB, only: Only = "all"
) -> ImportPreview:
    batch, result = ImportService(db).map_columns(batch_id, body.mappings, actor=actor)
    return preview_read(batch, result, only=only)


@imports.post(
    "/{batch_id}/confirm",
    response_model=ConfirmResult,
    responses=_WRITE,
    summary="Commit the import (one transaction)",
    description="Revalidates against current data; refuses while any blocking error remains. "
    "Writes results, audit rows and runs the recompute hook in a single transaction.",
)
def confirm(
    batch_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    publish: Annotated[
        bool, Query(description="Also publish the assessment(s), in the same transaction")
    ] = False,
) -> ConfirmResult:
    return ImportService(db).confirm(batch_id, actor=actor, publish=publish)


@imports.post("/{batch_id}/discard", response_model=ImportBatchRead, responses=_WRITE)
def discard(batch_id: uuid.UUID, actor: CurrentUser, db: DB) -> ImportBatchRead:
    return ImportBatchRead.model_validate(ImportService(db).discard(batch_id, actor=actor))


# ------------------------------------------------------------------ multi-file TLP uploads

tlp = APIRouter(prefix="/tlp-uploads", tags=["imports"], responses=_COMMON)


@tlp.post(
    "",
    response_model=TlpUploadRead,
    status_code=201,
    responses=_WRITE,
    summary="Upload one or many SRM TLP mark reports (xlsx, csv or TLP pdf)",
    description=(
        "Each file is routed to its offering (course code and academic year from the "
        "report's title block, section from its register numbers) and assessment (test "
        "name), then staged through the ordinary import pipeline. Nothing is written to "
        "results until the group (or an individual import) is confirmed. Files that cannot "
        "be read or routed are reported as `rejected` with the reason. Pass `offering_id` to "
        "skip routing (a faculty member uploading their own section), or `course_id` / "
        "`term_id` for files without a title block."
    ),
)
async def upload_tlp(
    actor: CurrentUser,
    db: DB,
    files: Annotated[list[UploadFile], File(description="Up to 150 files, 5 MB each")],
    course_id: Annotated[uuid.UUID | None, Form()] = None,
    term_id: Annotated[uuid.UUID | None, Form()] = None,
    offering_id: Annotated[uuid.UUID | None, Form()] = None,
) -> TlpUploadRead:
    contents = [(f.filename, await f.read()) for f in files]
    return TlpUploadService(db).upload(
        contents, actor=actor, course_id=course_id, term_id=term_id, offering_id=offering_id
    )


@tlp.get("/{group_id}", response_model=TlpUploadRead, summary="Status of every staged file")
def tlp_group(group_id: uuid.UUID, actor: CurrentUser, db: DB) -> TlpUploadRead:
    return TlpUploadService(db).group(group_id, actor=actor)


@tlp.post(
    "/{group_id}/confirm",
    response_model=TlpUploadRead,
    responses=_WRITE,
    summary="Confirm every confirmable file of the upload",
    description=(
        "Each file is confirmed in its own transaction (results, audit, analytics). Files "
        "with blocking errors stay staged and are reported; nothing is half-written."
    ),
)
def tlp_confirm(
    group_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    publish: Annotated[bool, Query(description="Publish the assessments too")] = True,
) -> TlpUploadRead:
    return TlpUploadService(db).confirm_group(group_id, actor=actor, publish=publish)


ROUTERS = [uploads, imports, tlp]
