"""Synthetic demo dataset (contract C11). Never real people: fictional names, a fictional
email domain, register numbers in a demo range.

Embedded patterns (offering 21CSC201J / A1, percentages per CT1, CT2, CT3):

    RA2511003010001  high performer          90, 92, 88
    RA2511003010002  steady decline          78, 65, 52
    RA2511003010003  sharp drop on latest    80, 82, 40
    RA2511003010004  improving               40, 55, 72
    RA2511003010005  persistently low        30, 28, 34
    RA2511003010006  borderline (pass 50)    48, 52, 50
    RA2511003010007  borderline              46, 54, 51
    RA2511003010008  borderline              52, 49, 47
    RA2511003010009  absent on CT2           70, absent, 68
    RA2511003010010  exempt on CT2           60, exempt, 62
    RA2511003010011  single assessment       65, -, -      (no rows for CT2/CT3: missing)
    RA2511003010012  volatile                90, 35, 85

Plus: a very small cohort (21CSC202J / C1, 4 students), a dropped student with a result
(21CSC201J / B1), an inactive student, and an unpublished FT1 with no results everywhere.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.assessments.models import Assessment, AssessmentType, ResultSource, ResultStatus
from app.modules.assessments.service import ResultChange, ResultWriter
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    OfferingFaculty,
    Section,
)
from app.modules.students.models import (
    Enrollment,
    EnrollmentStatus,
    Student,
    StudentSectionHistory,
)
from app.modules.users.models import Role, User

DOMAIN = "acadlytics.dev"
PASS_PERCENT = Decimal("50")
ABSENT, EXEMPT, MISSING = "absent", "exempt", None

# (register number suffix, label, CT1 %, CT2 %, CT3 %)
PATTERNS: list[tuple[int, str, object, object, object]] = [
    (1, "high_performer", 90, 92, 88),
    (2, "steady_decline", 78, 65, 52),
    (3, "sharp_drop", 80, 82, 40),
    (4, "improving", 40, 55, 72),
    (5, "persistently_low", 30, 28, 34),
    (6, "borderline", 48, 52, 50),
    (7, "borderline", 46, 54, 51),
    (8, "borderline", 52, 49, 47),
    (9, "absent_ct2", 70, ABSENT, 68),
    (10, "exempt_ct2", 60, EXEMPT, 62),
    (11, "single_assessment", 65, MISSING, MISSING),
    (12, "volatile", 90, 35, 85),
]

FIRST = [
    "Aarav",
    "Diya",
    "Ishaan",
    "Ananya",
    "Vihaan",
    "Saanvi",
    "Aditya",
    "Myra",
    "Kabir",
    "Aadhya",
    "Rohan",
    "Kiara",
    "Arjun",
    "Meera",
    "Reyansh",
    "Anika",
    "Karthik",
    "Nila",
    "Dev",
    "Tara",
    "Nikhil",
    "Ira",
    "Harsh",
    "Riya",
    "Siddharth",
    "Pooja",
    "Varun",
    "Sneha",
    "Yash",
    "Lavanya",
]
LAST = [
    "Sharma",
    "Iyer",
    "Reddy",
    "Nair",
    "Menon",
    "Gupta",
    "Rao",
    "Pillai",
    "Verma",
    "Das",
    "Kulkarni",
    "Joshi",
    "Bose",
    "Chatterjee",
    "Patel",
    "Singh",
    "Krishnan",
    "Mishra",
]


@dataclass
class SeedReport:
    users: dict[str, str] = field(default_factory=dict)  # email -> role
    offerings: list[str] = field(default_factory=list)
    students: int = 0
    results: int = 0
    patterns: dict[str, str] = field(default_factory=dict)  # register number -> label


class SeedError(Exception):
    pass


def _cell(percent: object, max_marks: Decimal) -> tuple[ResultStatus, Decimal | None] | None:
    if percent is MISSING:
        return None
    if percent == ABSENT:
        return ResultStatus.ABSENT, None
    if percent == EXEMPT:
        return ResultStatus.EXEMPT, None
    # Round to half marks, like real answer scripts.
    raw = Decimal(str(percent)) * max_marks / 100
    score = (raw * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2
    return ResultStatus.PRESENT, min(max(score, Decimal("0")), max_marks)


def seed_demo(session: Session, *, password: str) -> SeedReport:
    """Create the demo dataset inside ``session`` (caller commits). Refuses on a
    non-empty database so it can never mix with real data."""
    if session.scalar(select(func.count()).select_from(Department)):
        raise SeedError(
            "The database already has departments; the demo seed only runs on an empty database."
        )
    rng = random.Random(2026)
    report = SeedReport()
    pw = hash_password(password)

    cse = Department(code="CSE", name="Computer Science and Engineering")
    session.add(cse)
    session.flush()
    term = AcademicTerm(
        code="2026-ODD",
        name="Odd Semester 2026-27",
        academic_year="2026-27",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 11, 30),
        is_current=True,
    )
    session.add(term)

    def user(local: str, name: str, role: Role, department: Department | None = None) -> User:
        account = User(
            email=f"{local}@{DOMAIN}",
            full_name=name,
            password_hash=pw,
            role=role,
            department_id=department.id if department else None,
        )
        session.add(account)
        report.users[account.email] = role.value
        return account

    user("admin", "Demo Administrator", Role.ADMIN)
    user("hod.cse", "Dr. Lakshmi Narayanan", Role.HOD, cse)
    priya = user("priya.nair", "Priya Nair", Role.FACULTY, cse)
    arjun = user("arjun.mehta", "Arjun Mehta", Role.FACULTY, cse)
    user("kavya.reddy", "Kavya Reddy", Role.FACULTY, cse)  # no offerings: sees nothing

    dsa = Course(
        department_id=cse.id,
        code="21CSC201J",
        name="Data Structures and Algorithms",
        credits=Decimal("4"),
    )
    os_ = Course(
        department_id=cse.id, code="21CSC202J", name="Operating Systems", credits=Decimal("4")
    )
    a1, b1, c1 = (
        Section(department_id=cse.id, name=n, batch_year=2025, program="B.Tech CSE")
        for n in ("A1", "B1", "C1")
    )
    session.add_all([dsa, os_, a1, b1, c1])
    session.flush()

    counter = iter(range(1, 10_000))

    def students_for(section: Section, count: int) -> list[Student]:
        created = []
        for _ in range(count):
            created.append(
                Student(
                    register_number=f"RA251100301{next(counter):04d}",
                    full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    department_id=cse.id,
                    batch_year=2025,
                    current_section_id=section.id,
                )
            )
        session.add_all(created)
        session.flush()
        session.add_all(
            StudentSectionHistory(student_id=s.id, section_id=section.id) for s in created
        )
        report.students += len(created)
        return created

    a1_students = students_for(a1, 30)  # RA...10001 - 10030: patterns are 1-12
    b1_students = students_for(b1, 26)
    c1_students = students_for(c1, 4)  # very small cohort
    for number, label, *_ in PATTERNS:
        report.patterns[f"RA251100301{number:04d}"] = label
    b1_students[-1].is_active = False  # inactive student (kept out of cohorts)
    b1_students[-1].deactivated_at = func.now()

    plans = [
        (dsa, a1, priya, a1_students),
        (dsa, b1, arjun, b1_students),
        (os_, a1, arjun, a1_students),
        (os_, c1, priya, c1_students),
    ]
    writer = ResultWriter(session)
    for course, section, teacher, members in plans:
        offering = CourseOffering(
            course_id=course.id, term_id=term.id, section_id=section.id, pass_percent=PASS_PERCENT
        )
        session.add(offering)
        session.flush()
        session.add(OfferingFaculty(offering_id=offering.id, user_id=teacher.id))
        session.add_all(Enrollment(offering_id=offering.id, student_id=s.id) for s in members)
        report.offerings.append(f"{course.code} / {section.name} ({teacher.full_name})")

        assessments = []
        for seq, (name, kind, max_marks, weight, when, published) in enumerate(
            (
                ("CT1", AssessmentType.CT, "50", "15", date(2026, 8, 20), True),
                ("CT2", AssessmentType.CT, "50", "15", date(2026, 9, 20), True),
                ("CT3", AssessmentType.CT, "50", "20", date(2026, 10, 20), True),
                ("FT1", AssessmentType.FT, "100", "50", date(2026, 11, 20), False),
            ),
            start=1,
        ):
            assessment = Assessment(
                offering_id=offering.id,
                name=name,
                assessment_type=kind,
                assessment_date=when,
                max_marks=Decimal(max_marks),
                weightage=Decimal(weight),
                sequence_no=seq,
                is_published=published,
                created_by_id=teacher.id,
            )
            session.add(assessment)
            assessments.append(assessment)
        session.flush()

        pattern_rows = {f"RA251100301{n:04d}": (a, b, c) for n, _, a, b, c in PATTERNS}
        for index, assessment in enumerate(assessments[:3]):
            changes = []
            for student in members:
                if not student.is_active:
                    continue
                if course is dsa and section is a1 and student.register_number in pattern_rows:
                    percent = pattern_rows[student.register_number][index]
                else:
                    base = rng.gauss(64, 13) + index * rng.uniform(-3, 3)
                    percent = ABSENT if rng.random() < 0.02 else round(min(max(base, 5), 100))
                cell = _cell(percent, assessment.max_marks)
                if cell is not None:
                    changes.append(ResultChange(student.id, *cell))
            summary = writer.apply(assessment, changes, actor=teacher, source=ResultSource.MANUAL)
            report.results += summary.created

    # A dropped student who keeps their CT1 result (history is never rewritten).
    dropped = session.scalar(select(Enrollment).where(Enrollment.student_id == b1_students[0].id))
    dropped.status = EnrollmentStatus.DROPPED
    dropped.dropped_at = func.now()
    session.flush()
    return report
