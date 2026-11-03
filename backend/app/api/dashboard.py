from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.bids import _checklist_rollups
from app.core.security import current_user, require_role
from app.db import get_db
from app.models import (
    AuditLog, Bid, ComplianceRequest, RequestStatus, RequestStep, StepKind,
    StepStatus, User, WorkflowTemplate,
)
from app.services.access_service import active_bid_clause, bid_visibility_clause, request_visibility_clause

router = APIRouter(tags=["dashboard"])
TERMINAL_BID_STATUSES = {"COMPLETED", "CLOSED"}
STATUS_LABELS = {"IN_PROGRESS": "Ongoing", "COMPLETED": "Completed", "CLOSED": "Closed"}
TYPE_LABELS = {
    "TENDER_FEE": "Tender Fee", "EMD_CHALLAN": "EMD by Challan",
    "EMD_BG": "EMD by Bank Guarantee", "FINANCIAL_DOCUMENTS": "Financial Documents",
    "POWER_OF_ATTORNEY": "Power of Attorney", "DECLARATION": "Declaration / Undertaking",
    "HR_DOCUMENTS": "HR Documents",
    "OMS_PACE_REDFLAG": "OMS / PACE / Red flag",
}


def _date_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _created_date(value):
    return value.date() if isinstance(value, datetime) else value


def _effective_bid_status(bid, requests):
    status = str(bid.status or "IN_PROGRESS").upper()
    if status in TERMINAL_BID_STATUSES:
        return "COMPLETED"
    submitted_requests = [req for req in requests if req.status != RequestStatus.DRAFT]
    if submitted_requests and all(req.status == RequestStatus.COMPLETED for req in submitted_requests):
        return "COMPLETED"
    return "IN_PROGRESS" if status not in TERMINAL_BID_STATUSES else status


def _tab_bid_match(tab, bid_status):
    if tab == "completed":
        return bid_status == "COMPLETED"
    if tab in {"ongoing", "not_completed"}:
        return bid_status != "COMPLETED"
    return True


def _tab_request_match(tab, request):
    if tab == "completed":
        return request.status == RequestStatus.COMPLETED
    if tab == "ongoing":
        return request.status != RequestStatus.COMPLETED and str(request.bid.status).upper() not in TERMINAL_BID_STATUSES
    if tab == "not_completed":
        return request.status != RequestStatus.COMPLETED
    return True


def _period_count(records, start, end, date_getter):
    return sum(1 for row in records if (d := date_getter(row)) is not None and start <= d <= end)


def _kpi(value, previous, sparkline):
    return {"value": value, "previous_period_value": previous, "sparkline": sparkline[-12:]}


