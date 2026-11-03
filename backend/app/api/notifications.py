from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Notification,User
from app.core.security import current_user
router=APIRouter(prefix="/notifications",tags=["notifications"])
@router.get("")
def list_notifications(db:Session=Depends(get_db),user:User=Depends(current_user)):
    rows=db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(100)).all()
    return {"unread_count":sum(not n.is_read for n in rows),"items":[{"id":n.id,"message":n.message,"request_id":n.request_id,"is_read":n.is_read,"created_at":n.created_at.isoformat()} for n in rows]}
@router.post("/{notification_id}/read")
def mark_read(notification_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    n=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.user_id==user.id))
    if not n: raise HTTPException(404,detail={"error":"not_found","message":"Notification not found"})
    n.is_read=True;db.commit();return {"id":n.id,"is_read":True}
