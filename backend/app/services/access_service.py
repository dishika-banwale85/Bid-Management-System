from sqlalchemy import and_,exists,or_,select

from app.models import Bid,ComplianceRequest,RequestStep,User,WorkflowStep


def active_bid_clause(bid_model=Bid):
    """Shared predicate for all ordinary bid and bid-linked request queries."""
    return bid_model.deleted_at.is_(None)


def active_request_bid_clause():
    return ComplianceRequest.bid.has(active_bid_clause())


def get_active_bid(db,bid_id:int,user:User|None=None):
    statement=select(Bid).where(Bid.id==bid_id,active_bid_clause())
    if user is not None:
        statement=statement.where(bid_visibility_clause(user))
    return db.scalar(statement)


def request_visibility_clause(user:User):
    role=user.role.name
    if role in {"ADMIN","APPROVER","PACE_COORDINATOR"}:
        return True
    if role=="BID_TEAM":
        return ComplianceRequest.created_by==user.id
    assigned_or_acted=exists(select(RequestStep.id).join(WorkflowStep,WorkflowStep.id==RequestStep.step_id).where(
        RequestStep.request_id==ComplianceRequest.id,
        or_(WorkflowStep.assigned_role==role,RequestStep.acted_by==user.id),
    ))
    return assigned_or_acted


def bid_visibility_clause(user:User):
    role=user.role.name
    if role in {"ADMIN","APPROVER","PACE_COORDINATOR"}:
        return active_bid_clause()
    if role=="BID_TEAM":
        return and_(active_bid_clause(),Bid.created_by==user.id)
    visible_request=exists(select(ComplianceRequest.id).where(
        ComplianceRequest.bid_id==Bid.id,
        request_visibility_clause(user),
    ))
    return and_(active_bid_clause(),visible_request)


def can_view_request(req:ComplianceRequest,user:User)->bool:
    role=user.role.name
    if role in {"ADMIN","APPROVER","PACE_COORDINATOR"}:return True
    if role=="BID_TEAM":return req.created_by==user.id
    return any(step.workflow_step.assigned_role==role or step.acted_by==user.id for step in req.steps)


def can_view_bid(bid:Bid,user:User)->bool:
    if bid.deleted_at is not None:return False
    role=user.role.name
    if role in {"ADMIN","APPROVER","PACE_COORDINATOR"}:return True
    if role=="BID_TEAM":return bid.created_by==user.id
    return any(can_view_request(req,user) for req in bid.requests)
