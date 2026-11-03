import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.models import RequestStep,RequestStatus,StepStatus,Document
from app.services.workflow_service import submit,approve,reject,complete_action
from app.schemas.requests import EmdBgData,EmdChallanData

def test_bg_workflow_transitions_to_completed(db,bg_request):
    s=db["db"];team=db["users"]["BID_TEAM"];approver=db["users"]["APPROVER"];ops=db["users"]["OPERATIONS"]
    submit(s,bg_request,team);s.commit()
    first=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    approve(s,bg_request,first.id,approver);s.commit()
    oprs=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    complete_action(s,bg_request,oprs.id,team,{"oprs_reference":"OPRS-900"});s.commit()
    operation=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    s.add(Document(request_id=bg_request.id,category="bg_copy",filename="bg.pdf",stored_name="bg.pdf",content_type="application/pdf",version=1,uploaded_by=ops.id));s.commit()
    complete_action(s,bg_request,operation.id,ops,{"bg_number":"BG-102","issue_date":"2026-10-22"});s.commit()
    assert bg_request.status==RequestStatus.COMPLETED

def test_creator_cannot_approve_own_request(db,bg_request):
    s=db["db"];creator=db["users"]["BID_TEAM"];submit(s,bg_request,creator);s.commit()
    approver=db["users"]["APPROVER"];bg_request.created_by=approver.id;s.commit()
    active=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    with pytest.raises(HTTPException) as error:approve(s,bg_request,active.id,approver)
    assert error.value.status_code==403

def test_wrong_role_gets_403(db,bg_request):
    s=db["db"];submit(s,bg_request,db["users"]["BID_TEAM"]);s.commit()
    active=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    with pytest.raises(HTTPException) as error:approve(s,bg_request,active.id,db["users"]["OPERATIONS"])
    assert error.value.status_code==403

def test_rejection_resubmission_starts_new_attempt_and_keeps_history(db,bg_request):
    s=db["db"];creator=db["users"]["BID_TEAM"];submit(s,bg_request,creator);s.commit()
    active=s.scalar(select(RequestStep).where(RequestStep.request_id==bg_request.id,RequestStep.attempt==1,RequestStep.status==StepStatus.ACTIVE))
    with pytest.raises(HTTPException) as error:reject(s,bg_request,active.id,db["users"]["APPROVER"],"")
    assert error.value.status_code==422
    reject(s,bg_request,active.id,db["users"]["APPROVER"],"Update BG amount");s.commit()
    assert bg_request.status==RequestStatus.REJECTED
    bg_request.form_data={**bg_request.form_data,"bg_amount":11000};bg_request.status=RequestStatus.DRAFT;s.commit()
    submit(s,bg_request,creator);s.commit()
    rows=s.scalars(select(RequestStep).where(RequestStep.request_id==bg_request.id)).all()
    assert {r.attempt for r in rows}=={1,2}
    assert sum(r.status==StepStatus.ACTIVE for r in rows if r.attempt==2)==1

def test_missing_attachment_blocks_submit(db,bg_request):
    s=db["db"];s.query(Document).filter_by(request_id=bg_request.id,category="rfp").delete();s.commit()
    with pytest.raises(HTTPException) as error:submit(s,bg_request,db["users"]["BID_TEAM"])
    assert error.value.status_code==422 and error.value.detail["missing"]==["rfp"]

def test_validation_rules():
    with pytest.raises(Exception):EmdBgData.model_validate({"engagement_code":"a","beneficiary_address":"b","mode_of_bg":"c","current_bg_maturity_date":"2026-01-01","tender_opening_date":"2026-02-01","contract_date":"2026-01-02","bg_amount":0,"contract_value":1,"contract_description":"x","bg_issued_from":"y","approved_by":"z"})
    invalid={"client_name":"C","department":"D","mobile":"123","contact_person":"p","landline":"1","email":"bad","beneficiary_name":"b","payment_mode":"x","relevant_rfp_pages":"p1","amount":3,"account_holder_name":"h","account_number":"123","branch_name":"b","ifsc":"wrong","branch_code":"c","micr":"123"}
    with pytest.raises(Exception):EmdChallanData.model_validate(invalid)
