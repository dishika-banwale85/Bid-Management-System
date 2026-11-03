from datetime import datetime, timedelta, timezone

import pytest

from app.api import auth as auth_api
from app.models import CaptchaChallenge
from app.services import captcha_service


def enable_local_captcha(monkeypatch):
    monkeypatch.setattr(auth_api, "CAPTCHA_ENABLED", True)
    monkeypatch.setattr(captcha_service, "CAPTCHA_ENABLED", True)
    monkeypatch.setattr(captcha_service, "CAPTCHA_PROVIDER", "local")
    monkeypatch.setattr(captcha_service.secrets, "choice", lambda _chars: "A")


def get_challenge(client):
    response = client.get("/auth/captcha")
    assert response.status_code == 200
    payload = response.json()
    assert payload["captcha_id"]
    assert payload["image"]
    return payload


def login_payload(challenge, answer="AAAAA", password="Demo123!"):
    return {
        "email": "bid_team@test.local",
        "password": password,
        "captcha_id": challenge["captcha_id"],
        "captcha_answer": answer,
    }


def test_login_without_captcha_is_rejected(client, monkeypatch):
    enable_local_captcha(monkeypatch)
    response = client.post("/auth/login", json={"email": "bid_team@test.local", "password": "Demo123!"})
    assert response.status_code == 400
    assert response.json()["message"] == "Captcha incorrect or expired"


def test_wrong_answer_is_rejected_and_challenge_is_single_use(client, monkeypatch):
    enable_local_captcha(monkeypatch)
    challenge = get_challenge(client)
    wrong = client.post("/auth/login", json=login_payload(challenge, "ZZZZZ"))
    reused = client.post("/auth/login", json=login_payload(challenge, "AAAAA"))
    assert wrong.status_code == reused.status_code == 400


def test_expired_challenge_is_rejected(client, db, monkeypatch):
    enable_local_captcha(monkeypatch)
    challenge = get_challenge(client)
    row = db["db"].get(CaptchaChallenge, challenge["captcha_id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db["db"].commit()
    response = client.post("/auth/login", json=login_payload(challenge))
    assert response.status_code == 400


def test_correct_answer_allows_login_and_registration(client, monkeypatch):
    enable_local_captcha(monkeypatch)
    challenge = get_challenge(client)
    login = client.post("/auth/login", json=login_payload(challenge))
    assert login.status_code == 200
    challenge = get_challenge(client)
    register = client.post("/auth/register", json={
        "full_name": "Captcha User", "email": "captcha-user@example.test",
        "password": "StrongPass123", "confirm_password": "StrongPass123", "role": "BID_TEAM",
        "captcha_id": challenge["captcha_id"], "captcha_answer": "AAAAA",
    })
    assert register.status_code == 201
    assert register.json()["access_token"]


def test_captcha_answer_is_never_returned(client, monkeypatch):
    enable_local_captcha(monkeypatch)
    response = client.get("/auth/captcha")
    assert "AAAAA" not in response.text
    assert "answer" not in response.json()


def test_five_failed_passwords_lock_out_email_and_ip(client, monkeypatch):
    enable_local_captcha(monkeypatch)
    for _ in range(5):
        challenge = get_challenge(client)
        response = client.post("/auth/login", json=login_payload(challenge, password="WrongPass123"))
        assert response.status_code == 401
    challenge = get_challenge(client)
    locked = client.post("/auth/login", json=login_payload(challenge))
    assert locked.status_code == 429
    assert "15 minutes" in locked.json()["message"]


def test_captcha_disabled_preserves_login_without_proof(client, monkeypatch):
    monkeypatch.setattr(auth_api, "CAPTCHA_ENABLED", False)
    monkeypatch.setattr(captcha_service, "CAPTCHA_ENABLED", False)
    response = client.post("/auth/login", json={"email": "bid_team@test.local", "password": "Demo123!"})
    assert response.status_code == 200
