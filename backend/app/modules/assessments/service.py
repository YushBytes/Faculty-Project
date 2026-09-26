"""Assessments, results, the offering results read (for analytics), settings and recompute.

Access:
    Assessments and results of an offering are readable AND writable by anyone who can
    VIEW the offering (assigned faculty, the department's HOD, ADMIN) — faculty enter
    their own marks. Anything else is 404.
    Department settings: readable by any signed-in user; writable by ADMIN or the HOD
    of that department.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.recompute import recompute
from app.db.repository import write_guard
from app.modules.assessments.models import (
    Assessment,
    AssessmentResult,
    ResultSource,
    ResultStatus,
)
from app.modules.assessments.repository import (
    AssessmentRepository,
    CohortRepository,
    ResultRepository,
)
from app.modules.assessments.schemas import (
    AssessmentCreate,
    AssessmentDetail,
    AssessmentList,
    AssessmentRead,
    AssessmentUpdate,
    MatrixOffering,
    MatrixResult,
    MatrixStudent,
    OfferingResults,
    ResultCounts,
    ResultEntry,
    ResultRead,
    ResultRow,
    ResultsGrid,
    UpsertSummary,
)
from app.modules.audit.service import AuditService
from app.modules.organization.models import CourseOffering, Department, DepartmentSetting
from app.modules.organization.scope import Access, OfferingAccess, can_manage_department
from app.modules.students.models import EnrollmentStatus, Student
from app.modules.students.schemas import StudentSummary
from app.modules.users.models import Role, User

HUNDRED = Decimal("100")
CENT = Decimal("0.01")


def percentage(score: Decimal | None, max_marks: Decimal) -> Decimal | None:
    """100 * score / max, rounded half-up to 2 dp. None unless a score exists."""
    if score is None:
        return None
    return (score * HUNDRED / max_marks).quantize(CENT, rounding=ROUND_HALF_UP)


def result_read(result: AssessmentResult) -> ResultRead:
    return ResultRead(
        score=result.score,
        status=result.status,
        max_marks_snapshot=result.max_marks_snapshot,
        percentage=percentage(result.score, result.max_marks_snapshot),
        source=result.source,
        recorded_at=result.recorded_at,
        updated_at=result.updated_at,
    )


def _snapshot(result: AssessmentResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "score": result.score,
        "max_marks_snapshot": result.max_marks_snapshot,
        "source": result.source,
    }


# ====================================================================== results writer


@dataclass(frozen=True)
class ResultChange:
    """A validated result for one student. ``score`` is None unless status is present."""

    student_id: uuid.UUID
    status: ResultStatus
    score: Decimal | None


class ResultWriter:
    """Applies validated results to one assessment inside the caller's transaction.

    Used by manual entry and by import confirm. Overwrites are audited with old and new
    values (contract C12); recompute (C4) runs before the caller commits. Never commits.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._results = ResultRepository(session)
        self._audit = AuditService(session)

    def apply(
        self,
        assessment: Assessment,
        changes: list[ResultChange],
        *,
        actor: User,
        source: ResultSource,
        import_batch_id: uuid.UUID | None = None,
    ) -> UpsertSummary:
        existing = self._results.for_assessment(assessment.id)
        created = updated = unchanged = 0
        with write_guard(self._session, invalid="A result violates a data rule."):
            for change in changes:
                current = existing.get(change.student_id)
                if current is None:
                    result = AssessmentResult(
                        student_id=change.student_id,
                        assessment_id=assessment.id,
                        status=change.status,
                        score=change.score,
                        max_marks_snapshot=assessment.max_marks,
                        source=source,
                        recorded_by_id=actor.id,
                    )
                    if import_batch_id is not None:
                        result.import_batch_id = import_batch_id
                    self._results.add(result)
                    created += 1
                    continue
                if current.status == change.status and current.score == change.score:
                    unchanged += 1
                    continue
                old = _snapshot(current)
                current.status = change.status
                current.score = change.score
                current.max_marks_snapshot = assessment.max_marks
                current.source = source
                current.recorded_by_id = actor.id
                if import_batch_id is not None:
                    current.import_batch_id = import_batch_id
                self._audit.record(
                    actor_id=actor.id,
                    entity="assessment_result",
                    entity_id=f"{assessment.id}:{change.student_id}",
                    action="update",
                    old=old,
                    new={**_snapshot(current), "import_batch_id": import_batch_id},
                    offering_id=assessment.offering_id,
                )
                updated += 1
        if created or updated:
            recompute(self._session, assessment.id)
        return UpsertSummary(created=created, updated=updated, unchanged=unchanged)

    def delete(self, assessment: Assessment, student_id: uuid.UUID, *, actor: User) -> None:
        result = self._results.for_assessment(assessment.id).get(student_id)
        if result is None:
            raise NotFoundError("No result recorded for this student.")
        self._audit.record(
            actor_id=actor.id,
            entity="assessment_result",
            entity_id=f"{assessment.id}:{student_id}",
            action="delete",
            old=_snapshot(result),
            offering_id=assessment.offering_id,
        )
        self._results.delete(result)
        self._session.flush()
        recompute(self._session, assessment.id)


