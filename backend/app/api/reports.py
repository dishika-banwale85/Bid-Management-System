from datetime import date,timedelta
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session,selectinload
from app.db import get_db
from app.models import Bid,ComplianceRequest,User,AuditLog
from app.core.security import current_user
from app.services.access_service import active_bid_clause,request_visibility_clause,bid_visibility_clause
from app.services.report_service import bid_summary_pdf,requests_xlsx,refunds_xlsx
router=APIRouter(prefix="/reports",tags=["reports"])
def _audit_export(db,user,kind,entity_id=0):
    db.add(AuditLog(user_id=user.id,action="REPORT_EXPORTED",entity_type=kind,entity_id=entity_id,detail={"report":kind}));db.commit()
def _filtered(db,user,status=None,request_type=None,bid_id=None,date_from=None,date_to=None,search=None):
    q=select(ComplianceRequest).options(selectinload(ComplianceRequest.bid)).join(Bid).where(request_visibility_clause(user),active_bid_clause())
    if status:q=q.where(ComplianceRequest.status==status)
    if request_type:q=q.where(ComplianceRequest.type==request_type)
    if bid_id:q=q.where(ComplianceRequest.bid_id==bid_id)
    if date_from:q=q.where(ComplianceRequest.created_at>=date_from)
    if date_to:q=q.where(ComplianceRequest.created_at<date_to+timedelta(days=1))
    if search:q=q.where(Bid.client_name.ilike(f"%{search}%")|Bid.rfp_reference.ilike(f"%{search}%"))
    return db.scalars(q.order_by(ComplianceRequest.created_at.desc())).all()
@router.get("/bids/{bid_id}/summary.pdf")
def bid_pdf(bid_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not db.scalar(select(Bid.id).where(Bid.id==bid_id,bid_visibility_clause(user))):raise HTTPException(404,detail="Bid not found")
    visible_ids=None
    if user.role.name!="ADMIN":
        visible_ids=[row.id for row in _filtered(db,user,bid_id=bid_id)]
    buf=bid_summary_pdf(db,bid_id,user.role.name=="ADMIN",visible_ids)
    if buf is None:raise HTTPException(404,detail="Bid not found")
    _audit_export(db,user,"BidSummaryPDF",bid_id)
    return StreamingResponse(buf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="BidEase_Bid_{bid_id}_Summary.pdf"'})
@router.get("/requests.xlsx")
def request_xlsx(status:str|None=None,request_type:str|None=None,bid_id:int|None=None,date_from:date|None=None,date_to:date|None=None,search:str|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    buf=requests_xlsx(_filtered(db,user,status,request_type,bid_id,date_from,date_to,search),user.role.name=="ADMIN")
    _audit_export(db,user,"RequestsExcel")
    return StreamingResponse(buf,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="BidEase_Requests.xlsx"'})
@router.get("/refunds.xlsx")
def refund_xlsx(db:Session=Depends(get_db),user:User=Depends(current_user)):
    rows=db.scalars(select(ComplianceRequest).options(selectinload(ComplianceRequest.bid)).join(Bid).where(ComplianceRequest.type.in_(["EMD_CHALLAN","EMD_BG"]),request_visibility_clause(user),active_bid_clause())).all()
    buf=refunds_xlsx(rows,user.role.name=="ADMIN")
    _audit_export(db,user,"RefundsExcel")
    return StreamingResponse(buf,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="BidEase_Refunds.xlsx"'})
