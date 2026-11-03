"""Build the academic structure a TLP report describes, from the report alone.

A fresh platform knows nothing: no semesters, courses, sections, students or staff. An SRM
TLP report carries all of it, so uploading one sets it up:

    semester    "Academic Year : AY2025-26-EVEN"            -> academic_terms
    course      "21CSC201J(Data Structures and Algorithms)"  -> courses (type from the code)
    faculty     "handled by Dr. X(902049)"                    -> users (FACULTY, with a login)
    section     the file name ("..._A1.xlsx"), else where the file's students already are,
                else the section typed on the upload screen   -> sections
    students    every Register No + Name row                  -> students + enrolments
    assessment  "Test Name : FJ-III" + "Component Max. Mark"  -> assessments

Existing records are reused, never overwritten: a student already on the platform keeps
their record, and a course keeps its name. Nothing here writes a mark; the file is then
staged and validated like any other import, and marks are written only on confirm.

Everything happens in the caller's transaction, so a file that fails to stage leaves
nothing behind. What was created is recorded on the batch (``source_metadata.provisioned``),
so discarding the upload can remove exactly that and nothing else.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.core.tabular import IDENTITY_HEADERS, Table, normalise_header
from app.modules.assessments.models import Assessment, AssessmentType
from app.modules.assessments.repository import AssessmentRepository
from app.modules.assessments.schemes import SCHEMES
from app.modules.imports.validation import NAME, match_key, normalise_register_number
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
    Semester,
    course_type_from_code,
)
from app.modules.organization.scope import can_manage_courses, coordinates
from app.modules.students.models import (
    Enrollment,
    EnrollmentStatus,
    Student,
    StudentSectionHistory,
)
from app.modules.users.models import Role, User

# A section token in a file name: A1, B12, N6, or anything after "sec"/"section".
_SECTION_WORD = re.compile(r"(?i)(?:^|[^a-z])sec(?:tion)?[\s_.\-]*([a-z]{1,2}\d{0,2})(?![a-z0-9])")
_SECTION_TOKEN = re.compile(r"^[A-Za-z]{1,2}\d{1,2}$")
# Prefixes that make a token an assessment or year, not a section (FJ3, FT2, AY25...).
_NOT_SECTIONS = ("FT", "FJ", "FL", "FP", "FM", "CT", "LL", "AY", "PB", "UT", "IA", "CA")
_ADMISSION_YEAR = re.compile(r"^[A-Z]{2}(\d{2})\d")
_TYPE_BY_PREFIX = {t.value: t for t in AssessmentType}


class SectionRequiredError(AppError):
    status_code = 422
    code = "section_required"


class ProvisionError(AppError):
    status_code = 422
    code = "routing_failed"


@dataclass
class Provisioned:
    offering: CourseOffering
    explanation: str
    created: dict = field(default_factory=dict)


def section_from_file_name(file_name: str | None) -> str | None:
    """'DSA_FJ-III_A1.xlsx' -> 'A1'; 'CSE sec B2 FT2.pdf' -> 'B2'; None when unclear."""
    if not file_name:
        return None
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", file_name)
    word = _SECTION_WORD.search(stem)
    if word:
        return word.group(1).upper()
    found = {
        token.upper()
        for token in re.split(r"[^A-Za-z0-9]+", stem)
        if _SECTION_TOKEN.match(token) and not token.upper().startswith(_NOT_SECTIONS)
    }
    return found.pop() if len(found) == 1 else None


def admission_year(register_number: str) -> int | None:
    """SRM register numbers start with the admission year: RA2411... -> 2024."""
    match = _ADMISSION_YEAR.match(register_number)
    return 2000 + int(match.group(1)) if match else None


def normalise_section(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"(?i)^sec(?:tion)?[\s_.\-]*", "", value.strip()).strip().upper()
    return cleaned[:32] or None


class Provisioner:
    def __init__(self, session: Session, actor: User) -> None:
        self._session = session
        self._actor = actor
        self._settings = get_settings()

    # ------------------------------------------------------------ entry point

    def provision(
        self, table: Table, metadata: dict, *, file_name: str, section_hint: str | None
    ) -> Provisioned:
        code = (metadata.get("course_code") or "").upper()
        if not code:
            raise ProvisionError(
                "The file has no TLP title block naming its course "
                "('21CSC201J(Course name) handled by ...'), so it cannot be set up automatically."
            )
        rows = self._student_rows(table)
        created: dict = {"ids": {}}
        term = self._term(metadata, created)
        department = self._department(table, code)
        course = self._course(code, metadata, department, created)
        section = self._section(section_hint, file_name, rows, department, course, term, created)
        offering = self._offering(course, term, section, created)
        self._faculty(metadata, offering, department, created)
        self._students(rows, offering, section, department, created)
        self._assessment(metadata, offering, created)
        self._session.flush()
        return Provisioned(offering, created.get("section_source", section.name), created)

    # ------------------------------------------------------------ pieces

    def _student_rows(self, table: Table) -> list[tuple[str, str]]:
        identity = next(
            (h for h in table.headers if h and normalise_header(h) in IDENTITY_HEADERS), None
        )
        if identity is None:
            raise ProvisionError("The file has no register number column.")
        name_col = next((h for h in table.headers if h and normalise_header(h) in NAME), None)
        rows: dict[str, str] = {}
        for row in table.rows:
            number = normalise_register_number(row.get(identity))
            if not number or not re.fullmatch(r"[A-Z0-9]{5,20}", number):
                continue
            name = re.sub(r"\s+", " ", (row.get(name_col) or "").strip()) if name_col else ""
            rows.setdefault(number, name or number)
        if not rows:
            raise ProvisionError("The file has no register numbers.")
        return list(rows.items())

    def _term(self, metadata: dict, created: dict) -> AcademicTerm:
        year, semester = metadata.get("year"), metadata.get("semester")
        if not year:
            raise ProvisionError(
                "The file does not state its academic year ('Academic Year : AY2025-26-EVEN')."
            )
        if semester not in ("ODD", "EVEN"):
            raise ProvisionError(
                f"The file's academic year ({metadata.get('academic_year')}) does not say ODD or "
                "EVEN, so the semester is unknown."
            )
        term = self._session.scalar(
            select(AcademicTerm).where(
                AcademicTerm.academic_year == year, AcademicTerm.semester == Semester(semester)
            )
        )
        if term is not None:
            return term
        first = int(year[:4])
        odd = semester == "ODD"
        term = AcademicTerm(
            code=f"AY{year}-{semester}",
            name=f"{'Odd' if odd else 'Even'} Semester {year}",
            academic_year=year,
            semester=Semester(semester),
            # SRM calendar: odd semester July-December, even semester January-June.
            start_date=date(first, 7, 1) if odd else date(first + 1, 1, 1),
            end_date=date(first, 12, 31) if odd else date(first + 1, 6, 30),
            is_current=False,
        )
        self._session.add(term)
        self._session.flush()
        self._make_latest_current(term)
        created["term"] = term.code
        created["ids"]["term"] = str(term.id)
        return term

    def _make_latest_current(self, term: AcademicTerm) -> None:
        """The most recent semester seen in the files is the current one."""
        latest = self._session.scalar(
            select(AcademicTerm).order_by(AcademicTerm.start_date.desc()).limit(1)
        )
        if latest is None or latest.is_current:
            return
        for other in self._session.scalars(select(AcademicTerm).where(AcademicTerm.is_current)):
            other.is_current = False
        self._session.flush()
        latest.is_current = True
        self._session.flush()

    def _department(self, table: Table, course_code: str) -> Department:
        existing = self._session.scalar(select(Course).where(Course.code == course_code))
        if existing is not None:
            return existing.department
        if self._actor.department_id is not None:
            return self._session.get(Department, self._actor.department_id)
        departments = list(self._session.scalars(select(Department)))
        dept_col = next(
            (h for h in table.headers if h and normalise_header(h) in ("dept", "department")),
            None,
        )
        stated = Counter(
            (r.get(dept_col) or "").strip().upper() for r in table.rows if dept_col
        ).most_common(1)
        if stated and stated[0][0]:
            match = next((d for d in departments if d.code == stated[0][0]), None)
            if match is not None:
                return match
        if len(departments) == 1:
            return departments[0]
        code = stated[0][0] if stated and stated[0][0] else "GEN"
        department = Department(code=code[:32], name=code)
        self._session.add(department)
        self._session.flush()
        return department

    def _course(self, code: str, metadata: dict, department: Department, created: dict) -> Course:
        course = self._session.scalar(select(Course).where(Course.code == code))
        if course is not None:
            return course
        course = Course(
            department_id=department.id,
            code=code,
            name=(metadata.get("course_name") or code)[:200],
            course_type=course_type_from_code(code),
        )
        self._session.add(course)
        self._session.flush()
        created["course"] = f"{course.code} {course.name}"
        created["ids"]["course"] = str(course.id)
        return course

    def check_permission(self, course: Course, metadata: dict) -> None:
        """Setting up new records needs course-level rights: ADMIN, the department's HOD or
        Academic Head, the course's coordinator, or the faculty member the report names."""
        actor = self._actor
        if can_manage_courses(actor, course.department_id):
            return
        if actor.role is Role.COURSE_COORDINATOR and coordinates(self._session, actor, course.id):
            return
        staff_id = (metadata.get("faculty_code") or "").strip()
        if actor.role is Role.FACULTY and staff_id and staff_id == actor.employee_code:
            return
        raise ProvisionError(
            f"This file would set up a new {course.code} class. Ask the HOD, the Academic Head "
            "or the course's coordinator to upload it, or upload a report of your own class."
        )

    def _section(
        self,
        hint: str | None,
        file_name: str,
        rows: list[tuple[str, str]],
        department: Department,
        course: Course,
        term: AcademicTerm,
        created: dict,
    ) -> Section:
        """Where the students already are wins; a typed or file-name section must agree."""
        numbers = [n for n, _ in rows]
        typed = normalise_section(hint)
        from_name = section_from_file_name(file_name)
        name = typed or from_name
        said = "The section typed" if typed else "The file name"
        known = self._known_section(numbers, department, course, term)
        if known is not None:
            section, why = known
            if name is not None and name != section.name:
                raise ProvisionError(
                    f"{said} says section {name}, but {why}. Rename the file or type the "
                    "right section, then upload again."
                )
            created["section_source"] = why
            return section
        if name is None:
            raise SectionRequiredError(
                "Which section is this report for? TLP reports do not name the section and the "
                "file name does not either (e.g. '..._A1.xlsx'). Type it and upload again."
            )
        years = Counter(y for y in (admission_year(n) for n in numbers) if y)
        batch = years.most_common(1)[0][0] if years else int(term.academic_year[:4])
        section = self._session.scalar(
            select(Section).where(
                Section.department_id == department.id,
                Section.batch_year == batch,
                Section.name == name,
            )
        )
        if section is None:
            section = Section(department_id=department.id, name=name, batch_year=batch)
            self._session.add(section)
            self._session.flush()
            created["section"] = f"{name} (batch {batch})"
            created["ids"]["section"] = str(section.id)
        created["section_source"] = (
            f"section {name} typed on upload" if typed else f"section {name} from the file name"
        )
        return section

    def _known_section(
        self, numbers: list[str], department: Department, course: Course, term: AcademicTerm
    ) -> tuple[Section, str] | None:
        """The section most of the file's students are already in: enrolled in this course
        this semester, else placed in by earlier uploads. Needs at least half the file and a
        clear winner."""
        enrolled = Counter(
            dict(
                self._session.execute(
                    select(CourseOffering.section_id, func.count())
                    .join(Enrollment, Enrollment.offering_id == CourseOffering.id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .where(
                        CourseOffering.course_id == course.id,
                        CourseOffering.term_id == term.id,
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Student.register_number.in_(numbers),
                    )
                    .group_by(CourseOffering.section_id)
                ).all()
            )
        )
        placed = Counter(
            sid
            for sid in self._session.scalars(
                select(Student.current_section_id).where(
                    Student.register_number.in_(numbers),
                    Student.department_id == department.id,
                    Student.current_section_id.is_not(None),
                )
            )
        )
        for counts, verb in (
            (enrolled, f"are enrolled in {course.code} in section"),
            (placed, "are already in section"),
        ):
            ranked = counts.most_common(2)
            if not ranked:
                continue
            best_id, best = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            if best >= len(numbers) * 0.5 and best > runner_up:
                section = self._session.get(Section, best_id)
                return section, f"{best} of {len(numbers)} register numbers {verb} {section.name}"
        return None

    def _offering(
        self, course: Course, term: AcademicTerm, section: Section, created: dict
    ) -> CourseOffering:
        offering = self._session.scalar(
            select(CourseOffering).where(
                CourseOffering.course_id == course.id,
                CourseOffering.term_id == term.id,
                CourseOffering.section_id == section.id,
            )
        )
        if offering is None:
            offering = CourseOffering(course_id=course.id, term_id=term.id, section_id=section.id)
            self._session.add(offering)
            self._session.flush()
            created["offering"] = f"{course.code} · {section.name} · {term.code}"
            created["ids"]["offering"] = str(offering.id)
        return offering

    def _faculty(
        self, metadata: dict, offering: CourseOffering, department: Department, created: dict
    ) -> None:
        staff_id = (metadata.get("faculty_code") or "").strip()[:32]
        name = re.sub(r"\s+", " ", (metadata.get("faculty_name") or "").strip())
        if not staff_id or not name:
            return
        user = self._session.scalar(select(User).where(User.employee_code == staff_id))
        if user is None:
            domain = self._settings.institution_email_domain
            email = f"{staff_id.lower()}@{domain}"
            taken = self._session.scalar(select(User).where(User.email == email))
            if taken is not None:
                email = f"{staff_id.lower()}.{uuid.uuid4().hex[:6]}@{domain}"
            user = User(
                email=email,
                full_name=name[:200],
                password_hash=hash_password(self._settings.faculty_default_password),
                role=Role.FACULTY,
                is_active=True,
                employee_code=staff_id,
                department_id=department.id,
            )
            self._session.add(user)
            self._session.flush()
            created["faculty"] = {"name": user.full_name, "email": user.email, "staff_id": staff_id}
            created["ids"]["faculty"] = str(user.id)
        assigned = self._session.scalar(
            select(OfferingFaculty.user_id).where(OfferingFaculty.offering_id == offering.id)
        )
        if assigned is None:
            self._session.add(OfferingFaculty(offering_id=offering.id, user_id=user.id))
            self._session.flush()
            created["faculty_assigned"] = user.full_name

    def _students(
        self,
        rows: list[tuple[str, str]],
        offering: CourseOffering,
        section: Section,
        department: Department,
        created: dict,
    ) -> None:
        numbers = [n for n, _ in rows]
        existing = {
            s.register_number: s
            for s in self._session.scalars(
                select(Student).where(Student.register_number.in_(numbers))
            )
        }
        new_students = []
        for number, name in rows:
            student = existing.get(number)
            if student is None:
                student = Student(
                    register_number=number,
                    full_name=name[:200],
                    department_id=department.id,
                    batch_year=admission_year(number) or section.batch_year,
                    current_section_id=section.id,
                )
                self._session.add(student)
                new_students.append(student)
                existing[number] = student
            elif student.current_section_id is None:
                student.current_section_id = section.id
        self._session.flush()
        for student in new_students:
            self._session.add(StudentSectionHistory(student_id=student.id, section_id=section.id))
        enrolled = set(
            self._session.scalars(
                select(Enrollment.student_id).where(Enrollment.offering_id == offering.id)
            )
        )
        enrolled_now: list[str] = []
        for number in numbers:
            student = existing[number]
            if student.id not in enrolled:
                self._session.add(
                    Enrollment(
                        offering_id=offering.id,
                        student_id=student.id,
                        status=EnrollmentStatus.ACTIVE,
                    )
                )
                enrolled_now.append(str(student.id))
        self._session.flush()
        if new_students:
            created["students"] = len(new_students)
            created["ids"]["students"] = [str(s.id) for s in new_students]
        if enrolled_now:
            created["enrolments"] = len(enrolled_now)
            created["ids"]["enrolled"] = enrolled_now

    def _assessment(self, metadata: dict, offering: CourseOffering, created: dict) -> None:
        test = (metadata.get("test_name") or "").strip()
        if not test:
            return
        repo = AssessmentRepository(self._session)
        current = repo.for_offering(offering.id)
        if any(match_key(a.name) == match_key(test) for a in current):
            return
        maximum = Decimal(metadata["component_max"]) if metadata.get("component_max") else None
        if maximum is None or maximum <= 0:
            raise ProvisionError(
                f"The file names test '{test}' but not its maximum ('Component Max. Mark'), so "
                "the test cannot be set up."
            )
        scheme = SCHEMES.get(offering.course.course_type) or ()
        slot = next(
            (i for i, (name, _, _) in enumerate(scheme) if match_key(name) == match_key(test)),
            None,
        )
        family = next(
            (
                _TYPE_BY_PREFIX[p]
                for p in sorted(_TYPE_BY_PREFIX, key=len, reverse=True)
                if re.sub(r"[^A-Z]", "", test.upper()).startswith(p)
            ),
            AssessmentType.OTHER,
        )
        used = {a.sequence_no for a in current}
        sequence = (slot + 1) * 10 if slot is not None else None
        if sequence is None or sequence in used:
            sequence = max([*used, 0, *((len(scheme) + 1) * 10,)]) + 1
        # SRM components contribute their scheme weight (non-credit ones 0); others their max.
        weight = scheme[slot][2] if slot is not None else maximum
        assessment = repo.add(
            Assessment(
                offering_id=offering.id,
                name=test[:100],
                assessment_type=family,
                max_marks=maximum,
                weightage=min(weight, Decimal(100)),
                sequence_no=sequence,
                is_published=False,
                created_by_id=self._actor.id,
            )
        )
        self._session.flush()
        created["assessment"] = f"{test} (out of {maximum.normalize():f})"
        created["ids"]["assessment"] = str(assessment.id)


# ------------------------------------------------------------------ undo


def remove_provisioned(session: Session, batch_id: uuid.UUID, ids: dict) -> dict[str, int]:
    """Remove what a discarded upload set up, as far as nothing else now depends on it.

    Each step runs in its own savepoint and the database's foreign keys decide: a student
    another upload has since enrolled elsewhere, a course with other classes, a term with
    other courses, a faculty member who has signed in... all stay. Nothing with marks is
    ever touched (marks exist only after confirm, and a confirmed upload is not discarded).
    """
    from sqlalchemy import delete

    from app.modules.imports.models import ImportBatch
    from app.modules.overview.models import OfferingSummary

    removed: Counter = Counter()

    def attempt(label: str, *statements) -> bool:
        try:
            with session.begin_nested():
                count = 0
                for statement in statements:
                    result = session.execute(statement)
                    count += result.rowcount or 0
            removed[label] += count
            return True
        except Exception:  # noqa: BLE001 - an FK in use means "keep it"
            return False

    offering_id = ids.get("offering")
    offering_uuid = uuid.UUID(offering_id) if offering_id else None
    enrolled = [uuid.UUID(s) for s in ids.get("enrolled", [])]
    batch = session.get(ImportBatch, batch_id)
    target_offering = offering_uuid or (batch.offering_id if batch else None)
    if enrolled and target_offering:
        attempt(
            "enrolments",
            delete(Enrollment).where(
                Enrollment.offering_id == target_offering, Enrollment.student_id.in_(enrolled)
            ),
        )
    for sid in (uuid.UUID(s) for s in ids.get("students", [])):
        attempt(
            "students",
            delete(StudentSectionHistory).where(StudentSectionHistory.student_id == sid),
            delete(Student).where(Student.id == sid),
        )
    if ids.get("assessment"):
        attempt(
            "assessments", delete(Assessment).where(Assessment.id == uuid.UUID(ids["assessment"]))
        )
    if offering_uuid:
        attempt(
            "classes",
            delete(OfferingFaculty).where(OfferingFaculty.offering_id == offering_uuid),
            delete(OfferingSummary).where(OfferingSummary.offering_id == offering_uuid),
            delete(ImportBatch).where(
                ImportBatch.offering_id == offering_uuid, ImportBatch.committed_at.is_(None)
            ),
            delete(CourseOffering).where(CourseOffering.id == offering_uuid),
        )
    if ids.get("section"):
        attempt("sections", delete(Section).where(Section.id == uuid.UUID(ids["section"])))
    if ids.get("course"):
        attempt("courses", delete(Course).where(Course.id == uuid.UUID(ids["course"])))
    if ids.get("faculty"):
        attempt(
            "faculty",
            delete(User).where(User.id == uuid.UUID(ids["faculty"]), User.last_login_at.is_(None)),
        )
    if ids.get("term"):
        term_id = uuid.UUID(ids["term"])
        was_current = session.scalar(
            select(AcademicTerm.is_current).where(AcademicTerm.id == term_id)
        )
        if attempt("terms", delete(AcademicTerm).where(AcademicTerm.id == term_id)) and was_current:
            latest = session.scalar(
                select(AcademicTerm).order_by(AcademicTerm.start_date.desc()).limit(1)
            )
            if latest is not None:
                latest.is_current = True
                session.flush()
    return dict(removed)
