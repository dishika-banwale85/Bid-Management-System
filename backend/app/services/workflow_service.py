from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (ComplianceRequest, WorkflowTemplate, RequestStep, WorkflowStep, User, Notification,
                        RequestStatus, StepStatus, StepKind, AuditLog, Document, FormTemplate)
from app.schemas.requests import TenderFeeData, EmdChallanData, EmdBgData, FinancialDocumentsData, PowerOfAttorneyData, DeclarationData, HRDocumentsData, OmsPaceRedflagData

DATA_MODELS={"TENDER_FEE":TenderFeeData,"EMD_CHALLAN":EmdChallanData,"EMD_BG":EmdBgData,"FINANCIAL_DOCUMENTS":FinancialDocumentsData,"POWER_OF_ATTORNEY":PowerOfAttorneyData,"DECLARATION":DeclarationData,"HR_DOCUMENTS":HRDocumentsData,"OMS_PACE_REDFLAG":OmsPaceRedflagData}
REQUIRED_DOCUMENTS={"TENDER_FEE":{"generated_challan","checklist"},"EMD_CHALLAN":{"generated_challan","checklist"},"EMD_BG":{"bg_format","checklist"},"FINANCIAL_DOCUMENTS":{"rfp","ca_certificate"},"POWER_OF_ATTORNEY":{"poa_format","executed_poa"},"DECLARATION":{"required_document_format"},"HR_DOCUMENTS":{"rfp"}}
REQUIRED_DOCUMENT_ORDER={"TENDER_FEE":["generated_challan","checklist"],"EMD_CHALLAN":["generated_challan","checklist"],"EMD_BG":["bg_format","checklist"],"FINANCIAL_DOCUMENTS":["rfp","ca_certificate"],"POWER_OF_ATTORNEY":["poa_format","executed_poa"],"DECLARATION":["required_document_format"],"HR_DOCUMENTS":["rfp"],"OMS_PACE_REDFLAG":[]}
DOCUMENT_LABELS={"generated_challan":"Generated Challan","checklist":"Checklist","bg_format":"BG Format","ca_certificate":"CA Certificate","final_approval":"Final Approval","poa_format":"POA Format","executed_poa":"Executed / Notarized POA","required_document_format":"Format of required document","rfp":"RFP","ep_approval":"EP Approval","bg_copy":"Bank Guarantee copy","rfp_format":"RFP format document","financial_documents":"Financial documents","signed_declaration":"Signed declaration","hr_certificate":"HR certificate"}

def get_allowed_actions(req:ComplianceRequest,user:User)->list[str]:
    """Return request mutations available to any authenticated user."""
    if req.type=="OMS_PACE_REDFLAG":
        return ["EDIT","UPDATE","UPLOAD","SUBMIT"] if req.status==RequestStatus.DRAFT else (["EDIT","UPDATE"] if req.status==RequestStatus.SUBMITTED else [])
    if req.status in (RequestStatus.DRAFT,RequestStatus.REJECTED):
        actions=["EDIT","UPLOAD","SUBMIT"]
        if req.status==RequestStatus.DRAFT:actions.append("DELETE")
        return actions
    if req.status==RequestStatus.COMPLETED and req.type in ("EMD_CHALLAN","EMD_BG") and not req.refund_received_at:
        return ["REFUND_RECEIVED"]
    return []

def require_action(req:ComplianceRequest,user:User,action:str)->None:
    if action not in get_allowed_actions(req,user):
        raise HTTPException(status_code=403,detail={"error":"forbidden","message":f"You cannot perform {action.lower().replace('_',' ')} on this request"})

def validate_form(req:ComplianceRequest):
    model=DATA_MODELS.get(req.type)
    if not model: raise HTTPException(422,detail={"error":"validation_error","message":"Unsupported request type"})
    try:
        original=dict(req.form_data or {})
        validated=model.model_validate(original).model_dump(mode="json")
        req.form_data={**original,**validated} if req.type in ("TENDER_FEE","EMD_CHALLAN") else validated
    except Exception as exc:
        errors=exc.errors() if hasattr(exc,"errors") else [{"msg":str(exc)}]
        raise HTTPException(422,detail={"error":"validation_error","message":"Form data is invalid","fields":errors})

