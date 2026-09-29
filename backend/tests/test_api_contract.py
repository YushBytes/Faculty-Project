"""The published API contract: what OpenAPI says the backend is.

These assertions are about the *document*, not about behaviour — the behaviour is tested
elsewhere. What matters here is that the document does not drift from the implementation and does
not describe things it should never offer: a way to create an attention flag, an undocumented
internal route, or a schema carrying a password hash.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

WRITE_METHODS = {"post", "put", "patch", "delete"}

# Operations that intentionally take no access token. `login` issues the pair; `refresh` and
# `logout` are addressed by the opaque refresh token in the body, not by the bearer header
# (README, "Authentication and roles"), so requiring one would make logging out impossible once an
# access token had expired. `/health` is an orchestration probe.
PUBLIC_BY_DESIGN = frozenset(
    {
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    }
)

# Fields that exist in the database and must never appear in a published schema.
NEVER_PUBLISHED = {
    "password_hash",
    "token_hash",
    "jwt_secret_key",
    "refresh_token_hash",
    "hashed_password",
}


@pytest.fixture(scope="module")
def spec() -> dict:
    return create_app().openapi()


@pytest.fixture(scope="module")
def paths(spec: dict) -> dict:
    return spec["paths"]


def operations(paths: dict):
    for path, methods in paths.items():
        for method, operation in methods.items():
            if method in WRITE_METHODS or method == "get":
                yield path, method, operation


class TestDocumentIsComplete:
    def test_every_route_the_app_serves_is_documented(self, spec: dict) -> None:
        app = create_app()
        served = {
            (route.path, method.lower())
            for route in app.routes
            for method in getattr(route, "methods", set())
            if method.lower() in WRITE_METHODS | {"get"}
            and getattr(route, "include_in_schema", True)
            and str(route.path).startswith(("/api/", "/health"))
        }
        documented = {(path, method) for path, method, _ in operations(spec["paths"])}
        assert served - documented == set(), f"undocumented routes: {sorted(served - documented)}"

    def test_every_operation_has_a_summary_or_description(self, paths: dict) -> None:
        bare = [
            f"{method.upper()} {path}"
            for path, method, operation in operations(paths)
            if not (operation.get("summary") or operation.get("description"))
        ]
        assert bare == [], f"operations with no documentation: {bare}"

    def test_the_phase_10_intervention_routes_are_published(self, paths: dict) -> None:
        base = "/api/v1/offerings/{offering_id}"
        assert set(paths[f"{base}/interventions"]) >= {"get", "post"}
        assert "get" in paths[f"{base}/interventions/outcomes"]
        assert "get" in paths[f"{base}/students/{{student_id}}/interventions"]

    def test_the_analytics_routes_are_published(self, paths: dict) -> None:
        base = "/api/v1/offerings/{offering_id}"
        for route in ("analytics", "attention", "insights"):
            assert "get" in paths[f"{base}/{route}"], f"{route} is not documented"
        assert "get" in paths[f"{base}/students/{{student_id}}/analytics"]

    def test_the_report_route_documents_all_three_formats(self, paths: dict) -> None:
        operation = paths["/api/v1/offerings/{offering_id}/reports/{report_kind}"]["get"]
        content = operation["responses"]["200"]["content"]
        assert "text/csv" in content
        assert "application/pdf" in content
        assert any("spreadsheetml" in media for media in content), "xlsx is not documented"

        formats = {
            parameter["name"]: parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "query"
        }
        assert "format" in formats
        assert "student_id" in formats


class TestAttentionIsNotWritable:
    def test_no_endpoint_can_create_or_change_an_attention_flag(self, paths: dict) -> None:
        """Flags are materialised state owned by the recompute hook, never client-authored."""
        writable = {
            f"{method.upper()} {path}"
            for path, methods in paths.items()
            if "attention" in path
            for method in methods
            if method in WRITE_METHODS
        }
        assert writable == set(), f"attention must not be writable over HTTP: {sorted(writable)}"

    def test_attention_is_readable_only_through_a_scope(self, paths: dict) -> None:
        """One offering's cohort, or the caller's scoped aggregate (read-only, GET)."""
        attention_paths = {path for path in paths if "attention" in path}
        assert attention_paths == {
            "/api/v1/offerings/{offering_id}/attention",
            "/api/v1/insights/attention",
        }, f"unexpected attention surface: {sorted(attention_paths)}"
        assert set(paths["/api/v1/insights/attention"]) == {"get"}


class TestSecurityIsDocumented:
    def test_protected_operations_declare_authentication(self, spec: dict, paths: dict) -> None:
        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert schemes, (
            "no security scheme is published, so clients cannot tell how to authenticate"
        )

        unprotected = []
        for path, method, operation in operations(paths):
            if path in PUBLIC_BY_DESIGN:
                continue
            if not operation.get("security") and not spec.get("security"):
                unprotected.append(f"{method.upper()} {path}")
        assert unprotected == [], f"operations with no declared security: {unprotected}"

    def test_scoped_operations_document_401_and_404(self, paths: dict) -> None:
        missing = []
        for path, method, operation in operations(paths):
            if "{offering_id}" not in path:
                continue
            for code in ("401", "404"):
                if code not in operation["responses"]:
                    missing.append(f"{method.upper()} {path} lacks {code}")
        assert missing == [], missing

    def test_write_operations_document_422(self, paths: dict) -> None:
        missing = [
            f"{method.upper()} {path}"
            for path, method, operation in operations(paths)
            if method in WRITE_METHODS
            and "{offering_id}" in path
            and "422" not in operation["responses"]
        ]
        assert missing == [], f"writes with no documented validation failure: {missing}"

    def test_the_intervention_create_returns_201(self, paths: dict) -> None:
        operation = paths["/api/v1/offerings/{offering_id}/interventions"]["post"]
        assert "201" in operation["responses"], "a create must document the resource it created"


class TestNoInternalsLeak:
    def test_no_published_schema_exposes_a_secret_field(self, spec: dict) -> None:
        offenders = []
        for name, schema in spec.get("components", {}).get("schemas", {}).items():
            for field in schema.get("properties", {}):
                if field.lower() in NEVER_PUBLISHED:
                    offenders.append(f"{name}.{field}")
        assert offenders == [], f"published schemas expose internals: {offenders}"

    def test_no_debug_or_internal_route_is_published(self, paths: dict) -> None:
        suspicious = [
            path
            for path in paths
            if any(marker in path.lower() for marker in ("/debug", "/internal", "/_", "/test"))
        ]
        assert suspicious == [], f"internal-looking routes are published: {suspicious}"

    def test_the_error_envelope_is_the_documented_failure_shape(self, spec: dict) -> None:
        schemas = spec["components"]["schemas"]
        assert "ErrorResponse" in schemas
        assert "error" in schemas["ErrorResponse"]["properties"]


class TestTheDocumentIsServed:
    def test_openapi_json_is_reachable_and_parses(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        document = response.json()
        assert document["openapi"].startswith("3.")
        assert document["info"]["title"]

    def test_health_is_unversioned_and_public(self, client: TestClient, paths: dict) -> None:
        assert "/health" in paths
        assert client.get("/health").status_code in (200, 503)
