from sqlalchemy import select

from app.models import Bid,ComplianceRequest,User


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
    return True


def bid_visibility_clause(user:User):
    return active_bid_clause()


def can_view_request(req:ComplianceRequest,user:User)->bool:
    return True


def can_view_bid(bid:Bid,user:User)->bool:
    return bid.deleted_at is None
