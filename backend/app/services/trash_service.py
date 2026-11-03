from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import case, delete, distinct, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import UPLOAD_DIR
from app.models import AuditLog, Bid, BidChecklistNA, BidDocument, ComplianceRequest, Document, Notification, ReminderSent, RequestStatus


def bid_request_stats(db: Session, bid_ids: list[int]) -> dict[int, dict[str, int]]:
    if not bid_ids:
        return {}
    draft_count = func.count(distinct(case((ComplianceRequest.status == RequestStatus.DRAFT, ComplianceRequest.id))))
    submitted_count = func.count(distinct(case((ComplianceRequest.status != RequestStatus.DRAFT, ComplianceRequest.id))))
    rows = db.execute(
        select(ComplianceRequest.bid_id, draft_count, submitted_count, func.count(Document.id))
        .outerjoin(Document, Document.request_id == ComplianceRequest.id)
        .where(ComplianceRequest.bid_id.in_(bid_ids))
        .group_by(ComplianceRequest.bid_id)
    ).all()
    result={
        bid_id: {"draft_request_count": int(drafts or 0), "submitted_request_count": int(submitted or 0), "file_count": int(files or 0)}
        for bid_id, drafts, submitted, files in rows
    }
    rfp_counts=dict(db.execute(select(BidDocument.bid_id,func.count(BidDocument.id)).where(BidDocument.bid_id.in_(bid_ids)).group_by(BidDocument.bid_id)).all())
    for bid_id in bid_ids:
        result.setdefault(bid_id,{"draft_request_count":0,"submitted_request_count":0,"file_count":0})
        result[bid_id]["file_count"]+=int(rfp_counts.get(bid_id,0))
    return result


def unlink_stored_files(stored_names: list[str]) -> None:
    for stored_name in stored_names:
        name = Path(stored_name).name
        if name != stored_name:
            continue
        try:
            (UPLOAD_DIR / name).unlink(missing_ok=True)
        except OSError:
            # Database deletion must complete even if a stale file cannot be removed.
            continue


def permanently_delete_bid(db: Session, bid_id: int, user_id: int) -> dict[str, int]:
    bid = db.scalar(
        select(Bid)
        .options(selectinload(Bid.requests).selectinload(ComplianceRequest.documents),selectinload(Bid.rfp_document))
        .where(Bid.id == bid_id, Bid.deleted_at.is_not(None))
    )
    if bid is None:
        return {"draft_request_count": 0, "submitted_request_count": 0, "file_count": 0}

    requests = list(bid.requests)
    request_ids = [request.id for request in requests]
    files = [doc.stored_name for request in requests for doc in request.documents]
    if bid.rfp_document:files.append(bid.rfp_document.stored_name)
    stats = bid_request_stats(db, [bid.id]).get(bid.id, {"draft_request_count": 0, "submitted_request_count": 0, "file_count": 0})
    db.add(AuditLog(
        user_id=user_id,
        action="BID_PERMANENTLY_DELETED",
        entity_type="Bid",
        entity_id=bid.id,
        detail={"rfp_reference": bid.rfp_reference, "delete_reason": bid.delete_reason, **stats},
    ))
    if request_ids:
        db.execute(delete(Notification).where(Notification.request_id.in_(request_ids)))
        db.execute(delete(ReminderSent).where(ReminderSent.request_id.in_(request_ids)))
    db.execute(delete(BidChecklistNA).where(BidChecklistNA.bid_id == bid.id))
    for request in requests:
        db.delete(request)
    db.delete(bid)
    db.commit()
    unlink_stored_files(files)
    return stats


def empty_old_trash(db: Session, user_id: int, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    old_ids = db.scalars(
        select(Bid.id).where(Bid.deleted_at.is_not(None), Bid.deleted_at < cutoff).order_by(Bid.deleted_at)
    ).all()
    removed = 0
    for bid_id in old_ids:
        permanently_delete_bid(db, bid_id, user_id)
        removed += 1
    return removed
