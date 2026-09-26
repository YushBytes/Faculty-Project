"""Department settings (analytics threshold storage)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.users.models import User
from tests.conftest import auth_headers


def _url(department, key: str = "") -> str:
    base = f"/api/v1/departments/{department.id}/settings"
    return f"{base}/{key}" if key else base


def test_hod_manages_own_department(
    client: TestClient, hod: User, cse, db_session: Session
) -> None:
    headers = auth_headers(hod)
    created = client.put(_url(cse, "TREND_DELTA"), json={"value": 5}, headers=headers)
    assert created.status_code == 200 and created.json()["value"] == 5
    updated = client.put(_url(cse, "TREND_DELTA"), json={"value": {"pp": 4.5}}, headers=headers)
    assert updated.json()["value"] == {"pp": 4.5}
    listed = client.get(_url(cse), headers=headers).json()
    assert [(s["key"], s["value"]) for s in listed] == [("TREND_DELTA", {"pp": 4.5})]

    assert client.delete(_url(cse, "TREND_DELTA"), headers=headers).status_code == 204
    assert client.delete(_url(cse, "TREND_DELTA"), headers=headers).status_code == 404
    actions = [
        log.action
        for log in db_session.scalars(
            select(AuditLog).where(AuditLog.entity == "setting").order_by(AuditLog.created_at)
        )
    ]
    assert sorted(actions) == ["create", "delete", "update"]


def test_write_permissions(client: TestClient, hod: User, faculty: User, admin: User, ece) -> None:
    body = {"value": 1}
    assert client.put(_url(ece, "K"), json=body, headers=auth_headers(hod)).status_code == 403
    assert client.put(_url(ece, "K"), json=body, headers=auth_headers(faculty)).status_code == 403
    assert client.put(_url(ece, "K"), json=body, headers=auth_headers(admin)).status_code == 200
    # Anyone signed in may read.
    assert client.get(_url(ece), headers=auth_headers(faculty)).status_code == 200


def test_key_format(client: TestClient, admin: User, cse) -> None:
    response = client.put(_url(cse, "bad key!"), json={"value": 1}, headers=auth_headers(admin))
    assert response.status_code == 422


def test_unknown_department(client: TestClient, admin: User) -> None:
    import uuid

    response = client.get(
        f"/api/v1/departments/{uuid.uuid4()}/settings", headers=auth_headers(admin)
    )
    assert response.status_code == 404
