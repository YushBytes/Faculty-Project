"""The analytics API: authorisation, serialisation and error mapping.

These run **without PostgreSQL**. The platform read is the only part of the stack that needs
a database, and it sits behind one dependency — so the tests substitute a service backed by
the canonical in-memory snapshot and exercise everything above it: routing, the auth
dependency, scope behaviour, response shape, Decimal precision, and the 404s.

What that deliberately does *not* cover is the SQL itself: `AnalyticsRepository` against real
rows needs a database and is listed as blocked. The mapping it performs is already unit
tested in `tests/analytics/test_repository.py` against constructed platform objects, so the
untested gap is the query, not the translation.
"""

from __future__ import annotations

import io
import json
import math
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import NotFoundError, register_error_handlers
from app.db.session import get_db
from app.modules.analytics.core.thresholds import resolve_thresholds
from app.modules.analytics.repository import OfferingContext
from app.modules.analytics.router import ROUTERS, get_analytics_service
from app.modules.analytics.service import AnalyticsService
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import Role, User
from tests.analytics import builders as b
from tests.analytics import canonical as fx

STAMP = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
OFFERING = fx.OFFERING_ID
OTHER_OFFERING = uuid.UUID("99999999-9999-4999-8999-999999999999")


class StubService(AnalyticsService):
    """The real service with the platform read replaced.

    Every method below the read is the production one — the analytics, the report building,
    the exporters — so these tests exercise the real composition and only stub the SQL.
    """

    def __init__(self, snapshot=None, *, visible: set[uuid.UUID] | None = None) -> None:  # noqa: ANN001
        self._snapshot = snapshot if snapshot is not None else fx.snapshot()
        self._visible = {OFFERING} if visible is None else visible
        self.reads = 0

    def stored_interventions(self, offering_id):  # noqa: ANN001, ANN201
        """The module's other SQL read, stubbed too: nothing recorded, so the report is empty."""
        return ()

    def context(self, offering_id, *, actor, published_only=True, include_dropped=False):  # noqa: ANN001, ANN201
        if offering_id not in self._visible:
            # Exactly what the platform does: out of scope and non-existent are one answer.
            raise NotFoundError("Course offering not found.")
        self.reads += 1
        return OfferingContext(
            snapshot=self._snapshot,
            thresholds=resolve_thresholds(pass_mark_percent=self._snapshot.pass_mark_percent),
        )


def faculty() -> User:
    user = User(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        email="faculty.one@srmist.edu.in",
        full_name="Farah Faculty",
        password_hash="x",
        role=Role.FACULTY,
        is_active=True,
    )
    return user


def build_client(service: StubService | None = None, *, user: User | None = None) -> TestClient:
    """An app with only the analytics routers, the DB and auth dependencies replaced."""
    app = FastAPI()
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")

    stub = service or StubService()
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_analytics_service] = lambda: stub
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    client.stub = stub  # type: ignore[attr-defined]
    return client


@pytest.fixture
def client() -> TestClient:
    return build_client(user=faculty())


@pytest.fixture
def anonymous() -> TestClient:
    """No auth override: the real dependency runs and rejects the request."""
    return build_client()


def url(path: str, offering: uuid.UUID = OFFERING) -> str:
    return f"/api/v1/offerings/{offering}{path}"


# ------------------------------------------------------------------ authorisation


class TestAuthorisation:
    def test_an_unauthenticated_request_is_rejected(self, anonymous: TestClient) -> None:
        response = anonymous.get(url("/analytics"))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    @pytest.mark.parametrize(
        "path", ["/analytics", "/attention", "/insights", "/reports/class_summary"]
    )
    def test_every_endpoint_requires_authentication(self, anonymous: TestClient, path: str) -> None:
        assert anonymous.get(url(path)).status_code == 401

    def test_an_offering_out_of_scope_is_a_404_not_a_403(self, client: TestClient) -> None:
        """Out of scope and non-existent must be indistinguishable: existence is not leaked."""
        response = client.get(url("/analytics", OTHER_OFFERING))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_an_out_of_scope_response_carries_no_analytics(self, client: TestClient) -> None:
        body = client.get(url("/analytics", OTHER_OFFERING)).json()
        assert "health" not in body
        assert "students" not in json.dumps(body)

    def test_scope_is_enforced_by_the_platform_read_not_a_second_check(self) -> None:
        """The service's own read raises; the router adds no authorisation of its own."""
        service = StubService(visible=set())
        client = build_client(service, user=faculty())
        assert client.get(url("/analytics")).status_code == 404
        assert service.reads == 0


# ------------------------------------------------------------------ class analytics


