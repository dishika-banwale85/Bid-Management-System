from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import uuid

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import current_user, require_role
from app.core.config import UPLOAD_DIR
from app.db import get_db
from app.models import AuditLog, Bid, BidChecklistNA, BidDocument, BidStatus, ComplianceRequest, Document, RequestStatus, User
from app.schemas.requests import BidChecklistNAIn, BidDetailOut, BidIn, BidOut, BidUpdate
from app.services.access_service import active_bid_clause, bid_visibility_clause, can_view_request, get_active_bid
from app.services.workflow_service import DOCUMENT_LABELS, REQUIRED_DOCUMENT_ORDER
from app.services.trash_service import bid_request_stats, permanently_delete_bid
from app.services.bid_rfp import MAX_RFP_BYTES, validate_rfp_file
from app.services.trash_service import unlink_stored_files

router=APIRouter(prefix="/bids",tags=["bids"])
TYPE_LABELS={"TENDER_FEE":"Tender Fee","EMD_CHALLAN":"EMD by Challan","EMD_BG":"EMD by Bank Guarantee","FINANCIAL_DOCUMENTS":"Financial Documents","POWER_OF_ATTORNEY":"Power of Attorney","DECLARATION":"Declaration / Undertaking","HR_DOCUMENTS":"HR Documents"}


class BidDeleteIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


def _delete_permissions(bid, user, submitted_count):
    admin = user.role.name == "ADMIN"
    creator = user.role.name == "BID_TEAM" and bid.created_by == user.id
    control = admin or creator
    can_delete = admin or (creator and submitted_count == 0)
    reason = None
    if not control:
        reason = "Only the bid creator or an Admin can move this bid to Trash."
    elif creator and submitted_count:
        reason = f"This bid has {submitted_count} submitted compliance request(s) and cannot be deleted by a Team Member."
    return can_delete, control, reason


def _checklist_rollups(db:Session,bid_ids:list[int],exclude_drafts:bool=False)->dict[int,dict]:
    """One set-based query returns required-document totals for every supplied bid."""
    if not bid_ids:return {}
    document_types=sorted({key for keys in REQUIRED_DOCUMENT_ORDER.values() for key in keys})
    statement=(select(Bid.id,ComplianceRequest.id,ComplianceRequest.type,ComplianceRequest.status,
                      Document.document_type,BidChecklistNA.request_type)
        .select_from(Bid)
        .outerjoin(ComplianceRequest,ComplianceRequest.bid_id==Bid.id)
        .outerjoin(Document,and_(Document.request_id==ComplianceRequest.id,Document.document_type.in_(document_types)))
        .outerjoin(BidChecklistNA,BidChecklistNA.bid_id==Bid.id)
        .where(Bid.id.in_(bid_ids),active_bid_clause()))
    if exclude_drafts:
        statement=statement.where(or_(ComplianceRequest.id.is_(None),ComplianceRequest.status!=RequestStatus.DRAFT))
    rows=db.execute(statement).all()
    requests={bid_id:{} for bid_id in bid_ids}
    attached={bid_id:{} for bid_id in bid_ids}
    not_applicable={bid_id:set() for bid_id in bid_ids}
    for bid_id,request_id,request_type,status,document_type,na_type in rows:
        if na_type:not_applicable[bid_id].add(na_type)
        if request_id is None or request_type not in REQUIRED_DOCUMENT_ORDER:continue
        requests[bid_id].setdefault(request_type,{})[request_id]=status.value if hasattr(status,"value") else status
        if document_type:
            attached[bid_id].setdefault(request_id,set()).add(document_type)
    result={}
    for bid_id in bid_ids:
        required_total=attached_total=0
        for request_type,keys in REQUIRED_DOCUMENT_ORDER.items():
            if request_type in not_applicable[bid_id]:continue
            type_requests=requests[bid_id].get(request_type,{})
            if not type_requests:
                required_total+=len(keys)
                continue
            for request_id in type_requests:
                required_total+=len(keys)
                attached_total+=len(set(keys)&attached[bid_id].get(request_id,set()))
        result[bid_id]={"required_total":required_total,"attached_total":attached_total,
                        "missing_count":max(0,required_total-attached_total),
                        "checklist_percent":int(attached_total*100/required_total+0.5) if required_total else 0}
    return result


