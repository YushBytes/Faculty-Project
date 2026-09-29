"""End-to-end scaffolding: one faculty member, one offering, driven entirely over HTTP.

These tests exercise the assembled system — real PostgreSQL, real Alembic-built schema, real
auth, the real C4 recompute hook — so the only way in is the API. A :class:`Journey` wraps the
calls a faculty member actually makes, which keeps each scenario a readable sequence of steps
rather than thirty lines of ``client.post`` noise.

Two details every scenario depends on:

*Everyone gets a mark.* A student with no result has 0% completion and fires R6, so a sheet
always carries a value for the whole cohort. A scenario that wants R6 leaves someone out on
purpose and says so.

*The token is real.* ``Journey.login`` goes through ``POST /auth/login`` rather than minting a
token in-process, because "authenticated faculty" is part of what is under test.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.modules.assessments.models import Assessment
from app.modules.organization.models import CourseOffering, Department, Section
from app.modules.students.models import Student
from app.modules.users.models import User
from tests.conftest import DEFAULT_PASSWORD, AssessmentFactory, StudentFactory

MAX_MARKS = "50"
COHORT_SIZE = 8


def xlsx(rows: list[list[Any]]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def csv_bytes(rows: list[list[Any]]) -> bytes:
    return "\n".join(
        ",".join("" if cell is None else str(cell) for cell in row) for row in rows
    ).encode()


class Journey:
    """The faculty member's path through the system, one method per real action."""

    def __init__(self, client: TestClient, actor: User, offering: CourseOffering) -> None:
        self._client = client
        self.actor = actor
        self.offering = offering
        self.students: list[Student] = []
        self._headers: dict[str, str] = {}

    # ---------------------------------------------------------------- auth

    def login(self) -> str:
        """Authenticate for real and keep the access token for every later call."""
        response = self._client.post(
            "/api/v1/auth/login",
            json={"email": self.actor.email, "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        self._headers = {"Authorization": f"Bearer {token}"}
        return token

    @property
    def headers(self) -> dict[str, str]:
        assert self._headers, "call login() first: these scenarios authenticate for real"
        return self._headers

    # ---------------------------------------------------------------- import

    def sheet(self, assessment: Assessment, scores: dict[uuid.UUID, Any]) -> list[list[Any]]:
        """A wide sheet for one assessment, one row per student in cohort order."""
        rows: list[list[Any]] = [["Register No", "Name", assessment.name]]
        for student in self.students:
            if student.id in scores:
                rows.append([student.register_number, student.full_name, scores[student.id]])
        return rows

    def upload(self, rows: list[list[Any]], *, name: str = "marks.xlsx") -> Any:
        content = xlsx(rows) if name.endswith((".xlsx", ".xlsm")) else csv_bytes(rows)
        return self.upload_raw(content, name=name)

    def upload_raw(self, content: bytes, *, name: str = "marks.xlsx") -> Any:
        return self._client.post(
            f"/api/v1/offerings/{self.offering.id}/imports",
            files={"file": (name, content)},
            headers=self.headers,
        )

    def preview(self, batch_id: str, **params: Any) -> Any:
        return self._client.get(
            f"/api/v1/imports/{batch_id}/preview", params=params, headers=self.headers
        )

    def confirm(self, batch_id: str) -> Any:
        return self._client.post(f"/api/v1/imports/{batch_id}/confirm", headers=self.headers)

    def import_marks(self, assessment: Assessment, scores: dict[uuid.UUID, Any]) -> str:
        """Stage, preview and confirm one assessment's marks. Asserts each step succeeded."""
        staged = self.upload(self.sheet(assessment, scores))
        assert staged.status_code == 201, staged.text
        batch_id = staged.json()["batch"]["id"]

        previewed = self.preview(batch_id)
        assert previewed.status_code == 200, previewed.text

        confirmed = self.confirm(batch_id)
        assert confirmed.status_code == 200, confirmed.text
        return batch_id

    # ---------------------------------------------------------------- analytics

    def analytics(self) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/analytics", headers=self.headers
        )

    def attention(self) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/attention", headers=self.headers
        )

    def student_analytics(self, student_id: uuid.UUID) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/students/{student_id}/analytics",
            headers=self.headers,
        )

    def insights(self) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/insights", headers=self.headers
        )

    def flags_for(self, student_id: uuid.UUID) -> list[dict[str, Any]]:
        """The live flags the API reports for one student, from the engine."""
        response = self.attention()
        assert response.status_code == 200, response.text
        for entry in response.json()["students"]:
            if entry["student"]["id"] == str(student_id):
                return entry["flags"]
        return []

    # ---------------------------------------------------------------- interventions

    def create_intervention(self, payload: dict[str, Any]) -> Any:
        return self._client.post(
            f"/api/v1/offerings/{self.offering.id}/interventions",
            json=payload,
            headers=self.headers,
        )

    def interventions(self, **params: Any) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/interventions",
            params=params,
            headers=self.headers,
        )

    def outcomes(self) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/interventions/outcomes", headers=self.headers
        )

    # ---------------------------------------------------------------- reports

    def report(self, kind: str, *, export_format: str = "csv", **params: Any) -> Any:
        return self._client.get(
            f"/api/v1/offerings/{self.offering.id}/reports/{kind}",
            params={"format": export_format, **params},
            headers=self.headers,
        )


@pytest.fixture
def journey(
    client: TestClient,
    db_session: Session,
    cse_offering: CourseOffering,
    cse: Department,
    faculty: User,
    make_student: StudentFactory,
) -> Journey:
    """A logged-in faculty member with a real cohort on their own offering."""
    section = db_session.get(Section, cse_offering.section_id)
    assert section is not None
    trip = Journey(client, faculty, cse_offering)
    trip.students = [
        make_student(cse, section, enroll_in=[cse_offering]) for _ in range(COHORT_SIZE)
    ]
    trip.login()
    return trip


@pytest.fixture
def ct1(cse_offering: CourseOffering, make_assessment: AssessmentFactory) -> Assessment:
    return make_assessment(cse_offering, "CT1", max_marks=MAX_MARKS)


def next_assessment(
    make_assessment: AssessmentFactory, offering: CourseOffering, name: str
) -> Assessment:
    """A later published assessment. Created only when a scenario reaches it, so the cohort is
    never sitting on an assessment nobody has marks for."""
    return make_assessment(offering, name, max_marks=MAX_MARKS)
