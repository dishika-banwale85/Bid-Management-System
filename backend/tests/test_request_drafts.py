import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import AuditLog, ComplianceRequest, RequestStatus, Role, User


@pytest.fixture
def client(db):
    session = db["db"]

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def headers(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def test_create_partial_draft_then_update_same_record(client, db):
    member = db["users"]["BID_TEAM"]
    response = client.post("/requests", headers=headers(member), json={
        "bid_id": db["bid"].id,
        "type": "TENDER_FEE",
    })
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "DRAFT"
    assert created["updated_at"]
    request_id = created["id"]

    saved = client.put(f"/requests/{request_id}", headers=headers(member), json={
        "form_data": {"client_name": "  Demo buyer  ", "account_number": "001234567890"},
    })
    assert saved.status_code == 200
    assert saved.json()["id"] == request_id
    assert saved.json()["form_data"]["client_name"] == "Demo buyer"
    assert saved.json()["form_data"]["account_number"] == "001234567890"
    assert saved.json()["updated_at"]
    logs = db["db"].scalars(select(AuditLog).where(AuditLog.request_id == request_id)).all()
    assert [log.action for log in logs] == ["DRAFT_SAVED", "DRAFT_SAVED"]


def test_incomplete_draft_submit_returns_field_errors(client, db):
    member = db["users"]["BID_TEAM"]
    created = client.post("/requests", headers=headers(member), json={
        "bid_id": db["bid"].id, "type": "EMD_BG", "form_data": {"engagement_code": "BG-1"},
    })
    request_id = created.json()["id"]
    response = client.post(f"/requests/{request_id}/submit", headers=headers(member))
    assert response.status_code == 422
    payload = response.json()
    assert payload["fields"]
    assert any("bg_amount" in error.get("loc", []) for error in payload["fields"])


def test_non_creator_and_admin_cannot_save(client, db):
    member = db["users"]["BID_TEAM"]
    created = client.post("/requests", headers=headers(member), json={
        "bid_id": db["bid"].id, "type": "TENDER_FEE", "form_data": {},
    })
    request_id = created.json()["id"]
    session = db["db"]
    role = session.scalar(select(Role).where(Role.name == "BID_TEAM"))
    another_member = User(email="another-member@test.local", full_name="Another Member", password_hash="x", role=role)
    session.add(another_member)
    session.commit()
    payload = {"form_data": {"mobile": "123"}}
    assert client.put(f"/requests/{request_id}", headers=headers(another_member), json=payload).status_code == 403
    assert client.put(f"/requests/{request_id}", headers=headers(db["users"]["ADMIN"]), json=payload).status_code == 403


def test_submitted_request_cannot_be_saved(client, db, bg_request):
    bg_request.status = RequestStatus.SUBMITTED
    db["db"].commit()
    response = client.put(f"/requests/{bg_request.id}", headers=headers(db["users"]["BID_TEAM"]), json={"form_data": {}})
    assert response.status_code == 409
