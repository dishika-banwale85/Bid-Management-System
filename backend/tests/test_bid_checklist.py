from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import AuditLog, Bid, BidChecklistNA, ComplianceRequest, Document, RequestStatus, User


def _client(db):
    session=db["db"]
    def override_db():yield session
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def _headers(user):return {"Authorization":f"Bearer {create_token(user)}"}


def _request(db,type="TENDER_FEE",status=RequestStatus.DRAFT):
    item=ComplianceRequest(bid_id=db["bid"].id,type=type,status=status,created_by=db["users"]["BID_TEAM"].id,form_data={})
    db["db"].add(item);db["db"].flush();return item


def _document(db,request,key,filename=None):
    db["db"].add(Document(request_id=request.id,category=key,document_type=key,filename=filename or f"{key}.pdf",stored_name=f"{request.id}-{key}.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id))


def test_empty_bid_checklist_has_all_active_types_not_started_and_zero_percent(db):
    client=_client(db)
    try:
        response=client.get(f"/bids/{db['bid'].id}/checklist",headers=_headers(db["users"]["BID_TEAM"]))
        payload=response.json()
        assert response.status_code==200
        assert payload["required_total"]==12 and payload["attached_total"]==0
        assert payload["missing_total"]==12 and payload["percent"]==0
        assert all(item["state"]=="NOT_STARTED" for item in payload["request_types"])
        assert all(item["requests"]==[] for item in payload["request_types"])
        assert sum(item["required_count"] for item in payload["request_types"])==12
        detail=client.get(f"/bids/{db['bid'].id}",headers=_headers(db["users"]["BID_TEAM"])).json()
        assert detail["checklist_percent"]==0 and detail["missing_count"]==12
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_checklist_percent_math_and_na_exclusion(db):
    client=_client(db);request=_request(db)
    _document(db,request,"generated_challan");_document(db,request,"checklist");db["db"].commit()
    try:
        before=client.get(f"/bids/{db['bid'].id}/checklist",headers=_headers(db["users"]["BID_TEAM"])).json()
        assert before["required_total"]==12 and before["attached_total"]==2 and before["percent"]==17
        na=client.put(f"/bids/{db['bid'].id}/checklist/na",headers=_headers(db["users"]["BID_TEAM"]),json={"request_type":"EMD_BG","applicable":False})
        assert na.status_code==200
        assert na.json()["required_total"]==10 and na.json()["missing_total"]==8 and na.json()["percent"]==20
        assert next(t for t in na.json()["request_types"] if t["request_type"]=="EMD_BG")["state"]=="NOT_APPLICABLE"
        audit=db["db"].scalar(select(AuditLog).where(AuditLog.action=="BID_CHECKLIST_NA_UPDATED"))
        assert audit and audit.detail["applicable"] is False
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_multiple_requests_of_one_type_are_counted_as_separate_groups(db):
    first=_request(db);second=_request(db)
    _document(db,first,"generated_challan");_document(db,second,"checklist");db["db"].commit()
    client=_client(db)
    try:
        payload=client.get(f"/bids/{db['bid'].id}/checklist",headers=_headers(db["users"]["BID_TEAM"])).json()
        fee=next(item for item in payload["request_types"] if item["request_type"]=="TENDER_FEE")
        assert len(fee["requests"])==2
        assert fee["required_count"]==4 and fee["attached_count"]==2
        assert payload["required_total"]==14 and payload["attached_total"]==2
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_only_bid_creator_can_toggle_checklist_na(db):
    client=_client(db)
    other_member=User(email="second-member@test.local",full_name="Second member",password_hash="unused",role=db["users"]["BID_TEAM"].role)
    db["db"].add(other_member);db["db"].commit()
    try:
        path=f"/bids/{db['bid'].id}/checklist/na";body={"request_type":"TENDER_FEE","applicable":False}
        assert client.put(path,headers=_headers(db["users"]["APPROVER"]),json=body).status_code==403
        assert client.put(path,headers=_headers(db["users"]["ADMIN"]),json=body).status_code==403
        assert client.put(path,headers=_headers(other_member),json=body).status_code==403
        assert client.put(path,headers=_headers(db["users"]["BID_TEAM"]),json=body).status_code==200
        assert db["db"].get(BidChecklistNA,(db["bid"].id,"TENDER_FEE")) is not None
    finally:
        client.close();app.dependency_overrides.pop(get_db,None)


def test_bid_list_checklist_queries_are_bulk_not_per_bid(db):
    session=db["db"]
    for index in range(5):
        session.add(Bid(client_name=f"Bulk {index}",department="Team",rfp_reference=f"BULK-{index}",tender_opening_date=date(2027,1,10),submission_deadline=date(2027,1,9),created_by=db["users"]["BID_TEAM"].id))
    session.commit();client=_client(db);statements=[]
    def capture(_conn,_cursor,statement,_parameters,_context,_executemany):
        if statement.lstrip().upper().startswith("SELECT"):statements.append(statement)
    event.listen(session.get_bind(),"before_cursor_execute",capture)
    try:
        result=client.get("/bids",headers=_headers(db["users"]["BID_TEAM"]))
        assert result.status_code==200 and len(result.json())==6
        assert all("checklist_percent" in item and "missing_count" in item for item in result.json())
        # The query count is fixed (bids, eager-loaded requests, one checklist aggregate, auth), not per bid.
        assert len(statements)<=5
    finally:
        event.remove(session.get_bind(),"before_cursor_execute",capture)
        client.close();app.dependency_overrides.pop(get_db,None)