def bid_json(b,user=None,checklist=None,stats=None):
    requests=[r for r in b.requests if user is None or can_view_request(r,user)]
    total=len(requests)
    complete=sum(r.status.value=="COMPLETED" for r in requests)
    stats=stats or {}
    submitted_count=stats.get("submitted_request_count",sum(r.status!=RequestStatus.DRAFT for r in requests))
    can_delete,can_delete_control,delete_blocked_reason=_delete_permissions(b,user,submitted_count) if user else (False,False,None)
    return {
        "id":b.id,
        "client_name":b.client_name,
        "department":b.department,
        "rfp_reference":b.rfp_reference,
        "rfp_number":b.rfp_reference,
        "rfp_published_date":b.rfp_published_date.isoformat() if b.rfp_published_date else None,
        "project_title":b.project_title,
        "submission_deadline":b.submission_deadline.isoformat() if b.submission_deadline else None,
        "tender_opening_date":b.tender_opening_date.isoformat() if b.tender_opening_date else None,
        "prebid_meeting_date":b.prebid_meeting_date.isoformat() if b.prebid_meeting_date else None,
        "prebid_query_deadline":b.prebid_query_deadline.isoformat() if b.prebid_query_deadline else None,
        "prebid_meeting_na":bool(b.prebid_meeting_na),
        "prebid_query_na":bool(b.prebid_query_na),
        "client_address":b.client_address,
        "status":b.status,
        "bid_status":b.bid_status.value if hasattr(b.bid_status,"value") else b.bid_status,
        "rfp":{"id":b.rfp_document.id,"filename":b.rfp_document.original_name,"size":b.rfp_document.size,"uploaded_at":b.rfp_document.uploaded_at.isoformat()} if b.rfp_document else None,
        "can_manage_bid":bool(user and user.role.name=="BID_TEAM" and user.id==b.created_by),
        "request_count":total,
        "completed_count":complete,
        "progress":round(complete*100/total) if total else 0,
        "checklist_percent":(checklist or {}).get("checklist_percent",0),
        "missing_count":(checklist or {}).get("missing_count",0),
        "can_delete":can_delete,
        "can_delete_control":can_delete_control,
        "delete_blocked_reason":delete_blocked_reason,
        "draft_request_count":stats.get("draft_request_count",sum(r.status==RequestStatus.DRAFT for r in requests)),
        "submitted_request_count":submitted_count,
        "file_count":stats.get("file_count",0),
    }


def _check_duplicate(db,rfp_number,exclude_bid_id=None):
    statement=select(Bid.id).where(func.lower(Bid.rfp_reference)==rfp_number.strip().lower(),active_bid_clause())
    if exclude_bid_id is not None:
        statement=statement.where(Bid.id!=exclude_bid_id)
    return db.scalar(statement) is not None


def _validate_create_dates(data):
    today=datetime.now(ZoneInfo("Asia/Kolkata")).date()
    fields=[]
    if data.submission_deadline<today:
        fields.append({"loc":["submission_deadline"],"msg":"Bid submission date cannot be before today when creating a bid","type":"date_from_past"})
    if data.tender_opening_date<today:
        fields.append({"loc":["tender_opening_date"],"msg":"Bid opening date cannot be before today when creating a bid","type":"date_from_past"})
    if fields:
        raise HTTPException(status_code=422,detail={"error":"validation_error","message":"Correct the date fields and try again","fields":fields})


