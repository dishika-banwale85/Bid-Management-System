from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Contact,User,AuditLog
from app.schemas.requests import ContactIn
from app.core.security import current_user,require_role
router=APIRouter(prefix="/contacts",tags=["contacts"])
def item(c): return {"id":c.id,"request_type":c.request_type,"contact_type":c.contact_type,"name":c.name,"designation":c.designation,"department":c.department,"email":c.email,"is_active":c.is_active}
@router.get("")
def list_contacts(request_type:str|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    q=select(Contact).where(Contact.is_active.is_(True))
    if request_type:q=q.where((Contact.request_type==request_type)|(Contact.request_type.is_(None)))
    return [item(c) for c in db.scalars(q.order_by(Contact.contact_type,Contact.name)).all()]
@router.post("")
def create_contact(data:ContactIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    c=Contact(**data.model_dump());db.add(c);db.flush();db.add(AuditLog(user_id=user.id,action="CONTACT_CREATED",entity_type="Contact",entity_id=c.id,detail={"request_type":c.request_type,"contact_type":c.contact_type,"name":c.name}));db.commit();db.refresh(c);return item(c)
@router.put("/{contact_id}")
def update_contact(contact_id:int,data:ContactIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    c=db.get(Contact,contact_id)
    if not c:raise HTTPException(404,detail={"error":"not_found","message":"Contact not found"})
    for k,v in data.model_dump().items():setattr(c,k,v)
    db.add(AuditLog(user_id=user.id,action="CONTACT_UPDATED",entity_type="Contact",entity_id=c.id,detail={"request_type":c.request_type,"contact_type":c.contact_type,"name":c.name}));db.commit();return item(c)
@router.delete("/{contact_id}")
def delete_contact(contact_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    c=db.get(Contact,contact_id)
    if not c:raise HTTPException(404,detail={"error":"not_found","message":"Contact not found"})
    c.is_active=False;db.add(AuditLog(user_id=user.id,action="CONTACT_DEACTIVATED",entity_type="Contact",entity_id=c.id,detail={"name":c.name}));db.commit();return {"ok":True}
