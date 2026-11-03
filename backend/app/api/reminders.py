from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User,AuditLog
from app.core.security import require_role
from app.services.reminder_service import run_reminders
router=APIRouter(prefix="/admin/reminders",tags=["reminders"])
@router.post("/run")
def run_now(db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    db.add(AuditLog(user_id=user.id,action="REMINDERS_RUN",entity_type="System",entity_id=0,detail={"trigger":"manual"}));db.commit()
    run_reminders();return {"ok":True,"message":"Reminder scan completed"}
