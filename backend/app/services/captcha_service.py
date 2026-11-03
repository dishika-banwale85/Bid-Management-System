"""Captcha issuance and verification. Answers are never persisted in plain text."""
import base64
import hashlib
import hmac
import io
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from captcha.image import ImageCaptcha
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import (
    CAPTCHA_ENABLED, CAPTCHA_PROVIDER, CAPTCHA_SECRET_KEY, CAPTCHA_SITE_KEY,
    CAPTCHA_TTL_SECONDS, JWT_SECRET,
)
from app.models import CaptchaChallenge

_CHARACTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I/L


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _answer_hash(answer: str) -> str:
    normalized = answer.strip().upper().encode("utf-8")
    return hmac.new(JWT_SECRET.encode("utf-8"), normalized, hashlib.sha256).hexdigest()


def create_local_challenge(db: Session) -> dict:
    now = _now()
    # Opportunistic cleanup avoids a separate scheduled job for short-lived rows.
    db.execute(delete(CaptchaChallenge).where(CaptchaChallenge.expires_at < now))
    answer = "".join(secrets.choice(_CHARACTERS) for _ in range(5))
    challenge_id = secrets.token_urlsafe(24)
    image = ImageCaptcha(width=190, height=64)
    image_bytes = io.BytesIO()
    image.write(answer, image_bytes)
    db.add(CaptchaChallenge(
        id=challenge_id,
        answer_hash=_answer_hash(answer),
        expires_at=now + timedelta(seconds=CAPTCHA_TTL_SECONDS),
    ))
    db.commit()
    return {"captcha_id": challenge_id, "image": base64.b64encode(image_bytes.getvalue()).decode("ascii")}


def _verify_local(db: Session, captcha_id: str | None, answer: str | None) -> bool:
    if not captcha_id:
        return False
    challenge = db.scalar(select(CaptchaChallenge).where(CaptchaChallenge.id == captcha_id).with_for_update())
    if challenge is None or challenge.used_at is not None:
        return False
    now = _now()
    expires_at = challenge.expires_at
    # SQLite returns naive datetimes even for timezone-aware columns.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    challenge.used_at = now  # wrong answers burn the challenge too
    valid = bool(answer and answer.strip()) and expires_at > now and hmac.compare_digest(challenge.answer_hash, _answer_hash(answer or ""))
    db.commit()
    return valid


def _verify_external(provider: str, token: str | None, remote_ip: str | None) -> bool:
    if not token:
        return False
    if not CAPTCHA_SECRET_KEY:
        raise HTTPException(503, detail={"error": "captcha_unavailable", "message": "CAPTCHA verification is not configured. Please contact support."})
    if provider == "turnstile":
        url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    else:
        url = "https://www.google.com/recaptcha/api/siteverify"
    try:
        response = httpx.post(url, data={"secret": CAPTCHA_SECRET_KEY, "response": token, "remoteip": remote_ip}, timeout=5.0)
        response.raise_for_status()
        result = response.json()
        return result.get("success") is True
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(503, detail={"error": "captcha_unavailable", "message": "CAPTCHA verification is temporarily unavailable. Please try again."})


def verify_captcha(db: Session, *, captcha_id: str | None, captcha_answer: str | None,
                   captcha_token: str | None, remote_ip: str | None) -> None:
    if not CAPTCHA_ENABLED:
        return
    if CAPTCHA_PROVIDER == "local":
        valid = _verify_local(db, captcha_id, captcha_answer)
    else:
        valid = _verify_external(CAPTCHA_PROVIDER, captcha_token, remote_ip)
    if not valid:
        raise HTTPException(400, detail={"error": "captcha_invalid", "message": "Captcha incorrect or expired"})


def captcha_settings() -> dict:
    return {
        "enabled": CAPTCHA_ENABLED,
        "provider": CAPTCHA_PROVIDER,
        "site_key": CAPTCHA_SITE_KEY if CAPTCHA_PROVIDER != "local" else None,
        "ttl_seconds": CAPTCHA_TTL_SECONDS,
    }
