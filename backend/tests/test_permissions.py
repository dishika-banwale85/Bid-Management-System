import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import RequestStep, RequestStatus, StepStatus
from app.services.access_service import can_view_request
from app.services.workflow_service import get_allowed_actions, submit


def test_draft_actions_are_for_creator_only_and_admin_is_read_only(db, bg_request):
    team = db["users"]["BID_TEAM"]
    assert set(get_allowed_actions(bg_request, team)) == {"EDIT", "UPLOAD", "SUBMIT"}
    assert get_allowed_actions(bg_request, db["users"]["ADMIN"]) == []
    assert get_allowed_actions(bg_request, db["users"]["APPROVER"]) == []


def test_only_assigned_approver_can_approve_and_creator_cannot(db, bg_request):
    s = db["db"]
    submit(s, bg_request, db["users"]["BID_TEAM"])
    s.commit()
    assert set(get_allowed_actions(bg_request, db["users"]["APPROVER"])) == {"APPROVE", "REJECT"}
    assert get_allowed_actions(bg_request, db["users"]["FINANCE"]) == []
    assert get_allowed_actions(bg_request, db["users"]["ADMIN"]) == []


def test_visibility_follows_creator_assignment_or_prior_action(db, bg_request):
    s = db["db"]
    team = db["users"]["BID_TEAM"]
    submit(s, bg_request, team)
    s.commit()
    assert can_view_request(bg_request, team)
    assert can_view_request(bg_request, db["users"]["APPROVER"])
    assert not can_view_request(bg_request, db["users"]["FINANCE"])
    assert can_view_request(bg_request, db["users"]["ADMIN"])


def test_api_admin_is_read_only_and_wrong_role_cannot_approve(db, bg_request):
    s = db["db"]
    submit(s, bg_request, db["users"]["BID_TEAM"])
    s.commit()
    active = s.scalar(select(RequestStep).where(
        RequestStep.request_id == bg_request.id,
        RequestStep.attempt == 1,
        RequestStep.status == StepStatus.ACTIVE,
    ))

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            admin_headers = {"Authorization": f"Bearer {create_token(db['users']['ADMIN'])}"}
            finance_headers = {"Authorization": f"Bearer {create_token(db['users']['FINANCE'])}"}
            approver_headers = {"Authorization": f"Bearer {create_token(db['users']['APPROVER'])}"}

            detail = client.get(f"/requests/{bg_request.id}", headers=admin_headers)
            assert detail.status_code == 200
            assert detail.json()["allowed_actions"] == []
            assert client.put(f"/requests/{bg_request.id}", json={"form_data": {}}, headers=admin_headers).status_code == 403
            upload = client.post(
                f"/requests/{bg_request.id}/documents",
                data={"document_type": "rfp"},
                files={"file": ("rfp.pdf", b"test", "application/pdf")},
                headers=admin_headers,
            )
            assert upload.status_code == 403
            assert client.post(
                f"/requests/{bg_request.id}/steps/{active.id}/approve", json={}, headers=admin_headers
            ).status_code == 403
            assert client.post(
                f"/requests/{bg_request.id}/steps/{active.id}/approve", json={}, headers=finance_headers
            ).status_code == 403
            assert client.post(
                f"/requests/{bg_request.id}/steps/{active.id}/approve", json={}, headers=approver_headers
            ).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_creator_cannot_submit_request_for_another_users_bid(db):
    from app.models import ComplianceRequest
    from app.services.workflow_service import require_action

    request = ComplianceRequest(
        bid_id=db["bid"].id,
        type="EMD_BG",
        status=RequestStatus.DRAFT,
        created_by=db["users"]["APPROVER"].id,
        form_data={},
    )
    db["db"].add(request)
    db["db"].flush()
    with pytest.raises(HTTPException) as error:
        require_action(request, db["users"]["BID_TEAM"], "SUBMIT")
    assert error.value.status_code == 403
