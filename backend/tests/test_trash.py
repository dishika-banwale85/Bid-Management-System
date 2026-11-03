from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import requests as requests_api
from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import AuditLog, Bid, BidChecklistNA, ComplianceRequest, Document, RequestStatus
from app.services import trash_service


def _client(db):
    session=db["db"]
    def override_db():
        yield session
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def _headers(user):
    return {"Authorization":f"Bearer {create_token(user)}"}


def _draft(db, status=RequestStatus.DRAFT):
    request=ComplianceRequest(bid_id=db["bid"].id,type="TENDER_FEE",status=status,created_by=db["users"]["BID_TEAM"].id,form_data={})
    db["db"].add(request);db["db"].flush()
    return request


def test_creator_deletes_draft_and_removes_files_and_na_marks(db,tmp_path,monkeypatch):
    client=_client(db);request=_draft(db)
    filename="draft-checklist.pdf";(tmp_path/filename).write_bytes(b"file")
    db["db"].add(Document(request_id=request.id,category="checklist",document_type="checklist",filename=filename,stored_name=filename,content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id))
    db["db"].add(BidChecklistNA(bid_id=db["bid"].id,request_type="TENDER_FEE",marked_by=db["users"]["BID_TEAM"].id));db["db"].commit()
    monkeypatch.setattr(requests_api,"UPLOAD_DIR",tmp_path)
    try:
        response=client.delete(f"/requests/{request.id}",headers=_headers(db["users"]["BID_TEAM"]))
        assert response.status_code==204
        assert not (tmp_path/filename).exists()
        assert db["db"].get(ComplianceRequest,request.id) is None
        assert db["db"].get(BidChecklistNA,(db["bid"].id,"TENDER_FEE")) is None
        audit=db["db"].scalar(select(AuditLog).where(AuditLog.action=="DRAFT_DELETED"))
        assert audit and audit.request_id is None and audit.detail["bid_id"]==db["bid"].id
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_submitted_request_delete_conflicts_and_other_user_is_forbidden(db):
    request=_draft(db,RequestStatus.SUBMITTED);client=_client(db)
    try:
        path=f"/requests/{request.id}"
        assert client.delete(path,headers=_headers(db["users"]["BID_TEAM"])).status_code==409
        assert client.delete(path,headers=_headers(db["users"]["ADMIN"])).status_code==403
        assert client.delete(path,headers=_headers(db["users"]["APPROVER"])).status_code==403
        assert client.delete(path,headers=_headers(db["users"]["PACE_COORDINATOR"])).status_code==403
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_creator_moves_bid_with_drafts_to_trash_and_restore_works(db):
    session=db["db"];request=_draft(db);session.commit();client=_client(db)
    try:
        bid_id=db["bid"].id;headers=_headers(db["users"]["BID_TEAM"])
        response=client.delete(f"/bids/{bid_id}",headers=headers)
        assert response.status_code==200
        assert client.get("/bids",headers=headers).json()==[]
        assert client.get(f"/bids/{bid_id}/checklist",headers=headers).status_code==404
        assert client.get(f"/bids/{bid_id}",headers=headers).json()["detail"]["message"]=="This bid was deleted"
        assert client.get("/bids/check-rfp",params={"rfp_number":"RFP-42"},headers=headers).json()["exists"] is False
        dashboard=client.get("/dashboard",headers=headers).json()
        assert dashboard["kpis"]["bids"]["value"]==0
        assert all(item.get("id")!=bid_id for item in dashboard["recent_bids"])
        assert client.get("/requests",params={"mine":"true","status":"DRAFT"},headers=headers).json()["total"]==0
        assert client.get("/bids/trash",headers=headers).json()["items"][0]["draft_request_count"]==1
        assert session.get(ComplianceRequest,request.id) is not None
        assert session.scalar(select(AuditLog).where(AuditLog.action=="BID_MOVED_TO_TRASH")) is not None
        restored=client.post(f"/bids/{bid_id}/restore",headers=headers)
        assert restored.status_code==200 and len(client.get("/bids",headers=headers).json())==1
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_submitted_bid_blocked_for_creator_but_admin_can_delete_with_reason(db):
    session=db["db"];_draft(db,RequestStatus.SUBMITTED);session.commit();client=_client(db);bid_id=db["bid"].id
    try:
        member=_headers(db["users"]["BID_TEAM"]);admin=_headers(db["users"]["ADMIN"])
        blocked=client.delete(f"/bids/{bid_id}",headers=member)
        assert blocked.status_code==409 and blocked.json()["detail"]["submitted_request_count"]==1
        assert client.delete(f"/bids/{bid_id}",headers=admin,json={"reason":"Duplicate tender record"}).status_code==200
        assert client.post(f"/bids/{bid_id}/restore",headers=admin).status_code==200
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_restore_duplicate_rfp_and_admin_permanent_only_from_trash(db):
    client=_client(db);bid_id=db["bid"].id;admin=_headers(db["users"]["ADMIN"])
    try:
        assert client.delete(f"/bids/{bid_id}/permanent",headers=admin).status_code==409
        assert client.delete(f"/bids/{bid_id}",headers=_headers(db["users"]["BID_TEAM"])).status_code==200
        other=Bid(client_name="Other",department="D",rfp_reference="RFP-42",created_by=db["users"]["BID_TEAM"].id)
        db["db"].add(other);db["db"].commit()
        assert client.post(f"/bids/{bid_id}/restore",headers=admin).status_code==409
        assert client.delete(f"/bids/{bid_id}/permanent",headers=_headers(db["users"]["APPROVER"])).status_code==403
        assert client.delete(f"/bids/{bid_id}/permanent",headers=admin).status_code==204
        assert db["db"].get(Bid,bid_id) is None
        assert db["db"].scalar(select(AuditLog).where(AuditLog.action=="BID_PERMANENTLY_DELETED")) is not None
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_permanent_delete_removes_draft_files_and_keeps_prior_audit(db,tmp_path,monkeypatch):
    client=_client(db);bid=db["bid"];request=_draft(db);filename="permanent-draft.pdf";(tmp_path/filename).write_bytes(b"draft")
    db["db"].add(Document(request_id=request.id,category="checklist",document_type="checklist",filename=filename,stored_name=filename,content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id))
    bid.deleted_at=datetime.now(timezone.utc);bid.deleted_by=db["users"]["BID_TEAM"].id;bid.delete_reason="Cleanup";db["db"].add(AuditLog(user_id=db["users"]["BID_TEAM"].id,action="BID_MOVED_TO_TRASH",entity_type="Bid",entity_id=bid.id,detail={"rfp_reference":bid.rfp_reference}));db["db"].commit()
    monkeypatch.setattr(trash_service,"UPLOAD_DIR",tmp_path)
    try:
        result=client.delete(f"/bids/{bid.id}/permanent",headers=_headers(db["users"]["ADMIN"]))
        assert result.status_code==204 and not (tmp_path/filename).exists()
        assert db["db"].get(Bid,bid.id) is None and db["db"].get(ComplianceRequest,request.id) is None
        actions=set(db["db"].scalars(select(AuditLog.action)).all())
        assert {"BID_MOVED_TO_TRASH","BID_PERMANENTLY_DELETED"}.issubset(actions)
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_approver_and_pace_cannot_access_bid_delete_restore_or_trash(db):
    bid_id=db["bid"].id;client=_client(db)
    try:
        for role in ("APPROVER","PACE_COORDINATOR"):
            headers=_headers(db["users"][role])
            assert client.delete(f"/bids/{bid_id}",headers=headers).status_code==403
            assert client.post(f"/bids/{bid_id}/restore",headers=headers).status_code==403
            assert client.get("/bids/trash",headers=headers).status_code==403
            assert client.delete(f"/bids/{bid_id}/permanent",headers=headers).status_code==403
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_old_trash_emptying_is_admin_only(db):
    client=_client(db);bid=db["bid"];bid.deleted_at=datetime.now(timezone.utc)-timedelta(days=31);bid.deleted_by=db["users"]["BID_TEAM"].id;bid.delete_reason="Old record";db["db"].commit()
    try:
        assert client.post("/admin/trash/empty",headers=_headers(db["users"]["BID_TEAM"])).status_code==403
        result=client.post("/admin/trash/empty",headers=_headers(db["users"]["ADMIN"]))
        assert result.status_code==200 and result.json()["deleted_count"]==1
        assert db["db"].get(Bid,bid.id) is None
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)
