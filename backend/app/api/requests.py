import uuid
from datetime import date,timedelta
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form,Body,Response
from fastapi.responses import FileResponse
from sqlalchemy import delete,select
from sqlalchemy.orm import Session,selectinload
from app.db import get_db
from app.models import ComplianceRequest,User,Bid,BidChecklistNA,Document,RequestStatus,RequestStep,StepStatus,AuditLog,StepKind
from app.schemas.requests import RequestCreate,RequestUpdate,DecisionIn,ActionIn,RefundReceivedIn,OmsPaceRedflagData
from app.core.security import current_user,require_role,deny_admin_writes
from app.core.config import UPLOAD_DIR,MAX_UPLOAD_MB
from app.services.workflow_service import (submit,approve,reject,complete_action,audit,
    get_allowed_actions,require_action,REQUIRED_DOCUMENTS,REQUIRED_DOCUMENT_ORDER,DOCUMENT_LABELS)
from app.services.mail_service import notify as notify_mail
from app.services.access_service import active_request_bid_clause,get_active_bid,request_visibility_clause,can_view_request
from app.services.trash_service import unlink_stored_files
router=APIRouter(prefix="/requests",tags=["requests"])
ALLOWED={".pdf",".docx",".jpg",".jpeg",".png"}
VALID_CATEGORIES={"generated_challan","checklist","bg_format","ca_certificate","final_approval","poa_format","executed_poa","required_document_format","rfp","ep_approval","bg_copy","rfp_format","financial_documents","signed_declaration","hr_certificate","OTHER"}
MAX_DRAFT_TEXT_LENGTH=10000


def _active_request(db:Session,request_id:int):
    return db.scalar(select(ComplianceRequest).options(selectinload(ComplianceRequest.documents)).join(Bid).where(ComplianceRequest.id==request_id,active_request_bid_clause()))

def _sanitize_draft_form(value):
    """Trim draft strings without applying the strict per-request submission schema."""
    if not isinstance(value,dict):
        raise HTTPException(422,detail={"error":"validation_error","message":"form_data must be an object"})
    def clean(item):
        if isinstance(item,str):
            item=item.strip()
            if len(item)>MAX_DRAFT_TEXT_LENGTH:
                raise HTTPException(422,detail={"error":"validation_error","message":f"Text fields cannot exceed {MAX_DRAFT_TEXT_LENGTH} characters"})
            return item
        if isinstance(item,list):return [clean(child) for child in item]
        if isinstance(item,dict):return {str(key).strip():clean(child) for key,child in item.items()}
        return item
    return clean(value)

def _form_for_user(form,user,owner_id):
    data=dict(form or {})
    if "account_number" in data and user.id!=owner_id:
        value=str(data["account_number"]);data["account_number"]="•"*max(0,len(value)-4)+value[-4:]
    return data
def _detail(req,user):
    attempt=max((s.attempt for s in req.steps),default=0)
    active=next((s for s in req.steps if s.attempt==attempt and s.status==StepStatus.ACTIVE),None)
    keys=list(REQUIRED_DOCUMENT_ORDER.get(req.type,[]))
    if active and active.workflow_step.step_kind.value=="ACTION":
        keys.extend(str(item).split(":",1)[1] for item in (active.workflow_step.requires_fields or []) if str(item).startswith("attachment:"))
    latest={}
    for doc in sorted(req.documents,key=lambda x:(x.category,x.version)):
        latest[doc.category]=doc
    required_documents=[{"key":key,"label":DOCUMENT_LABELS.get(key,key.replace("_"," ").title()),"uploaded":key in latest,"document_id":latest[key].id if key in latest else None} for key in dict.fromkeys(keys)]
    return {"id":req.id,"bid_id":req.bid_id,"bid_name":req.bid.client_name if req.bid else "","type":req.type,"status":req.status.value,"form_data":_form_for_user(req.form_data,user,req.created_by),"created_by":req.created_by,"created_by_name":req.creator.full_name if req.creator else "","created_at":req.created_at.isoformat(),"updated_at":req.updated_at.isoformat() if req.updated_at else None,"refund_received_at":req.refund_received_at.isoformat() if req.refund_received_at else None,"documents":[{"id":d.id,"category":d.category,"document_type":d.document_type,"filename":d.filename,"version":d.version,"uploaded_by":d.uploaded_by,"created_at":d.created_at.isoformat()} for d in sorted(req.documents,key=lambda x:(x.category,x.version))],"required_documents":required_documents,"allowed_actions":get_allowed_actions(req,user),"active_step_id":active.id if active else None,"workflow":[{"id":s.id,"step_id":s.step_id,"attempt":s.attempt,"status":s.status.value,"name":s.workflow_step.name,"step_order":s.workflow_step.step_order,"step_kind":s.workflow_step.step_kind.value,"assigned_role":s.workflow_step.assigned_role,"requires_fields":s.workflow_step.requires_fields or [],"acted_by":s.acted_by,"actor_name":s.actor.full_name if s.actor else None,"acted_at":s.acted_at.isoformat() if s.acted_at else None,"comment":s.comment,"extra_data":s.extra_data} for s in sorted(req.steps,key=lambda x:(x.attempt,x.workflow_step.step_order))],"attempt":attempt}
