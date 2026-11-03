from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User,RequestStep,ComplianceRequest,StepStatus,StepKind,RequestStatus
from app.core.security import current_user,require_role
from app.services.access_service import active_request_bid_clause
router=APIRouter(tags=["queues"])
def _queue(db,user,kind):
    query=select(RequestStep).join(RequestStep.request).join(RequestStep.workflow_step).where(RequestStep.status==StepStatus.ACTIVE,RequestStep.request.has(status=RequestStatus.IN_APPROVAL),RequestStep.workflow_step.has(assigned_role=user.role.name),active_request_bid_clause())
    if kind is not None:query=query.where(RequestStep.workflow_step.has(step_kind=kind))
    rows=db.scalars(query).all()
    return [{"request_id":s.request_id,"step_id":s.id,"step_name":s.workflow_step.name,"type":s.request.type,"status":s.request.status.value,"bid_id":s.request.bid_id,"client_name":s.request.bid.client_name,"created_by":s.request.creator.full_name,"attempt":s.attempt,"step_kind":s.workflow_step.step_kind.value} for s in rows if s.request.created_by!=user.id or user.role.name=="BID_TEAM"]
@router.get("/approvals/pending")
def approvals(db:Session=Depends(get_db),user:User=Depends(require_role("APPROVER"))): return _queue(db,user,None)
@router.get("/operations/queue")
def operations(db:Session=Depends(get_db),user:User=Depends(require_role("APPROVER"))): return _queue(db,user,StepKind.ACTION)
@router.get("/actions/pending")
def actions(db:Session=Depends(get_db),user:User=Depends(require_role("BID_TEAM","APPROVER","PACE_COORDINATOR"))): return _queue(db,user,StepKind.ACTION)