def audit(db,user,action,req,old_status=None,new_status=None,detail=None):
    db.add(AuditLog(user_id=user.id,action=action,request_id=req.id,entity_id=req.id,old_status=str(old_status.value if hasattr(old_status,"value") else old_status) if old_status else None,new_status=str(new_status.value if hasattr(new_status,"value") else new_status) if new_status else None,detail=detail or {}))

def notify(db,user_id,message,req): db.add(Notification(user_id=user_id,message=message,request_id=req.id))

def active_attempt_steps(db,request_id):
    attempt=db.scalar(select(RequestStep.attempt).where(RequestStep.request_id==request_id).order_by(RequestStep.attempt.desc()).limit(1)) or 0
    rows=db.scalars(select(RequestStep).where(RequestStep.request_id==request_id,RequestStep.attempt==attempt).order_by(RequestStep.id)).all()
    return attempt,rows

def submit(db:Session,req:ComplianceRequest,user:User):
    with db.begin_nested():
        require_action(req,user,"SUBMIT")
        if req.status not in (RequestStatus.DRAFT,RequestStatus.REJECTED): raise HTTPException(409,detail={"error":"conflict","message":"Request cannot be submitted in its current status"})
        validate_form(req)
        have=set(db.scalars(select(Document.category).where(Document.request_id==req.id)).all())
        form_template=db.scalar(select(FormTemplate).where(FormTemplate.request_type==req.type))
        required=REQUIRED_DOCUMENTS.get(req.type,set())
        missing=sorted(required-have)
        if missing: raise HTTPException(422,detail={"error":"missing_attachments","message":"Upload all required attachments before submitting","missing":missing,"missing_labels":[DOCUMENT_LABELS.get(key,key.replace("_"," ").title()) for key in missing]})
        old=req.status;req.status=RequestStatus.SUBMITTED
        audit(db,user,"SUBMITTED",req,old,req.status,{})
    db.flush();return req

def _current(db,req,attempt,step_row_id):
    row=db.scalar(select(RequestStep).where(RequestStep.id==step_row_id,RequestStep.request_id==req.id,RequestStep.attempt==attempt))
    if not row: raise HTTPException(404,detail={"error":"not_found","message":"Workflow step not found"})
    if row.status!=StepStatus.ACTIVE: raise HTTPException(409,detail={"error":"conflict","message":"This workflow step is not active"})
    return row

def _advance(db,req,row,user,final_status):
    all_rows=db.scalars(select(RequestStep).where(RequestStep.request_id==req.id,RequestStep.attempt==row.attempt).order_by(RequestStep.id)).all()
    idx=all_rows.index(row)
    if idx+1==len(all_rows):
        old=req.status;req.status=RequestStatus.COMPLETED;audit(db,user,"COMPLETED",req,old,req.status,{"step_id":row.step_id})
        for recipient in [req.created_by]: notify(db,recipient,f"Request #{req.id} is completed.",req)
        return "completed"
    nxt=all_rows[idx+1];nxt.status=StepStatus.ACTIVE
    for assignee in db.scalars(select(User).join(User.role).where(User.role.has(name=nxt.workflow_step.assigned_role),User.is_active.is_(True))).all():
        notify(db,assignee.id,f"Request #{req.id} is ready for {nxt.workflow_step.name}.",req)
    audit(db,user,"STEP_ACTIVATED",req,req.status,req.status,{"step_id":nxt.step_id,"assigned_role":nxt.workflow_step.assigned_role})
    return "next"

