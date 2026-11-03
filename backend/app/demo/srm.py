"""The SRM demonstration institution: deterministic, fictional, and large.

    python -m app.cli seed-demo            # this dataset (about 2-4 minutes)
    python -m app.cli seed-demo --minimal  # the small analytics fixture (contract C11)

One department (Computer Science and Engineering) with the full hierarchy — one Administrator,
one HOD, one Academic Head, a Course Coordinator per course and a faculty pool — 97 sections of
the 2024 batch (about 4,100 students) and two semesters of AY 2025-26:

    ODD  (complete)  21CSC204J Design and Analysis of Algorithms, 21CSC205P Database
                     Management Systems
    EVEN (current)   21CSC201J Data Structures and Algorithms, 21CSC202J Operating Systems,
                     21CSC203P Advanced Programming Practice, 21DCS201P Design Thinking and
                     Methodology

Assessments follow the SRM scheme for each course type (FJ-I, LLJ-I, FJ-II, FJ-III, LLJ-II for
joint courses; FP-I, PBL-I..., for project courses), with the component maximum equal to its
contribution as on SRM's TLP reports. The current semester is in progress: the last components
are not yet published and have no marks. For DSA, FJ-III marks exist only for some sections —
the rest arrive through the TLP upload demo (``demo/tlp-uploads``). DSA's FJ-II marks for the
first sections are imported through the real TLP pipeline, so import history is genuine.

Performance varies deliberately and reproducibly: every section has a profile (high performing,
average, borderline, high failure, declining, improving, incomplete data, volatile), every
faculty member and course a small offset, every student a persistent ability, and FJ-II of DSA
is a harder paper — so charts show real spikes, drops and spreads, not noise.

Nothing here is real: names are generated, register numbers use the fictional RA2411999 series,
staff ids the 9xxxxx series, and every account uses the ``acadlytics.dev`` domain.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.analytics.core.rules import AttentionRuleCode
from app.modules.analytics.core.vocabulary import InterventionKind, InterventionStatus
from app.modules.assessments.models import (
    Assessment,
    AssessmentResult,
    ResultSource,
    ResultStatus,
)
from app.modules.assessments.schemes import SCHEMES, component_max
from app.modules.attention.models import AttentionFlag
from app.modules.imports.tlp_writer import TlpHeader, TlpRow, to_csv, to_pdf, to_xlsx
from app.modules.organization.models import (
    AcademicTerm,
    Course,
    CourseCoordinator,
    CourseOffering,
    CourseType,
    Department,
    DepartmentSetting,
    OfferingFaculty,
    Section,
    Semester,
)
from app.modules.students.models import (
    Enrollment,
    EnrollmentStatus,
    Student,
    StudentSectionHistory,
)
from app.modules.users.models import Role, User

DOMAIN = "acadlytics.dev"
SEED = 2026
SECTIONS = 97
PASS = Decimal("50")
DEMO_DIR = Path(__file__).resolve().parents[3] / "demo" / "tlp-uploads"

FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Vihaan",
    "Arjun",
    "Sai",
    "Reyansh",
    "Ayaan",
    "Krishna",
    "Ishaan",
    "Shaurya",
    "Atharv",
    "Advik",
    "Pranav",
    "Advait",
    "Dhruv",
    "Kabir",
    "Ritvik",
    "Aarush",
    "Kiaan",
    "Rohan",
    "Nikhil",
    "Varun",
    "Karthik",
    "Siddharth",
    "Manav",
    "Yash",
    "Rahul",
    "Charan",
    "Dev",
    "Gautam",
    "Hari",
    "Jai",
    "Kunal",
    "Laksh",
    "Madhav",
    "Naveen",
    "Om",
    "Parth",
    "Raghav",
    "Surya",
    "Tejas",
    "Uday",
    "Vikram",
    "Yuvan",
    "Ananya",
    "Diya",
    "Aadhya",
    "Saanvi",
    "Pari",
    "Anika",
    "Navya",
    "Myra",
    "Ira",
    "Kavya",
    "Meera",
    "Riya",
    "Tara",
    "Nisha",
    "Pooja",
    "Sneha",
    "Lakshmi",
    "Divya",
    "Keerthi",
    "Harini",
    "Tanvi",
    "Isha",
    "Nandini",
    "Shreya",
    "Aditi",
    "Janani",
    "Bhavana",
    "Deepika",
    "Gayathri",
    "Hema",
    "Ishita",
    "Jyothi",
    "Kritika",
    "Lavanya",
    "Mahima",
    "Nithya",
    "Priyanka",
    "Ramya",
    "Sanjana",
    "Swathi",
    "Varsha",
    "Vaishnavi",
    "Yamini",
    "Zoya",
]
LAST = [
    "Sharma",
    "Iyer",
    "Reddy",
    "Nair",
    "Menon",
    "Rao",
    "Pillai",
    "Das",
    "Gupta",
    "Kulkarni",
    "Joshi",
    "Patel",
    "Singh",
    "Verma",
    "Bose",
    "Chatterjee",
    "Mehta",
    "Shah",
    "Naidu",
    "Krishnan",
    "Subramanian",
    "Raghavan",
    "Venkatesh",
    "Srinivasan",
    "Banerjee",
    "Mukherjee",
    "Agarwal",
    "Kapoor",
    "Malhotra",
    "Chopra",
    "Bhat",
    "Hegde",
    "Shetty",
    "Kamath",
    "Prabhu",
    "Pai",
    "Varma",
    "Kumar",
    "Mishra",
    "Pandey",
    "Tiwari",
    "Saxena",
    "Srivastava",
    "Dubey",
    "Jain",
    "Arora",
    "Sethi",
    "Khanna",
    "Anand",
    "Ramesh",
]

COURSES = {
    # code: (name, type, semester, difficulty offset, per-component offsets)
    "21CSC204J": ("Design and Analysis of Algorithms", CourseType.JOINT, Semester.ODD, -3, {}),
    "21CSC205P": ("Database Management Systems", CourseType.PROJECT, Semester.ODD, 4, {}),
    "21CSC201J": (
        "Data Structures and Algorithms",
        CourseType.JOINT,
        Semester.EVEN,
        0,
        {"FJ-II": -9, "LLJ-I": 4, "FJ-III": 3},
    ),
    "21CSC202J": (
        "Operating Systems",
        CourseType.JOINT,
        Semester.EVEN,
        -6,
        {"FJ-I": 3, "FJ-II": -2},
    ),
    "21CSC203P": (
        "Advanced Programming Practice",
        CourseType.PROJECT,
        Semester.EVEN,
        6,
        {"FP-I": -4},
    ),
    "21DCS201P": ("Design Thinking and Methodology", CourseType.PROJECT, Semester.EVEN, 8, {}),
}
COORDINATORS = {
    "21CSC201J": ("coord.dsa", "Dr. Priya Nair", "Associate Professor"),
    "21CSC202J": ("coord.os", "Dr. Arjun Mehta", "Associate Professor"),
    "21CSC203P": ("coord.app", "Dr. Kavya Reddy", "Assistant Professor (Sr. G)"),
    "21DCS201P": ("coord.dt", "Dr. Rahul Iyer", "Assistant Professor (Sr. G)"),
    "21CSC204J": ("coord.daa", "Dr. Deepa Krishnan", "Associate Professor"),
    "21CSC205P": ("coord.dbms", "Dr. Suresh Babu", "Associate Professor"),
}
# How far each current-semester course has got: components with marks (published).
EVEN_DONE = {
    "21CSC201J": ("FJ-I", "LLJ-I", "FJ-II"),  # FJ-III: some sections now, rest via TLP upload
    "21CSC202J": ("FJ-I", "LLJ-I", "FJ-II", "FJ-III"),
    "21CSC203P": ("FP-I", "PBL-I", "PBL-II"),
    "21DCS201P": ("FP-I", "PBL-I"),
}
DSA_FJ3_SEEDED = 60  # sections whose FJ-III marks are already in (the rest: TLP upload demo)
DSA_FJ2_VIA_TLP = 12  # sections whose FJ-II marks are imported through the real TLP pipeline

PROFILES = (
    ("high performing", 12, 0, 0.02),
    ("average", 0, 0, 0.03),
    ("average", 2, 0, 0.03),
    ("borderline", -12, 0, 0.04),
    ("high failure", -20, 0, 0.05),
    ("declining", 4, -5, 0.03),
    ("improving", -8, 5, 0.03),
    ("incomplete data", -2, 0, 0.14),
    ("volatile", 0, 0, 0.03),
    ("average", -3, 0, 0.03),
)


@dataclass
class Report:
    departments: int = 0
    sections: int = 0
    students: int = 0
    faculty: int = 0
    offerings: int = 0
    results: int = 0
    interventions: int = 0
    imports: int = 0
    seconds: float = 0
    accounts: dict[str, str] = field(default_factory=dict)
    demo_files: list[str] = field(default_factory=list)


class SeedError(Exception):
    pass


def _q(value: float, step: Decimal) -> Decimal:
    return (Decimal(str(value)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def section_names(n: int) -> list[str]:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    names = []
    for i in range(n):
        names.append(f"{letters[i // 7]}{i % 7 + 1}")
    return names


def seed_srm(
    session: Session,
    *,
    password: str,
    sections: int = SECTIONS,
    students_per_section: tuple[int, int] = (38, 46),
    write_demo_files: bool = True,
    progress=print,
) -> Report:
    if session.scalar(select(func.count()).select_from(User)):
        raise SeedError("The database already has users; seed-demo only runs on an empty database.")
    started = time.monotonic()
    rng = random.Random(SEED)
    report = Report()
    pw_hash = hash_password(password)

    def user(
        local: str,
        name: str,
        role: Role,
        dept: Department | None,
        code: str | None,
        title: str | None,
    ) -> User:
        u = User(
            email=f"{local}@{DOMAIN}",
            full_name=name,
            password_hash=pw_hash,
            role=role,
            department_id=dept.id if dept else None,
            employee_code=code,
            designation=title,
            is_active=True,
        )
        session.add(u)
        report.accounts[u.email] = role.value
        return u

    # ---------------------------------------------------------------- structure
    cse = Department(code="CSE", name="Computer Science and Engineering")
    session.add(cse)
    session.flush()
    report.departments = 1
    odd = AcademicTerm(
        code="AY2025-26-ODD",
        name="Odd Semester 2025-26",
        academic_year="2025-26",
        semester=Semester.ODD,
        start_date=date(2025, 7, 14),
        end_date=date(2025, 11, 28),
    )
    even = AcademicTerm(
        code="AY2025-26-EVEN",
        name="Even Semester 2025-26",
        academic_year="2025-26",
        semester=Semester.EVEN,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 5, 29),
        is_current=True,
    )
    session.add_all([odd, even])
    session.add(
        DepartmentSetting(
            department_id=cse.id, key="institution", value="SRM Institute of Science and Technology"
        )
    )

    user("admin", "Dr. Kavitha Subramanian", Role.ADMIN, None, "900001", "Registrar (Academics)")
    user("hod.cse", "Dr. Lakshmi Narayanan", Role.HOD, cse, "900002", "Professor and Head")
    head = user(
        "academic.head",
        "Dr. Meenakshi Raghavan",
        Role.ACADEMIC_HEAD,
        cse,
        "900003",
        "Professor, Academic Head",
    )
    session.flush()

    courses: dict[str, Course] = {}
    coordinators: dict[str, User] = {}
    for n, (code, (name, kind, _sem, _d, _o)) in enumerate(COURSES.items()):
        course = Course(
            department_id=cse.id,
            code=code,
            name=name,
            credits=Decimal("4") if kind is CourseType.JOINT else Decimal("3"),
            course_type=kind,
        )
        session.add(course)
        local, cname, title = COORDINATORS[code]
        coord = user(local, cname, Role.COURSE_COORDINATOR, cse, f"9001{n + 10:02d}", title)
        session.flush()
        session.add(
            CourseCoordinator(course_id=course.id, user_id=coord.id, assigned_by_id=head.id)
        )
        courses[code], coordinators[code] = course, coord

    pool: list[User] = []
    used_names: set[str] = set()
    titles = ("Assistant Professor", "Assistant Professor (Sr. G)", "Associate Professor")
    for i in range(100):
        while True:
            # Half hold a doctorate. No Mr./Ms.: the generator cannot know anyone's gender
            # and a random honorific would contradict the first name.
            title = "Dr. " if rng.random() < 0.5 else ""
            name = f"{title}{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                break
        pool.append(
            user(f"faculty{i + 1}", name, Role.FACULTY, cse, f"90{2001 + i}", titles[i % 3])
        )
    session.flush()
    report.faculty = len(pool) + len(coordinators)
    faculty_offset = {u.id: rng.gauss(0, 3.5) for u in [*pool, *coordinators.values()]}

    names = section_names(sections)
    section_rows = [
        Section(department_id=cse.id, name=n, batch_year=2024, program="B.Tech CSE") for n in names
    ]
    session.add_all(section_rows)
    session.flush()
    report.sections = len(section_rows)
    profile_of = {s.id: PROFILES[(i * 7 + 3) % len(PROFILES)] for i, s in enumerate(section_rows)}

    # ---------------------------------------------------------------- students
    progress(f"  structure ready; creating students for {len(section_rows)} sections")
    student_rows, history_rows, ability = [], [], {}
    serial = 0
    by_section: dict[uuid.UUID, list[uuid.UUID]] = {}
    for section in section_rows:
        by_section[section.id] = []
        for _ in range(rng.randint(*students_per_section)):
            serial += 1
            sid = uuid.uuid4()
            first, last = rng.choice(FIRST), rng.choice(LAST)
            student_rows.append(
                {
                    "id": sid,
                    "register_number": f"RA2411999{serial:06d}",
                    "full_name": f"{first} {last}".upper(),
                    "email": f"s{serial:06d}@students.{DOMAIN}",
                    "department_id": cse.id,
                    "batch_year": 2024,
                    "current_section_id": section.id,
                    "is_active": True,
                }
            )
            history_rows.append({"student_id": sid, "section_id": section.id})
            ability[sid] = rng.gauss(0, 11)
            by_section[section.id].append(sid)
    session.execute(insert(Student), student_rows)
    session.execute(insert(StudentSectionHistory), history_rows)
    report.students = len(student_rows)
    names_of = {r["id"]: (r["register_number"], r["full_name"]) for r in student_rows}

    # ---------------------------------------------------------------- offerings & marks
    progress(f"  {report.students} students; creating offerings and marks")
    offerings: dict[tuple[str, str], CourseOffering] = {}
    teachers: dict[uuid.UUID, User] = {}
    results: list[dict] = []
    tlp_later: dict[str, list] = {"fj2": [], "fj3": []}
    for c_index, (code, (_name, kind, semester, difficulty, comp_offsets)) in enumerate(
        COURSES.items()
    ):
        course, coord = courses[code], coordinators[code]
        term = odd if semester is Semester.ODD else even
        scheme = SCHEMES[kind]
        done = EVEN_DONE.get(code, tuple(c[0] for c in scheme))
        for s_index, section in enumerate(section_rows):
            # Faculty teach blocks of four sections; the coordinator takes the first block.
            if s_index < 3:
                teacher = coord
            else:
                teacher = pool[(c_index * 17 + (s_index - 3) // 4) % len(pool)]
            offering = CourseOffering(
                course_id=course.id, term_id=term.id, section_id=section.id, pass_percent=PASS
            )
            session.add(offering)
            session.flush()
            session.add(OfferingFaculty(offering_id=offering.id, user_id=teacher.id))
            offerings[(code, section.name)] = offering
            teachers[offering.id] = teacher
            session.execute(
                insert(Enrollment),
                [{"offering_id": offering.id, "student_id": sid} for sid in by_section[section.id]],
            )

            label, level, slope, absent_rate = profile_of[section.id]
            volatile = label == "volatile"
            for seq, (aname, family, weight) in enumerate(scheme, start=1):
                maximum = component_max(weight)
                has_marks = aname in done
                if code == "21CSC201J" and aname == "FJ-III":
                    has_marks = s_index < DSA_FJ3_SEEDED
                assessment = Assessment(
                    offering_id=offering.id,
                    name=aname,
                    assessment_type=family,
                    max_marks=maximum,
                    weightage=weight,
                    sequence_no=seq,
                    is_published=has_marks,
                    assessment_date=_date_for(term, seq, len(scheme)),
                    created_by_id=coord.id,
                )
                session.add(assessment)
                session.flush()
                if not has_marks:
                    continue
                via_tlp = code == "21CSC201J" and aname == "FJ-II" and s_index < DSA_FJ2_VIA_TLP
                comp = comp_offsets.get(aname, 0) + (rng.gauss(0, 9) if volatile else 0)
                rows = []
                for sid in by_section[section.id]:
                    roll = rng.random()
                    if roll < absent_rate:
                        status, score = ResultStatus.ABSENT, None
                    elif roll < absent_rate + 0.003:
                        status, score = ResultStatus.EXEMPT, None
                    else:
                        pct = (
                            64
                            + level
                            + difficulty
                            + faculty_offset[teacher.id]
                            + ability[sid]
                            + comp
                            + slope * (seq - 1)
                            + rng.gauss(0, 7)
                        )
                        pct = max(0.0, min(100.0, pct))
                        score = min(maximum, _q(pct / 100 * float(maximum), Decimal("0.5")))
                        status = ResultStatus.PRESENT
                    rows.append((sid, status, score))
                if via_tlp:
                    tlp_later["fj2"].append((offering, assessment, section, teacher, rows))
                    continue
                for sid, status, score in rows:
                    results.append(
                        {
                            "student_id": sid,
                            "assessment_id": assessment.id,
                            "score": score,
                            "status": status,
                            "max_marks_snapshot": maximum,
                            "source": ResultSource.IMPORT,
                            "recorded_by_id": teacher.id,
                        }
                    )
            report.offerings += 1
        if len(results) > 20000:
            session.execute(insert(AssessmentResult), results)
            report.results += len(results)
            results = []
    if results:
        session.execute(insert(AssessmentResult), results)
        report.results += len(results)
    session.flush()

    # A realistic handful of changes to the record: two late drops keep their history, and
    # one repeater has an inactive record.
    first_dsa = offerings[("21CSC201J", section_rows[0].name)]
    dropped = by_section[section_rows[0].id][-1]
    enrolment = session.scalar(
        select(Enrollment).where(
            Enrollment.offering_id == first_dsa.id, Enrollment.student_id == dropped
        )
    )
    enrolment.status = EnrollmentStatus.DROPPED
    enrolment.dropped_at = datetime(2026, 2, 20, tzinfo=UTC)
    session.flush()

    # ---------------------------------------------------------------- analytics for everything
    progress(f"  {report.offerings} offerings, {report.results} results; computing analytics")
    from app.modules.analytics.recompute import recompute_offering

    for i, offering in enumerate(offerings.values(), start=1):
        anchor = session.scalar(
            select(Assessment.id)
            .where(Assessment.offering_id == offering.id)
            .order_by(Assessment.sequence_no)
        )
        recompute_offering(session, offering.id, anchor)
        if i % 100 == 0:
            session.commit()
            progress(f"    analytics {i}/{len(offerings)}")
    session.commit()

    # ---------------------------------------------------------------- real TLP imports (history)
    progress("  importing DSA FJ-II for the first sections through the TLP pipeline")
    from app.modules.imports.tlp_service import TlpUploadService

    files = []
    for _offering, assessment, section, teacher, rows in tlp_later["fj2"]:
        header = _header("FJ-II", assessment.max_marks, courses["21CSC201J"], teacher)
        tlp_rows = [
            TlpRow(
                names_of[sid][0],
                names_of[sid][1],
                score if status is ResultStatus.PRESENT else None,
            )
            for sid, status, score in rows
            if status is not ResultStatus.EXEMPT and sid != dropped
        ]
        files.append((f"DSA_FJ-II_{section.name}.xlsx", to_xlsx(header, tlp_rows)))
    service = TlpUploadService(session)
    upload = service.upload(files, actor=coordinators["21CSC201J"])
    confirmed = service.confirm_group(
        upload.group_id, actor=coordinators["21CSC201J"], publish=True
    )
    report.imports = confirmed.counts.get("confirmed", 0)
    if report.imports != len(files):
        raise SeedError(
            f"TLP demo import failed: {confirmed.counts} {[f.message for f in confirmed.files]}"
        )

    # ---------------------------------------------------------------- interventions
    progress("  recording interventions")
    report.interventions = _interventions(session, offerings, teachers, rng)

    # ---------------------------------------------------------------- demo upload files
    if write_demo_files:
        report.demo_files = write_tlp_demo(
            session, courses["21CSC201J"], names_of, section_rows, offerings, teachers, ability, rng
        )
    session.commit()
    report.seconds = round(time.monotonic() - started, 1)
    return report


def _date_for(term: AcademicTerm, seq: int, total: int) -> date:
    span = (term.end_date - term.start_date).days
    return term.start_date.fromordinal(term.start_date.toordinal() + int(span * seq / (total + 1)))


def _header(test: str, maximum: Decimal, course: Course, teacher: User) -> TlpHeader:
    return TlpHeader(
        test_name=test,
        academic_year="AY2025-26-EVEN",
        component_max=maximum,
        course_code=course.code,
        course_name=course.name,
        faculty_name=teacher.full_name,
        faculty_code=teacher.employee_code or "",
        report_date="10-Apr-26",
    )


def _interventions(session: Session, offerings, teachers, rng: random.Random) -> int:
    from app.modules.interventions.schemas import InterventionCreate, InterventionReasonIn
    from app.modules.interventions.service import InterventionService

    service = InterventionService(session)
    count = 0
    targets = [o for (code, _), o in offerings.items() if code in ("21CSC201J", "21CSC202J")]
    for offering in targets[::4]:
        flags = list(
            session.scalars(
                select(AttentionFlag)
                .where(
                    AttentionFlag.offering_id == offering.id,
                    AttentionFlag.status != "resolved",
                    AttentionFlag.rule_code.in_(
                        [
                            AttentionRuleCode.R1_LOW_PERFORMANCE,
                            AttentionRuleCode.R2_FAILED_LATEST,
                            AttentionRuleCode.R4_SHARP_DECLINE,
                        ]
                    ),
                )
                .order_by(AttentionFlag.rule_code, AttentionFlag.student_id)
            )
        )
        if not flags:
            continue
        chosen = flags[: rng.randint(1, 3)]
        kind = rng.choice(
            [
                InterventionKind.REMEDIAL_SESSION,
                InterventionKind.ACADEMIC_SUPPORT,
                InterventionKind.ADDITIONAL_PRACTICE,
                InterventionKind.FACULTY_MEETING,
            ]
        )
        payload = InterventionCreate(
            student_ids=tuple(dict.fromkeys(f.student_id for f in chosen)),
            kind=kind,
            status=rng.choice(
                [
                    InterventionStatus.COMPLETED,
                    InterventionStatus.COMPLETED,
                    InterventionStatus.ACTIVE,
                ]
            ),
            after_sequence_no=2,
            recorded_on=date(2026, 3, rng.randint(2, 27)),
            reasons=tuple(
                InterventionReasonIn(student_id=f.student_id, flag_id=f.id) for f in chosen
            ),
            note={
                InterventionKind.REMEDIAL_SESSION: "Weekend remedial session on trees and graphs.",
                InterventionKind.ACADEMIC_SUPPORT: "One-to-one review of the last paper.",
                InterventionKind.ADDITIONAL_PRACTICE: "Extra practice set shared on the LMS.",
                InterventionKind.FACULTY_MEETING: "Met the student with their faculty advisor.",
            }[kind],
        )
        service.create(offering.id, payload, actor=teachers[offering.id])
        count += 1
    return count


def write_tlp_demo(
    session, dsa: Course, names_of, section_rows, offerings, teachers, ability, rng
) -> list[str]:
    """The files the Course Coordinator uploads in the demo: FJ-III for DSA sections that do
    not have it yet, in all three formats, plus the cases the importer must catch."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for old in DEMO_DIR.glob("*"):
        if old.is_file() and old.suffix in (".xlsx", ".csv", ".pdf"):
            old.unlink()
    written = []
    pending = section_rows[DSA_FJ3_SEEDED : DSA_FJ3_SEEDED + 10]
    writers = (("xlsx", to_xlsx), ("csv", to_csv), ("pdf", to_pdf))
    for i, section in enumerate(pending):
        offering = offerings[("21CSC201J", section.name)]
        teacher = teachers[offering.id]
        maximum = Decimal("15")
        rows = []
        for (sid,) in session.execute(
            select(Enrollment.student_id)
            .join(Student)
            .where(
                Enrollment.offering_id == offering.id, Enrollment.status == EnrollmentStatus.ACTIVE
            )
            .order_by(Student.register_number)
        ):
            if rng.random() < 0.03:
                rows.append(TlpRow(names_of[sid][0], names_of[sid][1], None))
                continue
            pct = max(0.0, min(100.0, 66 + ability[sid] + rng.gauss(0, 7)))
            rows.append(
                TlpRow(
                    names_of[sid][0],
                    names_of[sid][1],
                    min(maximum, _q(pct / 100 * 15, Decimal("0.5"))),
                )
            )
        ext, writer = writers[i % 3]
        header = _header("FJ-III", maximum, dsa, teacher)
        if i == 8:  # a report exported with the wrong component maximum: must be refused
            header = TlpHeader(**{**header.__dict__, "component_max": Decimal("20")})
            name = f"DSA_FJ-III_{section.name}_wrong-max.{ext}"
        elif i == 9:  # one mark above the maximum: a cell error to fix in the preview
            rows[3] = TlpRow(rows[3].register_number, rows[3].name, Decimal("17"))
            name = f"DSA_FJ-III_{section.name}_needs-fix.{ext}"
        else:
            name = f"DSA_FJ-III_{section.name}.{ext}"
        (DEMO_DIR / name).write_bytes(writer(header, rows))
        written.append(name)
    (DEMO_DIR / "README.md").write_text(
        "# TLP upload demo files\n\n"
        "Generated by `python -m app.cli seed-demo` (deterministic; fictional students).\n\n"
        "Sign in as the DSA Course Coordinator (`coord.dsa@acadlytics.dev`), open **Import**, "
        "and drop every file here at once. Each file is routed to its section by the register "
        "numbers it contains and to FJ-III by its test name. Expect:\n\n"
        "* eight files **valid** (xlsx, csv and TLP-format pdf)\n"
        "* `*_wrong-max.*` **error**: the report says the component is out of 20; "
        "FJ-III is out of 15\n"
        "* `*_needs-fix.*` **error**: one mark above the maximum; fix the cell in the "
        "preview or exclude the row\n\n"
        "Upload any file twice to see it reported as a duplicate.\n"
    )
    return written
