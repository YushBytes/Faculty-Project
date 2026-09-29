"""File upload security for the marks import, over HTTP.

`tests/test_tabular.py` proves the parser's rules in isolation and `tests/test_imports_api.py`
proves the pipeline's happy paths. What is asserted here is the security property that spans them:
**a file the system should not accept produces zero unintended database writes.** Every rejection
test therefore counts result rows, batch rows and attention flags before and after.

Nothing here weakens a validation rule. Where the existing design deliberately *stages* a bad file
so a human can see the errors and fix them, that is asserted as the behaviour — staging a batch is
not a write to academic data, and `confirm` is what these tests check stays shut.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import Assessment, AssessmentResult
from app.modules.attention.models import AttentionFlag
from app.modules.imports.models import ImportBatch
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import User
from tests.conftest import AssessmentFactory, StudentFactory, auth_headers

# A 5 MB ceiling lives in app/core/tabular.py; go decisively past it.
OVERSIZE_BYTES = 6 * 1024 * 1024
MS_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls
ELF_MAGIC = b"\x7fELF\x02\x01\x01\x00"
PE_MAGIC = b"MZ\x90\x00\x03\x00\x00\x00"


def xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class Counts:
    def __init__(self, session: Session) -> None:
        self.results = session.scalar(select(func.count()).select_from(AssessmentResult))
        self.batches = session.scalar(select(func.count()).select_from(ImportBatch))
        self.flags = session.scalar(select(func.count()).select_from(AttentionFlag))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Counts) and (self.results, self.batches, self.flags) == (
            other.results,
            other.batches,
            other.flags,
        )

    def __repr__(self) -> str:
        return f"Counts(results={self.results}, batches={self.batches}, flags={self.flags})"


class Fixture:
    def __init__(
        self, offering: CourseOffering, students: list[Student], ct1: Assessment, actor: User
    ) -> None:
        self.offering = offering
        self.students = students
        self.ct1 = ct1
        self.actor = actor

    @property
    def url(self) -> str:
        return f"/api/v1/offerings/{self.offering.id}/imports"

    def valid_rows(self) -> list[list]:
        rows: list[list] = [["Register No", "Name", "CT1"]]
        for student in self.students:
            rows.append([student.register_number, student.full_name, "40"])
        return rows


@pytest.fixture
def setup(
    db_session: Session,
    cse: Department,
    cse_offering: CourseOffering,
    faculty: User,
    make_student: StudentFactory,
    make_assessment: AssessmentFactory,
) -> Fixture:
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    students = [make_student(cse, section, enroll_in=[cse_offering]) for _ in range(3)]
    return Fixture(
        cse_offering, students, make_assessment(cse_offering, "CT1", max_marks="50"), faculty
    )


def upload(client: TestClient, setup: Fixture, content: bytes, name: str = "marks.xlsx"):
    return client.post(
        setup.url, files={"file": (name, content)}, headers=auth_headers(setup.actor)
    )


class TestAcceptedFiles:
    def test_a_valid_xlsx_is_accepted(self, client: TestClient, setup: Fixture) -> None:
        response = upload(client, setup, xlsx(setup.valid_rows()))
        assert response.status_code == 201, response.text
        assert response.json()["summary"]["will_create"] == len(setup.students)

    def test_a_valid_csv_is_accepted(self, client: TestClient, setup: Fixture) -> None:
        body = "\n".join(",".join(str(c) for c in row) for row in setup.valid_rows()).encode()
        response = upload(client, setup, body, "marks.csv")
        assert response.status_code == 201, response.text
        assert response.json()["summary"]["will_create"] == len(setup.students)


class TestRejectedFilesWriteNothing:
    @pytest.mark.parametrize(
        "label,name,content",
        [
            ("corrupt pdf", "marks.pdf", b"%PDF-1.7\n trailing junk"),
            ("executable renamed to xlsx", "marks.xlsx", ELF_MAGIC + b"\x00" * 64),
            ("windows executable", "marks.csv", PE_MAGIC + b"\x00" * 64),
            ("legacy xls", "marks.xls", MS_OLE_MAGIC + b"\x00" * 64),
            ("zip that is not a workbook", "marks.xlsx", None),  # built in the test
            ("malformed workbook", "marks.xlsx", b"PK\x03\x04 truncated nonsense"),
            ("not utf-8 csv", "marks.csv", b"Register No,CT1\n\xff\xfe\x00bad,40\n"),
            ("html masquerading", "marks.html", b"<html><body>marks</body></html>"),
            ("empty file", "marks.csv", b""),
        ],
    )
    def test_a_file_the_system_should_refuse_changes_nothing(
        self,
        client: TestClient,
        db_session: Session,
        setup: Fixture,
        label: str,
        name: str,
        content: bytes | None,
    ) -> None:
        if content is None:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("not-a-workbook.txt", "hello")
            content = buffer.getvalue()

        before = Counts(db_session)
        response = upload(client, setup, content, name)
        assert response.status_code == 422, f"{label}: {response.status_code} {response.text[:200]}"
        assert "error" in response.json()
        assert Counts(db_session) == before, f"{label} wrote to the database"

    def test_an_oversized_upload_is_refused(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        before = Counts(db_session)
        padding = b"x" * OVERSIZE_BYTES
        response = upload(client, setup, b"Register No,CT1\nRA1,40\n" + padding, "marks.csv")
        assert response.status_code == 422, response.text
        assert Counts(db_session) == before

    def test_too_many_rows_is_refused(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        """The 5000-row ceiling, reached with a narrow file so the payload stays under 5 MB."""
        before = Counts(db_session)
        lines = ["Register No,CT1"] + [f"RA{i:013d},40" for i in range(5001)]
        response = upload(client, setup, "\n".join(lines).encode(), "marks.csv")
        assert response.status_code == 422, response.text
        assert Counts(db_session) == before

    def test_too_many_columns_is_refused(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        before = Counts(db_session)
        header = ",".join(["Register No"] + [f"C{i}" for i in range(250)])
        response = upload(client, setup, f"{header}\nRA1,{'40,' * 249}40\n".encode(), "marks.csv")
        assert response.status_code == 422, response.text
        assert Counts(db_session) == before


class TestStructurallyInvalidSheets:
    @pytest.mark.parametrize(
        "label,rows",
        [
            ("no register-number column", [["Name", "CT1"], ["Asha", "40"]]),
            ("duplicate headers", [["Register No", "CT1", "CT1"], ["RA1", "40", "41"]]),
            ("header only", [["Register No", "CT1"]]),
            ("blank header cell", [["Register No", ""], ["RA1", "40"]]),
        ],
    )
    def test_a_sheet_that_cannot_be_read_is_refused_without_writing(
        self, client: TestClient, db_session: Session, setup: Fixture, label: str, rows: list[list]
    ) -> None:
        before = Counts(db_session)
        response = upload(client, setup, xlsx(rows))
        assert response.status_code == 422, f"{label}: {response.status_code}"
        assert Counts(db_session) == before, f"{label} wrote to the database"


class TestRowLevelProblemsStageButCannotConfirm:
    """Row-level problems are *shown*, not silently dropped — and confirm stays shut."""

    @pytest.mark.parametrize(
        "label,row",
        [
            ("unknown student", ["RA9999999999999", "Ghost", "40"]),
            ("non-numeric score", [None, None, "forty"]),
            ("score above maximum", [None, None, "500"]),
            ("negative score", [None, None, "-1"]),
            ("invalid status word", [None, None, "MAYBE"]),
        ],
    )
    def test_an_error_row_blocks_confirm_and_writes_no_results(
        self, client: TestClient, db_session: Session, setup: Fixture, label: str, row: list
    ) -> None:
        student = setup.students[0]
        filled = [
            row[0] or student.register_number,
            row[1] or student.full_name,
            row[2],
        ]
        staged = upload(client, setup, xlsx([["Register No", "Name", "CT1"], filled]))
        assert staged.status_code == 201, f"{label}: {staged.text[:200]}"
        batch_id = staged.json()["batch"]["id"]
        assert staged.json()["summary"]["errors"] >= 1, f"{label} was not reported as an error"

        refused = client.post(
            f"/api/v1/imports/{batch_id}/confirm", headers=auth_headers(setup.actor)
        )
        assert refused.status_code == 422, f"{label} was confirmable: {refused.text[:200]}"
        assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == 0

    def test_a_duplicate_student_row_is_an_error(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        student = setup.students[0]
        rows = [
            ["Register No", "Name", "CT1"],
            [student.register_number, student.full_name, "40"],
            [student.register_number, student.full_name, "41"],
        ]
        staged = upload(client, setup, xlsx(rows))
        assert staged.status_code == 201, staged.text
        assert staged.json()["summary"]["errors"] >= 1
        refused = client.post(
            f"/api/v1/imports/{staged.json()['batch']['id']}/confirm",
            headers=auth_headers(setup.actor),
        )
        assert refused.status_code == 422
        assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == 0

    def test_an_unknown_assessment_column_is_not_guessed(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        student = setup.students[0]
        rows = [
            ["Register No", "Name", "Midterm Viva"],
            [student.register_number, student.full_name, "40"],
        ]
        staged = upload(client, setup, xlsx(rows))
        assert staged.status_code in (201, 422), staged.text
        if staged.status_code == 201:
            assert staged.json()["summary"]["errors"] >= 1, (
                "an unmatched column must not be guessed"
            )
            refused = client.post(
                f"/api/v1/imports/{staged.json()['batch']['id']}/confirm",
                headers=auth_headers(setup.actor),
            )
            assert refused.status_code == 422
        assert db_session.scalar(select(func.count()).select_from(AssessmentResult)) == 0

    def test_a_blank_cell_becomes_absent_and_never_zero(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        rows: list[list] = [["Register No", "Name", "CT1"]]
        for index, student in enumerate(setup.students):
            rows.append([student.register_number, student.full_name, "" if index == 0 else "40"])
        staged = upload(client, setup, xlsx(rows))
        assert staged.status_code == 201, staged.text
        confirmed = client.post(
            f"/api/v1/imports/{staged.json()['batch']['id']}/confirm",
            headers=auth_headers(setup.actor),
        )
        assert confirmed.status_code == 200, confirmed.text

        blank = db_session.execute(
            select(AssessmentResult.score, AssessmentResult.status).where(
                AssessmentResult.student_id == setup.students[0].id
            )
        ).one()
        assert blank.score is None, "a blank cell must never be stored as 0"
        assert blank.status.value == "absent"


class TestUploadAuthorisation:
    def test_a_stranger_cannot_upload_to_another_offering(
        self, client: TestClient, db_session: Session, setup: Fixture, make_user
    ) -> None:
        from app.modules.users.models import Role

        stranger = make_user(Role.FACULTY, email="upload.stranger@srmist.edu.in")
        before = Counts(db_session)
        response = client.post(
            setup.url,
            files={"file": ("marks.xlsx", xlsx(setup.valid_rows()))},
            headers=auth_headers(stranger),
        )
        assert response.status_code == 404, response.text
        assert Counts(db_session) == before

    def test_an_anonymous_upload_is_rejected(
        self, client: TestClient, db_session: Session, setup: Fixture
    ) -> None:
        before = Counts(db_session)
        response = client.post(setup.url, files={"file": ("marks.xlsx", xlsx(setup.valid_rows()))})
        assert response.status_code == 401
        assert Counts(db_session) == before
