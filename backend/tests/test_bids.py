from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import AuditLog, Bid


def _payload(**overrides):
    today=date.today()
    values={
        "client_name":"Example Client",
        "department":"Public Sector",
        "client_address":"1 Main Street, New Delhi",
        "rfp_number":"RFP-NEW-01",
        "project_title":"Road Safety Improvement Project",
        "rfp_published_date":(today-timedelta(days=10)).isoformat(),
        "prebid_query_deadline":(today+timedelta(days=4)).isoformat(),
        "prebid_meeting_date":(today+timedelta(days=7)).isoformat(),
        "prebid_query_na":False,
        "prebid_meeting_na":False,
        "submission_deadline":(today+timedelta(days=20)).isoformat(),
        "tender_opening_date":(today+timedelta(days=20)).isoformat(),
    }
    values.update(overrides)
    return values


def _client(db):
    session=db["db"]
    def override_db():
        yield session
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def _headers(user):
    return {"Authorization":f"Bearer {create_token(user)}"}


def test_create_bid_returns_full_details_and_writes_audit(db):
    client=_client(db)
    try:
        response=client.post("/bids",json=_payload(),headers=_headers(db["users"]["BID_TEAM"]))
        assert response.status_code==201
        created=response.json()
        assert created["rfp_number"]==created["rfp_reference"]=="RFP-NEW-01"
        assert created["project_title"]=="Road Safety Improvement Project"
        details=client.get(f"/bids/{created['id']}",headers=_headers(db["users"]["BID_TEAM"]))
        assert details.status_code==200
        assert details.json()["client_address"]=="1 Main Street, New Delhi"
        assert details.json()["rfp_published_date"]==_payload()["rfp_published_date"]
        legacy_payload=_payload(rfp_number="RFP-LEGACY-NAME")
        legacy_payload["rfp_reference"]=legacy_payload.pop("rfp_number")
        legacy_response=client.post("/bids",json=legacy_payload,headers=_headers(db["users"]["BID_TEAM"]))
        assert legacy_response.status_code==201 and legacy_response.json()["rfp_number"]=="RFP-LEGACY-NAME"
        audit=db["db"].scalar(select(AuditLog).where(AuditLog.entity_type=="Bid",AuditLog.entity_id==created["id"]))
        assert audit and audit.action=="BID_CREATED"
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)


def test_create_requires_fields_and_validates_date_ranges(db):
    client=_client(db)
    headers=_headers(db["users"]["BID_TEAM"])
    try:
        missing=_payload()
        del missing["project_title"]
        response=client.post("/bids",json=missing,headers=headers)
        assert response.status_code==422
        assert any("project_title" in str(issue) for issue in response.json()["fields"])

        dates=_payload(submission_deadline=(date.today()-timedelta(days=1)).isoformat())
        assert client.post("/bids",json=dates,headers=headers).status_code==422
        dates=_payload(submission_deadline=(date.today()+timedelta(days=12)).isoformat(),tender_opening_date=(date.today()+timedelta(days=11)).isoformat())
        assert client.post("/bids",json=dates,headers=headers).status_code==422
        dates=_payload(prebid_query_deadline=(date.today()+timedelta(days=25)).isoformat())
        assert client.post("/bids",json=dates,headers=headers).status_code==422
        dates=_payload(prebid_meeting_date=(date.today()+timedelta(days=25)).isoformat())
        assert client.post("/bids",json=dates,headers=headers).status_code==422
        dates=_payload(rfp_published_date=(date.today()+timedelta(days=21)).isoformat())
        assert client.post("/bids",json=dates,headers=headers).status_code==422
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)