def _mail_contact_types(req,step=None):
    if req.type in ("TENDER_FEE","EMD_CHALLAN"):return ["PROCESSING"]
    if req.type=="EMD_BG":
        if step and "bank guarantee" in step.workflow_step.name.lower():return ["OPERATIONS"]
        if step and step.workflow_step.step_kind==StepKind.ACTION:return ["PROCESSING"]
        return ["VETTING"]
    if req.type=="FINANCIAL_DOCUMENTS":return ["PRIMARY"]
    if req.type=="POWER_OF_ATTORNEY":return ["RISK"] if step and "risk" in step.workflow_step.name.lower() else ["PRIMARY"]
    if req.type in ("DECLARATION","HR_DOCUMENTS"):return ["PRIMARY","CC"]
    return ["PRIMARY"]

def _mail_event(db,req,step,title,message,comment=""):
    event={"title":title,"message":message,"comment":comment,"template":step.workflow_step.name if step else "request_event"}
    return notify_mail(event,req,_mail_contact_types(req,step),db=db)

@router.post("/parse-checklist")
async def parse_checklist(file:UploadFile=File(...),request_type:str=Form(...),user:User=Depends(current_user)):
    from app.services.checklist_extractor import InvalidChecklist,parse_checklist_xlsx
    raw=await file.read(MAX_UPLOAD_MB*1024*1024+1)
    if len(raw)>MAX_UPLOAD_MB*1024*1024:
        raise HTTPException(413,detail={"error":"file_too_large","message":f"Maximum file size is {MAX_UPLOAD_MB} MB"})
    if request_type not in {"TENDER_FEE","EMD_CHALLAN","EMD_BG"}:
        raise HTTPException(422,detail={"error":"invalid_request_type","message":"Checklist parsing is supported for Tender Fee, EMD by Challan and EMD by Bank Guarantee."})
    try:
        return parse_checklist_xlsx(raw,file.filename or "",request_type)
    except InvalidChecklist as exc:
        raise HTTPException(422,detail={"error":"invalid_checklist","message":str(exc)})
    finally:
        await file.close()

