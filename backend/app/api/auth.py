from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import CAPTCHA_ENABLED, CAPTCHA_PROVIDER, SIGNUP_REQUIRE_ADMIN_APPROVAL
from app.core.security import create_token, current_user, hash_password, verify_password
from app.db import get_db
from app.models import AuditLog, Role, User
from app.schemas.auth import RegisterIn
from app.schemas.requests import LoginIn
from app.services.captcha_service import captcha_settings, create_local_challenge, verify_captcha

router = APIRouter(prefix="/auth", tags=["auth"])

_rate_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_rate_lock = Lock()
_rate_window_seconds = 60
_failed_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_login_blocked_until: dict[str, float] = {}
_login_lock = Lock()
_login_window_seconds = 15 * 60
_login_failure_limit = 5


def _login_keys(email: str, request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    return f"email:{email.strip().lower()}", f"ip:{ip}"


def _check_login_lockout(email: str, request: Request) -> None:
    now = monotonic()
    with _login_lock:
        blocked = [key for key in _login_keys(email, request) if _login_blocked_until.get(key, 0) > now]
        if blocked:
            remaining = max(1, int(max(_login_blocked_until[key] for key in blocked) - now))
            raise HTTPException(429, detail={"error": "login_locked", "message": "Too many failed sign-in attempts. Please try again in 15 minutes."}, headers={"Retry-After": str(remaining)})


def _record_failed_login(email: str, request: Request) -> None:
    now = monotonic()
    with _login_lock:
        for key in _login_keys(email, request):
            hits = _failed_login_attempts[key]
            while hits and now - hits[0] >= _login_window_seconds:
                hits.popleft()
            hits.append(now)
            if len(hits) >= _login_failure_limit:
                _login_blocked_until[key] = now + _login_window_seconds
                hits.clear()


def _clear_login_failures(email: str, request: Request) -> None:
    with _login_lock:
        for key in _login_keys(email, request):
            _failed_login_attempts.pop(key, None)
            _login_blocked_until.pop(key, None)


def _rate_limit(request: Request, endpoint: str, limit: int) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = (endpoint, client_ip)
    now = monotonic()
    with _rate_lock:
        hits = _rate_hits[key]
        while hits and now - hits[0] >= _rate_window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(_rate_window_seconds - (now - hits[0])))
            raise HTTPException(
                status_code=429,
                detail={"error": "rate_limited", "message": "Too many attempts. Please try again shortly."},
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)


def _session_payload(user: User):
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.full_name, "email": user.email, "role": user.role.name},
    }


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, "login", 10)
    _check_login_lockout(str(data.email), request)
    verify_captcha(db, captcha_id=data.captcha_id, captcha_answer=data.captcha_answer,
                   captcha_token=data.captcha_token,
                   remote_ip=request.client.host if request.client else None)
    user = db.scalar(select(User).where(func.lower(User.email) == str(data.email).lower()))
    if not user or not verify_password(data.password, user.password_hash):
        _record_failed_login(str(data.email), request)
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Email or password is incorrect"})
    if not user.is_active:
        raise HTTPException(403, detail={"error": "account_pending", "message": "Your account is waiting for admin approval"})
    _clear_login_failures(str(data.email), request)
    return _session_payload(user)


@router.post("/register", status_code=201)
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, "register", 20)
    verify_captcha(db, captcha_id=data.captcha_id, captcha_answer=data.captcha_answer,
                   captcha_token=data.captcha_token,
                   remote_ip=request.client.host if request.client else None)
    email = str(data.email).strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, detail={"error": "email_registered", "message": "This email is already registered"})

    role = db.scalar(select(Role).where(Role.name == data.role))
    if not role:
        raise HTTPException(503, detail={"error": "roles_not_seeded", "message": "Account roles are not configured. Run the database seed first."})
    active = not (SIGNUP_REQUIRE_ADMIN_APPROVAL and data.role in {"APPROVER", "PACE_COORDINATOR"})
    user = User(email=email, full_name=data.full_name, password_hash=hash_password(data.password), role=role, is_active=active)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"error": "email_registered", "message": "This email is already registered"})

    db.add(AuditLog(user_id=user.id, action="USER_REGISTERED", entity_type="User", entity_id=user.id, detail={"email": email, "role": data.role}))
    db.commit()
    db.refresh(user)
    if not user.is_active:
        return {"account_created": True, "pending_approval": True, "message": "Your account is waiting for admin approval"}
    return {"account_created": True, **_session_payload(user)}


@router.get("/captcha")
def get_captcha(db: Session = Depends(get_db)):
    settings = captcha_settings()
    if not CAPTCHA_ENABLED or CAPTCHA_PROVIDER != "local":
        return settings
    return {**settings, **create_local_challenge(db)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.full_name, "email": user.email, "role": user.role.name}
