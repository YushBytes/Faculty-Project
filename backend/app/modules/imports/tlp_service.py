"""Multi-file TLP uploads: a coordinator drops one report per section, the platform works out
where each belongs, stages each through the ordinary import pipeline, and confirms them.

Routing a file (nothing is guessed; an ambiguous file is rejected with the reason):

    course     the report's own course code (21DCS201P), or the course chosen in the UI
    semester   the report's academic year (AY2025-26-EVEN), or the term chosen, or the
               current term
    section    the offering of that course and term, within the uploader's scope, in which
               most of the file's register numbers are actively enrolled. The best match must
               cover at least half the file and beat the runner-up, otherwise the file is
               rejected as ambiguous.
    assessment the report's test name (FP-I), matched to the offering's assessments

Each routed file becomes an ordinary ``import_batches`` row (same validation, same preview,
same fixes, same atomic confirm, same audit), tagged with the upload's ``group_id``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.core.tabular import IDENTITY_HEADERS, Table, normalise_header, read_table
from app.modules.assessments.models import Assessment
from app.modules.imports.models import ImportBatch, ImportStatus
from app.modules.imports.provision import Provisioner, SectionRequiredError
from app.modules.imports.schemas import IssueRead, TlpFileResult, TlpUploadRead
from app.modules.imports.service import ImportService
from app.modules.imports.tlp import parse_metadata
from app.modules.imports.validation import normalise_register_number
from app.modules.organization.models import AcademicTerm, Course, CourseOffering, Section
from app.modules.organization.scope import Access, OfferingAccess, visible_offerings
from app.modules.students.models import Enrollment, EnrollmentStatus, Student
from app.modules.users.models import User

MAX_FILES = 150
MIN_ROUTING_SHARE = 0.5


class RoutingError(AppError):
    status_code = 422
    code = "routing_failed"


@dataclass
class _Route:
    offering: CourseOffering
    explanation: str


class TlpUploadService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._imports = ImportService(session)
        self._access = OfferingAccess(session)

    # ------------------------------------------------------------ upload

    def upload(
        self,
        files: list[tuple[str | None, bytes]],
        *,
        actor: User,
        course_id: uuid.UUID | None = None,
        term_id: uuid.UUID | None = None,
        offering_id: uuid.UUID | None = None,
        sections: dict[str, str] | None = None,
        group_id: uuid.UUID | None = None,
    ) -> TlpUploadRead:
        """``sections`` maps a file name to the section it is for, when neither the file name
        nor the file's students tell (the upload screen asks for it)."""
        sections = sections or {}
        if not files:
            raise RoutingError("Choose at least one file.")
        if len(files) > MAX_FILES:
            raise RoutingError(f"Upload at most {MAX_FILES} files at a time.")
        # A file re-sent with its section joins the upload it came from.
        group_id = group_id or uuid.uuid4()
        seen: dict[str, str] = {}
        results: list[TlpFileResult] = []
        for name, content in files:
            file_name = (name or "upload")[:255]
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                results.append(
                    TlpFileResult(
                        file_name=file_name,
                        status="skipped",
                        message=f"Identical to '{seen[digest]}' in this upload; not staged twice.",
                    )
                )
                continue
            seen[digest] = file_name
            results.append(
                self._one(
                    file_name,
                    content,
                    actor=actor,
                    group_id=group_id,
                    course_id=course_id,
                    term_id=term_id,
                    offering_id=offering_id,
                    section=sections.get(file_name),
                )
            )
        return TlpUploadRead(group_id=group_id, files=results, counts=_counts(results))

    def _one(
        self,
        file_name: str,
        content: bytes,
        *,
        actor: User,
        group_id: uuid.UUID,
        course_id: uuid.UUID | None,
        term_id: uuid.UUID | None,
        offering_id: uuid.UUID | None,
        section: str | None = None,
    ) -> TlpFileResult:
        metadata: dict = {}
        created: dict = {}
        try:
            table = read_table(file_name, content)
            metadata = parse_metadata(table.preamble, table.trailer)
            if offering_id is not None:
                route = _Route(
                    self._access.get(actor, offering_id, Access.VIEW), "chosen in the upload"
                )
            elif metadata.get("course_code") and course_id is None and term_id is None:
                route, created = self._provision(table, metadata, actor, file_name, section)
            else:
                route = self._route(table, metadata, actor, course_id, term_id)
            batch, _ = self._imports._stage(
                route.offering,
                None,
                file_name,
                content,
                actor,
                table=table,
                upload_group_id=group_id,
            )
        except SectionRequiredError as exc:
            self._session.rollback()
            return TlpFileResult(
                file_name=file_name,
                status="needs_section",
                message=exc.message,
                source_metadata=metadata,
            )
        except AppError as exc:
            self._session.rollback()
            return TlpFileResult(
                file_name=file_name,
                status="rejected",
                message=exc.message,
                source_metadata=metadata,
                issues=[
                    IssueRead(level="error", code=d.get("code", exc.code), message=d["message"])
                    for d in (exc.details or [])
                    if isinstance(d, dict) and "message" in d
                ],
            )
        if created:
            batch.source_metadata = {**(batch.source_metadata or {}), "provisioned": created}
            self._session.commit()
        return self._result(batch, routed_by=route.explanation)

    def _provision(
        self, table: Table, metadata: dict, actor: User, file_name: str, section: str | None
    ) -> tuple[_Route, dict]:
        """Find or set up the class the report describes (see ``provision.py``)."""
        provisioner = Provisioner(self._session, actor)
        done = provisioner.provision(table, metadata, file_name=file_name, section_hint=section)
        made = {k for k in done.created if k not in ("ids", "section_source")}
        offering = done.offering
        if made - {"enrolments"}:
            provisioner.check_permission(offering.course, metadata)
        elif made:
            # Only enrolling students into an existing class: its administrators may.
            self._access.get(actor, offering.id, Access.ADMINISTER)
        # Whatever was set up must be within the uploader's scope.
        self._access.get(actor, offering.id, Access.VIEW)
        return _Route(offering, done.explanation), (done.created if made else {})

    def _route(
        self,
        table: Table,
        metadata: dict,
        actor: User,
        course_id: uuid.UUID | None,
        term_id: uuid.UUID | None,
    ) -> _Route:
        course = self._course(metadata, course_id)
        term = self._term(metadata, term_id)
        identity = next(
            (h for h in table.headers if h and normalise_header(h) in IDENTITY_HEADERS), None
        )
        if identity is None:
            raise RoutingError("The file has no register number column.")
        numbers = {
            n
            for n in (normalise_register_number(r.get(identity)) for r in table.rows)
            if n is not None
        }
        if not numbers:
            raise RoutingError("The file has no register numbers to route it by.")
        candidates = select(CourseOffering.id).where(
            CourseOffering.course_id == course.id,
            CourseOffering.term_id == term.id,
            visible_offerings(actor),
        )
        overlap = Counter(
            dict(
                self._session.execute(
                    select(Enrollment.offering_id, func.count())
                    .join(Student, Student.id == Enrollment.student_id)
                    .where(
                        Enrollment.offering_id.in_(candidates),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Student.register_number.in_(numbers),
                    )
                    .group_by(Enrollment.offering_id)
                ).all()
            )
        )
        if not overlap:
            raise RoutingError(
                f"None of the file's {len(numbers)} students is enrolled in a {course.code} "
                f"section you can access in {term.code}."
            )
        ranked = overlap.most_common(2)
        best_id, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if best < len(numbers) * MIN_ROUTING_SHARE or best == runner_up:
            raise RoutingError(
                f"Could not tell which {course.code} section this file belongs to "
                f"(best match: {best} of {len(numbers)} students). Upload it from the "
                "section's page instead."
            )
        offering = self._session.get(CourseOffering, best_id)
        section: Section = offering.section
        return _Route(
            offering,
            f"{best} of {len(numbers)} register numbers are enrolled in section {section.name}",
        )

    def _course(self, metadata: dict, course_id: uuid.UUID | None) -> Course:
        code = metadata.get("course_code")
        if course_id is not None:
            course = self._session.get(Course, course_id)
            if course is None:
                raise NotFoundError("Course not found.")
            if code and code.upper() != course.code:
                raise RoutingError(
                    f"The file is a report for {code}, not for the selected course {course.code}."
                )
            return course
        if not code:
            raise RoutingError(
                "The file does not name its course (no TLP title block); choose the course "
                "before uploading."
            )
        course = self._session.scalar(select(Course).where(Course.code == code.upper()))
        if course is None:
            raise RoutingError(f"Course {code} is not registered on the platform.")
        return course

    def _term(self, metadata: dict, term_id: uuid.UUID | None) -> AcademicTerm:
        if term_id is not None:
            term = self._session.get(AcademicTerm, term_id)
            if term is None:
                raise NotFoundError("Academic term not found.")
            return term
        year, semester = metadata.get("year"), metadata.get("semester")
        if year and semester:
            term = self._session.scalar(
                select(AcademicTerm).where(
                    AcademicTerm.academic_year == year, AcademicTerm.semester == semester
                )
            )
            if term is None:
                raise RoutingError(
                    f"No {semester.lower()} semester of {year} is registered on the platform."
                )
            return term
        term = self._session.scalar(select(AcademicTerm).where(AcademicTerm.is_current))
        if term is None:
            raise RoutingError("The file does not name its semester and no term is current.")
        return term

    # ------------------------------------------------------------ group

    def group(self, group_id: uuid.UUID, *, actor: User) -> TlpUploadRead:
        results = [self._result(b) for b in self._batches(group_id, actor)]
        if not results:
            raise NotFoundError("Upload not found.")
        return TlpUploadRead(group_id=group_id, files=results, counts=_counts(results))

    def confirm_group(
        self, group_id: uuid.UUID, *, actor: User, publish: bool = True
    ) -> TlpUploadRead:
        """Confirm every confirmable file of the upload, each in its own transaction.

        A file that still has errors is left staged (and reported), never half-written.
        """
        batches = self._batches(group_id, actor)
        if not batches:
            raise NotFoundError("Upload not found.")
        results = []
        for batch in batches:
            if batch.status is ImportStatus.PREVIEWED and batch.summary.get("can_confirm"):
                try:
                    self._imports.confirm(batch.id, actor=actor, publish=publish)
                except AppError as exc:
                    self._session.rollback()
                    result = self._result(self._session.get(ImportBatch, batch.id))
                    result.message = exc.message
                    results.append(result)
                    continue
                self._session.refresh(batch)
            results.append(self._result(batch))
        return TlpUploadRead(group_id=group_id, files=results, counts=_counts(results))

    def _batches(self, group_id: uuid.UUID, actor: User) -> list[ImportBatch]:
        return list(
            self._session.scalars(
                select(ImportBatch)
                .where(
                    ImportBatch.upload_group_id == group_id,
                    ImportBatch.offering_id.in_(
                        select(CourseOffering.id).where(visible_offerings(actor))
                    ),
                )
                .order_by(ImportBatch.created_at, ImportBatch.file_name)
            )
        )

    def _result(self, batch: ImportBatch, *, routed_by: str | None = None) -> TlpFileResult:
        offering = self._session.get(CourseOffering, batch.offering_id)
        assessment = (
            self._session.get(Assessment, batch.assessment_id) if batch.assessment_id else None
        )
        summary = dict(batch.summary or {})
        if batch.status is ImportStatus.COMMITTED:
            status = "confirmed"
        elif batch.status is ImportStatus.DISCARDED:
            status = "discarded"
        elif summary.get("errors"):
            status = "error"
        elif summary.get("duplicate_file"):
            status = "duplicate"
        elif summary.get("warnings"):
            status = "warning"
        else:
            status = "valid"
        return TlpFileResult(
            file_name=batch.file_name,
            status=status,
            batch_id=batch.id,
            offering_id=offering.id,
            offering_label=(
                f"{offering.course.code} · {offering.section.name} · {offering.term.code}"
            ),
            section_name=offering.section.name,
            assessment_id=assessment.id if assessment else None,
            assessment_name=assessment.name if assessment else None,
            routed_by=routed_by,
            source_metadata={
                k: v for k, v in (batch.source_metadata or {}).items() if k != "provisioned"
            },
            summary=summary,
            created={
                k: v
                for k, v in ((batch.source_metadata or {}).get("provisioned") or {}).items()
                if k not in ("ids", "section_source")
            },
        )


def _counts(results: list[TlpFileResult]) -> dict[str, int]:
    counts = Counter(r.status for r in results)
    counts["total"] = len(results)
    return dict(counts)