@pytest.mark.parametrize("field",[
    "client_name","client_address","rfp_number","project_title","rfp_published_date",
    "prebid_query_deadline","prebid_meeting_date","submission_deadline","tender_opening_date",
])
def test_each_required_bid_field_is_reported_when_missing(db,field):
    client=_client(db)
    payload=_payload()
    payload.pop(field)
    try:
        response=client.post("/bids",json=payload,headers=_headers(db["users"]["BID_TEAM"]))
        assert response.status_code==422
        assert any(field in str(issue) for issue in response.json()["fields"])
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)


def test_na_flags_clear_prebid_dates(db):
    client=_client(db)
    try:
        payload=_payload(prebid_meeting_na=True,prebid_meeting_date=None,prebid_query_na=True,prebid_query_deadline=None)
        response=client.post("/bids",json=payload,headers=_headers(db["users"]["BID_TEAM"]))
        assert response.status_code==201
        assert response.json()["prebid_meeting_date"] is None
        assert response.json()["prebid_query_deadline"] is None
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)


def test_duplicate_check_warns_but_does_not_block_create(db):
    client=_client(db)
    try:
        payload=_payload(rfp_number="RFP-42")
        check=client.get("/bids/check-rfp",params={"rfp_number":"rfp-42"},headers=_headers(db["users"]["BID_TEAM"]))
        assert check.status_code==200 and check.json()=={"exists":True,"message":"A bid with this RFP number already exists"}
        created=client.post("/bids",json=payload,headers=_headers(db["users"]["BID_TEAM"]))
        assert created.status_code==201
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)


def test_bid_roles_old_records_search_and_edit(db):
    client=_client(db)
    try:
        payload=_payload()
        denied=client.post("/bids",json=payload,headers=_headers(db["users"]["APPROVER"]))
        assert denied.status_code==403
        created=client.post("/bids",json=payload,headers=_headers(db["users"]["ADMIN"]))
        assert created.status_code==201

        old=client.get(f"/bids/{db['bid'].id}",headers=_headers(db["users"]["BID_TEAM"]))
        assert old.status_code==200
        assert old.json()["project_title"] is None
        assert old.json()["client_address"] is None
        assert old.json()["rfp_number"]=="RFP-42"
        old_bid=db["db"].get(Bid,db["bid"].id)
        old_bid.submission_deadline=date.today()-timedelta(days=2)
        old_bid.tender_opening_date=date.today()-timedelta(days=1)
        db["db"].commit()
        legacy_edit=client.put(f"/bids/{old_bid.id}",json={"project_title":"Legacy bid update"},headers=_headers(db["users"]["BID_TEAM"]))
        assert legacy_edit.status_code==200
        assert legacy_edit.json()["submission_deadline"]==(date.today()-timedelta(days=2)).isoformat()
        listing=client.get("/bids",params={"search":"Demo Client"},headers=_headers(db["users"]["BID_TEAM"]))
        assert any(row["id"]==db["bid"].id for row in listing.json())
        title_search=client.get("/bids",params={"search":"Road Safety Improvement"},headers=_headers(db["users"]["ADMIN"]))
        rfp_search=client.get("/bids",params={"search":"RFP-NEW-01"},headers=_headers(db["users"]["ADMIN"]))
        assert any(row["project_title"]=="Road Safety Improvement Project" for row in title_search.json())
        assert any(row["rfp_number"]=="RFP-NEW-01" for row in rfp_search.json())

        own=client.post("/bids",json={**payload,"rfp_number":"RFP-OWN-EDIT"},headers=_headers(db["users"]["BID_TEAM"]))
        bid_id=own.json()["id"]
        updated=client.put(f"/bids/{bid_id}",json={"project_title":"Updated Project"},headers=_headers(db["users"]["BID_TEAM"]))
        assert updated.status_code==200 and updated.json()["project_title"]=="Updated Project"
        edit_audit=db["db"].scalar(select(AuditLog).where(AuditLog.entity_type=="Bid",AuditLog.entity_id==bid_id,AuditLog.action=="BID_UPDATED"))
        assert edit_audit
    finally:
        client.close()
        app.dependency_overrides.pop(get_db,None)