def validate_entry(
    entry_status: ResultStatus | None, score: Decimal | None, max_marks: Decimal
) -> tuple[ResultStatus | None, str | None, str | None]:
    """(status, field, message). A message means the entry is invalid.

    Shared by manual entry and the import validator so both apply identical rules.
    """
    status = entry_status
    if status is None:
        if score is None:
            return None, "score", "Give a score, or status 'absent' / 'exempt'."
        status = ResultStatus.PRESENT
    if status is ResultStatus.PRESENT and score is None:
        return None, "score", "A present result needs a score."
    if status is not ResultStatus.PRESENT and score is not None:
        return None, "score", f"A result marked {status.value} must not have a score."
    if score is not None:
        if score < 0:
            return None, "score", "Score cannot be negative."
        if score > max_marks:
            return None, "score", f"Score {score} is above the maximum {max_marks}."
    return status, None, None


# ====================================================================== assessments


class AssessmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = OfferingAccess(session)
        self._assessments = AssessmentRepository(session)
        self._results = ResultRepository(session)
        self._cohort = CohortRepository(session)

    # ---------------------------------------------------------------- access

    def get(self, assessment_id: uuid.UUID, *, actor: User) -> Assessment:
        assessment = self._assessments.get(assessment_id)
        if assessment is None:
            raise NotFoundError("Assessment not found.")
        try:
            self._access.get(actor, assessment.offering_id, Access.VIEW)
        except NotFoundError as exc:
            raise NotFoundError("Assessment not found.") from exc
        return assessment

    # ---------------------------------------------------------------- definitions

    def list(self, offering_id: uuid.UUID, *, actor: User) -> AssessmentList:
        self._access.get(actor, offering_id, Access.VIEW)
        assessments = self._assessments.for_offering(offering_id)
        counts = self._counts(offering_id, assessments)
        total = sum((a.weightage for a in assessments), Decimal("0"))
        warnings = []
        if total > HUNDRED:
            warnings.append(f"Total weightage is {total}, which exceeds 100.")
        return AssessmentList(
            items=[self._detail(a, counts[a.id]) for a in assessments],
            weightage_total=total,
            warnings=warnings,
        )

    def detail(self, assessment: Assessment) -> AssessmentDetail:
        return self._detail(
            assessment, self._counts(assessment.offering_id, [assessment])[assessment.id]
        )

    def create(self, offering_id: uuid.UUID, data: AssessmentCreate, *, actor: User) -> Assessment:
        self._access.get(actor, offering_id, Access.VIEW)
        sequence_no = data.sequence_no or self._assessments.next_sequence_no(offering_id)
        with write_guard(
            self._session,
            conflict=(
                f"An assessment named '{data.name}' or with sequence {sequence_no} already "
                "exists in this offering."
            ),
        ):
            assessment = self._assessments.add(
                Assessment(
                    offering_id=offering_id,
                    name=data.name,
                    assessment_type=data.assessment_type,
                    assessment_date=data.assessment_date,
                    max_marks=data.max_marks,
                    weightage=data.weightage,
                    sequence_no=sequence_no,
                    is_published=data.is_published,
                    created_by_id=actor.id,
                )
            )
        self._session.commit()
        self._session.refresh(assessment)
        return assessment

    def update(
        self, assessment_id: uuid.UUID, data: AssessmentUpdate, *, actor: User
    ) -> Assessment:
        assessment = self.get(assessment_id, actor=actor)
        changes = data.model_dump(exclude_unset=True)
        for required in ("name", "assessment_type", "max_marks", "weightage", "sequence_no"):
            if required in changes and changes[required] is None:
                changes.pop(required)
        if (
            "max_marks" in changes
            and changes["max_marks"] != assessment.max_marks
            and self._results.exists_for_assessment(assessment.id)
        ):
            raise BusinessRuleError(
                "max_marks cannot change after results are recorded; existing percentages "
                "would silently change. Delete the results first or create a new assessment."
            )
        with write_guard(
            self._session,
            conflict="Another assessment in this offering already uses that name or sequence.",
        ):
            for field, value in changes.items():
                setattr(assessment, field, value)
        self._session.commit()
        self._session.refresh(assessment)
        return assessment

    def delete(self, assessment_id: uuid.UUID, *, actor: User) -> None:
        assessment = self.get(assessment_id, actor=actor)
        if self._results.exists_for_assessment(assessment.id):
            raise ConflictError(
                "Assessment has recorded results; delete the results before the assessment."
            )
        with write_guard(self._session, in_use="Assessment is still referenced."):
            self._assessments.delete(assessment)
        self._session.commit()

    # ---------------------------------------------------------------- results

    def results_grid(
        self, assessment_id: uuid.UUID, *, actor: User, include_dropped: bool = False
    ) -> ResultsGrid:
        assessment = self.get(assessment_id, actor=actor)
        results = self._results.for_assessment(assessment.id)
        members = self._cohort.members(assessment.offering_id, include_dropped=include_dropped)
        rows: list[ResultRow] = []
        seen: set[uuid.UUID] = set()
        for student, enrollment in members:
            seen.add(student.id)
            result = results.get(student.id)
            rows.append(
                ResultRow(
                    student=StudentSummary.model_validate(student),
                    enrollment_status=enrollment.status,
                    state=result.status.value if result else "missing",
                    result=result_read(result) if result else None,
                )
            )
        # Results of students no longer in the active cohort stay visible, never hidden.
        enrollments = self._cohort.enrollments_by_student(assessment.offering_id)
        for student_id, result in results.items():
            if student_id not in seen:
                rows.append(
                    ResultRow(
                        student=StudentSummary.model_validate(result.student),
                        enrollment_status=enrollments[student_id].status
                        if student_id in enrollments
                        else EnrollmentStatus.DROPPED,
                        state=result.status.value,
                        result=result_read(result),
                    )
                )
        return ResultsGrid(
            assessment=AssessmentRead.model_validate(assessment),
            counts=self._counts(assessment.offering_id, [assessment])[assessment.id],
            rows=rows,
        )

    def upsert_results(
        self, assessment_id: uuid.UUID, entries: list[ResultEntry], *, actor: User
    ) -> UpsertSummary:
        assessment = self.get(assessment_id, actor=actor)
        changes = self.validate_entries(assessment, entries)
        summary = ResultWriter(self._session).apply(
            assessment, changes, actor=actor, source=ResultSource.MANUAL
        )
        self._session.commit()
        return summary

    def delete_result(
        self, assessment_id: uuid.UUID, student_id: uuid.UUID, *, actor: User
    ) -> None:
        assessment = self.get(assessment_id, actor=actor)
        ResultWriter(self._session).delete(assessment, student_id, actor=actor)
        self._session.commit()

    def validate_entries(
        self, assessment: Assessment, entries: list[ResultEntry]
    ) -> list[ResultChange]:
        """All-or-nothing: raise 422 listing every bad entry, or return all changes."""
        enrollments = self._cohort.enrollments_by_student(assessment.offering_id)
        existing = self._results.for_assessment(assessment.id)
        numbers = [e.register_number.strip().upper() for e in entries if e.register_number]
        by_number = {
            s.register_number: s
            for s in self._session.scalars(
                select(Student).where(Student.register_number.in_(numbers))
            ).unique()
        }
        ids = [e.student_id for e in entries if e.student_id]
        by_id = {
            s.id: s
            for s in self._session.scalars(select(Student).where(Student.id.in_(ids))).unique()
        }

        errors: list[dict[str, Any]] = []
        changes: list[ResultChange] = []
        seen: dict[uuid.UUID, int] = {}
        for index, entry in enumerate(entries):
            loc = ["body", "results", index]

            def fail(field: str, message: str, _loc: list = loc) -> None:
                errors.append({"loc": [*_loc, field], "message": message, "code": "invalid"})

            if entry.register_number:
                student = by_number.get(entry.register_number.strip().upper())
                ident, ident_field = entry.register_number, "register_number"
            else:
                student = by_id.get(entry.student_id)
                ident, ident_field = str(entry.student_id), "student_id"
            if student is None:
                fail(ident_field, f"Unknown student {ident}.")
                continue
            if student.id in seen:
                fail(ident_field, f"Duplicate of entry {seen[student.id]}.")
                continue
            seen[student.id] = index
            enrollment = enrollments.get(student.id)
            if enrollment is None:
                fail(ident_field, f"{student.register_number} is not enrolled in this offering.")
                continue
            is_new = student.id not in existing
            if is_new and (enrollment.status is EnrollmentStatus.DROPPED or not student.is_active):
                fail(
                    ident_field,
                    f"{student.register_number} has dropped the offering or is inactive; "
                    "new results cannot be added.",
                )
                continue
            status, field, message = validate_entry(entry.status, entry.score, assessment.max_marks)
            if message:
                fail(field or "score", message)
                continue
            changes.append(ResultChange(student_id=student.id, status=status, score=entry.score))

        if errors:
            raise BusinessRuleError(
                f"{len(errors)} result(s) are invalid; nothing was saved.", details=errors
            )
        return changes

    # ---------------------------------------------------------------- helpers

    def _counts(
        self, offering_id: uuid.UUID, assessments: list[Assessment]
    ) -> dict[uuid.UUID, ResultCounts]:
        enrolled = self._cohort.size(offering_id)
        raw = self._results.status_counts(offering_id, [a.id for a in assessments])
        out: dict[uuid.UUID, ResultCounts] = {}
        for assessment in assessments:
            by_status = raw.get(assessment.id, {})
            present = by_status.get(ResultStatus.PRESENT, 0)
            absent = by_status.get(ResultStatus.ABSENT, 0)
            exempt = by_status.get(ResultStatus.EXEMPT, 0)
            out[assessment.id] = ResultCounts(
                present=present,
                absent=absent,
                exempt=exempt,
                missing=max(enrolled - present - absent - exempt, 0),
                enrolled=enrolled,
            )
        return out

    @staticmethod
    def _detail(assessment: Assessment, counts: ResultCounts) -> AssessmentDetail:
        return AssessmentDetail.model_validate(
            {**AssessmentRead.model_validate(assessment).model_dump(), "result_counts": counts}
        )


