"""``/api/v1`` intervention endpoints. Thin: authorise, call the service, serialise.

Four routes, and deliberately no more:

===========================================================  ==================================
``POST   /offerings/{id}/interventions``                     record one
``GET    /offerings/{id}/interventions``                     list them for the offering
``GET    /offerings/{id}/students/{sid}/interventions``       list them for one student
``GET    /offerings/{id}/interventions/outcomes``             measure them (Phase 6 engine)
===========================================================  ==================================

**There is no endpoint that creates an attention flag.** Flags are materialised state owned by
the recompute hook: a client-created flag would be indistinguishable from a fired rule, and the
attention responses under ``/offerings/{id}/attention`` are computed by the engine from the
current snapshot. Reading the stored table over HTTP would be a second source of truth for the
same question, so it is not exposed.

Insufficient data stays a 200 with its own reason, as everywhere else in analytics. The 4xx
responses are about the request: unauthenticated, out of scope (404), or a target who is not an
active enrolment of the offering (422).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.analytics.core.vocabulary import InterventionStatus
from app.modules.auth.dependencies import CurrentUser
from app.modules.interventions.schemas import InterventionCreate, InterventionRead
from app.modules.interventions.service import InterventionOutcomes, InterventionService

DB = Annotated[Session, Depends(get_db)]

_COMMON = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    404: {"model": ErrorResponse, "description": "Not found or out of scope"},
    422: {"model": ErrorResponse, "description": "Validation or data rule violation"},
}


def get_intervention_service(db: DB) -> InterventionService:
    """The service, as a dependency so tests can substitute one without a database."""
    return InterventionService(db)


Interventions = Annotated[InterventionService, Depends(get_intervention_service)]
Paging = Annotated[PageParams, Depends(page_params)]

OfferingId = Annotated[uuid.UUID, Path(description="Course offering the intervention belongs to")]
StudentId = Annotated[uuid.UUID, Path(description="Student enrolled in that offering")]
StatusFilter = Annotated[
    InterventionStatus | None, Query(description="Only interventions in this status")
]

router = APIRouter(prefix="/offerings/{offering_id}", tags=["interventions"], responses=_COMMON)


@router.post(
    "/interventions",
    response_model=InterventionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record an intervention for one or more students",
    description=(
        "Anyone who can view the offering may record one: the faculty assigned to it, their "
        "HOD, and an admin.\n\n"
        "Every target must be an active enrolment of the offering. A reason may name a live "
        "attention flag (`flag_id`), and its rule, observed value and threshold are then frozen "
        "into the stored reason as they stand now — recomputing that flag later will not rewrite "
        "what the teacher saw. A `rule_code` cannot be asserted directly, so an analytics reason "
        "always traces back to a rule that actually fired.\n\n"
        "The pre/post boundary is `after_sequence_no`, an assessment sequence rather than a "
        "date: assessment dates are optional in this system and ordering never depends on them."
    ),
)
def create_intervention(
    offering_id: OfferingId,
    payload: InterventionCreate,
    actor: CurrentUser,
    service: Interventions,
) -> InterventionRead:
    return service.create(offering_id, payload, actor=actor)


@router.get(
    "/interventions",
    response_model=Page[InterventionRead],
    summary="Interventions recorded for this offering",
    description="Ordered by the assessment window they sit in, then by when they were recorded.",
)
def list_interventions(
    offering_id: OfferingId,
    actor: CurrentUser,
    service: Interventions,
    page: Paging,
    intervention_status: StatusFilter = None,
) -> Page[InterventionRead]:
    return service.list_for_offering(
        offering_id, actor=actor, page=page, status=intervention_status
    )


@router.get(
    "/interventions/outcomes",
    response_model=InterventionOutcomes,
    summary="Observed outcomes for this offering's interventions",
    description=(
        "Measured by the Phase 6 engine from the current results, never stored: an outcome "
        "changes the moment a new assessment lands.\n\n"
        "Every outcome carries the observational caveat. The targeted students were chosen "
        "*because* they were struggling, the groups were not randomised and nobody was withheld "
        "support, so a change after an intervention is reported and never attributed to it. An "
        "intervention with too little data on either side of the boundary is returned with its "
        "own insufficient-data reason, not as a zero."
    ),
)
def intervention_outcomes(
    offering_id: OfferingId, actor: CurrentUser, service: Interventions
) -> InterventionOutcomes:
    return service.outcomes(offering_id, actor=actor)


@router.get(
    "/students/{student_id}/interventions",
    response_model=Page[InterventionRead],
    summary="Interventions recorded for one student in this offering",
    description="404 when the offering is out of scope; 422 when the student is not enrolled here.",
)
def list_student_interventions(
    offering_id: OfferingId,
    student_id: StudentId,
    actor: CurrentUser,
    service: Interventions,
    page: Paging,
    intervention_status: StatusFilter = None,
) -> Page[InterventionRead]:
    return service.list_for_offering(
        offering_id,
        actor=actor,
        page=page,
        student_id=student_id,
        status=intervention_status,
    )


ROUTERS = [router]
