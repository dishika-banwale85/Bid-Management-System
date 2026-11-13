import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db import get_db
from app.models import AuditLog, Bid, ComplianceRequest, User

router = APIRouter(tags=["history"])

ACTION_LABELS = {
    "BID_CREATED": "Bid created",
    "BID_UPDATED": "Bid updated",
    "BID_STATUS_UPDATED": "Bid status updated",
    "BID_RFP_UPLOADED": "RFP uploaded",
    "BID_RFP_REPLACED": "RFP replaced",
    "BID_RFP_REMOVED": "RFP removed",
    "BID_MOVED_TO_TRASH": "Bid moved to Trash",
    "BID_RESTORED": "Bid restored",
    "BID_PERMANENTLY_DELETED": "Bid permanently deleted",
    "DRAFT_SAVED": "Draft saved",
    "DRAFT_DELETED": "Draft deleted",
    "SUBMITTED": "Request submitted",
    "UPLOADED": "Document uploaded",
    "OMS_PACE_REDFLAG_UPDATED": "OMS / PACE record updated",
    "REMINDER_SENT": "Reminder sent",
    "CONTACT_CREATED": "Contact created",
    "CONTACT_UPDATED": "Contact updated",
    "CONTACT_DEACTIVATED": "Contact deactivated",
    "USER_REGISTERED": "Account registered",
    "USER_CREATED": "User created",
    "USER_UPDATED": "User updated",
}
SENSITIVE_FIELD = re.compile(r"account.?number|ifsc|micr|branch.?code|mobile|email|password|token", re.I)
DROPDOWN_FIELDS = {
    "bid_status", "oms_created", "pace_created", "approval_status", "red_flag_status",
    "mail_sent", "mail_received", "declaration_type", "certificate_type", "payment_mode",
    "mode_of_approval",
}
REQUEST_TYPES = {
    "TENDER_FEE": "Tender Fee", "EMD_CHALLAN": "EMD by Challan", "EMD_BG": "EMD by Bank Guarantee",
    "FINANCIAL_DOCUMENTS": "Financial Documents", "POWER_OF_ATTORNEY": "Power of Attorney",
    "DECLARATION": "Declaration / Undertaking", "HR_DOCUMENTS": "HR Documents",
    "OMS_PACE_REDFLAG": "OMS / PACE / Red flag",
}


def _action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " ").title())


def _summary(row: AuditLog) -> str:
    detail = row.detail if isinstance(row.detail, dict) else {}
    if row.old_status != row.new_status and (row.old_status is not None or row.new_status is not None):
        return f"Status: {row.old_status or '—'} -> {row.new_status or '—'}"

    old_values = detail.get("old_values")
    new_values = detail.get("new_values")
    if isinstance(old_values, dict) and isinstance(new_values, dict):
        changed = [key for key in old_values.keys() | new_values.keys() if old_values.get(key) != new_values.get(key)]
        if len(changed) == 1 and changed[0] in DROPDOWN_FIELDS:
            key = changed[0]
            return f"Status: {old_values.get(key) or '—'} -> {new_values.get(key) or '—'}"
        visible = sorted(key.replace("_", " ") for key in changed if not SENSITIVE_FIELD.search(key))
        return f"Changed fields: {', '.join(visible)}" if visible else ("Sensitive fields updated" if changed else _action_label(row.action))

    changed_fields = detail.get("changed_fields")
    if isinstance(changed_fields, list):
        visible = sorted(str(key).replace("_", " ") for key in changed_fields if not SENSITIVE_FIELD.search(str(key)))
        return f"Changed fields: {', '.join(visible)}" if visible else ("Sensitive fields updated" if changed_fields else _action_label(row.action))

    if row.action == "UPLOADED" and detail.get("category"):
        return f"Document uploaded: {str(detail['category']).replace('_', ' ').title()}"
    if row.action == "DRAFT_DELETED" and detail.get("request_type"):
        return f"{REQUEST_TYPES.get(detail['request_type'], detail['request_type'])} draft deleted"
    return _action_label(row.action)


@router.get("/history")
def get_history(
    page: int = Query(1, ge=1),
    page_size: Literal[25, 50] = 25,
    q: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    bid_id: int | None = None,
    request_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(current_user),
):
    bid_id_expr = case(
        (AuditLog.entity_type == "Bid", AuditLog.entity_id),
        (ComplianceRequest.bid_id.is_not(None), ComplianceRequest.bid_id),
        else_=AuditLog.detail["bid_id"].as_integer(),
    )
    request_type_expr = func.coalesce(
        ComplianceRequest.type,
        AuditLog.detail["request_type"].as_string(),
        AuditLog.detail["type"].as_string(),
    )
    request_id_expr = case(
        (AuditLog.request_id.is_not(None), AuditLog.request_id),
        (AuditLog.entity_type == "ComplianceRequest", AuditLog.entity_id),
        else_=None,
    )
    base = (
        select(AuditLog)
        .select_from(AuditLog)
        .outerjoin(User, User.id == AuditLog.user_id)
        .outerjoin(ComplianceRequest, ComplianceRequest.id == AuditLog.request_id)
        .outerjoin(Bid, Bid.id == bid_id_expr)
    )
    filters = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(
            Bid.client_name.ilike(pattern), Bid.project_title.ilike(pattern), Bid.rfp_reference.ilike(pattern),
            AuditLog.detail["client_name"].as_string().ilike(pattern),
            AuditLog.detail["project_title"].as_string().ilike(pattern),
            AuditLog.detail["rfp_reference"].as_string().ilike(pattern),
        ))
    if actor and actor.strip():
        filters.append(func.lower(func.coalesce(User.full_name, User.email)).like(f"%{actor.strip().lower()}%"))
    if action and action.strip():
        filters.append(AuditLog.action.ilike(f"%{action.strip().replace(' ', '_')}%"))
    if bid_id is not None:
        filters.append(bid_id_expr == bid_id)
    if request_type:
        filters.append(request_type_expr == request_type)
    if date_from:
        filters.append(AuditLog.created_at >= date_from)
    if date_to:
        filters.append(AuditLog.created_at < date_to + timedelta(days=1))

    count_statement = (
        select(func.count(AuditLog.id)).select_from(AuditLog)
        .outerjoin(ComplianceRequest, ComplianceRequest.id == AuditLog.request_id)
        .outerjoin(Bid, Bid.id == bid_id_expr)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*filters)
    )
    total = db.scalar(count_statement) or 0
    rows = db.execute(
        base.with_only_columns(
            AuditLog, User.full_name, User.email, ComplianceRequest.id, request_type_expr,
            Bid.id, Bid.project_title, Bid.client_name, Bid.deleted_at,
        )
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = []
    for log, full_name, email, joined_request_id, type_value, joined_bid_id, project_title, client_name, deleted_at in rows:
        details = log.detail if isinstance(log.detail, dict) else {}
        resolved_bid_id = joined_bid_id or details.get("bid_id")
        resolved_request_id = log.request_id or (log.entity_id if log.entity_type == "ComplianceRequest" else None)
        items.append({
            "id": log.id,
            "at": log.created_at.isoformat() if log.created_at else None,
            "actor": full_name or email or "Unknown user",
            "action": _action_label(log.action),
            "bid_id": resolved_bid_id,
            "bid_title": project_title or client_name or details.get("client_name") or details.get("project_title"),
            "bid_deleted": deleted_at is not None,
            "request_id": resolved_request_id,
            "request_deleted": resolved_request_id is not None and joined_request_id is None,
            "request_type": type_value,
            "summary": _summary(log),
        })
    return {"items": items, "page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size}