# ====================================================================== analytics read


class OfferingResultsService:
    """The analytics read interface (contract C3 / request D8)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = OfferingAccess(session)

    def for_user(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingResults:
        """Scoped: 404 unless ``actor`` can view the offering. Use from API routes."""
        offering = self._access.get(actor, offering_id, Access.VIEW)
        return self._build(offering, published_only, include_dropped)

    def unscoped(
        self,
        offering_id: uuid.UUID,
        *,
        published_only: bool = True,
        include_dropped: bool = False,
    ) -> OfferingResults:
        """NO access check. Only for system work that has no user (the recompute hook).
        Never call it from a route with a user-supplied id."""
        offering = self._session.get(CourseOffering, offering_id)
        if offering is None:
            raise NotFoundError("Course offering not found.")
        return self._build(offering, published_only, include_dropped)

    def _build(
        self, offering: CourseOffering, published_only: bool, include_dropped: bool
    ) -> OfferingResults:
        assessments = AssessmentRepository(self._session).for_offering(
            offering.id, published_only=published_only
        )
        members = CohortRepository(self._session).members(
            offering.id, include_dropped=include_dropped
        )
        member_ids = {s.id for s, _ in members}
        results = [
            r
            for r in ResultRepository(self._session).for_assessments(a.id for a in assessments)
            if r.student_id in member_ids
        ]
        return OfferingResults(
            offering=MatrixOffering(
                id=offering.id,
                course_code=offering.course.code,
                section_name=offering.section.name,
                term_code=offering.term.code,
                pass_percent=offering.pass_percent,
                config=offering.config,
                department_id=offering.course.department_id,
            ),
            assessments=[AssessmentRead.model_validate(a) for a in assessments],
            students=[
                MatrixStudent(
                    id=s.id,
                    register_number=s.register_number,
                    full_name=s.full_name,
                    enrollment_status=e.status,
                    is_active=s.is_active,
                )
                for s, e in members
            ],
            results=[
                MatrixResult(
                    student_id=r.student_id,
                    assessment_id=r.assessment_id,
                    status=r.status,
                    score=r.score,
                    max_marks_snapshot=r.max_marks_snapshot,
                    percentage=percentage(r.score, r.max_marks_snapshot),
                )
                for r in sorted(results, key=lambda r: (str(r.student_id), str(r.assessment_id)))
            ],
        )


class RecomputeService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def offering(self, offering_id: uuid.UUID, *, actor: User) -> int:
        """Re-run the recompute hook for every assessment of an offering (ADMIN)."""
        if actor.role is not Role.ADMIN:
            raise PermissionDeniedError("Only administrators can trigger a recompute.")
        OfferingAccess(self._session).get(actor, offering_id, Access.VIEW)
        assessments = AssessmentRepository(self._session).for_offering(offering_id)
        for assessment in assessments:
            recompute(self._session, assessment.id)
        self._session.commit()
        return len(assessments)


# ====================================================================== settings


class SettingsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _department(self, department_id: uuid.UUID) -> Department:
        department = self._session.get(Department, department_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    def list(self, department_id: uuid.UUID) -> list[DepartmentSetting]:
        self._department(department_id)
        return list(
            self._session.scalars(
                select(DepartmentSetting)
                .where(DepartmentSetting.department_id == department_id)
                .order_by(DepartmentSetting.key)
            )
        )

    def as_dict(self, department_id: uuid.UUID) -> dict[str, Any]:
        """key -> value for the department (for threshold resolution)."""
        return {s.key: s.value for s in self.list(department_id)}

    def put(
        self, department_id: uuid.UUID, key: str, value: Any, *, actor: User
    ) -> DepartmentSetting:
        self._department(department_id)
        if not can_manage_department(actor, department_id):
            raise PermissionDeniedError("You can only change settings of your own department.")
        setting = self._session.scalar(
            select(DepartmentSetting).where(
                DepartmentSetting.department_id == department_id, DepartmentSetting.key == key
            )
        )
        audit = AuditService(self._session)
        with write_guard(self._session, invalid="Setting keys use letters, digits, '_', '.', '-'."):
            if setting is None:
                setting = DepartmentSetting(
                    department_id=department_id, key=key, value=value, updated_by_id=actor.id
                )
                self._session.add(setting)
                audit.record(
                    actor_id=actor.id,
                    entity="setting",
                    entity_id=f"{department_id}:{key}",
                    action="create",
                    new={"value": value},
                )
            elif setting.value != value:
                audit.record(
                    actor_id=actor.id,
                    entity="setting",
                    entity_id=f"{department_id}:{key}",
                    action="update",
                    old={"value": setting.value},
                    new={"value": value},
                )
                setting.value = value
                setting.updated_by_id = actor.id
        self._session.commit()
        self._session.refresh(setting)
        return setting

    def delete(self, department_id: uuid.UUID, key: str, *, actor: User) -> None:
        self._department(department_id)
        if not can_manage_department(actor, department_id):
            raise PermissionDeniedError("You can only change settings of your own department.")
        setting = self._session.scalar(
            select(DepartmentSetting).where(
                DepartmentSetting.department_id == department_id, DepartmentSetting.key == key
            )
        )
        if setting is None:
            raise NotFoundError("Setting not found.")
        AuditService(self._session).record(
            actor_id=actor.id,
            entity="setting",
            entity_id=f"{department_id}:{key}",
            action="delete",
            old={"value": setting.value},
        )
        self._session.delete(setting)
        self._session.commit()
