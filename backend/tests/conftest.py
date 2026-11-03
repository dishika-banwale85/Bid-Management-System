import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Role,User,Bid,WorkflowTemplate,WorkflowStep,StepKind,Contact,ComplianceRequest,RequestStatus,Document
from app.core.security import hash_password
from app.api import auth as auth_api
from app.services import captcha_service

@pytest.fixture(autouse=True)
def auth_state_for_tests(monkeypatch):
    """Keep pre-CAPTCHA tests in legacy mode; CAPTCHA-specific tests opt in."""
    monkeypatch.setattr(auth_api, "CAPTCHA_ENABLED", False)
    monkeypatch.setattr(captcha_service, "CAPTCHA_ENABLED", False)
    auth_api._rate_hits.clear()
    auth_api._failed_login_attempts.clear()
    auth_api._login_blocked_until.clear()
    yield
    auth_api._rate_hits.clear()
    auth_api._failed_login_attempts.clear()
    auth_api._login_blocked_until.clear()

@pytest.fixture
def db(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'test.db'}",connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine);Session=sessionmaker(bind=engine,expire_on_commit=False);session=Session()
    roles={name:Role(name=name) for name in ["BID_TEAM","APPROVER","FINANCE","OPERATIONS","ADMIN","HR","RISK","SENIOR_MANAGER","PACE_COORDINATOR","DECLARATION_TEAM"]};session.add_all(roles.values());session.flush()
    users={name:User(email=f"{name.lower()}@test.local",full_name=name,password_hash=hash_password("Demo123!"),role=role) for name,role in roles.items()};session.add_all(users.values());session.flush()
    bid=Bid(client_name="Demo Client",department="Public Sector",rfp_reference="RFP-42",tender_opening_date=date(2026,11,1),submission_deadline=date(2026,11,10),created_by=users["BID_TEAM"].id);session.add(bid)
    template=WorkflowTemplate(request_type="EMD_BG",name="EMD BG",is_active=True);session.add(template);session.flush()
    steps=[WorkflowStep(template_id=template.id,step_order=1,name="Approval",step_kind=StepKind.APPROVAL,assigned_role="APPROVER",requires_fields=[]),WorkflowStep(template_id=template.id,step_order=2,name="OPRS request",step_kind=StepKind.ACTION,assigned_role="BID_TEAM",requires_fields=["oprs_reference"]),WorkflowStep(template_id=template.id,step_order=3,name="Issue Bank Guarantee",step_kind=StepKind.ACTION,assigned_role="OPERATIONS",requires_fields=["bg_number","issue_date","attachment:bg_copy"])]
    session.add_all(steps);session.commit()
    yield {"db":session,"users":users,"bid":bid,"template":template,"steps":steps}
    session.close();Base.metadata.drop_all(engine);engine.dispose()

@pytest.fixture
def bg_request(db):
    req=ComplianceRequest(bid_id=db["bid"].id,type="EMD_BG",status=RequestStatus.DRAFT,created_by=db["users"]["BID_TEAM"].id,form_data={"engagement_code":"ENG-1","beneficiary_address":"1 Main Road","mode_of_bg":"Performance","current_bg_maturity_date":"2027-12-01","tender_opening_date":"2026-11-01","contract_date":"2026-12-01","bg_amount":10000,"contract_value":100000,"contract_description":"Supply","bg_issued_from":"Bank One","approved_by":"EP"})
    db["db"].add(req);db["db"].flush();db["db"].add(Document(request_id=req.id,category="rfp",filename="rfp.pdf",stored_name="test.pdf",content_type="application/pdf",version=1,uploaded_by=db["users"]["BID_TEAM"].id));db["db"].commit();return req
