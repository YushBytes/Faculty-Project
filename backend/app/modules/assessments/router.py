import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.modules.assessments.schemas import (
    AssessmentCreate,
    AssessmentDetail,
    AssessmentList,
    AssessmentUpdate,
    OfferingResults,
    ResultsGrid,
    ResultsUpsert,
    SettingRead,
    SettingWrite,
    UpsertSummary,
)
from app.modules.assessments.service import (
    AssessmentService,
    OfferingResultsService,
    RecomputeService,
    SettingsService,
)
from app.modules.auth.dependencies import AdminUser, CurrentUser

DB = Annotated[Session, Depends(get_db)]
_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Not permitted"},
    404: {"model": ErrorResponse, "description": "Not found or out of scope"},
}
_WRITE = {**_COMMON, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
_NO_CONTENT = {"status_code": status.HTTP_204_NO_CONTENT, "response_class": Response}

# ------------------------------------------------------------------ per offering

by_offering = APIRouter(prefix="/offerings/{offering_id}", tags=["assessments"], responses=_COMMON)


@by_offering.get(
    "/assessments",
    response_model=AssessmentList,
    description="Ordered by sequence_no, with result counts over the active cohort and a "
    "warning when total weightage exceeds 100.",
)
def list_assessments(offering_id: uuid.UUID, actor: CurrentUser, db: DB) -> AssessmentList:
    return AssessmentService(db).list(offering_id, actor=actor)


@by_offering.post(
    "/assessments", response_model=AssessmentDetail, status_code=201, responses=_WRITE
)
def create_assessment(
    offering_id: uuid.UUID, body: AssessmentCreate, actor: CurrentUser, db: DB
) -> AssessmentDetail:
    service = AssessmentService(db)
    return service.detail(service.create(offering_id, body, actor=actor))


@by_offering.post(
    "/assessments/apply-scheme",
    response_model=AssessmentList,
    summary="Create the SRM assessment components for the course type",
    description=(
        "Theory: FT-I..FT-IV + LLT-I (60). Joint: FJ-I..III + LLJ-I/II (60). Project: FP-I/II, "
        "PBL-I..III, Report and Viva Voce (100). Practical: FL-I..IV + Practical Exam (100). "
        "Non-credit: FM-I..III (no marks). Components that already exist are left alone."
    ),
)
def apply_scheme(offering_id: uuid.UUID, actor: CurrentUser, db: DB) -> AssessmentList:
    service = AssessmentService(db)
    service.apply_scheme(offering_id, actor=actor)
    return service.list(offering_id, actor=actor)


@by_offering.get(
    "/results",
    response_model=OfferingResults,
    summary="All results of an offering (analytics read)",
    description=(
        "Offering settings, assessments (published only by default), the cohort (ACTIVE "
        "enrolments of active students by default) and every stored result. A student "
        "without a row for an assessment is *missing* — never 0."
    ),
)
def offering_results(
    offering_id: uuid.UUID,
    actor: CurrentUser,
    db: DB,
    published_only: bool = True,
    include_dropped: bool = False,
) -> OfferingResults:
    return OfferingResultsService(db).for_user(
        offering_id, actor=actor, published_only=published_only, include_dropped=include_dropped
    )


# ------------------------------------------------------------------ single assessment

assessments = APIRouter(prefix="/assessments", tags=["assessments"], responses=_COMMON)


@assessments.get("/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(assessment_id: uuid.UUID, actor: CurrentUser, db: DB) -> AssessmentDetail:
    service = AssessmentService(db)
    return service.detail(service.get(assessment_id, actor=actor))


@assessments.patch("/{assessment_id}", response_model=AssessmentDetail, responses=_WRITE)
def update_assessment(
    assessment_id: uuid.UUID, body: AssessmentUpdate, actor: CurrentUser, db: DB
) -> AssessmentDetail:
    service = AssessmentService(db)
    return service.detail(service.update(assessment_id, body, actor=actor))


@assessments.delete("/{assessment_id}", responses=_WRITE, **_NO_CONTENT)
def delete_assessment(assessment_id: uuid.UUID, actor: CurrentUser, db: DB) -> None:
    AssessmentService(db).delete(assessment_id, actor=actor)


@assessments.get(
    "/{assessment_id}/results",
    response_model=ResultsGrid,
    description="One row per cohort student; state is present/absent/exempt/missing.",
)
def get_results(
    assessment_id: uuid.UUID, actor: CurrentUser, db: DB, include_dropped: bool = False
) -> ResultsGrid:
    return AssessmentService(db).results_grid(
        assessment_id, actor=actor, include_dropped=include_dropped
    )


@assessments.put(
    "/{assessment_id}/results",
    response_model=UpsertSummary,
    responses=_WRITE,
    summary="Bulk upsert results",
    description=(
        "All-or-nothing. Each entry: student_id or register_number, and a score (present) or "
        "status absent/exempt. Blank entries are rejected, never stored as 0. Changed results "
        "are audited with their old values; the recompute hook runs before commit."
    ),
)
def put_results(
    assessment_id: uuid.UUID, body: ResultsUpsert, actor: CurrentUser, db: DB
) -> UpsertSummary:
    return AssessmentService(db).upsert_results(assessment_id, body.results, actor=actor)


@assessments.delete(
    "/{assessment_id}/results/{student_id}",
    responses=_WRITE,
    summary="Remove a result (student becomes missing)",
    **_NO_CONTENT,
)
def delete_result(
    assessment_id: uuid.UUID, student_id: uuid.UUID, actor: CurrentUser, db: DB
) -> None:
    AssessmentService(db).delete_result(assessment_id, student_id, actor=actor)


# ------------------------------------------------------------------ settings

SettingKey = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,100}$")]
settings = APIRouter(
    prefix="/departments/{department_id}/settings", tags=["settings"], responses=_COMMON
)


@settings.get("", response_model=list[SettingRead])
def list_settings(department_id: uuid.UUID, _: CurrentUser, db: DB) -> list[SettingRead]:
    return [SettingRead.model_validate(s) for s in SettingsService(db).list(department_id)]


@settings.put("/{key}", response_model=SettingRead, responses=_WRITE)
def put_setting(
    department_id: uuid.UUID, key: SettingKey, body: SettingWrite, actor: CurrentUser, db: DB
) -> SettingRead:
    return SettingRead.model_validate(
        SettingsService(db).put(department_id, key, body.value, actor=actor)
    )


@settings.delete("/{key}", responses=_WRITE, **_NO_CONTENT)
def delete_setting(department_id: uuid.UUID, key: SettingKey, actor: CurrentUser, db: DB) -> None:
    SettingsService(db).delete(department_id, key, actor=actor)


# ------------------------------------------------------------------ admin

admin = APIRouter(prefix="/admin", tags=["admin"], responses=_COMMON)


class RecomputeResult(BaseModel):
    offering_id: uuid.UUID
    assessments_recomputed: int


@admin.post(
    "/recompute",
    response_model=RecomputeResult,
    summary="Re-run the analytics recompute hook for an offering",
)
def recompute_offering(
    actor: AdminUser, db: DB, offering_id: Annotated[uuid.UUID, Query()]
) -> RecomputeResult:
    count = RecomputeService(db).offering(offering_id, actor=actor)
    return RecomputeResult(offering_id=offering_id, assessments_recomputed=count)


ROUTERS = [by_offering, assessments, settings, admin]