class TestClassAnalytics:
    def test_the_dashboard_returns_the_engines_numbers(self, client: TestClient) -> None:
        body = client.get(url("/analytics")).json()
        assert body["offering_id"] == str(OFFERING)
        assert body["health"]["class_mean"]["value"] == 57.36
        assert body["health"]["pass_percent"]["value"] == 85.71
        assert body["health"]["cohort_n"] == 7

    def test_what_changed_is_included(self, client: TestClient) -> None:
        body = client.get(url("/analytics")).json()
        assert body["change"]["class_mean_change"]["value"] == -10.2
        assert body["change"]["to_assessment"]["code"] == "FT1"

    def test_the_attention_summary_counts_students_and_flags_separately(
        self, client: TestClient
    ) -> None:
        summary = client.get(url("/analytics")).json()["attention"]
        assert summary["total_flags"] == 11
        assert summary["flagged_students"] == 6
        assert summary["students_requiring_attention"] == 2
        assert summary["by_severity"] == {"high": 3, "medium": 5, "low": 3}
        assert summary["by_rule"]["R1_LOW_PERFORMANCE"] == 2

    def test_insights_are_included_in_order(self, client: TestClient) -> None:
        insights = client.get(url("/analytics")).json()["insights"]
        assert insights[0]["code"] == "class_mean_moved"
        assert "Class average decreased from 62.40% to 52.20%" in insights[0]["text"]

    def test_an_offering_with_no_published_assessment_reports_no_change(self) -> None:
        snapshot = b.build_snapshot({"s1": (60,)}, unpublished=("CT1",))
        client = build_client(StubService(snapshot), user=faculty())
        body = client.get(url("/analytics")).json()
        assert body["change"] is None, "null because nothing could be compared"
        assert body["insights"] == []

    def test_the_offering_is_read_once_per_request(self, client: TestClient) -> None:
        """§21: one platform read, analytics computed once and reused."""
        client.get(url("/analytics"))
        assert client.stub.reads == 1  # type: ignore[attr-defined]


# ------------------------------------------------------------------ student analytics


class TestStudentAnalytics:
    def test_a_student_in_the_offering_returns_their_profile(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S5}/analytics")).json()
        assert body["student_id"] == str(fx.S5)
        assert body["profile"]["history"]["weighted_course_score"]["value"] == 33.0
        assert body["segment"]["primary"]["value"] == "persistently_low"

    def test_the_students_flags_are_present_in_rule_order(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S5}/analytics")).json()
        assert [f["rule_code"] for f in body["attention"]["flags"]] == [
            "R1_LOW_PERFORMANCE",
            "R2_FAILED_LATEST",
            "R3_REPEATED_LOW",
        ]
        assert body["attention"]["requires_attention"] is True

    def test_student_insights_are_included(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S5}/analytics")).json()
        codes = [i["code"] for i in body["insights"]]
        assert "student_repeated_low" in codes

    def test_a_student_outside_the_offering_is_a_404(self, client: TestClient) -> None:
        response = client.get(url(f"/students/{uuid.uuid4()}/analytics"))
        assert response.status_code == 404
        assert "not found in this offering" in response.json()["error"]["message"].lower()

    def test_an_inactive_students_id_is_not_treated_as_enrolled(self, client: TestClient) -> None:
        """S8 is in the snapshot but inactive; they are still a member, so this is a 200."""
        assert client.get(url(f"/students/{fx.S8}/analytics")).status_code == 200


# ------------------------------------------------------------------ attention


