import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://bidease:bidease@db:5432/bidease")
JWT_SECRET = os.getenv("JWT_SECRET", "local-only-change-this-secret")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(ROOT / "backend" / "private_uploads"))).resolve()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
FERNET_KEY = os.getenv("FERNET_KEY") or os.getenv("DATA_ENCRYPTION_KEY", "")
SMTP_HOST = os.getenv("SMTP_HOST", "mailhog")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@bidease.local")
SMTP_TLS = os.getenv("SMTP_TLS", "false").lower() == "true"
MAIL_MODE = os.getenv("MAIL_MODE", "simulate").strip().lower()
SIGNUP_REQUIRE_ADMIN_APPROVAL = os.getenv("SIGNUP_REQUIRE_ADMIN_APPROVAL", "false").strip().lower() in {"1", "true", "yes", "on"}
CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
CAPTCHA_PROVIDER = os.getenv("CAPTCHA_PROVIDER", "local").strip().lower()
if CAPTCHA_PROVIDER not in {"local", "turnstile", "recaptcha"}:
    raise ValueError("CAPTCHA_PROVIDER must be local, turnstile, or recaptcha")
CAPTCHA_SITE_KEY = os.getenv("CAPTCHA_SITE_KEY", "")
CAPTCHA_SECRET_KEY = os.getenv("CAPTCHA_SECRET_KEY", "")
CAPTCHA_TTL_SECONDS = int(os.getenv("CAPTCHA_TTL_SECONDS", "180"))
