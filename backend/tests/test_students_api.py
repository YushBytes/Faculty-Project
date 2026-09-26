"""Students: PII scope, management rights, section history and bulk import."""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.organization.models import AcademicTerm, Department
from app.modules.students.models import Enrollment, Student
from app.modules.users.models import Role, User
from tests.conftest import OrgFactory, StudentFactory, auth_headers

STUDENTS = "/api/v1/students"


@pytest.fixture
def cse_a1(org: OrgFactory, cse: Department):
    return org.section(cse, name="A1")


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Student))


class TestCreate:
    def _body(self, department: Department, **extra) -> dict:
        return {
            "register_number": " ra2511003010001 ",
            "full_name": "Asha Rao",
            "email": "Asha.Rao@SRMIST.edu.in",
            "department_id": str(department.id),
            "batch_year": 2025,
            **extra,
        }

    def test_admin_creates_normalised(self, client: TestClient, admin: User, cse, cse_a1) -> None:
        response = client.post(
            STUDENTS, json=self._body(cse, section_id=str(cse_a1.id)), headers=auth_headers(admin)
        )
        assert response.status_code == 201
        body = response.json()
        assert body["register_number"] == "RA2511003010001"
        assert body["email"] == "asha.rao@srmist.edu.in"
        assert body["current_section"]["name"] == "A1"
        assert body["department"]["code"] == "CSE"

    def test_hod_own_department_only(self, client: TestClient, hod: User, cse, ece) -> None:
        headers = auth_headers(hod)
        assert client.post(STUDENTS, json=self._body(cse), headers=headers).status_code == 201
        other = client.post(
            STUDENTS,
            json=self._body(ece, register_number="RA2511004010001", email=None),
            headers=headers,
        )
        assert other.status_code == 403

    def test_faculty_cannot_create(self, client: TestClient, faculty: User, cse) -> None:
        assert (
            client.post(STUDENTS, json=self._body(cse), headers=auth_headers(faculty)).status_code
            == 403
        )

    @pytest.mark.parametrize(
        "override",
        [
            {"register_number": "RA-25"},
            {"register_number": "abc"},
            {"email": "not-an-email"},
            {"batch_year": 1990},
            {"full_name": ""},
        ],
    )
    def test_invalid(self, client: TestClient, admin: User, cse, override: dict) -> None:
        response = client.post(
            STUDENTS, json=self._body(cse, **override), headers=auth_headers(admin)
        )
        assert response.status_code == 422

    def test_duplicates_conflict(
        self, client: TestClient, admin: User, cse, make_student: StudentFactory
    ) -> None:
        existing = make_student(cse, register_number="RA2511003010001")
        headers = auth_headers(admin)
        assert (
            client.post(STUDENTS, json=self._body(cse, email=None), headers=headers).status_code
            == 409
        )
        same_email = self._body(cse, register_number="RA2511003010002", email=existing.email)
        assert client.post(STUDENTS, json=same_email, headers=headers).status_code == 409

    def test_section_must_match_department(
        self, client: TestClient, admin: User, cse, ece, org: OrgFactory
    ) -> None:
        body = self._body(cse, section_id=str(org.section(ece).id))
        assert client.post(STUDENTS, json=body, headers=auth_headers(admin)).status_code == 422


class TestScope:
    @pytest.fixture
    def setup(
        self,
        org: OrgFactory,
        cse,
        ece,
        term: AcademicTerm,
        faculty: User,
        make_user,
        make_student: StudentFactory,
    ):
        other = make_user(Role.FACULTY, email="other.fac@srmist.edu.in")
        mine = org.offering(org.course(cse), org.section(cse), term, faculty=[faculty])
        theirs = org.offering(org.course(ece), org.section(ece), term, faculty=[other])
        return {
            "in_mine": make_student(cse, enroll_in=[mine]),
            "in_theirs": make_student(ece, enroll_in=[theirs]),
            "cse_unenrolled": make_student(cse),
            "ece_unenrolled": make_student(ece),
            "mine": mine,
        }

    def _ids(self, response) -> set[str]:
        return {s["register_number"] for s in response.json()["items"]}

    def test_faculty_sees_only_their_enrolled_students(
        self, client: TestClient, faculty: User, setup
    ) -> None:
        headers = auth_headers(faculty)
        assert self._ids(client.get(STUDENTS, headers=headers)) == {
            setup["in_mine"].register_number
        }
        for key in ("in_theirs", "cse_unenrolled", "ece_unenrolled"):
            assert client.get(f"{STUDENTS}/{setup[key].id}", headers=headers).status_code == 404
        assert client.get(f"{STUDENTS}/{setup['in_mine'].id}", headers=headers).status_code == 200

    def test_hod_sees_department(self, client: TestClient, hod: User, setup) -> None:
        visible = self._ids(client.get(STUDENTS, headers=auth_headers(hod)))
        assert visible == {
            setup["in_mine"].register_number,
            setup["cse_unenrolled"].register_number,
        }

    def test_admin_sees_all(self, client: TestClient, admin: User, setup) -> None:
        assert client.get(STUDENTS, headers=auth_headers(admin)).json()["total"] == 4

    def test_filters_cannot_widen_scope(self, client: TestClient, faculty: User, setup) -> None:
        response = client.get(
            STUDENTS,
            params={"department_id": str(setup["in_theirs"].department_id)},
            headers=auth_headers(faculty),
        )
        assert response.json()["total"] == 0

    def test_losing_assignment_loses_access(
        self, client: TestClient, faculty: User, admin: User, setup
    ) -> None:
        student_url = f"{STUDENTS}/{setup['in_mine'].id}"
        assert client.get(student_url, headers=auth_headers(faculty)).status_code == 200
        client.delete(
            f"/api/v1/offerings/{setup['mine'].id}/faculty/{faculty.id}",
            headers=auth_headers(admin),
        )
        assert client.get(student_url, headers=auth_headers(faculty)).status_code == 404

    def test_search(self, client: TestClient, admin: User, setup) -> None:
        number = setup["in_mine"].register_number
        response = client.get(STUDENTS, params={"q": number[-5:]}, headers=auth_headers(admin))
        assert self._ids(response) == {number}


