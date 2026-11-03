from sqlalchemy import select,func
from datetime import date,timedelta,datetime,timezone
from app.models import WorkflowTemplate,WorkflowStep,StepKind,RequestStep,StepStatus,ComplianceRequest,RequestStatus,Document,ReminderSent,Notification
from app.services.workflow_service import submit,approve,complete_action
from app.schemas.requests import FinancialDocumentsData,PowerOfAttorneyData,DeclarationData,HRDocumentsData
from app.services.report_service import requests_xlsx
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_db
from app.core.security import create_token

def _request(db,kind,step_defs,form,attachment):
    s=db["db"];t=WorkflowTemplate(request_type=kind,name=kind,is_active=True);s.add(t);s.flush()
    s.add_all([WorkflowStep(template_id=t.id,step_order=i,name=name,step_kind=StepKind(step_kind),assigned_role=role,requires_fields=required) for i,(name,step_kind,role,required) in enumerate(step_defs,1)]);s.flush()
    r=ComplianceRequest(bid_id=db["bid"].id,type=kind,status=RequestStatus.DRAFT,form_data=form,created_by=db["users"]["BID_TEAM"].id);s.add(r);s.flush()
    s.add(Document(request_id=r.id,category=attachment,filename="source.pdf",stored_name=f"{r.id}-source.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id));s.commit();return r

def _active(s,r):return s.scalar(select(RequestStep).where(RequestStep.request_id==r.id,RequestStep.status==StepStatus.ACTIVE))

def test_financial_documents_to_complete(db):
    FinancialDocumentsData.model_validate({"description":"Prepare","documents_required":["Balance Sheet"],"financial_years":"2024-25","purpose":"RFP"})
    r=_request(db,"FINANCIAL_DOCUMENTS",[("Help Desk","ACTION","BID_TEAM",["sr_number"]),("Prepare files","ACTION","FINANCE",["attachment:financial_documents"])],{"description":"Prepare","documents_required":["Balance Sheet"],"financial_years":"2024-25","purpose":"RFP"},"rfp")
    s=db["db"];submit(s,r,db["users"]["BID_TEAM"]);a=_active(s,r);complete_action(s,r,a.id,db["users"]["BID_TEAM"],{"sr_number":"SR-100"});s.add(Document(request_id=r.id,category="financial_documents",filename="balance.pdf",stored_name="balance.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["FINANCE"].id));s.flush();a=_active(s,r);complete_action(s,r,a.id,db["users"]["FINANCE"],{});s.commit();assert r.status==RequestStatus.COMPLETED

def test_poa_primary_then_risk(db):
    form={"signatory_name":"A","signatory_designation":"Partner","purpose":"Bid","validity_period":30,"rfp_format_attached":True};PowerOfAttorneyData.model_validate(form)
    r=_request(db,"POWER_OF_ATTORNEY",[("Primary","APPROVAL","APPROVER",[]),("Risk","APPROVAL","RISK",[])],form,"rfp_format");s=db["db"];submit(s,r,db["users"]["BID_TEAM"]);a=_active(s,r);approve(s,r,a.id,db["users"]["APPROVER"]);a=_active(s,r);assert a.workflow_step.assigned_role=="RISK";approve(s,r,a.id,db["users"]["RISK"]);s.commit();assert r.status==RequestStatus.COMPLETED

def test_declaration_and_hr_action_completion(db):
    s=db["db"]
    DeclarationData.model_validate({"declaration_type":"Undertaking","subject":"Offer","rfp_clause_reference":"4.2"})
    d=_request(db,"DECLARATION",[("Signed declaration","ACTION","BID_TEAM",["attachment:signed_declaration"])],{"declaration_type":"Undertaking","subject":"Offer","rfp_clause_reference":"4.2"},"rfp_format");submit(s,d,db["users"]["BID_TEAM"]);s.add(Document(request_id=d.id,category="signed_declaration",filename="signed.pdf",stored_name="signed.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id));s.flush();complete_action(s,d,_active(s,d).id,db["users"]["BID_TEAM"],{});s.commit();assert d.status==RequestStatus.COMPLETED
    f={"certificate_type":"Manpower Certificate","number_of_employees":4,"details_required":"Role mix"};HRDocumentsData.model_validate(f)
    h=_request(db,"HR_DOCUMENTS",[("HR certificate","ACTION","HR",["attachment:hr_certificate"])],f,"rfp");submit(s,h,db["users"]["BID_TEAM"]);s.add(Document(request_id=h.id,category="hr_certificate",filename="hr.pdf",stored_name="hr.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["HR"].id));s.flush();complete_action(s,h,_active(s,h).id,db["users"]["HR"],{});s.commit();assert h.status==RequestStatus.COMPLETED

def test_request_excel_report_has_xlsx_signature(db):
    r=_request(db,"FINANCIAL_DOCUMENTS",[("Help Desk","ACTION","BID_TEAM",["sr_number"])],{"description":"Prepare","documents_required":["Balance Sheet"],"financial_years":"2024-25","purpose":"RFP"},"rfp")
    data=requests_xlsx([r],False).read();assert data[:2]==b"PK"

def test_reminders_deduplicate_and_refund_received_stops_overdue(db,monkeypatch):
    import app.services.reminder_service as reminders
    due=date(2026,10,22);today=date(2026,10,25);s=db["db"]
    r=ComplianceRequest(bid_id=db["bid"].id,type="EMD_CHALLAN",status=RequestStatus.COMPLETED,created_by=db["users"]["BID_TEAM"].id,form_data={"amount":500,"expected_refund_date":due.isoformat(),"person_responsible_for_refund":"member@test.local"});s.add(r);s.commit()
    async def no_email(*args,**kwargs):return None
    monkeypatch.setattr(reminders,"SessionLocal",lambda:s);monkeypatch.setattr(reminders,"send_logged_email",no_email)
    reminders.run_reminders(today);count=s.scalar(select(func.count()).select_from(ReminderSent));notifications=s.scalar(select(func.count()).select_from(Notification));assert count>=1 and notifications>=1
    reminders.run_reminders(today);assert s.scalar(select(func.count()).select_from(ReminderSent))==count
    r.refund_received_at=datetime.now(timezone.utc);s.commit();reminders.run_reminders(due+timedelta(days=6))
    assert s.scalar(select(func.count()).select_from(ReminderSent).where(ReminderSent.reminder_key.like("refund-overdue-%-6")))==0

def test_report_endpoints_and_admin_rbac(db):
    s=db["db"]
    def override_db():yield s
    app.dependency_overrides[get_db]=override_db
    try:
        with TestClient(app) as client:
            token=create_token(db["users"]["ADMIN"]);headers={"Authorization":f"Bearer {token}"}
            pdf=client.get(f"/reports/bids/{db['bid'].id}/summary.pdf",headers=headers)
            xlsx=client.get("/reports/requests.xlsx",headers=headers)
            refunds=client.get("/reports/refunds.xlsx",headers=headers)
            assert pdf.status_code==200 and pdf.headers["content-type"].startswith("application/pdf")
            assert xlsx.status_code==200 and "spreadsheetml" in xlsx.headers["content-type"]
            assert refunds.status_code==200 and "spreadsheetml" in refunds.headers["content-type"]
            wrong=client.post("/admin/reminders/run",headers={"Authorization":f"Bearer {create_token(db['users']['APPROVER'])}"})
            assert wrong.status_code==403
    finally:app.dependency_overrides.pop(get_db,None)
