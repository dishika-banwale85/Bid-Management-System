"""Contact-based prototype mail routing.

The default mode records a simulated result and returns UI-ready notices. SMTP
is an explicit opt-in for future use and is never used when MAIL_MODE is unset.
"""
import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import MAIL_MODE
from app.db import SessionLocal
from app.models import Contact, EmailLog

logger = logging.getLogger("bidease.mail")

_REQUEST_TYPE_ALIASES = {
    "TENDER_FEE": ("TENDER_FEE", "FEE"),
    "EMD_CHALLAN": ("EMD_CHALLAN", "EMD"),
    "EMD_BG": ("EMD_BG", "BANK_GUARANTEE"),
}


def _smtp_send(contact: Contact, event: dict, request) -> str:
    """Use the existing SMTP sender in explicit smtp mode; do not bubble errors."""
    try:
        from app.services.email_service import send_logged_email
        return asyncio.run(send_logged_email(
            [contact.email], [],
            f"BidEase: {event.get('title', 'Request update')} · Request #{request.id}",
            event.get("template", "request_event"),
            {
                "title": event.get("title", "Request update"),
                "message": event.get("message", "There is an update to your request."),
                "comment": event.get("comment", ""),
                "request_id": request.id,
                "request_type": request.type,
            }, request.id,
        )) or "SENT"
    except Exception:
        logger.exception("SMTP send failed for request %s", request.id)
        return "FAILED"


def _notify(db: Session, event: dict, request, contact_types: list[str]) -> list[dict[str, str]]:
    """Log and return one notice per active contact matching this request.

    A missing address is a normal prototype state: it creates a NOT_SENT_NO_EMAIL
    log entry, returns an explanatory notice, and never prevents the action.
    """
    try:
        request_types = _REQUEST_TYPE_ALIASES.get(request.type, (request.type,))
        query = select(Contact).where(
            Contact.is_active.is_(True),
            Contact.contact_type.in_(contact_types),
            Contact.request_type.in_(request_types),
        ).order_by(Contact.name, Contact.id)
        contacts = db.scalars(query).all()
    except Exception:
        logger.exception("Could not look up mail contacts for request %s", getattr(request, "id", "?"))
        return []

    notices: list[dict[str, str]] = []
    for contact in contacts:
        if not contact.email:
            status = "NOT_SENT_NO_EMAIL"
            message = f"No email ID on file for {contact.name} yet. The mail will be sent once an email is added."
            log_to = contact.name
        elif MAIL_MODE == "smtp":
            status = _smtp_send(contact, event, request)
            message = f"Mail has been sent to {contact.name}" if status == "SENT" else f"Mail could not be sent to {contact.name}."
            log_to = contact.email
        else:
            status = "SIMULATED"
            message = f"Mail has been sent to {contact.name}"
            log_to = contact.email

        if not (contact.email and MAIL_MODE == "smtp"):
            try:
                db.add(EmailLog(
                    to=log_to,
                    cc="",
                    subject=f"BidEase: {event.get('title', 'Request update')} · Request #{request.id}",
                    template=event.get("template", "request_event"),
                    status=status,
                    error=None,
                    related_request_id=request.id,
                ))
            except Exception:
                # Mail logging is best-effort and must not block a workflow action.
                logger.exception("Could not record mail result for contact %s", contact.id)
        notices.append({"recipient": contact.name, "status": status, "message": message})

    try:
        db.commit()
    except Exception:
        # Workflow changes are committed before notify is called by the router.
        logger.exception("Could not persist mail logs for request %s", request.id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Could not roll back mail-log transaction for request %s", request.id)
    return notices


def notify(event: dict, request, contact_types: list[str], db: Session | None = None) -> list[dict[str, str]]:
    """Public notification API; a request session may be supplied by the router."""
    if db is not None:
        return _notify(db, event, request, contact_types)
    try:
        with SessionLocal() as session:
            return _notify(session, event, request, contact_types)
    except Exception:
        logger.exception("Mail notification failed for request %s", getattr(request, "id", "?"))
        return []
