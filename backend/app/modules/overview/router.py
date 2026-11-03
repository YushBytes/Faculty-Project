"""``/api/v1/insights`` — scoped, aggregated analytics for every level of the hierarchy, and
``/api/v1/me/workspace`` — the signed-in user's institutional context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.overview import reports
from app.modules.overview.models import GeneratedReport
from app.modules.overview.service import Filters, InsightsService, filters_from
from app.modules.overview.workspace import student_overview, workspace

DB = Annotated[Session, Depends(get_db)]
_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    404: {"model": ErrorResponse, "description": "Not found or out of scope"},
}


def scope_filters(
    academic_year: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    semester: Annotated[Literal["ODD", "EVEN", "YEAR"] | None, Query()] = None,
    term_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    coordinator_id: uuid.UUID | None = None,
    offering_id: uuid.UUID | None = None,
) -> Filters:
    return filters_from(
        academic_year=academic_year,
        semester=semester,
        term_id=term_id,
        department_id=department_id,
        course_id=course_id,
        section_id=section_id,
        faculty_id=faculty_id,
        coordinator_id=coordinator_id,
        offering_id=offering_id,
    )


Scope = Annotated[Filters, Depends(scope_filters)]
insights = APIRouter(prefix="/insights", tags=["insights"], responses=_COMMON)

_SCOPE_DOC = (
    "Scope is the caller's (Admin: everything; HOD / Academic Head: their department; "
    "Coordinator: their courses; Faculty: their classes), narrowed by the filters. Period "
    "defaults to the current term; `semester=YEAR` covers both semesters of the academic year."
)


@insights.get("/overview", summary="Dashboard for any scope", description=_SCOPE_DOC)
def overview(actor: CurrentUser, db: DB, filters: Scope) -> dict[str, Any]:
    return InsightsService(db).overview(filters, actor=actor)


@insights.get("/offerings", summary="Every class in scope with headline measures")
def offerings(actor: CurrentUser, db: DB, filters: Scope) -> dict[str, Any]:
    return InsightsService(db).offerings(filters, actor=actor)


@insights.get("/assessments/{key}", summary="One assessment name across every class in scope")
def assessment(key: str, actor: CurrentUser, db: DB, filters: Scope) -> dict[str, Any]:
    return InsightsService(db).assessment(filters, key.lower(), actor=actor)


@insights.get("/attention", summary="Live attention flags across the scope")
def attention(
    actor: CurrentUser,
    db: DB,
    filters: Scope,
    rule: str | None = None,
    severity: Literal["high", "medium", "low"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return InsightsService(db).attention(
        filters, actor=actor, rule=rule, severity=severity, limit=limit, offset=offset
    )


@insights.get("/interventions", summary="Interventions recorded across the scope")
def interventions(
    actor: CurrentUser,
    db: DB,
    filters: Scope,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return InsightsService(db).interventions(filters, actor=actor, limit=limit, offset=offset)


@insights.get("/students/{student_id}", summary="One student across their classes")
def student(student_id: uuid.UUID, actor: CurrentUser, db: DB) -> dict[str, Any]:
    return student_overview(db, actor, student_id)


@insights.get(
    "/report",
    response_class=Response,
    summary="Download the scope report (PDF, XLSX or CSV)",
    description=(
        "Built from the same aggregation as `/insights/overview` for the same filters, so the "
        "numbers match the dashboard. " + _SCOPE_DOC
    ),
)
def report(
    actor: CurrentUser,
    db: DB,
    filters: Scope,
    export_format: Annotated[Literal["pdf", "xlsx", "csv"], Query(alias="format")] = "pdf",
    kind: Annotated[Literal["summary", "attention", "comparison"], Query()] = "summary",
) -> Response:
    data = InsightsService(db).overview(filters, actor=actor)
    built = reports.build(data, kind=kind, role=actor.role.value, generated_at=datetime.now(UTC))
    body, media = reports.export(built, data, export_format)
    stem = "".join(ch if ch.isalnum() else "-" for ch in built.metadata.title.lower()).strip("-")
    stem = "-".join(part for part in stem.split("-") if part)[:80]
    name = f"{stem}-{datetime.now(UTC):%Y%m%d}.{export_format}"
    db.add(
        GeneratedReport(
            generated_by_id=actor.id,
            title=built.metadata.title,
            scope={**data["filters"], "period": data["period"]},
            kind=kind,
            export_format=export_format,
            file_name=name,
            size_bytes=len(body),
        )
    )
    db.commit()
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@insights.get("/reports/history", summary="Reports you generated")
def report_history(
    actor: CurrentUser, db: DB, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(GeneratedReport)
        .where(GeneratedReport.generated_by_id == actor.id)
        .order_by(GeneratedReport.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "scope": r.scope,
            "kind": r.kind,
            "format": r.export_format,
            "file_name": r.file_name,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


me = APIRouter(prefix="/me", tags=["auth"], responses=_COMMON)


@me.get("/workspace", summary="The signed-in user's institutional context")
def my_workspace(actor: CurrentUser, db: DB) -> dict[str, Any]:
    return workspace(db, actor)


ROUTERS = [insights, me]