def approve(db:Session,req:ComplianceRequest,step_row_id:int,user:User,comment:str|None=None):
    with db.begin_nested():
        require_action(req,user,"APPROVE")
        if req.status!=RequestStatus.IN_APPROVAL: raise HTTPException(409,detail={"error":"conflict","message":"Request is not in approval"})
        attempt,_=active_attempt_steps(db,req.id);row=_current(db,req,attempt,step_row_id)
        if row.workflow_step.step_kind!=StepKind.APPROVAL: raise HTTPException(409,detail={"error":"conflict","message":"This is an action step"})
        if req.created_by==user.id: raise HTTPException(403,detail={"error":"forbidden","message":"A request creator cannot approve their own request"})
        row.status=StepStatus.APPROVED;row.acted_by=user.id;row.acted_at=datetime.now(timezone.utc);row.comment=(comment or "").strip() or None
        audit(db,user,"STEP_APPROVED",req,req.status,req.status,{"step_id":row.step_id,"attempt":attempt,"comment":row.comment})
        notify(db,req.created_by,f"A workflow step on request #{req.id} was approved.",req)
        _advance(db,req,row,user,RequestStatus.COMPLETED)
    db.flush();return req

def reject(db:Session,req:ComplianceRequest,step_row_id:int,user:User,comment:str|None):
    if not (comment or "").strip(): raise HTTPException(422,detail={"error":"validation_error","message":"A rejection comment is required"})
    with db.begin_nested():
        require_action(req,user,"REJECT")
        if req.status!=RequestStatus.IN_APPROVAL: raise HTTPException(409,detail={"error":"conflict","message":"Request is not in approval"})
        attempt,_=active_attempt_steps(db,req.id);row=_current(db,req,attempt,step_row_id)
        if row.workflow_step.step_kind!=StepKind.APPROVAL: raise HTTPException(409,detail={"error":"conflict","message":"Only approval steps can reject"})
        if req.created_by==user.id: raise HTTPException(403,detail={"error":"forbidden","message":"A request creator cannot reject their own request"})
        old=req.status;row.status=StepStatus.REJECTED;row.acted_by=user.id;row.acted_at=datetime.now(timezone.utc);row.comment=comment.strip();req.status=RequestStatus.REJECTED
        audit(db,user,"REJECTED",req,old,req.status,{"step_id":row.step_id,"comment":comment.strip(),"attempt":attempt})
        notify(db,req.created_by,f"Request #{req.id} was rejected: {comment.strip()}",req)
        for later in db.scalars(select(RequestStep).where(RequestStep.request_id==req.id,RequestStep.attempt==attempt,RequestStep.id>row.id)).all(): later.status=StepStatus.SKIPPED
    db.flush();return req

def complete_action(db:Session,req:ComplianceRequest,step_row_id:int,user:User,extra_data:dict):
    with db.begin_nested():
        action="RECORD_REFERENCE" if user.role.name!="ADMIN" else "COMPLETE"
        require_action(req,user,action)
        if req.status!=RequestStatus.IN_APPROVAL: raise HTTPException(409,detail={"error":"conflict","message":"Request is not in approval"})
        attempt,_=active_attempt_steps(db,req.id);row=_current(db,req,attempt,step_row_id);step=row.workflow_step
        if step.step_kind!=StepKind.ACTION: raise HTTPException(409,detail={"error":"conflict","message":"This is not an action step"})
        allowed_roles={step.assigned_role}
        required=step.requires_fields or []
        missing=[key for key in required if (key.startswith("attachment:") and not db.scalar(select(Document.id).where(Document.request_id==req.id,Document.category==key.split(":",1)[1]))) or (not key.startswith("attachment:") and not str(extra_data.get(key,"")).strip())]
        if missing: raise HTTPException(422,detail={"error":"validation_error","message":"Complete required action fields","missing":missing})
        row.status=StepStatus.DONE;row.acted_by=user.id;row.acted_at=datetime.now(timezone.utc);row.extra_data=extra_data
        audit(db,user,"STEP_COMPLETED",req,req.status,req.status,{"step_id":row.step_id,"extra_data":extra_data,"attempt":attempt})
        _advance(db,req,row,user,RequestStatus.COMPLETED)
    db.flush();return req
