from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select

from app.db.repository import BaseRepository
from app.modules.assessments.models import Assessment, AssessmentResult, ResultStatus
from app.modules.students.models import Enrollment, EnrollmentStatus, Student


def cohort_condition(offering_id: uuid.UUID, include_dropped: bool = False):
    """Enrolments forming an offering's cohort: ACTIVE enrolments of active students."""
    conditions = [Enrollment.offering_id == offering_id]
    if not include_dropped:
        conditions += [Enrollment.status == EnrollmentStatus.ACTIVE, Student.is_active.is_(True)]
    return conditions


class AssessmentRepository(BaseRepository[Assessment]):
    model = Assessment

    def for_offering(
        self, offering_id: uuid.UUID, *, published_only: bool = False
    ) -> list[Assessment]:
        query = select(Assessment).where(Assessment.offering_id == offering_id)
        if published_only:
            query = query.where(Assessment.is_published.is_(True))
        return list(self.session.scalars(query.order_by(Assessment.sequence_no)))

    def next_sequence_no(self, offering_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.max(Assessment.sequence_no)).where(Assessment.offering_id == offering_id)
        )
        return (current or 0) + 1

    def by_name(self, offering_id: uuid.UUID) -> dict[str, Assessment]:
        """Lower-cased name -> assessment."""
        return {a.name.lower(): a for a in self.for_offering(offering_id)}


class ResultRepository(BaseRepository[AssessmentResult]):
    model = AssessmentResult

    def for_assessment(self, assessment_id: uuid.UUID) -> dict[uuid.UUID, AssessmentResult]:
        rows = self.session.scalars(
            select(AssessmentResult).where(AssessmentResult.assessment_id == assessment_id)
        )
        return {r.student_id: r for r in rows.unique()}

    def for_assessments(self, assessment_ids: Iterable[uuid.UUID]) -> list[AssessmentResult]:
        ids = list(assessment_ids)
        if not ids:
            return []
        return list(
            self.session.scalars(
                select(AssessmentResult).where(AssessmentResult.assessment_id.in_(ids))
            ).unique()
        )

    def exists_for_assessment(self, assessment_id: uuid.UUID) -> bool:
        return self.exists(AssessmentResult.assessment_id == assessment_id)

    def status_counts(
        self, offering_id: uuid.UUID, assessment_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[ResultStatus, int]]:
        """Per assessment, result counts over the active cohort only."""
        if not assessment_ids:
            return {}
        rows = self.session.execute(
            select(AssessmentResult.assessment_id, AssessmentResult.status, func.count())
            .join(Enrollment, Enrollment.student_id == AssessmentResult.student_id)
            .join(Student, Student.id == Enrollment.student_id)
            .where(
                AssessmentResult.assessment_id.in_(assessment_ids), *cohort_condition(offering_id)
            )
            .group_by(AssessmentResult.assessment_id, AssessmentResult.status)
        )
        counts: dict[uuid.UUID, dict[ResultStatus, int]] = {}
        for assessment_id, status, n in rows:
            counts.setdefault(assessment_id, {})[status] = n
        return counts


class CohortRepository:
    """Enrolled students of an offering, joined with their enrolment status."""

    def __init__(self, session) -> None:
        self.session = session

    def members(
        self, offering_id: uuid.UUID, *, include_dropped: bool = False
    ) -> list[tuple[Student, Enrollment]]:
        rows = self.session.execute(
            select(Student, Enrollment)
            .join(Enrollment, Enrollment.student_id == Student.id)
            .where(*cohort_condition(offering_id, include_dropped))
            .order_by(Student.register_number)
        )
        return [(s, e) for s, e in rows.unique()]

    def size(self, offering_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(Enrollment)
                .join(Student, Student.id == Enrollment.student_id)
                .where(*cohort_condition(offering_id))
            )
            or 0
        )

    def enrollments_by_student(self, offering_id: uuid.UUID) -> dict[uuid.UUID, Enrollment]:
        rows = self.session.scalars(select(Enrollment).where(Enrollment.offering_id == offering_id))
        return {e.student_id: e for e in rows.unique()}