@router.get("")
def list_requests(page:int=1,page_size:int=20,status:str|None=None,request_type:str|None=None,bid_id:int|None=None,mine:bool=False,date_from:date|None=None,date_to:date|None=None,client:str|None=None,tab:str|None=None,search:str|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload
    page=max(1,page);page_size=min(100,max(1,page_size));q=select(ComplianceRequest).options(selectinload(ComplianceRequest.bid),selectinload(ComplianceRequest.documents)).where(request_visibility_clause(user),active_request_bid_clause())
    if mine:q=q.where(ComplianceRequest.created_by==user.id)
    if status:q=q.where(ComplianceRequest.status==status)
    elif not mine:q=q.where(ComplianceRequest.status!=RequestStatus.DRAFT)
    if request_type:q=q.where(ComplianceRequest.type==request_type)
    if bid_id:q=q.where(ComplianceRequest.bid_id==bid_id)
    if date_from:q=q.where(ComplianceRequest.created_at>=date_from)
    if date_to:q=q.where(ComplianceRequest.created_at<date_to+timedelta(days=1))
    if client:q=q.join(Bid,ComplianceRequest.bid_id==Bid.id).where(Bid.client_name.ilike(f"%{client.strip()}%"))
    if search:
        if not client:q=q.join(Bid,ComplianceRequest.bid_id==Bid.id)
        q=q.where(Bid.client_name.ilike(f"%{search.strip()}%")|Bid.rfp_reference.ilike(f"%{search.strip()}%"))
    if tab=="completed":q=q.where(ComplianceRequest.status==RequestStatus.COMPLETED)
    elif tab in {"ongoing","not_completed"}:q=q.where(ComplianceRequest.status!=RequestStatus.COMPLETED)
    if tab=="ongoing":
        if not client and not search:q=q.join(Bid,ComplianceRequest.bid_id==Bid.id)
        q=q.where(Bid.status.not_in(["COMPLETED","CLOSED"]))
    q=q.order_by(ComplianceRequest.updated_at.desc() if mine and status=="DRAFT" else ComplianceRequest.created_at.desc())
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[{"id":r.id,"bid_id":r.bid_id,"client_name":r.bid.client_name if r.bid else "","bid_name":r.bid.client_name if r.bid else "","type":r.type,"status":r.status.value,"document_count":len(r.documents),"created_at":r.created_at.isoformat(),"updated_at":r.updated_at.isoformat()} for r in rows],"page":page,"page_size":page_size,"total":total,"pages":(total+page_size-1)//page_size}

@router.post("",status_code=201)
def create_request(data:RequestCreate,db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    if data.type not in {"TENDER_FEE","EMD_CHALLAN","EMD_BG","FINANCIAL_DOCUMENTS","POWER_OF_ATTORNEY","DECLARATION","HR_DOCUMENTS","OMS_PACE_REDFLAG"}:
        raise HTTPException(422,detail={"error":"invalid_request_type","message":"Unknown request type"})
    if data.type=="OMS_PACE_REDFLAG" and user.role.name not in {"BID_TEAM","PACE_COORDINATOR"}:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid Team Member or PACE Coordinator can create this record"})
    if data.type!="OMS_PACE_REDFLAG" and user.role.name!="BID_TEAM":raise HTTPException(403,detail={"error":"forbidden","message":"Only Team Members can create this request type"})
    bid=get_active_bid(db,data.bid_id)
    if not bid: raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    if data.type=="OMS_PACE_REDFLAG" and db.scalar(select(ComplianceRequest.id).where(ComplianceRequest.bid_id==bid.id,ComplianceRequest.type==data.type)):
        raise HTTPException(409,detail={"error":"conflict","message":"This bid already has an OMS / PACE / Red flag record"})
    if user.role.name=="BID_TEAM" and bid.created_by!=user.id:raise HTTPException(403,detail={"error":"forbidden","message":"You can create requests only for bids you own"})
    req=ComplianceRequest(bid_id=data.bid_id,type=data.type,status=RequestStatus.DRAFT,form_data=_sanitize_draft_form(data.form_data),created_by=user.id);db.add(req);db.flush()
    db.add(AuditLog(user_id=user.id,action="DRAFT_SAVED",request_id=req.id,entity_id=req.id,old_status=None,new_status="DRAFT",detail={"type":data.type}));db.commit();db.refresh(req);return _detail(req,user)

@router.get("/history")
def request_history(page:int=1,page_size:int=50,date_from:date|None=None,date_to:date|None=None,client:str|None=None,request_type:str|None=None,tab:str|None=None,search:str|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload
    page=max(1,page);page_size=min(100,max(1,page_size))
    q=select(ComplianceRequest).options(selectinload(ComplianceRequest.bid)).join(Bid).where(ComplianceRequest.status!=RequestStatus.DRAFT,active_request_bid_clause()).order_by(ComplianceRequest.created_at.desc())
    if date_from:q=q.where(ComplianceRequest.created_at>=date_from)
    if date_to:q=q.where(ComplianceRequest.created_at<date_to+timedelta(days=1))
    if client:q=q.where(Bid.client_name.ilike(f"%{client.strip()}%"))
    if request_type:q=q.where(ComplianceRequest.type==request_type)
    if search:q=q.where(Bid.client_name.ilike(f"%{search.strip()}%")|Bid.rfp_reference.ilike(f"%{search.strip()}%"))
    if tab=="completed":q=q.where(ComplianceRequest.status==RequestStatus.COMPLETED)
    elif tab in {"ongoing","not_completed"}:q=q.where(ComplianceRequest.status!=RequestStatus.COMPLETED)
    if tab=="ongoing":q=q.where(Bid.status.not_in(["COMPLETED","CLOSED"]))
    if user.role.name=="BID_TEAM":q=q.where(ComplianceRequest.created_by==user.id)
    elif user.role.name=="ADMIN":q=q.where(False)
    else:q=q.where(ComplianceRequest.id.in_(select(RequestStep.request_id).where(RequestStep.acted_by==user.id)))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[{"id":r.id,"bid_id":r.bid_id,"client_name":r.bid.client_name if r.bid else "","type":r.type,"status":r.status.value,"created_at":r.created_at.isoformat()} for r in rows],"page":page,"page_size":page_size,"total":total,"pages":(total+page_size-1)//page_size}


@router.delete("/{request_id}",status_code=204)
def delete_draft_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    req=_active_request(db,request_id)
    if not req:raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    if user.role.name!="BID_TEAM" or req.created_by!=user.id:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the Team Member who created this request can delete it"})
    if req.status!=RequestStatus.DRAFT:
        raise HTTPException(409,detail={"error":"conflict","message":"Only a draft request can be deleted"})
    stored_names=[doc.stored_name for doc in req.documents]
    request_type=req.type;bid_id=req.bid_id
    db.add(AuditLog(user_id=user.id,action="DRAFT_DELETED",request_id=None,entity_type="ComplianceRequest",entity_id=req.id,detail={"request_type":request_type,"bid_id":bid_id,"creator_id":user.id}))
    db.execute(delete(BidChecklistNA).where(BidChecklistNA.bid_id==bid_id,BidChecklistNA.request_type==request_type))
    db.delete(req)
    db.commit()
    unlink_stored_files(stored_names)
    return Response(status_code=204)

@router.put("/{request_id}")
def update_request(request_id:int,data:RequestUpdate,db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    req=_active_request(db,request_id)
    if not req: raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    if req.type=="OMS_PACE_REDFLAG":
        if not ((user.role.name=="PACE_COORDINATOR") or (user.role.name=="BID_TEAM" and req.bid and req.bid.created_by==user.id)):
            raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid Team Member or PACE Coordinator can update this record"})
        if req.status not in (RequestStatus.DRAFT,RequestStatus.SUBMITTED):raise HTTPException(409,detail={"error":"conflict","message":"This record cannot be updated in its current status"})
        old_data=dict(req.form_data or {});new_data=_sanitize_draft_form(data.form_data)
        if req.status==RequestStatus.SUBMITTED:
            try:new_data=OmsPaceRedflagData.model_validate(new_data).model_dump(mode="json")
            except Exception as exc:raise HTTPException(422,detail={"error":"validation_error","message":"Form data is invalid","fields":exc.errors()})
        req.form_data=new_data
        db.add(AuditLog(user_id=user.id,action="OMS_PACE_REDFLAG_UPDATED",request_id=req.id,entity_type="ComplianceRequest",entity_id=req.id,old_status=req.status.value,new_status=req.status.value,detail={"old_values":old_data,"new_values":new_data}));db.commit();db.refresh(req);return _detail(req,user)
    if user.role.name!="BID_TEAM" or req.created_by!=user.id:raise HTTPException(403,detail={"error":"forbidden","message":"Only the request creator can save a draft"})
    if req.status not in (RequestStatus.DRAFT,RequestStatus.REJECTED): raise HTTPException(409,detail={"error":"conflict","message":"Only draft or rejected requests can be edited"})
    old=req.status;req.form_data=_sanitize_draft_form(data.form_data);req.status=RequestStatus.DRAFT
    db.add(AuditLog(user_id=user.id,action="DRAFT_SAVED",request_id=req.id,entity_id=req.id,old_status=old.value,new_status=req.status.value,detail={}));db.commit();db.refresh(req);return _detail(req,user)

@router.get("/{request_id}")
def get_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    req=_active_request(db,request_id)
    if not req or not can_view_request(req,user): raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    return _detail(req,user)

@router.post("/{request_id}/documents")
async def upload_document(request_id:int,category:str|None=Form(None),document_type:str|None=Form(None),file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    req=_active_request(db,request_id)
    if not req: raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    category=document_type or category or "OTHER"
    if category not in VALID_CATEGORIES: raise HTTPException(422,detail={"error":"validation_error","message":"Unknown document category"})
    require_action(req,user,"UPLOAD")
    owner=req.created_by==user.id and user.role.name=="BID_TEAM"
    attempt=max((s.attempt for s in req.steps),default=0)
    active_step=next((s for s in req.steps if s.attempt==attempt and s.status==StepStatus.ACTIVE),None)
    allowed_for_owner=owner and req.status in (RequestStatus.DRAFT,RequestStatus.REJECTED) and category in REQUIRED_DOCUMENTS.get(req.type,set())|{"OTHER"}
    required_by_active=[]
    if active_step and active_step.workflow_step.step_kind.value=="ACTION":
        required_by_active=[str(item).split(":",1)[1] for item in (active_step.workflow_step.requires_fields or []) if str(item).startswith("attachment:")]
    allowed_for_action=bool(active_step and req.status==RequestStatus.IN_APPROVAL and category in required_by_active and user.role.name==active_step.workflow_step.assigned_role and (user.role.name!="BID_TEAM" or owner))
    if not (allowed_for_owner or allowed_for_action): raise HTTPException(403,detail={"error":"forbidden","message":"You cannot upload this document at the current workflow step"})
    original=Path(file.filename or "document").name;ext=Path(original).suffix.lower()
    if ext not in ALLOWED and not (category=="checklist" and ext==".xlsx"):
        raise HTTPException(415,detail={"error":"invalid_file","message":"Allowed types are PDF, DOCX, JPG and PNG; XLSX is allowed for Checklist"})
    raw=await file.read(MAX_UPLOAD_MB*1024*1024+1)
    if len(raw)>MAX_UPLOAD_MB*1024*1024: raise HTTPException(413,detail={"error":"file_too_large","message":f"Maximum file size is {MAX_UPLOAD_MB} MB"})
    if ext==".xlsx":
        from app.services.checklist_extractor import InvalidChecklist,validate_xlsx
        try:
            workbook=validate_xlsx(raw,original);workbook.close()
        except InvalidChecklist as exc:
            raise HTTPException(422,detail={"error":"invalid_checklist","message":str(exc)})
    old=req.status;UPLOAD_DIR.mkdir(parents=True,exist_ok=True);stored=f"{uuid.uuid4().hex}{ext}";(UPLOAD_DIR/stored).write_bytes(raw)
    version=(db.scalar(select(Document.version).where(Document.request_id==req.id,Document.category==category).order_by(Document.version.desc()).limit(1)) or 0)+1
    doc=Document(request_id=req.id,category=category,document_type=category,filename=original,stored_name=stored,content_type=file.content_type or "application/octet-stream",version=version,uploaded_by=user.id);db.add(doc);db.flush()
    db.add(AuditLog(user_id=user.id,action="UPLOADED",request_id=req.id,entity_id=req.id,old_status=old.value,new_status=req.status.value,detail={"document_id":doc.id,"category":category,"version":version}));db.commit()
    result={"id":doc.id,"category":doc.category,"filename":doc.filename,"version":doc.version}
    return result

@router.get("/{request_id}/documents")
def list_documents(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    req=_active_request(db,request_id)
    if not req or not can_view_request(req,user): raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    return [{"id":d.id,"category":d.category,"document_type":d.document_type,"filename":d.filename,"version":d.version,"created_at":d.created_at.isoformat()} for d in sorted(req.documents,key=lambda x:(x.category,x.version))]
@router.get("/{request_id}/documents/{document_id}/download")
def download_document(request_id:int,document_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    doc=db.scalar(select(Document).where(Document.id==document_id,Document.request_id==request_id))
    req=_active_request(db,request_id)
    if not doc or not req or not can_view_request(req,user): raise HTTPException(404,detail={"error":"not_found","message":"Document not found"})
    path=UPLOAD_DIR/doc.stored_name
    if not path.is_file(): raise HTTPException(404,detail={"error":"not_found","message":"Stored file not found"})
    return FileResponse(path,filename=doc.filename,media_type=doc.content_type)

@router.post("/{request_id}/submit")
def submit_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    req=_active_request(db,request_id)
    if not req: raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    if req.type=="OMS_PACE_REDFLAG":
        if not ((user.role.name=="PACE_COORDINATOR") or (user.role.name=="BID_TEAM" and req.bid and req.bid.created_by==user.id)):
            raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid Team Member or PACE Coordinator can submit this record"})
        if req.status!=RequestStatus.DRAFT:raise HTTPException(409,detail={"error":"conflict","message":"This record has already been submitted; use Update"})
        try:req.form_data=OmsPaceRedflagData.model_validate(req.form_data or {}).model_dump(mode="json")
        except Exception as exc:raise HTTPException(422,detail={"error":"validation_error","message":"Form data is invalid","fields":exc.errors()})
        req.status=RequestStatus.SUBMITTED;db.add(AuditLog(user_id=user.id,action="SUBMITTED",request_id=req.id,entity_type="ComplianceRequest",entity_id=req.id,old_status="DRAFT",new_status="SUBMITTED",detail={}));db.commit();db.refresh(req);return _detail(req,user)
    submit(db,req,user);db.commit();db.refresh(req)
    attempt=max(s.attempt for s in req.steps)
    active=next(s for s in req.steps if s.attempt==attempt and s.status==StepStatus.ACTIVE)
    notices=_mail_event(db,req,active,"Approval requested",f"A {req.type.replace('_',' ').title()} request is waiting for your action.")
    result=_detail(req,user);result["mail_notices"]=notices;return result

@router.get("/{request_id}/workflow")
def workflow(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    req=_active_request(db,request_id)
    if not req or not can_view_request(req,user): raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    return _detail(req,user)["workflow"]

def _step_transition(request_id,step_id,db,user,action,comment=None,extra=None):
    req=_active_request(db,request_id)
    if not req: raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    step=db.get(RequestStep,step_id)
    if not step or step.request_id!=req.id: raise HTTPException(404,detail={"error":"not_found","message":"Workflow step not found"})
    old=req.status
    if action=="approve": approve(db,req,step_id,user,comment)
    elif action=="reject": reject(db,req,step_id,user,comment)
    else: complete_action(db,req,step_id,user,extra or {})
    db.commit();db.refresh(req)
    if action=="reject":
        notices=_mail_event(db,req,step,"Request returned for changes","The approver returned this request for changes.",comment or "")
    elif req.status==RequestStatus.COMPLETED:
        notices=_mail_event(db,req,step,"Request completed","Your compliance request has completed its workflow.")
    else:
        current=next((s for s in req.steps if s.attempt==step.attempt and s.status==StepStatus.ACTIVE),None)
        if current:
            message=f"Request #{req.id} is ready for {current.workflow_step.name}."
            if req.type=="FINANCIAL_DOCUMENTS" and current.workflow_step.assigned_role=="APPROVER":message=f"Approver: prepare the requested files for request #{req.id}. Help Desk SR number: {step.extra_data.get('sr_number','')}."
            notices=_mail_event(db,req,current,"Action required",message)
        else: notices=_mail_event(db,req,step,"Request updated",f"Request #{req.id} was updated.")
    result=_detail(req,user);result["mail_notices"]=notices;return result

@router.post("/{request_id}/steps/{step_id}/approve")
def approve_step(request_id:int,step_id:int,data:DecisionIn|None=Body(default=None),db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    return _step_transition(request_id,step_id,db,user,"approve",data.comment if data else None)
@router.post("/{request_id}/steps/{step_id}/reject")
def reject_step(request_id:int,step_id:int,data:DecisionIn,db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    return _step_transition(request_id,step_id,db,user,"reject",data.comment)
@router.post("/{request_id}/steps/{step_id}/complete")
def complete_step(request_id:int,step_id:int,data:ActionIn,db:Session=Depends(get_db),user:User=Depends(current_user),_write_user:User=Depends(deny_admin_writes)):
    return _step_transition(request_id,step_id,db,user,"complete",extra=data.extra_data)

@router.post("/{request_id}/refund-received")
def refund_received(request_id:int,data:RefundReceivedIn,db:Session=Depends(get_db),user:User=Depends(require_role("BID_TEAM")),_write_user:User=Depends(deny_admin_writes)):
    req=_active_request(db,request_id)
    if not req: raise HTTPException(404,detail={"error":"not_found","message":"Request not found"})
    if req.type not in ("EMD_CHALLAN","EMD_BG"): raise HTTPException(422,detail={"error":"invalid_request_type","message":"Refund tracking applies to EMD requests"})
    require_action(req,user,"REFUND_RECEIVED")
    from datetime import datetime,time,timezone
    req.refund_received_at=datetime.combine(data.received_date,time.min,tzinfo=timezone.utc)
    audit(db,user,"REFUND_RECEIVED",req,req.status,req.status,{"received_date":data.received_date.isoformat()})
    db.commit();return {"request_id":req.id,"refund_received_at":req.refund_received_at.isoformat()}