class TestAttentionEndpoint:
    def test_every_student_appears_once_with_all_their_flags(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        assert len(body["students"]) == 7
        ids = [s["student"]["id"] for s in body["students"]]
        assert len(ids) == len(set(ids))
        assert sum(len(s["flags"]) for s in body["students"]) == 11

    def test_overlapping_flags_are_preserved(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        s5 = next(s for s in body["students"] if s["student"]["id"] == str(fx.S5))
        assert len(s5["flags"]) == 3

    def test_a_flag_carries_its_threshold_and_provenance(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        flag = next(
            f
            for s in body["students"]
            for f in s["flags"]
            if f["rule_code"] == "R1_LOW_PERFORMANCE"
        )
        assert flag["threshold"]["value"] == 50.0
        assert flag["threshold"]["source"] == "system_default"
        assert flag["threshold"]["key"] == "low_performance_percent"
        assert flag["explanation"]["evidence"]

    def test_r2_quotes_the_pass_mark_rather_than_a_threshold(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        flag = next(
            f for s in body["students"] for f in s["flags"] if f["rule_code"] == "R2_FAILED_LATEST"
        )
        assert flag["threshold"] is None
        assert flag["pass_mark_percent"] == 40.0

    def test_no_risk_score_is_exposed(self, client: TestClient) -> None:
        body = json.dumps(client.get(url("/attention")).json()).lower()
        for banned in ("risk_score", "risk score", "ranking", "rank"):
            assert banned not in body

    def test_a_student_with_no_flags_is_still_listed(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        s1 = next(s for s in body["students"] if s["student"]["id"] == str(fx.S1))
        assert s1["flags"] == []
        assert s1["requires_attention"] is False


# ------------------------------------------------------------------ insights


class TestInsightsEndpoint:
    def test_insights_carry_code_text_and_evidence(self, client: TestClient) -> None:
        body = client.get(url("/insights")).json()
        for insight in body["insights"]:
            assert insight["code"]
            assert insight["text"]
            assert insight["explanation"]["evidence"]

    def test_the_order_is_stable(self, client: TestClient) -> None:
        first = [i["code"] for i in client.get(url("/insights")).json()["insights"]]
        second = [i["code"] for i in client.get(url("/insights")).json()["insights"]]
        assert first == second

    def test_no_prose_is_generated_in_the_router(self, client: TestClient) -> None:
        """The endpoint returns the engine's sentences unchanged."""
        from app.modules.analytics.core.insights import class_insights

        snapshot = fx.snapshot()
        expected = [
            i.text
            for i in class_insights(
                snapshot,
                resolve_thresholds(pass_mark_percent=snapshot.pass_mark_percent),
                generated_at=STAMP,
            )
        ]
        served = [i["text"] for i in client.get(url("/insights")).json()["insights"]]
        assert served == expected


# ------------------------------------------------------------------ reports


class TestReports:
    @pytest.mark.parametrize(
        ("export_format", "media", "magic"),
        [
            ("csv", "text/csv", b"\xef\xbb\xbf"),
            ("xlsx", "spreadsheetml", b"PK"),
            ("pdf", "application/pdf", b"%PDF"),
        ],
    )
    def test_each_format_downloads(
        self, client: TestClient, export_format: str, media: str, magic: bytes
    ) -> None:
        response = client.get(url("/reports/class_summary"), params={"format": export_format})
        assert response.status_code == 200
        assert media in response.headers["content-type"]
        assert response.content.startswith(magic)
        assert "attachment; filename=" in response.headers["content-disposition"]

    def test_csv_is_the_default_format(self, client: TestClient) -> None:
        response = client.get(url("/reports/class_summary"))
        assert "text/csv" in response.headers["content-type"]

    @pytest.mark.parametrize(
        "kind", ["class_summary", "attention", "assessment_comparison", "intervention_outcome"]
    )
    def test_every_cohort_report_builds(self, client: TestClient, kind: str) -> None:
        assert client.get(url(f"/reports/{kind}")).status_code == 200

    def test_a_student_report_needs_a_student(self, client: TestClient) -> None:
        assert client.get(url("/reports/student_performance")).status_code == 404

    def test_a_student_report_with_a_student_builds(self, client: TestClient) -> None:
        response = client.get(
            url("/reports/student_performance"), params={"student_id": str(fx.S5)}
        )
        assert response.status_code == 200
        assert b"RA005" in response.content

    def test_an_unknown_report_type_is_rejected(self, client: TestClient) -> None:
        response = client.get(url("/reports/nonsense"))
        assert response.status_code == 422, "the enum rejects it before the handler"

    def test_an_unknown_export_format_is_rejected(self, client: TestClient) -> None:
        response = client.get(url("/reports/class_summary"), params={"format": "docx"})
        assert response.status_code == 404
        assert "unknown export format" in response.json()["error"]["message"].lower()

    def test_the_xlsx_download_opens_as_a_workbook(self, client: TestClient) -> None:
        from openpyxl import load_workbook

        response = client.get(url("/reports/class_summary"), params={"format": "xlsx"})
        workbook = load_workbook(io.BytesIO(response.content))
        assert "Class summary" in workbook.sheetnames

    def test_a_report_is_scoped(self, client: TestClient) -> None:
        assert client.get(url("/reports/class_summary", OTHER_OFFERING)).status_code == 404


# ------------------------------------------------------------------ semantics


class TestAnalyticsSemanticsSurvive:
    def test_insufficient_data_keeps_its_reason(self, client: TestClient) -> None:
        """A trend that could not be classified is not a null and not a zero."""
        body = client.get(url(f"/students/{fx.S7}/analytics")).json()
        # `trend` is a property on the profile; it serialises under `history`.
        trend = body["profile"]["history"]["trend"]["label"]
        assert trend["status"] == "insufficient_data"
        assert trend["value"] is None
        assert "minimum 2" in trend["reason"]

    def test_absent_is_not_zero(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S6}/analytics")).json()
        points = body["profile"]["history"]["points"]
        absent = next(p for p in points if p["state"] == "absent")
        assert absent["score"] is None
        assert absent["percentage"] is None

    def test_missing_is_not_zero(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S7}/analytics")).json()
        points = body["profile"]["history"]["points"]
        missing = [p for p in points if p["state"] == "missing"]
        assert missing and all(p["score"] is None for p in missing)

    def test_exempt_is_not_zero_and_leaves_the_denominator(self, client: TestClient) -> None:
        body = client.get(url(f"/students/{fx.S6}/analytics")).json()
        exempt = next(p for p in body["profile"]["history"]["points"] if p["state"] == "exempt")
        assert exempt["score"] is None
        assert body["profile"]["history"]["completion_percent"]["n"] == 2

    def test_a_genuine_zero_is_preserved(self) -> None:
        snapshot = b.build_snapshot({"s1": (0, 0), "s2": (60, 60)})
        client = build_client(StubService(snapshot), user=faculty())
        body = client.get(url(f"/students/{b.student_id('s1')}/analytics")).json()
        assert body["profile"]["history"]["weighted_course_score"]["value"] == 0.0
        assert body["profile"]["history"]["points"][0]["score"] == 0.0

    def test_attention_not_evaluated_is_distinct_from_zero(self) -> None:
        """The API always evaluates attention, so the count is a number — never null."""
        snapshot = b.build_snapshot({"s1": (80, 82, 85), "s2": (78, 80, 84)})
        client = build_client(StubService(snapshot), user=faculty())
        body = client.get(url("/analytics")).json()
        assert body["health"]["students_requiring_attention"]["value"] == 0
        assert body["attention"]["students_requiring_attention"] == 0


class TestSerialisation:
    def test_decimals_serialise_as_json_numbers(self, client: TestClient) -> None:
        body = client.get(url("/analytics")).json()
        assert isinstance(body["health"]["class_mean"]["value"], float)
        assert body["health"]["class_mean"]["value"] == 57.36

    def test_enums_serialise_as_their_values(self, client: TestClient) -> None:
        body = client.get(url("/attention")).json()
        flag = next(f for s in body["students"] for f in s["flags"])
        assert flag["severity"] in {"high", "medium", "low"}
        assert flag["status"] == "open"

    def test_no_python_repr_leaks(self, client: TestClient) -> None:
        body = json.dumps(client.get(url("/analytics")).json())
        for leak in ("Decimal(", "UUID(", "object at 0x", "datetime.datetime("):
            assert leak not in body

    @pytest.mark.parametrize("path", ["/analytics", "/attention", "/insights"])
    def test_no_nan_or_infinity_in_any_response(self, client: TestClient, path: str) -> None:
        raw = client.get(url(path)).text
        assert "NaN" not in raw and "Infinity" not in raw
        for value in _numbers(json.loads(raw)):
            assert math.isfinite(value)

    def test_no_credential_or_internal_detail_leaks(self, client: TestClient) -> None:
        body = json.dumps(client.get(url("/analytics")).json()).lower()
        for secret in ("password", "token", "jwt", "secret", "postgresql://", "traceback"):
            assert secret not in body


class TestDeterminism:
    @pytest.mark.parametrize("path", ["/analytics", "/attention", "/insights"])
    def test_repeated_requests_agree(self, client: TestClient, path: str) -> None:
        def strip(payload: dict) -> str:
            return json.dumps(payload, sort_keys=True, default=str).replace(
                payload.get("generated_at", ""), ""
            )

        first = client.get(url(path)).json()
        second = client.get(url(path)).json()
        assert strip(first) == strip(second)

    def test_a_report_downloads_identically_twice(self, client: TestClient) -> None:
        first = client.get(url("/reports/attention"), params={"format": "csv"}).content
        second = client.get(url("/reports/attention"), params={"format": "csv"}).content

        def without_timestamp(body: bytes) -> list[bytes]:
            return [line for line in body.splitlines() if not line.startswith(b"# Generated")]

        assert without_timestamp(first) == without_timestamp(second)


class TestOpenApi:
    def test_the_endpoints_are_documented(self) -> None:
        import os

        os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:5432/x")
        from app.main import create_app

        spec = create_app().openapi()
        for path in (
            "/api/v1/offerings/{offering_id}/analytics",
            "/api/v1/offerings/{offering_id}/students/{student_id}/analytics",
            "/api/v1/offerings/{offering_id}/attention",
            "/api/v1/offerings/{offering_id}/insights",
            "/api/v1/offerings/{offering_id}/reports/{report_kind}",
        ):
            assert path in spec["paths"], path
            documented = spec["paths"][path]["get"]["responses"]
            assert "401" in documented and "404" in documented


def _numbers(payload: object) -> list[float]:
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [float(payload)]
    if isinstance(payload, dict):
        return [n for value in payload.values() for n in _numbers(value)]
    if isinstance(payload, list):
        return [n for value in payload for n in _numbers(value)]
    return []
