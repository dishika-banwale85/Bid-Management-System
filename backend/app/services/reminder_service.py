from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal
from app.models import Bid, ComplianceRequest, ReminderSent, Notification, User, EmailLog, Contact, AuditLog, RequestStatus
from app.services.email_service import send_logged_email
from app.services.access_service import active_bid_clause

def run_reminders(today=None):
    """Idempotent daily reminder scan. Each reminder key is unique per request."""
    today=today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    with SessionLocal() as db:
        requests=db.scalars(select(ComplianceRequest).options(joinedload(ComplianceRequest.bid),joinedload(ComplianceRequest.creator)).join(Bid).where(ComplianceRequest.type.in_(["EMD_CHALLAN","EMD_BG"]),ComplianceRequest.status!=RequestStatus.DRAFT,active_bid_clause())).unique().all()
        for req in requests:
            bid=req.bid; data=req.form_data or {}; candidates=[]
            def add(key,when,label):
                if when and (when if isinstance(when,date) else date.fromisoformat(str(when)[:10]))==today: candidates.append((key,label))
            if bid:
                for k,field,label in [("tender-opening",bid.tender_opening_date,"tender opening"),("submission-deadline",bid.submission_deadline,"bid submission deadline")]:
                    if field:
                        days=(field-today).days
                        if days in (7,3,1): candidates.append((k+"-"+str(days),label))
            for field,prefix,days_list,label in [("last_emd_submission_date","emd-submission",(3,1,0),"EMD submission"),("expected_refund_date","expected-refund",(7,1),"EMD refund")]:
                raw=data.get(field)
                if raw:
                    due=raw if isinstance(raw,date) else date.fromisoformat(str(raw)[:10]); remain=(due-today).days
                    if remain in days_list:candidates.append((f"{prefix}-{remain}",label))
                    if field=="expected_refund_date" and req.refund_received_at is None and remain<0 and (-remain)%3==0:candidates.append((f"refund-overdue-{due.isoformat()}-{remain}","OVERDUE EMD refund"))
            for key,label in set(candidates):
                if db.scalar(select(ReminderSent.id).where(ReminderSent.request_id==req.id,ReminderSent.reminder_key==key)):continue
                db.add(ReminderSent(request_id=req.id,reminder_key=key,sent_on=datetime.now(timezone.utc)))
                try: db.flush()
                except IntegrityError: db.rollback();continue
                msg=f"{label} reminder for request #{req.id} ({bid.client_name if bid else ''})."
                db.add(Notification(user_id=req.created_by,message=msg,request_id=req.id))
                recipients=[req.creator.email] if req.creator else []
                person=data.get("person_responsible_for_refund")
                if person:
                    if "@" in person:
                        recipients.append(person)
                        responsible=db.scalar(select(User).where(User.email.ilike(person),User.is_active.is_(True)))
                        if responsible:db.add(Notification(user_id=responsible.id,message=msg,request_id=req.id))
                    else:
                        responsible=db.scalar(select(User).where(User.full_name.ilike(person),User.is_active.is_(True)))
                        match=responsible.email if responsible else db.scalar(select(Contact.email).where(Contact.name.ilike(person),Contact.is_active.is_(True)))
                        if responsible:db.add(Notification(user_id=responsible.id,message=msg,request_id=req.id))
                        if match:recipients.append(match)
                if recipients:
                    cc=db.scalars(select(Contact.email).where(Contact.is_active.is_(True),Contact.contact_type=="CC",(Contact.request_type==req.type)|(Contact.request_type.is_(None)))).all()
                    try: asyncio.run(send_logged_email(list(set(recipients)),list(cc),f"BidEase reminder: {label}","deadline_reminder",{"title":label,"message":msg,"request_id":req.id,"request_type":req.type},req.id))
                    except Exception as exc: db.add(EmailLog(to=", ".join(recipients),cc="",subject=f"BidEase reminder: {label}",template="deadline_reminder",status="FAILED",error=str(exc)[:1000],related_request_id=req.id))
                db.add(AuditLog(user_id=req.created_by,action="REMINDER_SENT",request_id=req.id,entity_type="ComplianceRequest",entity_id=req.id,detail={"reminder_key":key}))
        db.commit()