@router.get("/dashboard")
def dashboard(
    status: str | None = None,
    request_type: str | None = None,
    bid_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    client: str | None = None,
    tab: str = "all",
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    tab = tab.lower() if tab.lower() in {"ongoing", "completed", "not_completed", "all"} else "all"
    client = (client or "").strip()
    search = (search or "").strip()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    end = date_to or today
    start = date_from or (end - timedelta(days=29))
    if start > end:
        start, end = end, start
    span = (end - start) + timedelta(days=1)
    previous_start, previous_end = start - span, start - timedelta(days=1)
    visible_requests = request_visibility_clause(user)

    # Two bulk reads replace the former relationship access inside per-bid loops.
    all_requests = db.scalars(
        select(ComplianceRequest)
        .options(joinedload(ComplianceRequest.bid))
        .join(Bid)
        .where(visible_requests, active_bid_clause())
    ).unique().all()
    all_bids = db.scalars(
        select(Bid).where(bid_visibility_clause(user)).order_by(Bid.submission_deadline)
    ).all()
    requests_by_bid = defaultdict(list)
    for request in all_requests:
        if request.bid:
            requests_by_bid[request.bid_id].append(request)
    requests_by_bid = dict(requests_by_bid)

    client_filter = client.casefold()
    search_filter = search.casefold()
    matching_type_bids = {
        req.bid_id for req in all_requests
        if not request_type or req.type == request_type
    }

    def bid_matches(bid, window_start=None, window_end=None):
        if bid_id and bid.id != bid_id:
            return False
        if client_filter and client_filter not in (bid.client_name or "").casefold():
            return False
        if search_filter and search_filter not in " ".join((bid.client_name or "", bid.rfp_reference or "", bid.project_title or "")).casefold():
            return False
        if request_type and bid.id not in matching_type_bids:
            return False
        if window_start and window_end:
            created = _created_date(bid.created_at)
            if created is None or not window_start <= created <= window_end:
                return False
        effective = _effective_bid_status(bid, requests_by_bid.get(bid.id, []))
        return _tab_bid_match(tab, effective)

    def request_matches(request, window_start=None, window_end=None, apply_legacy_status=False):
        bid = request.bid
        if bid is None or (bid_id and request.bid_id != bid_id):
            return False
        if request_type and request.type != request_type:
            return False
        if client_filter and client_filter not in (bid.client_name or "").casefold():
            return False
        if search_filter and search_filter not in " ".join((bid.client_name or "", bid.rfp_reference or "", bid.project_title or "")).casefold():
            return False
        if window_start and window_end:
            created = _created_date(request.created_at)
            if created is None or not window_start <= created <= window_end:
                return False
        if not _tab_request_match(tab, request):
            return False
        if apply_legacy_status and status and request.status.value != status:
            return False
        return True

    selected_bids = [b for b in all_bids if bid_matches(b, start, end)]
    previous_bids = [b for b in all_bids if bid_matches(b, previous_start, previous_end)]
    selected_requests = [r for r in all_requests if request_matches(r, start, end)]
    previous_requests = [r for r in all_requests if request_matches(r, previous_start, previous_end)]
    table_requests = [r for r in selected_requests if not status or r.status.value == status]
    request_ids = {r.id for r in selected_requests}
    previous_request_ids = {r.id for r in previous_requests}
    selected_bid_ids = [b.id for b in selected_bids]
    previous_bid_ids = {b.id for b in previous_bids}

    # One workflow query serves all roles. Only the relevant workflow step kind counts.
    active_rows = []
    if user.role.name in {"APPROVER", "PACE_COORDINATOR"}:
        desired_kind = StepKind.APPROVAL if user.role.name == "APPROVER" else StepKind.ACTION
        active_rows = db.execute(
            select(RequestStep.request_id, ComplianceRequest.created_by)
            .join(ComplianceRequest, ComplianceRequest.id == RequestStep.request_id)
            .join(RequestStep.workflow_step)
            .where(
                RequestStep.status == StepStatus.ACTIVE,
                ComplianceRequest.status == RequestStatus.IN_APPROVAL,
                ComplianceRequest.created_by != user.id,
                RequestStep.workflow_step.has(assigned_role=user.role.name, step_kind=desired_kind),
            )
        ).all()
    pending_request_ids = {request_id for request_id, _ in active_rows}
    approvals = len(request_ids & pending_request_ids)
    previous_approvals = len(previous_request_ids & pending_request_ids)

    def overdue_sets(requests, bids):
        bid_overdue = [b for b in bids if b.submission_deadline < today and _effective_bid_status(b, requests_by_bid.get(b.id, [])) != "COMPLETED"]
        refunds = []
        for req in requests:
            if req.status == RequestStatus.DRAFT or req.type != "EMD_CHALLAN" or req.refund_received_at:
                continue
            expected = _date_value((req.form_data or {}).get("expected_refund_date"))
            if expected and expected < today:
                refunds.append((req, expected))
        return bid_overdue, refunds

    overdue_bids, overdue_refunds = overdue_sets(selected_requests, selected_bids)
    previous_overdue_bids, previous_overdue_refunds = overdue_sets(previous_requests, previous_bids)
    overdue_value = len(overdue_bids) + len(overdue_refunds)
    previous_overdue_value = len(previous_overdue_bids) + len(previous_overdue_refunds)

    # The checklist helper performs one aggregate query for every visible bid.
    rollups = _checklist_rollups(db, selected_bid_ids, exclude_drafts=True)
    counts_by_status = Counter(_effective_bid_status(b, requests_by_bid.get(b.id, [])) for b in selected_bids)
    requests_by_type = Counter(r.type for r in selected_requests)

    completion_ranges = [("0-25%", 0, 25), ("26-50%", 26, 50), ("51-75%", 51, 75), ("76-100%", 76, 100)]
    completion_buckets = []
    for label, lower, upper in completion_ranges:
        completion_buckets.append({
            "bucket": label,
            "count": sum(1 for bid in selected_bids if lower <= rollups.get(bid.id, {}).get("checklist_percent", 0) <= upper),
        })

    now_month = today.replace(day=1)
    month_starts = []
    for offset in range(-8, 4):
        month_number = now_month.month - 1 + offset
        year = now_month.year + month_number // 12
        month = month_number % 12 + 1
        month_starts.append(date(year, month, 1))
    submissions_by_month = []
    for month in month_starts:
        next_month = date(month.year + (month.month == 12), 1 if month.month == 12 else month.month + 1, 1)
        submission_count = sum(1 for bid in selected_bids if month <= bid.submission_deadline < next_month)
        is_future = month > now_month
        submissions_by_month.append({
            "month": month.strftime("%b %Y"),
            "month_key": month.strftime("%Y-%m"),
            "actual": None if is_future else submission_count,
            "forecast": submission_count if is_future or month == now_month else None,
        })

    upcoming_deadlines = []
    for bid in selected_bids:
        deadline = bid.submission_deadline
        if deadline <= today + timedelta(days=365):
            days = (deadline - today).days
            upcoming_deadlines.append({"bid_id": bid.id, "client_name": bid.client_name, "date": deadline.isoformat(), "label": "Submission deadline", "days_until": days, "severity": "red" if days < 0 else "amber" if days <= 3 else "green"})
    for req in selected_requests:
        form = req.form_data or {}
        for field, label in (("last_emd_submission_date", "EMD submission"), ("expected_refund_date", "Expected refund")):
            due = _date_value(form.get(field))
            if due and due <= today + timedelta(days=365) and (field != "expected_refund_date" or not req.refund_received_at):
                days = (due - today).days
                upcoming_deadlines.append({"bid_id": req.bid_id, "request_id": req.id, "client_name": req.bid.client_name if req.bid else "", "date": due.isoformat(), "label": label, "days_until": days, "severity": "red" if days < 0 else "amber" if days <= 3 else "green"})
    upcoming_deadlines.sort(key=lambda item: (item["date"], item.get("request_id", 0)))
    upcoming_deadlines = upcoming_deadlines[:10]

    needs_attention = []
    for bid in selected_bids:
        rollup = rollups.get(bid.id, {})
        missing = rollup.get("missing_count", 0)
        days = (bid.submission_deadline - today).days
        if days < 0 and _effective_bid_status(bid, requests_by_bid.get(bid.id, [])) != "COMPLETED":
            issue, priority = f"Submission overdue by {abs(days)} days", 0
        elif days <= 7:
            issue, priority = f"Submission in {days} days", 1
        elif missing:
            issue, priority = f"{missing} documents missing", 2
        else:
            continue
        needs_attention.append({"bid_id": bid.id, "client_name": bid.client_name, "rfp_reference": bid.rfp_reference, "issue": issue, "priority": priority, "date": bid.submission_deadline.isoformat()})
    for req, due in overdue_refunds:
        needs_attention.append({"bid_id": req.bid_id, "request_id": req.id, "client_name": req.bid.client_name if req.bid else "", "rfp_reference": req.bid.rfp_reference if req.bid else "", "issue": f"EMD refund overdue by {(today-due).days} days", "priority": 0, "date": due.isoformat()})
    needs_attention.sort(key=lambda item: (item["priority"], item["date"]))
    needs_attention = needs_attention[:8]

    def weekly_sparkline(rows, date_getter):
        result = []
        for weeks_ago in range(11, -1, -1):
            week_end = today - timedelta(days=weeks_ago * 7)
            week_start = week_end - timedelta(days=6)
            result.append(_period_count(rows, week_start, week_end, date_getter))
        return result

    current_spark_bids = [b for b in all_bids if bid_matches(b)]
    current_spark_requests = [r for r in all_requests if request_matches(r)]
    bids_spark = weekly_sparkline(current_spark_bids, lambda row: _created_date(row.created_at))
    requests_spark = weekly_sparkline(current_spark_requests, lambda row: _created_date(row.created_at))
    overdue_spark = [overdue_value for _ in range(12)]
    approvals_spark = [approvals for _ in range(12)]
    kpis = {
        "bids": _kpi(len(selected_bids), len(previous_bids), bids_spark),
        "requests": _kpi(len(selected_requests), len(previous_requests), requests_spark),
        "overdue": _kpi(overdue_value, previous_overdue_value, overdue_spark),
        "approvals": _kpi(approvals, previous_approvals, approvals_spark),
    }

    # Keep the original endpoint fields for existing dashboard consumers.
    statuses = {state.value: sum(req.status == state for req in selected_requests) for state in RequestStatus}
    page_total = len(table_requests)
    paged_requests = sorted(table_requests, key=lambda req: req.created_at, reverse=True)[(page-1)*page_size:page*page_size]
    recent_ids = {req.id for req in selected_requests}
    audit_query = select(AuditLog).where(
        or_(AuditLog.request_id.in_(recent_ids), AuditLog.request_id.is_(None))
        if user.role.name == "ADMIN" and recent_ids
        else AuditLog.request_id.in_(recent_ids) if recent_ids
        else AuditLog.request_id.is_(None) if user.role.name == "ADMIN"
        else AuditLog.id == -1
    )
    activity = db.scalars(audit_query.order_by(AuditLog.created_at.desc()).limit(10)).all()
    templates = db.scalars(select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True))).all()
    required_types = {template.request_type for template in templates}
    legacy_checklist = []
    for bid in selected_bids:
        done = {req.type for req in requests_by_bid.get(bid.id, []) if req.status == RequestStatus.COMPLETED}
        legacy_checklist.append({"id": bid.id, "client_name": bid.client_name, "department": bid.department, "rfp_reference": bid.rfp_reference, "submission_deadline": bid.submission_deadline.isoformat(), "required_items": len(required_types), "completed_items": len(done & required_types), "progress": round(100 * len(done & required_types) / len(required_types)) if required_types else 0})
    refund_items = [{"request_id": req.id, "bid_id": req.bid_id, "client_name": req.bid.client_name if req.bid else "", "date": due.isoformat(), "amount": (req.form_data or {}).get("amount"), "days_overdue": (today-due).days} for req, due in overdue_refunds]
    status_names = {"IN_PROGRESS": "Ongoing", "COMPLETED": "Completed"}
    bids_by_status = [{"status": key, "label": status_names.get(key, key.replace("_", " ").title()), "count": value} for key, value in sorted(counts_by_status.items())]
    requests_by_type_data = [{"request_type": key, "label": TYPE_LABELS.get(key, key.replace("_", " ").title()), "count": value} for key, value in sorted(requests_by_type.items())]
    client_options = sorted({bid.client_name for bid in all_bids if bid.client_name})

    return {
        "counts": {"total_bids": len(selected_bids), "total_requests": len(selected_requests), "requests_by_status": statuses, "pending_approvals_for_me": approvals, "overdue_refunds": len(overdue_refunds), "deadlines_next_7_days": sum(1 for row in upcoming_deadlines if 0 <= row["days_until"] <= 7)},
        "bids": len(selected_bids), "requests": len(selected_requests), "pending_approvals": approvals,
        "upcoming_deadlines": len(upcoming_deadlines), "recent_bids": [{**row, "request_count": sum(req.bid_id == row["id"] for req in selected_requests)} for row in legacy_checklist[:6]],
        "checklist": legacy_checklist,
        "upcoming_deadline_items": upcoming_deadlines,
        "overdue_refund_items": refund_items,
        "recent_activity": [{"id": a.id, "action": a.action, "request_id": a.request_id, "user_id": a.user_id, "created_at": a.created_at.isoformat(), "detail": a.detail} for a in activity],
        "requests": [{"id": req.id, "bid_id": req.bid_id, "client_name": req.bid.client_name if req.bid else "", "type": req.type, "status": req.status.value, "created_at": req.created_at.isoformat()} for req in paged_requests],
        "pagination": {"page": page, "page_size": page_size, "total": page_total, "pages": (page_total+page_size-1)//page_size},
        "filters": {"date_from": start.isoformat(), "date_to": end.isoformat(), "client": client, "request_type": request_type, "tab": tab, "clients": client_options},
        "kpis": kpis,
        "bids_by_status": bids_by_status,
        "requests_by_type": requests_by_type_data,
        "completion_buckets": completion_buckets,
        "submissions_by_month": submissions_by_month,
        "upcoming_deadlines": upcoming_deadlines,
        "needs_attention": needs_attention,
    }


@router.get("/audit")
def audit(db: Session = Depends(get_db), user: User = Depends(require_role("ADMIN")), page: int = 1, page_size: int = 50):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return [{"id": a.id, "user_id": a.user_id, "action": a.action, "request_id": a.request_id, "old_status": a.old_status, "new_status": a.new_status, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in rows]
