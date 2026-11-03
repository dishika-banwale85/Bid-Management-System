import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import Contact, EmailLog, Notification, RequestStatus


@pytest.mark.parametrize(
    ("email", "expected_status", "expected_message"),
    [
        (None, "NOT_SENT_NO_EMAIL", "No email ID on file for Sambhavya Shanker yet."),
        ("sambhavya@example.test", "SIMULATED", "Mail has been sent to Sambhavya Shanker"),
    ],
)
def test_submit_succeeds_and_returns_mail_notice_with_or_without_email(
    db, bg_request, monkeypatch, email, expected_status, expected_message
):
    from app.services import mail_service

    monkeypatch.setattr(mail_service, "MAIL_MODE", "simulate")
    session = db["db"]
    session.add(Contact(
        request_type="BANK_GUARANTEE",
        contact_type="VETTING",
        name="Sambhavya Shanker",
        email=email,
        is_active=True,
    ))
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        headers = {"Authorization": f"Bearer {create_token(db['users']['BID_TEAM'])}"}
        with TestClient(app) as client:
            response = client.post(f"/requests/{bg_request.id}/submit", headers=headers)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == RequestStatus.IN_APPROVAL.value
        assert payload["mail_notices"] == [{
            "recipient": "Sambhavya Shanker",
            "status": expected_status,
            "message": expected_message if expected_status == "SIMULATED" else expected_message + " The mail will be sent once an email is added.",
        }]
        log = session.scalar(select(EmailLog).where(EmailLog.related_request_id == bg_request.id))
        assert log is not None and log.status == expected_status
        assert session.scalar(select(Notification.id).where(Notification.request_id == bg_request.id)) is not None
    finally:
        app.dependency_overrides.pop(get_db, None)
