import asyncio
from contextlib import contextmanager
from app.models import EmailLog
from app.services import email_service

def test_email_log_is_created_when_send_succeeds(monkeypatch,db):
    @contextmanager
    def fake_session():
        yield db["db"]
    class FakeMail:
        def __init__(self,config):pass
        async def send_message(self,message):return None
    monkeypatch.setattr(email_service,"SessionLocal",fake_session)
    monkeypatch.setattr(email_service,"FastMail",FakeMail)
    monkeypatch.setattr(email_service,"MAIL_MODE","smtp")
    monkeypatch.setattr(email_service,"SMTP_FROM","noreply@example.com")
    asyncio.run(email_service.send_logged_email(["to@example.com"],["cc@example.com"],"Subject","Approval",{"title":"Approved","message":"Ready","comment":"","request_id":7,"request_type":"EMD_BG"},7))
    db["db"].commit()
    row=db["db"].query(EmailLog).one()
    assert row.status=="SENT" and row.related_request_id==7 and row.cc=="cc@example.com"
