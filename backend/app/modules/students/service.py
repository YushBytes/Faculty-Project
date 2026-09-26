"""Students (PII), section history, bulk import and offering enrolments.

Student visibility (server-side):
    ADMIN    every student
    HOD      students of their department, plus students enrolled in offerings they can view
    FACULTY  only students enrolled (any status) in offerings they are assigned to
A student outside scope is reported as 404.

Student management (create / update / deactivate / import): ADMIN, or HOD of the
student's department.
"""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import ColumnElement, select, true
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.pagination import Page, PageParams
from app.core.tabular import normalise_header, read_table
from app.db.repository import write_guard
from app.modules.audit.service import AuditService
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.organization.scope import (
    Access,
    OfferingAccess,
    can_manage_department,
    visible_offering_ids,
)
from app.modules.students.models import (
    Enrollment,
    EnrollmentStatus,
    Student,
    StudentSectionHistory,
)
from app.modules.students.repository import (
    EnrollmentRepository,
    SectionHistoryRepository,
    StudentRepository,
)
from app.modules.students.schemas import (
    BulkResult,
    EnrollmentRead,
    EnrollResult,
    RowError,
    StudentBulkRow,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)
from app.modules.users.models import Role, User

# Accepted spellings of each column in an uploaded student file (after normalise_header).
STUDENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "register_number": (
        "register_number",
        "register_no",
        "reg_no",
        "regno",
        "registration_number",
        "registration_no",
        "roll_no",
        "roll_number",
    ),
    "full_name": ("full_name", "name", "student_name"),
    "email": ("email", "email_id", "mail", "email_address"),
    "department_code": ("department_code", "department", "dept", "dept_code"),
    "batch_year": ("batch_year", "batch", "admission_year", "year_of_admission"),
    "section": ("section", "sec", "section_name"),
}


def visible_students(user: User) -> ColumnElement[bool]:
    """SQL condition on Student restricting rows to what ``user`` may see."""
    if user.role is Role.ADMIN:
        return true()
    enrolled_in_scope = Student.id.in_(
        select(Enrollment.student_id).where(Enrollment.offering_id.in_(visible_offering_ids(user)))
    )
    if user.role is Role.HOD:
        return (Student.department_id == user.department_id) | enrolled_in_scope
    return enrolled_in_scope


def _require_manager(user: User, department_id: uuid.UUID) -> None:
    if not can_manage_department(user, department_id):
        raise PermissionDeniedError("You can only manage students of your own department.")


class StudentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._students = StudentRepository(session)
        self._history = SectionHistoryRepository(session)
        self._enrollments = EnrollmentRepository(session)

    # ------------------------------------------------------------ reads

    def get(self, student_id: uuid.UUID, *, actor: User) -> Student:
        student = self._students.get_visible(student_id, visible_students(actor))
        if student is None:
            raise NotFoundError("Student not found.")
        return student

    def list(
        self,
        page: PageParams,
        *,
        actor: User,
        department_id: uuid.UUID | None,
        batch_year: int | None,
        section_id: uuid.UUID | None,
        offering_id: uuid.UUID | None,
        is_active: bool | None,
        q: str | None,
    ) -> Page[StudentRead]:
        items, total = self._students.list(
            limit=page.limit,
            offset=page.offset,
            scope=visible_students(actor),
            department_id=department_id,
            batch_year=batch_year,
            section_id=section_id,
            offering_id=offering_id,
            is_active=is_active,
            q=q,
        )
        return Page[StudentRead](
            items=[StudentRead.model_validate(s) for s in items], total=total, **page.model_dump()
        )

    def section_history(self, student_id: uuid.UUID, *, actor: User) -> list[StudentSectionHistory]:
        self.get(student_id, actor=actor)
        return self._history.for_student(student_id)

    def enrollments(self, student_id: uuid.UUID, *, actor: User) -> list[Enrollment]:
        """The student's enrolments limited to offerings the caller can view."""
        self.get(student_id, actor=actor)
        return list(
            self._session.scalars(
                select(Enrollment).where(
                    Enrollment.student_id == student_id,
                    Enrollment.offering_id.in_(visible_offering_ids(actor)),
                )
            ).unique()
        )

    # ------------------------------------------------------------ writes

    def create(self, data: StudentCreate, *, actor: User) -> Student:
        if self._session.get(Department, data.department_id) is None:
            raise NotFoundError("Department not found.")
        _require_manager(actor, data.department_id)
        section = (
            self._section_for(data.section_id, data.department_id) if data.section_id else None
        )
        email = data.email.lower() if data.email else None

        with write_guard(
            self._session,
            conflict=f"A student with register number {data.register_number} or this email "
            "already exists.",
        ):
            student = self._students.add(
                Student(
                    register_number=data.register_number,
                    full_name=data.full_name,
                    email=email,
                    department_id=data.department_id,
                    batch_year=data.batch_year,
                    current_section_id=section.id if section else None,
                )
            )
            self._session.flush()
            if section is not None:
                self._history.add(
                    StudentSectionHistory(student_id=student.id, section_id=section.id)
                )
        self._session.commit()
        self._session.refresh(student)
        return student

    def update(self, student_id: uuid.UUID, data: StudentUpdate, *, actor: User) -> Student:
        student = self.get(student_id, actor=actor)
        _require_manager(actor, student.department_id)
        changes = data.model_dump(exclude_unset=True)
        new_section = None
        if "section_id" in changes and changes["section_id"] != student.current_section_id:
            new_section = (
                self._section_for(changes["section_id"], student.department_id)
                if changes["section_id"]
                else None
            )

        with write_guard(self._session, conflict="Another student already uses this email."):
            if changes.get("full_name") is not None:
                student.full_name = changes["full_name"]
            if "email" in changes:
                student.email = changes["email"].lower() if changes["email"] else None
            if changes.get("batch_year") is not None:
                student.batch_year = changes["batch_year"]
            if "section_id" in changes and changes["section_id"] != student.current_section_id:
                self._move(student, new_section)
        self._session.commit()
        self._session.refresh(student)
        return student

    def set_active(self, student_id: uuid.UUID, active: bool, *, actor: User) -> Student:
        student = self.get(student_id, actor=actor)
        _require_manager(actor, student.department_id)
        if student.is_active != active:
            student.is_active = active
            student.deactivated_at = None if active else datetime.now(UTC)
            AuditService(self._session).record(
                actor_id=actor.id,
                entity="student",
                entity_id=student.id,
                action="activate" if active else "deactivate",
            )
            self._session.commit()
        return student

    def _section_for(self, section_id: uuid.UUID, department_id: uuid.UUID) -> Section:
        section = self._session.get(Section, section_id)
        if section is None:
            raise NotFoundError("Section not found.")
        if section.department_id != department_id:
            raise BusinessRuleError("A student's section must belong to their department.")
        return section

    def _move(self, student: Student, section: Section | None, now: datetime | None = None) -> None:
        """Change the current section and keep the history; enrolments are not touched."""
        now = now or datetime.now(UTC)
        open_entry = self._history.open_entry(student.id)
        if open_entry is not None:
            open_entry.ended_at = now
            self._session.flush()
        student.current_section_id = section.id if section else None
        if section is not None:
            self._history.add(
                StudentSectionHistory(student_id=student.id, section_id=section.id, started_at=now)
            )

    # ------------------------------------------------------------ bulk

    def import_file(
        self, filename: str | None, content: bytes, *, dry_run: bool, actor: User
    ) -> BulkResult:
        table = read_table(filename, content)
        mapping, header_errors = _map_columns(table.headers)
        if header_errors:
            return BulkResult(
                dry_run=dry_run, valid=False, total_rows=len(table.rows), errors=header_errors
            )
        rows = [{field: row.get(header) for field, header in mapping.items()} for row in table.rows]
        return self.bulk_upsert(rows, table.row_numbers, dry_run=dry_run, actor=actor)

    def bulk_upsert(
        self,
        raw_rows: list[dict],
        row_numbers: list[int] | None = None,
        *,
        dry_run: bool,
        actor: User,
    ) -> BulkResult:
        """Validate every row first; write all rows in one transaction or none at all."""
        numbers = row_numbers or list(range(1, len(raw_rows) + 1))
        errors: list[RowError] = []
        parsed: list[tuple[int, StudentBulkRow]] = []

        for number, raw in zip(numbers, raw_rows, strict=True):
            try:
                parsed.append((number, StudentBulkRow.model_validate(raw)))
            except ValidationError as exc:
                for err in exc.errors():
                    field = str(err["loc"][0]) if err["loc"] else None
                    value = raw.get(field) if field else None
                    errors.append(
                        RowError(
                            row=number,
                            field=field,
                            value=None if value is None else str(value),
                            message=err["msg"],
                        )
                    )

        departments = {d.code: d for d in self._session.scalars(select(Department)).unique()}
        existing = self._students.by_register_numbers(r.register_number for _, r in parsed)
        emails = {r.email.lower() for _, r in parsed if r.email}
        taken = self._students.emails_taken(emails)
        sections: dict[tuple[uuid.UUID, int, str], Section] = {
            (s.department_id, s.batch_year, s.name): s
            for s in self._session.scalars(select(Section)).unique()
        }

        seen_numbers: dict[str, int] = {}
        seen_emails: dict[str, int] = {}
        plan: list[tuple[StudentBulkRow, Department, Section | None, Student | None]] = []
        for number, row in parsed:
            row_errors: list[RowError] = []
            fail = _collector(row_errors, number)

            if row.register_number in seen_numbers:
                fail(
                    "register_number",
                    row.register_number,
                    f"Duplicate of row {seen_numbers[row.register_number]} in this file.",
                )
            else:
                seen_numbers[row.register_number] = number
            email = row.email.lower() if row.email else None
            if email:
                if email in seen_emails:
                    fail("email", email, f"Duplicate of row {seen_emails[email]} in this file.")
                else:
                    seen_emails[email] = number
                owner = taken.get(email)
                if owner is not None and owner != row.register_number:
                    fail("email", email, f"Email already belongs to student {owner}.")

            department = departments.get(row.department_code)
            if department is None:
                fail("department_code", row.department_code, "Unknown department code.")
            elif not can_manage_department(actor, department.id):
                fail(
                    "department_code",
                    row.department_code,
                    "You can only import students of your own department.",
                )

            current = existing.get(row.register_number)
            if (
                current is not None
                and department is not None
                and current.department_id != department.id
            ):
                fail(
                    "department_code",
                    row.department_code,
                    "A student's department cannot be changed by import.",
                )

            section = None
            if row.section and department is not None:
                section = sections.get((department.id, row.batch_year, row.section))
                if section is None:
                    fail(
                        "section",
                        row.section,
                        f"No section '{row.section}' for batch {row.batch_year} in "
                        f"{department.code}.",
                    )

            if row_errors:
                errors.extend(row_errors)
            else:
                assert department is not None
                plan.append((row, department, section, current))

        if errors:
            errors.sort(key=lambda e: (e.row, e.field or ""))
            return BulkResult(dry_run=dry_run, valid=False, total_rows=len(raw_rows), errors=errors)

        created = updated = unchanged = 0
        now = datetime.now(UTC)
        guard = (
            nullcontext()
            if dry_run
            else write_guard(self._session, conflict="Import conflicts with existing students.")
        )
        with guard:
            for row, department, section, current in plan:
                email = row.email.lower() if row.email else None
                if current is None:
                    created += 1
                    if not dry_run:
                        self._create_from_row(row, department, section, email, now)
                    continue
                section_changed = row.section is not None and (
                    section is None or current.current_section_id != section.id
                )
                changed = (
                    current.full_name != row.full_name
                    or (email is not None and current.email != email)
                    or current.batch_year != row.batch_year
                    or section_changed
                )
                if not changed:
                    unchanged += 1
                    continue
                updated += 1
                if not dry_run:
                    current.full_name = row.full_name
                    if email is not None:
                        current.email = email
                    current.batch_year = row.batch_year
                    if section_changed:
                        self._move(current, section, now)
        if not dry_run:
            self._session.commit()
        return BulkResult(
            dry_run=dry_run,
            valid=True,
            total_rows=len(raw_rows),
            created=created,
            updated=updated,
            unchanged=unchanged,
        )

    def _create_from_row(
        self,
        row: StudentBulkRow,
        department: Department,
        section: Section | None,
        email: str | None,
        now: datetime,
    ) -> None:
        student = self._students.add(
            Student(
                register_number=row.register_number,
                full_name=row.full_name,
                email=email,
                department_id=department.id,
                batch_year=row.batch_year,
                current_section_id=section.id if section else None,
            )
        )
        if section is not None:
            self._session.flush()
            self._history.add(
                StudentSectionHistory(student_id=student.id, section_id=section.id, started_at=now)
            )


