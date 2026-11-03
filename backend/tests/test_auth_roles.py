import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import ComplianceRequest, RequestStatus, RequestStep, Role, StepKind, StepStatus, User, WorkflowStep
from app.services.workflow_service import approve, get_allowed_actions


@pytest.fixture
def client(db):
    session = db["db"]

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def auth(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.mark.parametrize("role", ["BID_TEAM", "APPROVER", "PACE_COORDINATOR"])
def test_registers_supported_roles(client, db, role):
    response = client.post("/auth/register", json={
        "full_name": "  New User  ",
        "email": f"new-{role.lower()}@example.test",
        "password": "StrongPass123",
        "confirm_password": "StrongPass123",
        "role": role,
    })
    assert response.status_code == 201
    assert response.json()["user"]["role"] == role
    assert response.json()["user"]["name"] == "New User"
    assert response.json()["access_token"]


def test_register_rejects_admin_and_weak_password(client):
    base = {"full_name": "Example User", "email": "example@test.local", "password": "Strong123", "confirm_password": "Strong123"}
    assert client.post("/auth/register", json={**base, "role": "ADMIN"}).status_code == 422
    assert client.post("/auth/register", json={**base, "password": "weakpass", "confirm_password": "weakpass", "role": "BID_TEAM"}).status_code == 422


def test_duplicate_signup_has_friendly_conflict(client):
    payload = {"full_name": "Example User", "email": "duplicate@test.local", "password": "Strong123", "confirm_password": "Strong123", "role": "BID_TEAM"}
    assert client.post("/auth/register", json=payload).status_code == 201
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["message"] == "This email is already registered"


def test_approver_can_approve_migrated_finance_step_but_member_cannot(client, db):
    session = db["db"]
    template = db["template"]
    former_finance_step = WorkflowStep(template_id=template.id, version=template.version, step_order=10, name="Finance approval", step_kind=StepKind.APPROVAL, assigned_role="APPROVER", requires_fields=[])
    session.add(former_finance_step)
    session.flush()
    request = ComplianceRequest(bid_id=db["bid"].id, type="EMD_BG", status=RequestStatus.IN_APPROVAL, created_by=db["users"]["BID_TEAM"].id, form_data={})
    session.add(request)
    session.flush()
    step = RequestStep(request_id=request.id, step_id=former_finance_step.id, attempt=1, status=StepStatus.ACTIVE)
    session.add(step)
    session.commit()

    member_response = client.post(f"/requests/{request.id}/steps/{step.id}/approve", headers=auth(db["users"]["BID_TEAM"]), json={})
    assert member_response.status_code == 403
    assert "APPROVE" in get_allowed_actions(request, db["users"]["APPROVER"])
    approver_response = client.post(f"/requests/{request.id}/steps/{step.id}/approve", headers=auth(db["users"]["APPROVER"]), json={})
    assert approver_response.status_code == 200


def test_migration_remaps_legacy_users_and_steps(db):
    session = db["db"]
    finance = session.scalar(select(Role).where(Role.name == "FINANCE"))
    old_user = User(email="legacy-finance@test.local", full_name="Legacy Finance", password_hash="x", role=finance)
    session.add(old_user)
    legacy_step = db["steps"][0]
    legacy_step.assigned_role = "FINANCE"
    request = ComplianceRequest(bid_id=db["bid"].id, type="EMD_BG", status=RequestStatus.IN_APPROVAL, created_by=db["users"]["BID_TEAM"].id, form_data={})
    session.add(request)
    session.flush()
    active = RequestStep(request_id=request.id, step_id=legacy_step.id, attempt=1, status=StepStatus.ACTIVE)
    session.add(active)
    session.commit()

    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "20261101_0007_four_roles.py"
    spec = importlib.util.spec_from_file_location("bidease_role_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()

    session.expire_all()
    old_user = session.scalar(select(User).where(User.email == "legacy-finance@test.local"))
    request = session.get(ComplianceRequest, request.id)
    assert old_user.role.name == "APPROVER"
    assert session.get(WorkflowStep, legacy_step.id).assigned_role == "APPROVER"
    assert "APPROVE" in get_allowed_actions(request, old_user)
    approve(session, request, active.id, old_user)
    session.commit()
    assert session.get(RequestStep, active.id).status == StepStatus.APPROVED
