"""The adapter: the platform's stored data, mapped onto the analytics input contract.

This is the only place in the intelligence layer that knows what the platform's schema looks
like. Everything above it consumes :class:`OfferingSnapshot`, which is why the engine can be
proved against hand-written fixtures and why a change to a column name reaches exactly one
file.

It is deliberately split in two:

:func:`snapshot_from_offering_results`
    a **pure function** from the platform's ``OfferingResults`` to an ``OfferingSnapshot``.
    No session, no query, no I/O — so the mapping itself is unit-testable without a database,
    which matters because this is where a field could silently be read from the wrong place.

:class:`AnalyticsRepository`
    the thin session-bound part: one call to ``OfferingResultsService``, one call to
    ``SettingsService``, then the mapper. It adds no logic of its own.

Reads go through the platform's own service (README rule 4 / contract C3), never through a
query on its tables, so faculty scope and the PII rules are enforced in one place. Passing an
``actor`` gets the scoped read — an offering the user cannot see is a 404, and existence is
not disclosed; ``actor=None`` is the unscoped system path, for the recompute hook only.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.modules.analytics.config import resolve_offering_thresholds
from app.modules.analytics.core.contracts import (
    AssessmentRef,
    OfferingSnapshot,
    ResultRecord,
    ResultStatus,
    StudentRef,
)
from app.modules.analytics.core.thresholds import ThresholdSet
from app.modules.assessments.models import ResultStatus as StoredResultStatus
from app.modules.assessments.schemas import (
    AssessmentRead,
    MatrixResult,
    MatrixStudent,
    OfferingResults,
)
from app.modules.assessments.service import OfferingResultsService, SettingsService
from app.modules.reports.model import OfferingIdentity
from app.modules.students.models import EnrollmentStatus
from app.modules.users.models import User


def _status(stored: StoredResultStatus) -> ResultStatus:
    """Map the platform's stored status onto the analytics vocabulary.

    The two enums are deliberately identical in value, and
    ``tests/analytics/test_repository.py`` asserts that they stay that way: if the platform
    ever adds a fourth status, this raises instead of guessing what it means for a mean.
    """
    try:
        return ResultStatus(stored.value)
    except ValueError as exc:  # pragma: no cover - guarded by a test on the enum pair
        raise ValueError(
            f"the platform recorded result status {stored.value!r}, which analytics does not "
            "know how to treat. Add it to the missing-data policy before reading it."
        ) from exc


def _assessment(row: AssessmentRead) -> AssessmentRef:
    return AssessmentRef(
        id=row.id,
        code=row.name,
        sequence_no=row.sequence_no,
        max_marks=row.max_marks,
        weightage=row.weightage,
        held_on=row.assessment_date,
        is_published=row.is_published,
    )


def _student(row: MatrixStudent) -> StudentRef:
    """Active for analytics means *enrolled on this offering* and not a deactivated record.

    Two different flags, and both have to hold: a student who dropped the course keeps their
    results (they are history) but is not part of the cohort a class statistic is over.
    """
    return StudentRef(
        id=row.id,
        register_no=row.register_number,
        name=row.full_name,
        is_active=row.enrollment_status is EnrollmentStatus.ACTIVE and row.is_active,
    )


def _result(row: MatrixResult, max_marks: Mapping[uuid.UUID, Decimal]) -> ResultRecord:
    expected = max_marks[row.assessment_id]
    if row.max_marks_snapshot != expected:
        raise ValueError(
            f"result for student {row.student_id} on assessment {row.assessment_id} was "
            f"recorded out of {row.max_marks_snapshot} but the assessment is now out of "
            f"{expected}. The platform guarantees max_marks cannot change once results "
            "exist, so this is a data inconsistency: analytics will not guess which "
            "denominator the score belongs to."
        )
    return ResultRecord(
        student_id=row.student_id,
        assessment_id=row.assessment_id,
        status=_status(row.status),
        score=row.score,
    )


def snapshot_from_offering_results(data: OfferingResults) -> OfferingSnapshot:
    """Map one platform read onto the analytics input contract. Pure; no session.

    The platform's ``percentage`` field is intentionally **not** carried across: analytics
    recomputes it from ``score`` and ``max_marks`` through
    :func:`~app.modules.analytics.core.policy.assessment_percentage`, so there is one
    rounding rule in the system rather than two that agree until they do not.
    """
    assessments = tuple(_assessment(row) for row in data.assessments)
    max_marks = {row.id: row.max_marks for row in data.assessments}
    return OfferingSnapshot(
        offering_id=data.offering.id,
        pass_mark_percent=data.offering.pass_percent,
        assessments=assessments,
        students=tuple(_student(row) for row in data.students),
        results=tuple(_result(row, max_marks) for row in data.results),
    )


class OfferingContext(BaseModel):
    """One offering's data and its resolved thresholds, read together.

    They travel as a pair because they are read together and must agree: every analytic
    needs both, and a threshold set resolved against a different offering's pass mark is
    rejected by the engine.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    snapshot: OfferingSnapshot
    thresholds: ThresholdSet
    identity: OfferingIdentity = OfferingIdentity()
    """Course code, section and term, for naming a report. Not an analytics input: the engine
    never reads it, and the snapshot deliberately excludes it."""


class AnalyticsRepository:
    """Reads academic data for the analytics engine. Implements ``SnapshotSource``."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._results = OfferingResultsService(session)
        self._settings = SettingsService(session)

    def snapshot_for_offering(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User | None = None,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingSnapshot:
        """The offering's snapshot. ``actor=None`` skips the access check — system paths only."""
        return snapshot_from_offering_results(
            self._read(
                offering_id,
                actor=actor,
                published_only=published_only,
                include_dropped=include_dropped,
            )
        )

    def context_for_offering(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User | None = None,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingContext:
        """The snapshot plus thresholds resolved for this offering, in one read."""
        data = self._read(
            offering_id,
            actor=actor,
            published_only=published_only,
            include_dropped=include_dropped,
        )
        return OfferingContext(
            snapshot=snapshot_from_offering_results(data),
            thresholds=self.thresholds_from(data),
            identity=OfferingIdentity(
                course_code=data.offering.course_code,
                section_name=data.offering.section_name,
                term_code=data.offering.term_code,
            ),
        )

    def thresholds_from(self, data: OfferingResults) -> ThresholdSet:
        """Resolve thresholds for an offering already read.

        Contract C5's full order: the offering's ``config`` overrides the department's
        ``settings``, which override the deployment default, which overrides the built-in
        one. Keys this version of analytics does not know are ignored and reported in
        ``ignored_keys`` rather than failing the read.
        """
        return resolve_offering_thresholds(
            pass_mark_percent=data.offering.pass_percent,
            offering_overrides=data.offering.config,
            department_settings=self._settings.as_dict(data.offering.department_id),
        )

    def _read(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User | None,
        published_only: bool,
        include_dropped: bool,
    ) -> OfferingResults:
        if actor is None:
            return self._results.unscoped(
                offering_id, published_only=published_only, include_dropped=include_dropped
            )
        return self._results.for_user(
            offering_id,
            actor=actor,
            published_only=published_only,
            include_dropped=include_dropped,
        )
