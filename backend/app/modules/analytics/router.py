"""``/api/v1`` analytics endpoints. Thin: authorise, call the service, serialise.

No router function here computes anything. Each one resolves the current user through the
platform's own dependency, hands the offering to :class:`AnalyticsService`, and returns the
contract that comes back — FastAPI serialises it, and because the response models *are* the
analytics contracts, the OpenAPI document is generated from the same definitions the engine
produces.

**Scope** is the platform's. ``OfferingResultsService.for_user`` raises ``NotFoundError`` for
an offering the user may not see, so out-of-scope and non-existent are the same 404 and
existence is never disclosed. There is no second authorisation check here to fall out of step
with the first.

**Insufficient data is a 200.** A trend that could not be classified, a comparison with no
earlier assessment, an attention block that was not evaluated — each is a value in the
response with its own reason, not an error and not a silent zero. The only 4xx responses are
about the request: unauthenticated, out of scope, or an unknown report type or format.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

import app.modules.analytics.recompute  # noqa: F401  (installs the C4 hook)
from app.core.errors import ErrorResponse, NotFoundError
from app.db.session import get_db
from app.modules.analytics.service import (
    AnalyticsService,
    ClassAnalytics,
    CohortAttention,
    CohortInsights,
    ExportFormat,
    StudentAnalytics,
)
from app.modules.auth.dependencies import CurrentUser
from app.modules.reports.model import ReportKind

DB = Annotated[Session, Depends(get_db)]

_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Not permitted"},
    404: {"model": ErrorResponse, "description": "Not found or out of scope"},
}


def get_analytics_service(db: DB) -> AnalyticsService:
    """The service, as a dependency so tests can substitute one without a database."""
    return AnalyticsService(db)


Analytics = Annotated[AnalyticsService, Depends(get_analytics_service)]

OfferingId = Annotated[uuid.UUID, Path(description="Course offering to analyse")]
StudentId = Annotated[uuid.UUID, Path(description="Student enrolled in that offering")]

router = APIRouter(prefix="/offerings/{offering_id}", tags=["analytics"], responses=_COMMON)


@router.get(
    "/analytics",
    response_model=ClassAnalytics,
    summary="Class health, what changed, attention counts and insights",
    description=(
        "The offering dashboard, computed from a single read of the offering's results. "
        "Values that cannot be computed are returned as insufficient-data measures carrying "
        "their own reason — never as zero. `change` is null when the offering has no "
        "published assessment to analyse."
    ),
)
def class_analytics(
    offering_id: OfferingId, actor: CurrentUser, service: Analytics
) -> ClassAnalytics:
    return service.class_analytics(offering_id, actor=actor)


@router.get(
    "/students/{student_id}/analytics",
    response_model=StudentAnalytics,
    summary="One student's profile, segment, attention flags and insights",
    description=(
        "404 when the student is not enrolled in this offering: the question has no answer "
        "for them here, which is different from an empty profile."
    ),
)
def student_analytics(
    offering_id: OfferingId,
    student_id: StudentId,
    actor: CurrentUser,
    service: Analytics,
) -> StudentAnalytics:
    return service.student_analytics(offering_id, student_id, actor=actor)


@router.get(
    "/attention",
    response_model=CohortAttention,
    summary="Every attention flag in the cohort (R1-R7)",
    description=(
        "All flags are preserved: a student firing three rules appears with three flags, "
        "ordered by rule code R1 to R7. That ordering is deterministic, not a priority, and "
        "flags are never collapsed into a score or a single reason."
    ),
)
def attention(offering_id: OfferingId, actor: CurrentUser, service: Analytics) -> CohortAttention:
    return service.attention(offering_id, actor=actor)


@router.get(
    "/insights",
    response_model=CohortInsights,
    summary="Deterministic insight sentences for the cohort",
    description=(
        "Template-generated from the analytics above — no model of any kind. Each insight "
        "carries its stable code and the evidence that produced it, in a fixed presentation "
        "order."
    ),
)
def insights(offering_id: OfferingId, actor: CurrentUser, service: Analytics) -> CohortInsights:
    return service.insights(offering_id, actor=actor)


@router.get(
    "/reports/{report_kind}",
    response_class=Response,
    summary="Download a report as CSV, XLSX or PDF",
    description=(
        "The same report data serialised three ways; the numbers agree across formats "
        "because all three are rendered from one report object. A student report requires "
        "`student_id`."
    ),
    responses={
        **_COMMON,
        200: {
            "content": {
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/pdf": {},
            },
            "description": "The report file",
        },
    },
)
def report(
    offering_id: OfferingId,
    report_kind: Annotated[ReportKind, Path(description="Which report to build")],
    actor: CurrentUser,
    service: Analytics,
    export_format: Annotated[
        str, Query(alias="format", description="csv, xlsx or pdf")
    ] = ExportFormat.CSV,
    student_id: Annotated[
        uuid.UUID | None, Query(description="Required for a student report")
    ] = None,
) -> Response:
    if export_format not in ExportFormat.all():
        raise NotFoundError(
            f"Unknown export format {export_format!r}. Use one of {', '.join(ExportFormat.all())}."
        )
    built = service.report(
        offering_id,
        report_kind,
        actor=actor,
        student_id=student_id,
        generated_at=datetime.now(UTC),
    )
    body, media_type, filename = service.export(built, export_format)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


ROUTERS = [router]