def _validate_update_dates(bid,changes):
    published=changes.get("rfp_published_date",bid.rfp_published_date)
    submission=changes.get("submission_deadline",bid.submission_deadline)
    opening=changes.get("tender_opening_date",bid.tender_opening_date)
    meeting=None if changes.get("prebid_meeting_na") is True else changes.get("prebid_meeting_date",bid.prebid_meeting_date)
    query=None if changes.get("prebid_query_na") is True else changes.get("prebid_query_deadline",bid.prebid_query_deadline)
    fields=[]
    if published and submission and published>submission:
        fields.append({"loc":["rfp_published_date"],"msg":"RFP published date must be on or before bid submission date","type":"date_order"})
    if submission and opening and submission>opening:
        fields.append({"loc":["tender_opening_date"],"msg":"Bid opening date must be on or after bid submission date","type":"date_order"})
    if published and submission:
        for name,value in (("prebid_meeting_date",meeting),("prebid_query_deadline",query)):
            if value and not published<=value<=submission:
                fields.append({"loc":[name],"msg":f"{name} must be between RFP published date and bid submission date","type":"date_range"})
    if fields:
        raise HTTPException(status_code=422,detail={"error":"validation_error","message":"Correct the date fields and try again","fields":fields})


@router.get("/check-rfp")
def check_rfp(rfp_number:str=Query(min_length=1,max_length=120),exclude_bid_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    duplicate=_check_duplicate(db,rfp_number,exclude_bid_id)
    return {"exists":duplicate,"message":"A bid with this RFP number already exists" if duplicate else None}


@router.get("/trash")
def list_bid_trash(page:int=1,page_size:int=20,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role.name not in {"BID_TEAM","ADMIN"}:
        raise HTTPException(403,detail={"error":"forbidden","message":"Trash is available to Team Members and Admins"})
    page=max(1,page);page_size=min(100,max(1,page_size))
    statement=select(Bid,User.full_name).outerjoin(User,User.id==Bid.deleted_by).where(Bid.deleted_at.is_not(None))
    if user.role.name=="BID_TEAM":statement=statement.where(Bid.created_by==user.id)
    total=db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows=db.execute(statement.order_by(Bid.deleted_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    stats=bid_request_stats(db,[bid.id for bid,_ in rows])
    return {"items":[{"id":bid.id,"client_name":bid.client_name,"project_title":bid.project_title,"rfp_reference":bid.rfp_reference,"submission_deadline":bid.submission_deadline.isoformat() if bid.submission_deadline else None,"delete_reason":bid.delete_reason,"deleted_at":bid.deleted_at.isoformat() if bid.deleted_at else None,"deleted_by_name":name or "Unknown user",**stats.get(bid.id,{"draft_request_count":0,"submitted_request_count":0,"file_count":0})} for bid,name in rows],"page":page,"page_size":page_size,"total":total,"pages":(total+page_size-1)//page_size}


@router.get("",response_model=list[BidOut])
def list_bids(search:str|None=None,q:str|None=None,date_from:date|None=None,date_to:date|None=None,client:str|None=None,request_type:str|None=None,tab:str|None=None,status:str|None=None,bid_status:BidStatus|None=None,checklist_bucket:str|None=None,submission_month:str|None=None,overdue:bool|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    search=(search or q or "").strip()
    statement=select(Bid).options(selectinload(Bid.requests),selectinload(Bid.rfp_document)).where(bid_visibility_clause(user))
    if bid_status:statement=statement.where(Bid.bid_status==bid_status)
    if search:
        pattern=f"%{search}%"
        statement=statement.where(or_(Bid.client_name.ilike(pattern),Bid.project_title.ilike(pattern),Bid.rfp_reference.ilike(pattern)))
    if client and client.strip():statement=statement.where(Bid.client_name.ilike(f"%{client.strip()}%"))
    if date_from:statement=statement.where(Bid.created_at>=datetime.combine(date_from,time.min,tzinfo=timezone.utc))
    if date_to:statement=statement.where(Bid.created_at<datetime.combine(date_to+timedelta(days=1),time.min,tzinfo=timezone.utc))
    if submission_month:
        try:
            year,month=(int(part) for part in submission_month.split('-',1))
            month_start=date(year,month,1)
            month_end=date(year+1,1,1) if month==12 else date(year,month+1,1)
            statement=statement.where(Bid.submission_deadline>=month_start,Bid.submission_deadline<month_end)
        except (ValueError,TypeError):
            raise HTTPException(422,detail="submission_month must use YYYY-MM format")
    if request_type:
        statement=statement.where(exists(select(ComplianceRequest.id).where(ComplianceRequest.bid_id==Bid.id,ComplianceRequest.type==request_type,ComplianceRequest.status!=RequestStatus.DRAFT)))
    rows=db.scalars(statement.order_by(Bid.submission_deadline)).all()
    rollups=_checklist_rollups(db,[b.id for b in rows])
    stats=bid_request_stats(db,[b.id for b in rows])
    def effective_status(bid):
        reqs=[req for req in bid.requests if req.status!=RequestStatus.DRAFT and can_view_request(req,user)]
        if str(bid.status or "").upper() in {"COMPLETED","CLOSED"} or (reqs and all(req.status==RequestStatus.COMPLETED for req in reqs)):
            return "COMPLETED"
        return "IN_PROGRESS"
    result=[]
    for bid in rows:
        bid_status=effective_status(bid)
        if status and status.upper()!=bid_status:continue
        if tab and tab.lower()=="completed" and bid_status!="COMPLETED":continue
        if tab and tab.lower() in {"ongoing","not_completed"} and bid_status=="COMPLETED":continue
        metrics=rollups.get(bid.id,{})
        percent=metrics.get("checklist_percent",0)
        bucket=("0-25" if percent<=25 else "26-50" if percent<=50 else "51-75" if percent<=75 else "76-100")
        if checklist_bucket and checklist_bucket!=bucket:continue
        if overdue is not None:
            today=datetime.now(ZoneInfo("Asia/Kolkata")).date()
            bid_overdue=bool(bid.submission_deadline and bid.submission_deadline<today and bid_status!="COMPLETED")
            refund_overdue=any(req.type=="EMD_CHALLAN" and not req.refund_received_at and str((req.form_data or {}).get("expected_refund_date", ""))[:10] < today.isoformat() for req in bid.requests if req.status!=RequestStatus.DRAFT and can_view_request(req,user))
            if overdue != (bid_overdue or refund_overdue):continue
        result.append(bid_json(bid,user,metrics,stats.get(bid.id)))
    return result


async def _parse_create_bid(request:Request):
    content_type=request.headers.get("content-type","").lower()
    if content_type.startswith("multipart/form-data"):
        form=await request.form()
        raw_data=form.get("bid_data")
        if not isinstance(raw_data,str):
            raise HTTPException(422,detail="bid_data is required")
        try:
            data=BidIn.model_validate_json(raw_data)
        except ValidationError as exc:
            raise HTTPException(422,detail=exc.errors())
        uploaded=form.get("rfp_file")
        if uploaded is not None and not hasattr(uploaded,"read"):
            raise HTTPException(422,detail="Invalid RFP upload")
        if not uploaded:return data,None,None,None
        raw=await uploaded.read(MAX_RFP_BYTES+1)
        try:
            extension,content_type=validate_rfp_file(uploaded.filename or "",raw)
        except ValueError as exc:
            raise HTTPException(422,detail={"error":"invalid_rfp_file","message":str(exc)})
        return data,uploaded,raw,(extension,content_type)
    try:
        data=BidIn.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(422,detail=exc.errors())
    return data,None,None,None


@router.post("",response_model=BidOut,status_code=201)
async def create_bid(request:Request,db:Session=Depends(get_db),user:User=Depends(require_role("BID_TEAM","ADMIN"))):
    data,uploaded,raw,file_info=await _parse_create_bid(request)
    if uploaded and user.role.name!="BID_TEAM":
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the Team Member who creates the bid can upload its RFP"})
    if user.role.name=="ADMIN" and data.bid_status!=BidStatus.NOT_SUBMITTED:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only Team Members can set the bid status"})
    if data.bid_status==BidStatus.SUBMITTED and not uploaded:
        raise HTTPException(422,detail={"error":"rfp_required","message":"Attach the RFP before marking this bid as Submitted"})
    _validate_create_dates(data)
    values=data.model_dump()
    if _check_duplicate(db,values["rfp_reference"]):
        raise HTTPException(409,detail={"error":"conflict","message":"An active bid already uses this RFP number"})
    values["department"]=values["department"] or ""
    bid=Bid(**values,created_by=user.id)
    db.add(bid)
    db.flush()
    stored=None
    db.add(AuditLog(user_id=user.id,action="BID_CREATED",entity_type="Bid",entity_id=bid.id,detail={"client_name":bid.client_name,"rfp_reference":bid.rfp_reference,"project_title":bid.project_title,"bid_status":bid.bid_status.value}))
    if uploaded and raw is not None and file_info:
        extension,actual_type=file_info
        UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
        stored=f"{uuid.uuid4().hex}{extension}"
        (UPLOAD_DIR/stored).write_bytes(raw)
        bid.rfp_document=BidDocument(bid_id=bid.id,document_type="RFP",original_name=Path(uploaded.filename or "RFP").name[:255],stored_name=stored,size=len(raw),content_type=actual_type,uploaded_by=user.id)
        db.add(AuditLog(user_id=user.id,action="BID_RFP_UPLOADED",entity_type="Bid",entity_id=bid.id,detail={"filename":bid.rfp_document.original_name,"size":len(raw)}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        if stored:unlink_stored_files([stored])
        raise
    db.refresh(bid)
    return bid_json(bid,user,_checklist_rollups(db,[bid.id]).get(bid.id),bid_request_stats(db,[bid.id]).get(bid.id))


@router.get("/{bid_id}",response_model=BidDetailOut)
def get_bid(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=db.scalar(select(Bid).options(selectinload(Bid.requests),selectinload(Bid.rfp_document)).where(Bid.id==bid_id,bid_visibility_clause(user)))
    if not bid:
        deleted=db.scalar(select(Bid).where(Bid.id==bid_id,Bid.deleted_at.is_not(None)))
        if deleted and (user.role.name=="ADMIN" or (user.role.name=="BID_TEAM" and user.id==deleted.created_by)):
            raise HTTPException(404,detail={"error":"bid_deleted","message":"This bid was deleted"})
        raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    return {**bid_json(bid,user,_checklist_rollups(db,[bid.id]).get(bid.id),bid_request_stats(db,[bid.id]).get(bid.id)),"requests":[{"id":r.id,"type":r.type,"status":r.status.value,"created_at":r.created_at.isoformat()} for r in bid.requests if can_view_request(r,user)]}


def _owned_bid_for_rfp_write(db:Session,bid_id:int,user:User)->Bid:
    bid=get_active_bid(db,bid_id)
    if bid is None:
        raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    if user.role.name!="BID_TEAM" or bid.created_by!=user.id:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the Team Member who created this bid can manage its RFP"})
    return bid


@router.post("/{bid_id}/rfp")
async def upload_bid_rfp(bid_id:int,file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=_owned_bid_for_rfp_write(db,bid_id,user)
    raw=await file.read(MAX_RFP_BYTES+1)
    try:
        extension,content_type=validate_rfp_file(file.filename or "",raw)
    except ValueError as exc:
        raise HTTPException(422,detail={"error":"invalid_rfp_file","message":str(exc)})
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    stored=f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR/stored).write_bytes(raw)
    old=bid.rfp_document
    old_stored=old.stored_name if old else None
    original_name=Path(file.filename or "RFP").name[:255]
    action="BID_RFP_REPLACED" if old else "BID_RFP_UPLOADED"
    db.add(AuditLog(user_id=user.id,action=action,entity_type="Bid",entity_id=bid.id,detail={"filename":original_name,"size":len(raw),"replaced_filename":old.original_name if old else None}))
    if old:
        old.original_name=original_name;old.stored_name=stored;old.size=len(raw);old.content_type=content_type;old.uploaded_by=user.id;old.uploaded_at=datetime.now(timezone.utc)
    else:
        bid.rfp_document=BidDocument(bid_id=bid.id,document_type="RFP",original_name=original_name,stored_name=stored,size=len(raw),content_type=content_type,uploaded_by=user.id)
    try:
        db.commit()
    except Exception:
        db.rollback();unlink_stored_files([stored]);raise
    db.refresh(bid)
    if old_stored:unlink_stored_files([old_stored])
    document=bid.rfp_document
    return {"id":document.id,"filename":document.original_name,"size":document.size,"uploaded_at":document.uploaded_at.isoformat()}


@router.get("/{bid_id}/rfp/download")
def download_bid_rfp(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=get_active_bid(db,bid_id,user)
    if bid is None:raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    document=bid.rfp_document
    if not document:raise HTTPException(404,detail={"error":"not_found","message":"No RFP file is attached to this bid"})
    path=UPLOAD_DIR/document.stored_name
    if not path.is_file():raise HTTPException(404,detail={"error":"not_found","message":"Stored RFP file not found"})
    return FileResponse(path,filename=document.original_name,media_type=document.content_type)


@router.delete("/{bid_id}/rfp",status_code=204)
def remove_bid_rfp(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=_owned_bid_for_rfp_write(db,bid_id,user)
    document=bid.rfp_document
    if not document:raise HTTPException(404,detail={"error":"not_found","message":"No RFP file is attached to this bid"})
    stored=document.stored_name
    db.add(AuditLog(user_id=user.id,action="BID_RFP_REMOVED",entity_type="Bid",entity_id=bid.id,detail={"filename":document.original_name,"size":document.size}))
    db.delete(document);db.commit();unlink_stored_files([stored])
    return Response(status_code=204)


@router.delete("/{bid_id}")
def move_bid_to_trash(bid_id:int,data:BidDeleteIn|None=Body(default=None),db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role.name not in {"BID_TEAM","ADMIN"}:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid creator or Admin can move a bid to Trash"})
    bid=get_active_bid(db,bid_id)
    if bid is None:raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    submitted_count=db.scalar(select(func.count(ComplianceRequest.id)).where(ComplianceRequest.bid_id==bid.id,ComplianceRequest.status!=RequestStatus.DRAFT)) or 0
    if user.role.name=="BID_TEAM":
        if bid.created_by!=user.id:
            raise HTTPException(403,detail={"error":"forbidden","message":"You can move only bids you created to Trash"})
        if submitted_count:
            raise HTTPException(409,detail={"error":"conflict","message":f"This bid has {submitted_count} submitted compliance request(s) and cannot be deleted by a Team Member.","submitted_request_count":submitted_count})
    reason=(data.reason or "").strip() if data else ""
    if user.role.name=="ADMIN" and len(reason)<5:
        raise HTTPException(422,detail={"error":"validation_error","message":"Admin delete reason must be at least 5 characters"})
    bid.deleted_at=datetime.now(timezone.utc);bid.deleted_by=user.id;bid.delete_reason=reason or None
    db.add(AuditLog(user_id=user.id,action="BID_MOVED_TO_TRASH",entity_type="Bid",entity_id=bid.id,detail={"rfp_reference":bid.rfp_reference,"delete_reason":bid.delete_reason,"draft_request_count":int(db.scalar(select(func.count(ComplianceRequest.id)).where(ComplianceRequest.bid_id==bid.id,ComplianceRequest.status==RequestStatus.DRAFT)) or 0),"submitted_request_count":int(submitted_count)}))
    db.commit()
    return {"id":bid.id,"deleted_at":bid.deleted_at.isoformat(),"message":"Bid moved to Trash"}


@router.post("/{bid_id}/restore")
def restore_bid(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role.name not in {"BID_TEAM","ADMIN"}:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid creator or Admin can restore a bid"})
    bid=db.scalar(select(Bid).where(Bid.id==bid_id,Bid.deleted_at.is_not(None)))
    if bid is None:raise HTTPException(409,detail={"error":"conflict","message":"This bid is not in Trash"})
    if user.role.name=="BID_TEAM" and bid.created_by!=user.id:
        raise HTTPException(403,detail={"error":"forbidden","message":"You can restore only bids you created"})
    conflict=db.scalar(select(Bid.id).where(func.lower(Bid.rfp_reference)==bid.rfp_reference.lower(),active_bid_clause(),Bid.id!=bid.id))
    if conflict:
        raise HTTPException(409,detail={"error":"conflict","message":"Another active bid already uses this RFP number. Change that bid's RFP number before restoring."})
    bid.deleted_at=None;bid.deleted_by=None;bid.delete_reason=None
    db.add(AuditLog(user_id=user.id,action="BID_RESTORED",entity_type="Bid",entity_id=bid.id,detail={"rfp_reference":bid.rfp_reference}))
    db.commit();db.refresh(bid)
    return {"id":bid.id,"message":"Bid restored"}


@router.delete("/{bid_id}/permanent",status_code=204)
def permanently_delete_bid_route(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role.name!="ADMIN":
        raise HTTPException(403,detail={"error":"forbidden","message":"Only Admin can permanently delete bids"})
    bid=db.get(Bid,bid_id)
    if bid is None:raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    if bid.deleted_at is None:
        raise HTTPException(409,detail={"error":"conflict","message":"Only bids in Trash can be permanently deleted"})
    permanently_delete_bid(db,bid.id,user.id)
    return Response(status_code=204)


@router.get("/{bid_id}/checklist")
def get_bid_checklist(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from app.models import ComplianceRequest
    bid=db.scalar(select(Bid).options(selectinload(Bid.requests).selectinload(ComplianceRequest.documents)).where(Bid.id==bid_id,bid_visibility_clause(user)))
    if not bid:raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    na_types=set(db.scalars(select(BidChecklistNA.request_type).where(BidChecklistNA.bid_id==bid.id)).all())
    visible=[req for req in bid.requests if can_view_request(req,user)]
    type_data=[]
    required_total=attached_total=0
    for request_type,keys in REQUIRED_DOCUMENT_ORDER.items():
        type_requests=[req for req in visible if req.type==request_type]
        applicable=request_type not in na_types
        document_groups=[]
        if request_type in na_types:
            state="NOT_APPLICABLE"
        elif not type_requests:
            state="NOT_STARTED"
        else:
            states={req.status.value for req in type_requests}
            if states.issubset({"DRAFT","REJECTED"}):state="DRAFT"
            elif states=={"COMPLETED"}:state="COMPLETED"
            else:state="SUBMITTED"
            for req in sorted(type_requests,key=lambda item:item.id):
                latest={}
                for doc in sorted(req.documents,key=lambda item:(item.document_type or "",item.version,item.id)):
                    if doc.document_type:latest[doc.document_type]=doc
                document_groups.append({"request_id":req.id,"status":req.status.value,"documents":[{"key":key,"label":DOCUMENT_LABELS.get(key,key.replace("_"," ").title()),"attached":key in latest,"document_id":latest[key].id if key in latest else None,"filename":latest[key].filename if key in latest else None} for key in keys]})
        required_count=0 if not applicable else (len(keys) if not type_requests else len(keys)*len(type_requests))
        attached_count=0 if not applicable else sum(sum(doc["attached"] for doc in group["documents"]) for group in document_groups)
        required_total+=required_count
        attached_total+=attached_count
        type_data.append({"request_type":request_type,"label":TYPE_LABELS.get(request_type,request_type.replace("_"," ").title()),"applicable":applicable,"state":state,"requests":document_groups,"required_count":required_count,"attached_count":attached_count})
    missing_total=max(0,required_total-attached_total)
    return {"bid_id":bid.id,"request_types":type_data,"required_total":required_total,"attached_total":attached_total,"missing_total":missing_total,"percent":int(attached_total*100/required_total+0.5) if required_total else 0,"can_mark_na":user.role.name=="BID_TEAM" and bid.created_by==user.id}


@router.put("/{bid_id}/checklist/na")
def set_checklist_applicability(bid_id:int,data:BidChecklistNAIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=get_active_bid(db,bid_id)
    if not bid:raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    if user.role.name!="BID_TEAM" or bid.created_by!=user.id:
        raise HTTPException(403,detail={"error":"forbidden","message":"Only the bid creator can mark a request type not applicable"})
    if data.request_type not in REQUIRED_DOCUMENT_ORDER:
        raise HTTPException(422,detail={"error":"invalid_request_type","message":"This request type is not active"})
    existing=db.get(BidChecklistNA,(bid_id,data.request_type))
    if data.applicable:
        if existing:db.delete(existing)
    elif existing:
        existing.marked_by=user.id
        from app.models import now
        existing.marked_at=now()
    else:
        db.add(BidChecklistNA(bid_id=bid_id,request_type=data.request_type,marked_by=user.id))
    db.add(AuditLog(user_id=user.id,action="BID_CHECKLIST_NA_UPDATED",entity_type="Bid",entity_id=bid.id,detail={"request_type":data.request_type,"applicable":data.applicable}))
    db.commit()
    return get_bid_checklist(bid_id,db,user)


@router.put("/{bid_id}",response_model=BidOut)
@router.patch("/{bid_id}",response_model=BidOut)
def update_bid(bid_id:int,data:BidUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    bid=get_active_bid(db,bid_id)
    if not bid:
        raise HTTPException(404,detail={"error":"not_found","message":"Bid not found"})
    if user.role.name!="BID_TEAM":
        raise HTTPException(403,detail={"error":"forbidden","message":"Only Team Members can edit bids"})
    if bid.created_by!=user.id:
        raise HTTPException(403,detail={"error":"forbidden","message":"You can edit only bids you own"})
    changes=data.model_dump(exclude_unset=True)
    if changes.get("bid_status")==BidStatus.SUBMITTED and not bid.rfp_document:
        raise HTTPException(422,detail={"error":"rfp_required","message":"Attach the RFP before marking this bid as Submitted"})
    if bid.status.upper() in {"COMPLETED","CLOSED"} and any(key != "bid_status" for key in changes):
        raise HTTPException(409,detail={"error":"conflict","message":"Only open bids can be edited"})

    non_nullable={"client_name","rfp_reference","submission_deadline","tender_opening_date","prebid_meeting_na","prebid_query_na"}
    null_fields=sorted(key for key in non_nullable if key in changes and changes[key] is None)
    if null_fields:
        raise HTTPException(status_code=422,detail={"error":"validation_error","message":"These bid fields cannot be cleared","fields":[{"loc":[key],"msg":f"{key} cannot be empty","type":"missing"} for key in null_fields]})
    if changes.get("prebid_meeting_na") is True:
        changes["prebid_meeting_date"]=None
    if changes.get("prebid_query_na") is True:
        changes["prebid_query_deadline"]=None
    if "rfp_reference" in changes and _check_duplicate(db,changes["rfp_reference"],exclude_bid_id=bid.id):
        raise HTTPException(409,detail={"error":"conflict","message":"An active bid already uses this RFP number"})
    # A status-only edit does not change any dates; don't block it because an
    # older bid has dates that would fail today's edit-time validation.
    if any(key != "bid_status" for key in changes):
        _validate_update_dates(bid,changes)
    previous_bid_status=bid.bid_status.value if hasattr(bid.bid_status,"value") else bid.bid_status
    next_bid_status=changes.get("bid_status")
    for key,value in changes.items():
        if key=="department":
            value=value or ""
        setattr(bid,key,value)
    db.add(AuditLog(user_id=user.id,action="BID_UPDATED",entity_type="Bid",entity_id=bid.id,detail={"changed_fields":sorted(changes)}))
    if next_bid_status is not None and next_bid_status.value!=previous_bid_status:
        db.add(AuditLog(user_id=user.id,action="BID_STATUS_UPDATED",entity_type="Bid",entity_id=bid.id,old_status=previous_bid_status,new_status=next_bid_status.value,detail={"old_status":previous_bid_status,"new_status":next_bid_status.value}))
    db.commit()
    db.refresh(bid)
    return bid_json(bid,user,_checklist_rollups(db,[bid.id]).get(bid.id),bid_request_stats(db,[bid.id]).get(bid.id))