def _collector(errors: list[RowError], row: int):
    def fail(field: str, value: object, message: str) -> None:
        errors.append(
            RowError(
                row=row,
                field=field,
                value=None if value is None else str(value),
                message=message,
            )
        )

    return fail


def _map_columns(headers: list[str]) -> tuple[dict[str, str], list[RowError]]:
    """Map file headers to student fields. Unknown extra columns are ignored."""
    by_normalised: dict[str, list[str]] = {}
    for header in headers:
        by_normalised.setdefault(normalise_header(header), []).append(header)
    mapping: dict[str, str] = {}
    errors: list[RowError] = []
    for field, aliases in STUDENT_COLUMNS.items():
        matches = [h for alias in aliases for h in by_normalised.get(alias, [])]
        if len(matches) > 1:
            errors.append(
                RowError(
                    row=1,
                    field=field,
                    value=", ".join(matches),
                    message=f"Ambiguous: several columns could be '{field}'.",
                )
            )
        elif matches:
            mapping[field] = matches[0]
        elif field not in ("email", "section"):
            errors.append(
                RowError(
                    row=1,
                    field=field,
                    message=f"Missing required column '{field}'. "
                    f"Accepted headers: {', '.join(aliases)}.",
                )
            )
    return mapping, errors


class EnrollmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._access = OfferingAccess(session)
        self._enrollments = EnrollmentRepository(session)
        self._students = StudentRepository(session)

    def roster(
        self,
        offering_id: uuid.UUID,
        *,
        actor: User,
        include_dropped: bool,
        include_inactive: bool,
    ) -> list[EnrollmentRead]:
        self._access.get(actor, offering_id, Access.VIEW)
        rows = self._enrollments.for_offering(
            offering_id, include_dropped=include_dropped, include_inactive=include_inactive
        )
        return [EnrollmentRead.model_validate(e) for e in rows]

    def enroll(
        self, offering_id: uuid.UUID, student_ids: list[uuid.UUID], *, actor: User
    ) -> EnrollResult:
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        wanted = list(dict.fromkeys(student_ids))
        students = {
            s.id: s
            for s in self._session.scalars(select(Student).where(Student.id.in_(wanted))).unique()
        }
        missing = [str(i) for i in wanted if i not in students]
        if missing:
            raise NotFoundError(
                "Some students were not found.",
                details=[{"loc": ["body", "student_ids"], "message": i} for i in missing],
            )
        inactive = [s.register_number for s in students.values() if not s.is_active]
        if inactive:
            raise BusinessRuleError(
                "Inactive students cannot be enrolled.",
                details=[{"loc": ["body", "student_ids"], "message": n} for n in inactive],
            )
        return self._enroll_students(offering, [students[i] for i in wanted])

    def enroll_section(self, offering_id: uuid.UUID, *, actor: User) -> EnrollResult:
        """Enrol every active student currently in the offering's section (idempotent)."""
        offering = self._access.get(actor, offering_id, Access.ADMINISTER)
        return self._enroll_students(
            offering, self._students.active_in_section(offering.section_id)
        )

    def drop(self, offering_id: uuid.UUID, student_id: uuid.UUID, *, actor: User) -> None:
        self._access.get(actor, offering_id, Access.ADMINISTER)
        enrollment = self._enrollments.get_pair(offering_id, student_id)
        if enrollment is None:
            raise NotFoundError("The student is not enrolled in this offering.")
        if enrollment.status is EnrollmentStatus.ACTIVE:
            enrollment.status = EnrollmentStatus.DROPPED
            enrollment.dropped_at = datetime.now(UTC)
            self._session.commit()

    def _enroll_students(self, offering: CourseOffering, students: list[Student]) -> EnrollResult:
        current = self._enrollments.by_student(offering.id)
        enrolled = reactivated = already = 0
        with write_guard(self._session, conflict="Concurrent enrolment change; retry."):
            for student in students:
                existing = current.get(student.id)
                if existing is None:
                    self._enrollments.add(
                        Enrollment(offering_id=offering.id, student_id=student.id)
                    )
                    enrolled += 1
                elif existing.status is EnrollmentStatus.DROPPED:
                    existing.status = EnrollmentStatus.ACTIVE
                    existing.dropped_at = None
                    reactivated += 1
                else:
                    already += 1
        self._session.commit()
        return EnrollResult(enrolled=enrolled, reactivated=reactivated, already_enrolled=already)
