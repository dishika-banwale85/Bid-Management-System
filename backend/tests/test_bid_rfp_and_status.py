from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import bids as bids_api
from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import AuditLog, Bid, BidDocument, BidStatus
from app.services import trash_service


def _client(db):
    session=db["db"]
    def override_db():
        yield session
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def _headers(user):
    return {"Authorization":f"Bearer {create_token(user)}"}


def _docx_bytes():
    buffer=BytesIO()
    with ZipFile(buffer,"w") as archive:
        archive.writestr("[Content_Types].xml","<Types/>")
        archive.writestr("word/document.xml","<document/>")
    return buffer.getvalue()


def _pdf_bytes():
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def test_existing_bid_defaults_to_not_submitted_and_status_change_is_audited(db):
    client=_client(db);bid_id=db["bid"].id;member=_headers(db["users"]["BID_TEAM"])
    try:
        listed=client.get("/bids",headers=member).json()[0]
        assert listed["bid_status"]=="NOT_SUBMITTED" and listed["rfp"] is None
        response=client.patch(f"/bids/{bid_id}",headers=member,json={"bid_status":"SUBMITTED"})
        assert response.status_code==200 and response.json()["bid_status"]=="SUBMITTED"
        audit=db["db"].scalar(select(AuditLog).where(AuditLog.action=="BID_STATUS_UPDATED"))
        assert audit and audit.old_status=="NOT_SUBMITTED" and audit.new_status=="SUBMITTED"
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_status_update_permissions_and_validation(db):
    client=_client(db);bid_id=db["bid"].id
    try:
        for role in ("APPROVER","PACE_COORDINATOR","ADMIN"):
            assert client.patch(f"/bids/{bid_id}",headers=_headers(db["users"][role]),json={"bid_status":"WIN"}).status_code==403
        invalid=client.patch(f"/bids/{bid_id}",headers=_headers(db["users"]["BID_TEAM"]),json={"bid_status":"PENDING"})
        assert invalid.status_code==422
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_create_bid_accepts_optional_rfp_and_status(db,tmp_path,monkeypatch):
    client=_client(db);monkeypatch.setattr(bids_api,"UPLOAD_DIR",tmp_path)
    payload={"client_name":"New Client","department":"Finance","client_address":"1 Road","rfp_number":"RFP-CREATE-1","project_title":"New work","rfp_published_date":"2026-10-01","submission_deadline":"2026-12-01","tender_opening_date":"2026-12-02","prebid_meeting_date":None,"prebid_query_deadline":None,"prebid_meeting_na":True,"prebid_query_na":True,"bid_status":"WIN"}
    try:
        response=client.post("/bids",headers=_headers(db["users"]["BID_TEAM"]),files={"bid_data":(None,__import__("json").dumps(payload)),"rfp_file":("tender.docx",_docx_bytes(),"application/octet-stream")})
        assert response.status_code==201,response.text
        assert response.json()["bid_status"]=="WIN" and response.json()["rfp"]["filename"]=="tender.docx"
        assert (tmp_path/next(iter(tmp_path.iterdir())).name).exists()
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_rfp_upload_rejects_wrong_extension_spoof_and_oversize(db,tmp_path,monkeypatch):
    client=_client(db);monkeypatch.setattr(bids_api,"UPLOAD_DIR",tmp_path);bid_id=db["bid"].id;headers=_headers(db["users"]["BID_TEAM"])
    try:
        assert client.post(f"/bids/{bid_id}/rfp",headers=headers,files={"file":("notes.txt",b"text","text/plain")}).status_code==422
        assert client.post(f"/bids/{bid_id}/rfp",headers=headers,files={"file":("spoof.pdf",b"not a pdf","application/pdf")}).status_code==422
        assert client.post(f"/bids/{bid_id}/rfp",headers=headers,files={"file":("spoof.doc",bytes.fromhex("D0CF11E0A1B11AE1")+b"not a Word document","application/msword")}).status_code==422
        large=b"%PDF-1.4\n"+b"x"*(10*1024*1024)+b"%%EOF"
        assert client.post(f"/bids/{bid_id}/rfp",headers=headers,files={"file":("large.pdf",large,"application/pdf")}).status_code==422
        assert db["db"].scalar(select(BidDocument.id).where(BidDocument.bid_id==bid_id)) is None
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_rfp_pdf_docx_replace_download_visibility_and_remove(db,tmp_path,monkeypatch):
    client=_client(db);monkeypatch.setattr(bids_api,"UPLOAD_DIR",tmp_path);monkeypatch.setattr(trash_service,"UPLOAD_DIR",tmp_path);bid_id=db["bid"].id
    member=_headers(db["users"]["BID_TEAM"])
    try:
        first=client.post(f"/bids/{bid_id}/rfp",headers=member,files={"file":("first.pdf",_pdf_bytes(),"application/pdf")})
        assert first.status_code==200 and first.json()["filename"]=="first.pdf"
        old=db["db"].scalar(select(BidDocument).where(BidDocument.bid_id==bid_id)).stored_name
        old_path=tmp_path/old;assert old_path.exists()
        second=client.post(f"/bids/{bid_id}/rfp",headers=member,files={"file":("second.docx",_docx_bytes(),"application/octet-stream")})
        assert second.status_code==200 and not old_path.exists()
        for role in ("BID_TEAM","APPROVER","PACE_COORDINATOR","ADMIN"):
            downloaded=client.get(f"/bids/{bid_id}/rfp/download",headers=_headers(db["users"][role]))
            assert downloaded.status_code==200 and downloaded.content==_docx_bytes()
        assert client.get(f"/bids/{bid_id}",headers=member).json()["rfp"]["filename"]=="second.docx"
        for role in ("APPROVER","PACE_COORDINATOR","ADMIN"):
            assert client.delete(f"/bids/{bid_id}/rfp",headers=_headers(db["users"][role])).status_code==403
            assert client.post(f"/bids/{bid_id}/rfp",headers=_headers(db["users"][role]),files={"file":("no.docx",_docx_bytes(),"application/octet-stream")}).status_code==403
        assert client.delete(f"/bids/{bid_id}/rfp",headers=member).status_code==204
        assert client.get(f"/bids/{bid_id}",headers=member).json()["rfp"] is None
        actions=set(db["db"].scalars(select(AuditLog.action).where(AuditLog.entity_id==bid_id)).all())
        assert {"BID_RFP_UPLOADED","BID_RFP_REPLACED","BID_RFP_REMOVED"}.issubset(actions)
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)
