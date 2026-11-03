from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from sqlalchemy.orm import Session
from app.core.config import SMTP_HOST,SMTP_PORT,SMTP_USER,SMTP_PASSWORD,SMTP_FROM,SMTP_TLS,MAIL_MODE
from app.db import SessionLocal
from app.models import EmailLog

templates=Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/"templates"),autoescape=select_autoescape(["html"]))
def _config():
    return ConnectionConfig(MAIL_USERNAME=SMTP_USER,MAIL_PASSWORD=SMTP_PASSWORD,MAIL_FROM=SMTP_FROM,MAIL_PORT=SMTP_PORT,MAIL_SERVER=SMTP_HOST,MAIL_STARTTLS=SMTP_TLS,MAIL_SSL_TLS=False,USE_CREDENTIALS=bool(SMTP_USER),VALIDATE_CERTS=False)

async def send_logged_email(to:list[str],cc:list[str],subject:str,template_name:str,context:dict,request_id:int|None):
    status="SIMULATED" if MAIL_MODE!="smtp" else "SENT";error=None
    if MAIL_MODE=="smtp":
        try:
            html=templates.get_template("request_event.html").render(**context)
            message=MessageSchema(subject=subject,recipients=to,cc=cc,body=html,subtype=MessageType.html)
            await FastMail(_config()).send_message(message)
        except Exception as exc:
            status="FAILED";error=str(exc)[:4000]
    # Separate session ensures the email result is recorded even after the request transaction.
    with SessionLocal() as db:
        db.add(EmailLog(to=", ".join(to),cc=", ".join(cc),subject=subject,template=template_name,status=status,error=error,related_request_id=request_id));db.commit()
    return status

def recipients_for_step(db:Session,role:str)->list[str]:
    from sqlalchemy import select
    from app.models import User
    return db.scalars(select(User.email).join(User.role).where(User.role.has(name=role),User.is_active.is_(True))).all()

def always_cc(db:Session,request_type:str)->list[str]:
    from sqlalchemy import select
    from app.models import Contact
    return db.scalars(select(Contact.email).where(Contact.is_active.is_(True),Contact.contact_type=="CC",(Contact.request_type==request_type)|(Contact.request_type.is_(None)))).all()