class TestUpdateAndHistory:
    def test_section_move_keeps_history_and_enrolments(
        self,
        client: TestClient,
        hod: User,
        cse,
        org: OrgFactory,
        term,
        make_student: StudentFactory,
        db_session: Session,
    ) -> None:
        a1, b1 = org.section(cse, name="A1"), org.section(cse, name="B1")
        old_offering = org.offering(org.course(cse), a1, term)
        student = make_student(cse, a1, enroll_in=[old_offering])

        response = client.patch(
            f"{STUDENTS}/{student.id}", json={"section_id": str(b1.id)}, headers=auth_headers(hod)
        )
        assert response.status_code == 200
        assert response.json()["current_section"]["name"] == "B1"

        history = client.get(f"{STUDENTS}/{student.id}/sections", headers=auth_headers(hod)).json()
        assert [h["section"]["name"] for h in history] == ["A1", "B1"]
        assert history[0]["ended_at"] is not None and history[1]["ended_at"] is None

        # The enrolment in the A1 offering is untouched.
        enrollment = db_session.scalar(
            select(Enrollment).where(Enrollment.student_id == student.id)
        )
        assert enrollment.offering_id == old_offering.id and enrollment.status.value == "ACTIVE"

    def test_update_fields(self, client: TestClient, admin: User, cse, make_student) -> None:
        student = make_student(cse)
        response = client.patch(
            f"{STUDENTS}/{student.id}",
            json={"full_name": "New Name", "email": None},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "New Name" and response.json()["email"] is None

    def test_faculty_cannot_update_even_their_students(
        self, client: TestClient, faculty: User, cse, cse_offering, make_student
    ) -> None:
        student = make_student(cse, enroll_in=[cse_offering])
        response = client.patch(
            f"{STUDENTS}/{student.id}", json={"full_name": "X"}, headers=auth_headers(faculty)
        )
        assert response.status_code == 403

    def test_deactivate_and_activate(
        self, client: TestClient, hod: User, cse, make_student
    ) -> None:
        student = make_student(cse)
        headers = auth_headers(hod)
        off = client.post(f"{STUDENTS}/{student.id}/deactivate", headers=headers).json()
        assert off["is_active"] is False and off["deactivated_at"] is not None
        on = client.post(f"{STUDENTS}/{student.id}/activate", headers=headers).json()
        assert on["is_active"] is True and on["deactivated_at"] is None


class TestBulk:
    def _row(self, n: int, **extra) -> dict:
        return {
            "register_number": f"RA25110030{n:05d}",
            "full_name": f"Student {n}",
            "email": f"s{n}@srmist.edu.in",
            "department_code": "cse",
            "batch_year": 2025,
            "section": "a1",
            **extra,
        }

    def test_creates_and_updates(
        self, client: TestClient, admin: User, cse, cse_a1, make_student, db_session: Session
    ) -> None:
        make_student(cse, register_number="RA2511003000003")
        rows = [self._row(1), self._row(2), self._row(3, full_name="Renamed")]
        response = client.post(f"{STUDENTS}/bulk", json={"rows": rows}, headers=auth_headers(admin))
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is True and result["errors"] == []
        assert (result["created"], result["updated"], result["unchanged"]) == (2, 1, 0)
        assert _count(db_session) == 3

        again = client.post(f"{STUDENTS}/bulk", json={"rows": rows}, headers=auth_headers(admin))
        assert (again.json()["created"], again.json()["unchanged"]) == (0, 3)

    def test_dry_run_writes_nothing(
        self, client: TestClient, admin: User, cse, cse_a1, db_session: Session
    ) -> None:
        response = client.post(
            f"{STUDENTS}/bulk",
            json={"rows": [self._row(1)], "dry_run": True},
            headers=auth_headers(admin),
        )
        assert response.json()["valid"] is True and response.json()["created"] == 1
        assert _count(db_session) == 0

    def test_any_bad_row_blocks_all_rows(
        self, client: TestClient, admin: User, cse, cse_a1, make_student, db_session: Session
    ) -> None:
        taken = make_student(cse, register_number="RA2511009999999")
        rows = [
            self._row(1),
            self._row(1, email="dup@srmist.edu.in"),  # duplicate register number in file
            self._row(3, department_code="XYZ"),
            self._row(4, section="Z9"),
            self._row(5, register_number="bad-no"),
            self._row(6, email=taken.email),
            self._row(7, batch_year="twenty"),
        ]
        response = client.post(f"{STUDENTS}/bulk", json={"rows": rows}, headers=auth_headers(admin))
        result = response.json()
        assert result["valid"] is False and result["created"] == 0
        by_row = {(e["row"], e["field"]) for e in result["errors"]}
        assert by_row == {
            (2, "register_number"),
            (3, "department_code"),
            (4, "section"),
            (5, "register_number"),
            (6, "email"),
            (7, "batch_year"),
        }
        assert all(e["message"] for e in result["errors"])
        assert _count(db_session) == 1  # only the pre-existing student

    def test_hod_cannot_import_other_department(
        self, client: TestClient, hod: User, cse, ece, cse_a1
    ) -> None:
        response = client.post(
            f"{STUDENTS}/bulk",
            json={"rows": [self._row(1, department_code="ECE", section=None)]},
            headers=auth_headers(hod),
        )
        assert response.json()["valid"] is False

    def test_department_change_rejected(
        self, client: TestClient, admin: User, cse, ece, make_student
    ) -> None:
        make_student(cse, register_number="RA2511003000001")
        response = client.post(
            f"{STUDENTS}/bulk",
            json={"rows": [self._row(1, department_code="ECE", section=None)]},
            headers=auth_headers(admin),
        )
        assert response.json()["errors"][0]["field"] == "department_code"

    def test_section_move_via_bulk_records_history(
        self, client: TestClient, admin: User, cse, org: OrgFactory, make_student
    ) -> None:
        a1, b1 = org.section(cse, name="A1"), org.section(cse, name="B1")
        student = make_student(cse, a1, register_number="RA2511003000001")
        client.post(
            f"{STUDENTS}/bulk",
            json={"rows": [self._row(1, section="B1")]},
            headers=auth_headers(admin),
        )
        history = client.get(
            f"{STUDENTS}/{student.id}/sections", headers=auth_headers(admin)
        ).json()
        assert [h["section"]["id"] for h in history] == [str(a1.id), str(b1.id)]


class TestFileImport:
    def test_csv_with_flexible_headers(
        self, client: TestClient, admin: User, cse, cse_a1, db_session: Session
    ) -> None:
        csv = (
            "Reg No,Student Name,Dept,Batch,Sec,Remarks\n"
            "RA2511003000001,Asha,CSE,2025,A1,x\n"
            ",,,,,\n"
            "RA2511003000002,Vikram,CSE,2025,A1,\n"
        )
        response = client.post(
            f"{STUDENTS}/import",
            files={"file": ("students.csv", csv.encode(), "text/csv")},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200, response.text
        assert response.json()["created"] == 2 and _count(db_session) == 2

    def test_xlsx_errors_use_spreadsheet_row_numbers(
        self, client: TestClient, admin: User, cse, cse_a1
    ) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Register Number", "Name", "Department", "Batch Year"])
        sheet.append(["RA2511003000001", "Asha", "CSE", 2025])
        sheet.append(["RA2511003000002", "Vikram", "MECH", 2025])
        buffer = io.BytesIO()
        workbook.save(buffer)
        response = client.post(
            f"{STUDENTS}/import",
            files={"file": ("students.xlsx", buffer.getvalue())},
            data={"dry_run": "true"},
            headers=auth_headers(admin),
        )
        errors = response.json()["errors"]
        assert [(e["row"], e["field"], e["value"]) for e in errors] == [
            (3, "department_code", "MECH")
        ]

    def test_missing_and_ambiguous_columns(self, client: TestClient, admin: User, cse) -> None:
        csv = "Reg No,Register Number,Dept,Batch\nRA2511003000001,RA2511003000001,CSE,2025\n"
        response = client.post(
            f"{STUDENTS}/import",
            files={"file": ("s.csv", csv.encode())},
            headers=auth_headers(admin),
        )
        messages = {e["field"]: e["message"] for e in response.json()["errors"]}
        assert "Ambiguous" in messages["register_number"]
        assert "Missing required column" in messages["full_name"]

    def test_unsupported_file(self, client: TestClient, admin: User) -> None:
        response = client.post(
            f"{STUDENTS}/import",
            files={"file": ("s.pdf", b"%PDF-1.4")},
            headers=auth_headers(admin),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unsupported_file"

    def test_faculty_cannot_import(self, client: TestClient, faculty: User) -> None:
        response = client.post(
            f"{STUDENTS}/import",
            files={"file": ("s.csv", b"a\n1\n")},
            headers=auth_headers(faculty),
        )
        assert response.status_code == 403
