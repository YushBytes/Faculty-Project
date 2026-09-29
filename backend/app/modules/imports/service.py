"""The results import pipeline.

    upload -> detect file type -> parse (raw strings) -> header checks -> format detection
    -> stage (import_batches) -> preview (validation.py) -> fix / exclude / map columns
    -> revalidate -> confirm: ONE transaction (results + audit + recompute hook + batch state)

Access: anyone who can VIEW the offering may upload and see its import history. A batch
may be changed or confirmed by its uploader or by someone who can ADMINISTER the offering.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.pagination import Page, PageParams
from app.core.tabular import normalise_header, read_table
from app.modules.assessments.models import Assessment, AssessmentResult, ResultSource
from app.modules.assessments.repository import AssessmentRepository, CohortRepository
from app.modules.assessments.service import AssessmentService, ResultChange, ResultWriter
from app.modules.audit.service import AuditService
from app.modules.imports.models import ImportBatch, ImportStatus
from app.modules.imports.schemas import (
    CellFix,
    ConfirmResult,
    ImportBatchRead,
    ImportPreview,
    MissingStudent,
)
from app.modules.imports.tlp import parse_metadata
from app.modules.imports.validation import (
    IDENTITY,
    IGNORE,
    AssessmentRef,
    FileRejectedError,
    Preview,
    Snapshot,
    Staged,
    StudentRef,
    check_headers,
    detect_format,
    fix_key,
    match_key,
    normalise_register_number,
    validate,
)
from app.modules.organization.models import CourseOffering
from app.modules.organization.scope import (
    Access,
    OfferingAccess,
    can_administer,
    visible_offerings,
)
from app.modules.students.models import Enrollment, Student
from app.modules.users.models import User

BATCH_LIFETIME = timedelta(hours=24)


class ImportRejectedError(BusinessRuleError):
    code = "import_rejected"


def _issue_dicts(issues) -> list[dict[str, Any]]:
    return [i.as_dict() for i in issues]


class ImportService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = OfferingAccess(session)

    # ================================================================ upload

    def upload_for_offering(
        self, offering_id: uuid.UUID, filename: str | None, content: bytes, *, actor: User
    ) -> tuple[ImportBatch, Preview]:
        offering = self._access.get(actor, offering_id, Access.VIEW)
        return self._stage(offering, None, filename, content, actor)

    def upload_for_assessment(
        self, assessment_id: uuid.UUID, filename: str | None, content: bytes, *, actor: User
    ) -> tuple[ImportBatch, Preview]:
        assessment = AssessmentService(self._session).get(assessment_id, actor=actor)
        offering = self._session.get(CourseOffering, assessment.offering_id)
        return self._stage(offering, assessment, filename, content, actor)

    def _stage(
        self,
        offering: CourseOffering,
        assessment: Assessment | None,
        filename: str | None,
        content: bytes,
        actor: User,
        *,
        table=None,
        upload_group_id: uuid.UUID | None = None,
    ) -> tuple[ImportBatch, Preview]:
        table = table if table is not None else read_table(filename, content)
        metadata = parse_metadata(table.preamble, table.trailer)
        if assessment is None and metadata.get("test_name"):
            # A TLP report names its test: import into that assessment, or say why not.
            assessment = self._assessment_named(offering, metadata["test_name"])
        rows = [
            {"row": n, "values": values}
            for n, values in zip(table.row_numbers, table.rows, strict=True)
        ]
        try:
            check_headers(table.headers, rows)
        except FileRejectedError as exc:
            raise ImportRejectedError(
                "The file cannot be imported: " + " ".join(i.message for i in exc.issues),
                details=[
                    {"loc": ["file"], "message": i.message, "code": i.code} for i in exc.issues
                ],
            ) from exc
        if not rows:
            raise ImportRejectedError("The file has a header row but no data rows.")

        now = datetime.now(UTC)
        batch = ImportBatch(
            offering_id=offering.id,
            assessment_id=assessment.id if assessment else None,
            file_name=(filename or "upload")[:255],
            file_type=table.file_type.value,
            file_sha256=hashlib.sha256(content).hexdigest(),
            file_format=detect_format(table.headers),
            sheet_name=table.sheet_name,
            headers=table.headers,
            rows=rows,
            skipped_empty_rows=table.skipped_empty_rows,
            column_mapping={},
            fixes={},
            excluded_rows=[],
            summary={},
            total_rows=len(rows),
            uploaded_by_id=actor.id,
            expires_at=now + BATCH_LIFETIME,
            source_metadata=metadata,
            upload_group_id=upload_group_id,
        )
        self._session.add(batch)
        self._session.flush()
        preview = self._validate(batch)
        batch.summary = preview.summary
        self._session.commit()
        self._session.refresh(batch)
        return batch, preview

    def _assessment_named(self, offering: CourseOffering, test_name: str) -> Assessment:
        matches = [
            a
            for a in AssessmentRepository(self._session).for_offering(offering.id)
            if match_key(a.name) == match_key(test_name)
        ]
        if len(matches) == 1:
            return matches[0]
        label = f"{offering.course.code} / {offering.section.name}"
        if not matches:
            raise ImportRejectedError(
                f"The file is a report for test '{test_name}', but {label} has no assessment "
                "with that name. Create the assessment first (or apply the SRM scheme).",
                details=[
                    {"loc": ["file"], "message": test_name, "code": "missing_assessment_definition"}
                ],
            )
        raise ImportRejectedError(
            f"The file's test name '{test_name}' matches several assessments of {label}.",
            details=[{"loc": ["file"], "message": test_name, "code": "ambiguous_column"}],
        )

    # ================================================================ read

    def get(self, batch_id: uuid.UUID, *, actor: User) -> ImportBatch:
        batch = self._session.get(ImportBatch, batch_id)
        if batch is None:
            raise NotFoundError("Import not found.")
        try:
            self._access.get(actor, batch.offering_id, Access.VIEW)
        except NotFoundError as exc:
            raise NotFoundError("Import not found.") from exc
        return batch

    def preview(self, batch_id: uuid.UUID, *, actor: User) -> tuple[ImportBatch, Preview]:
        batch = self.get(batch_id, actor=actor)
        return batch, self._validate(batch)

    def history(
        self,
        page: PageParams,
        *,
        actor: User,
        offering_id: uuid.UUID | None,
        status: ImportStatus | None,
    ) -> Page[ImportBatchRead]:
        query = select(ImportBatch).where(
            ImportBatch.offering_id.in_(select(CourseOffering.id).where(visible_offerings(actor)))
        )
        if offering_id is not None:
            query = query.where(ImportBatch.offering_id == offering_id)
        if status is not None:
            query = query.where(ImportBatch.status == status)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self._session.scalars(
            query.order_by(ImportBatch.created_at.desc()).limit(page.limit).offset(page.offset)
        )
        return Page[ImportBatchRead](
            items=[ImportBatchRead.model_validate(b) for b in items],
            total=total,
            **page.model_dump(),
        )

    # ================================================================ edits

    def fix(
        self, batch_id: uuid.UUID, fixes: list[CellFix], *, actor: User
    ) -> tuple[ImportBatch, Preview]:
        batch = self._editable(batch_id, actor)
        rows = {r["row"]: r for r in batch.rows}
        errors = []
        for index, item in enumerate(fixes):
            if item.row not in rows:
                errors.append(
                    {
                        "loc": ["body", "fixes", index, "row"],
                        "message": f"Row {item.row} is not in this import.",
                    }
                )
            elif item.column not in batch.headers or item.column == "":
                errors.append(
                    {
                        "loc": ["body", "fixes", index, "column"],
                        "message": f"Column '{item.column}' is not in this import.",
                    }
                )
        if errors:
            raise BusinessRuleError("Some fixes do not match the import.", details=errors)

        updated = dict(batch.fixes)
        audit = AuditService(self._session)
        now = datetime.now(UTC).isoformat()
        for item in fixes:
            key = fix_key(item.row, item.column)
            original = rows[item.row]["values"].get(item.column)
            previous = updated.get(key, {}).get("value", original)
            if item.reset:
                if key in updated:
                    updated.pop(key)
                    new_value = original
                else:
                    continue
            else:
                new_value = item.value.strip() if item.value is not None else None
                new_value = new_value or None
                updated[key] = {
                    "value": new_value,
                    "original": original,
                    "by": str(actor.id),
                    "at": now,
                }
            # Every manual change to an uploaded value is audited (e.g. blank -> 0).
            audit.record(
                actor_id=actor.id,
                entity="import_batch",
                entity_id=str(batch.id),
                action="fix_reset" if item.reset else "fix",
                old={
                    "row": item.row,
                    "column": item.column,
                    "value": previous,
                    "uploaded": original,
                },
                new={"row": item.row, "column": item.column, "value": new_value},
                offering_id=batch.offering_id,
            )
        batch.fixes = updated
        return self._save_and_preview(batch)

    def exclude(
        self, batch_id: uuid.UUID, row_numbers: list[int], excluded: bool, *, actor: User
    ) -> tuple[ImportBatch, Preview]:
        batch = self._editable(batch_id, actor)
        known = {r["row"] for r in batch.rows}
        unknown = sorted(set(row_numbers) - known)
        if unknown:
            raise BusinessRuleError(f"Rows not in this import: {', '.join(map(str, unknown))}.")
        current = set(batch.excluded_rows)
        current = current | set(row_numbers) if excluded else current - set(row_numbers)
        batch.excluded_rows = sorted(current)
        return self._save_and_preview(batch)

    def map_columns(
        self, batch_id: uuid.UUID, mappings: dict[str, Any], *, actor: User
    ) -> tuple[ImportBatch, Preview]:
        batch = self._editable(batch_id, actor)
        assessments = {
            a.id for a in AssessmentRepository(self._session).for_offering(batch.offering_id)
        }
        updated = dict(batch.column_mapping)
        for header, target in mappings.items():
            if header not in batch.headers or header == "":
                raise BusinessRuleError(f"Column '{header}' is not in this import.")
            if target is None:
                updated.pop(header, None)
            elif target == IGNORE:
                updated[header] = IGNORE
            else:
                if target not in assessments:
                    raise NotFoundError(f"Assessment {target} is not part of this offering.")
                updated[header] = str(target)
        batch.column_mapping = updated
        return self._save_and_preview(batch)

    def discard(self, batch_id: uuid.UUID, *, actor: User) -> ImportBatch:
        batch = self._editable(batch_id, actor, allow_expired=True)
        batch.status = ImportStatus.DISCARDED
        self._session.commit()
        return batch

    # ================================================================ confirm

    def confirm(self, batch_id: uuid.UUID, *, actor: User, publish: bool = False) -> ConfirmResult:
        batch = self.get(batch_id, actor=actor)
        # Lock the batch row: two concurrent confirms cannot both write.
        batch = self._session.scalar(
            select(ImportBatch).where(ImportBatch.id == batch.id).with_for_update()
        )
        self._check_editable(batch, actor)

        preview = self._validate(batch)
        if preview.summary["errors"]:
            raise BusinessRuleError(
                f"The import still has {preview.summary['errors']} blocking error(s); fix or "
                "exclude them before confirming.",
                details=self._error_details(preview),
            )
        if not preview.summary["cells_to_write"]:
            raise BusinessRuleError("Nothing to import: every value already matches.")

        writer = ResultWriter(self._session)
        created = updated = unchanged = 0
        assessments = {
            a.id: a for a in AssessmentRepository(self._session).for_offering(batch.offering_id)
        }
        if publish:
            # Publishing is part of the same transaction, before the writes, so the recompute
            # hook analyses the assessment the moment its marks land.
            for assessment_id in preview.changes:
                assessment = assessments[assessment_id]
                if not assessment.is_published:
                    assessment.is_published = True
                    AuditService(self._session).record(
                        actor_id=actor.id,
                        entity="assessment",
                        entity_id=str(assessment.id),
                        action="publish",
                        new={"via_import": str(batch.id)},
                        offering_id=batch.offering_id,
                    )
            self._session.flush()
        for assessment_id, cells in preview.changes.items():
            summary = writer.apply(
                assessments[assessment_id],
                [ResultChange(student_id=s, status=st, score=sc) for s, st, sc in cells],
                actor=actor,
                source=ResultSource.IMPORT,
                import_batch_id=batch.id,
            )
            created += summary.created
            updated += summary.updated
            unchanged += summary.unchanged

        batch.status = ImportStatus.COMMITTED
        batch.committed_at = datetime.now(UTC)
        batch.committed_by_id = actor.id
        batch.summary = {**preview.summary, "created": created, "updated": updated}
        AuditService(self._session).record(
            actor_id=actor.id,
            entity="import_batch",
            entity_id=str(batch.id),
            action="confirm",
            new={
                "created": created,
                "updated": updated,
                "file_name": batch.file_name,
                "file_sha256": batch.file_sha256,
            },
            offering_id=batch.offering_id,
        )
        # Results, audit rows, derived analytics and batch state: all or nothing.
        self._session.commit()
        return ConfirmResult(
            batch_id=batch.id,
            status=batch.status,
            created=created,
            updated=updated,
            unchanged=preview.summary["unchanged"] + unchanged,
            assessments=sorted(preview.changes, key=str),
            summary=batch.summary,
        )

    # ================================================================ templates

    def template_for_offering(self, offering_id: uuid.UUID, *, actor: User) -> tuple[str, bytes]:
        offering = self._access.get(actor, offering_id, Access.VIEW)
        assessments = AssessmentRepository(self._session).for_offering(offering_id)
        return self._template(offering, assessments)

    def template_for_assessment(
        self, assessment_id: uuid.UUID, *, actor: User
    ) -> tuple[str, bytes]:
        assessment = AssessmentService(self._session).get(assessment_id, actor=actor)
        offering = self._session.get(CourseOffering, assessment.offering_id)
        return self._template(offering, [assessment])

    def _template(
        self, offering: CourseOffering, assessments: list[Assessment]
    ) -> tuple[str, bytes]:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Marks"
        header = ["Register No", "Name"] + [
            f"{a.name} (max {a.max_marks.normalize():f})" for a in assessments
        ]
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for student, _ in CohortRepository(self._session).members(offering.id):
            sheet.append([student.register_number, student.full_name])
        sheet.column_dimensions["A"].width = 20
        sheet.column_dimensions["B"].width = 30
        notes = workbook.create_sheet("Instructions")
        for line in (
            "Enter a score for each student, or AB / - for absent, EX for exempt.",
            "A blank cell is imported as absent (never 0) and shown as a warning.",
            "Do not rename the Register No column. Extra columns are ignored.",
        ):
            notes.append([line])
        buffer = io.BytesIO()
        workbook.save(buffer)
        name = f"{offering.course.code}_{offering.section.name}_{offering.term.code}_marks.xlsx"
        return name, buffer.getvalue()

    # ================================================================ internals

    def _editable(
        self, batch_id: uuid.UUID, actor: User, *, allow_expired: bool = False
    ) -> ImportBatch:
        batch = self.get(batch_id, actor=actor)
        self._check_editable(batch, actor, allow_expired=allow_expired)
        return batch

    def _check_editable(
        self, batch: ImportBatch, actor: User, *, allow_expired: bool = False
    ) -> None:
        offering = self._session.get(CourseOffering, batch.offering_id)
        if batch.uploaded_by_id != actor.id and not can_administer(actor, offering):
            raise PermissionDeniedError(
                "Only the uploader or an administrator can change this import."
            )
        if batch.status is not ImportStatus.PREVIEWED:
            raise ConflictError(f"This import is already {batch.status.value}.")
        if not allow_expired and batch.expires_at <= datetime.now(UTC):
            raise ConflictError("This import preview has expired; upload the file again.")

    def _save_and_preview(self, batch: ImportBatch) -> tuple[ImportBatch, Preview]:
        preview = self._validate(batch)
        batch.summary = preview.summary
        self._session.commit()
        self._session.refresh(batch)
        return batch, preview

    def _validate(self, batch: ImportBatch) -> Preview:
        staged = Staged(
            file_format=batch.file_format,
            headers=list(batch.headers),
            rows=list(batch.rows),
            column_mapping=dict(batch.column_mapping),
            fixes=dict(batch.fixes),
            excluded_rows=list(batch.excluded_rows),
            skipped_empty_rows=list(batch.skipped_empty_rows),
        )
        return validate(staged, self._snapshot(batch, staged))

    def _snapshot(self, batch: ImportBatch, staged: Staged) -> Snapshot:
        offering = self._session.get(CourseOffering, batch.offering_id)
        assessments = AssessmentRepository(self._session).for_offering(batch.offering_id)
        identity = next((h for h in staged.headers if h and _is_identity(h)), None)
        numbers = set()
        for row in staged.rows:
            fix = staged.fixes.get(fix_key(row["row"], identity)) if identity else None
            raw = fix["value"] if fix else row["values"].get(identity)
            number = normalise_register_number(raw)
            if number:
                numbers.add(number)
        enrollments = {
            e.student_id: e.status.value
            for e in self._session.scalars(
                select(Enrollment).where(Enrollment.offering_id == batch.offering_id)
            )
        }
        students = {
            s.register_number: StudentRef(
                id=s.id,
                register_number=s.register_number,
                full_name=s.full_name,
                is_active=s.is_active,
                enrollment=enrollments.get(s.id),
            )
            for s in self._session.scalars(
                select(Student).where(Student.register_number.in_(numbers))
            ).unique()
        }
        cohort = [
            StudentRef(
                id=s.id,
                register_number=s.register_number,
                full_name=s.full_name,
                is_active=s.is_active,
                enrollment=e.status.value,
            )
            for s, e in CohortRepository(self._session).members(batch.offering_id)
        ]
        existing = {
            (r.student_id, r.assessment_id): (r.status, r.score)
            for r in self._session.scalars(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id.in_([a.id for a in assessments])
                )
            ).unique()
        }
        earlier = self._session.scalar(
            select(ImportBatch)
            .where(
                ImportBatch.offering_id == batch.offering_id,
                ImportBatch.file_sha256 == batch.file_sha256,
                ImportBatch.status == ImportStatus.COMMITTED,
                ImportBatch.id != batch.id,
            )
            .order_by(ImportBatch.committed_at.desc())
        )
        duplicate_of = (
            f"This exact file was already imported on {earlier.committed_at:%Y-%m-%d %H:%M} UTC "
            f"(import {earlier.id})."
            if earlier
            else None
        )
        label = f"{offering.course.code} / {offering.section.name} / {offering.term.code}"
        faculty_codes = frozenset(
            a.user.employee_code for a in offering.faculty_assignments if a.user.employee_code
        )
        return Snapshot(
            offering_label=label,
            assessments=[AssessmentRef(a.id, a.name, a.max_marks) for a in assessments],
            students=students,
            cohort=cohort,
            existing=existing,
            target_assessment_id=batch.assessment_id,
            duplicate_of=duplicate_of,
            course_code=offering.course.code,
            term_year=offering.term.academic_year,
            term_semester=offering.term.semester.value if offering.term.semester else None,
            faculty_codes=faculty_codes,
            source_metadata=dict(batch.source_metadata or {}),
        )

    @staticmethod
    def _error_details(preview: Preview, limit: int = 200) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for issue in preview.file_issues + [i for c in preview.columns for i in c.issues]:
            if issue.level.value == "error":
                details.append(
                    {
                        "loc": ["file", issue.column or ""],
                        "message": issue.message,
                        "code": issue.code,
                    }
                )
        for row in preview.rows:
            if row.excluded:
                continue
            for issue in row.issues + [i for c in row.cells for i in c.issues]:
                if issue.level.value == "error":
                    details.append(
                        {
                            "loc": ["row", row.row, issue.column or ""],
                            "message": issue.message,
                            "code": issue.code,
                        }
                    )
        return details[:limit]


def _is_identity(header: str) -> bool:
    return normalise_header(header) in IDENTITY


def preview_read(batch: ImportBatch, preview: Preview, *, only: str = "all") -> ImportPreview:
    def keep(row) -> bool:
        if only == "all":
            return True
        issues = row.issues + [i for c in row.cells for i in c.issues]
        if only == "errors":
            return any(i.level.value == "error" for i in issues)
        return bool(issues)  # "issues": errors or warnings or infos

    return ImportPreview.model_validate(
        {
            "batch": ImportBatchRead.model_validate(batch),
            "summary": preview.summary,
            "file_issues": _issue_dicts(preview.file_issues),
            "columns": [
                {
                    "header": c.header,
                    "role": c.role,
                    "assessment_id": c.assessment_id,
                    "assessment_name": c.assessment_name,
                    "mapped_by": c.mapped_by,
                    "issues": _issue_dicts(c.issues),
                }
                for c in preview.columns
            ],
            "rows": [
                {
                    "row": r.row,
                    "register_number": r.register_number,
                    "student_id": r.student_id,
                    "student_name": r.student_name,
                    "excluded": r.excluded,
                    "issues": _issue_dicts(r.issues),
                    "cells": [
                        {
                            "column": c.column,
                            "assessment_id": c.assessment_id,
                            "assessment_name": c.assessment_name,
                            "raw": c.raw,
                            "value": c.value,
                            "fixed": c.fixed,
                            "status": c.status,
                            "score": c.score,
                            "change": c.change,
                            "issues": _issue_dicts(c.issues),
                        }
                        for c in r.cells
                    ],
                }
                for r in preview.rows
                if keep(r)
            ],
            "missing_students": [
                MissingStudent(id=s.id, register_number=s.register_number, full_name=s.full_name)
                for s in preview.missing_students
            ],
        }
    )
