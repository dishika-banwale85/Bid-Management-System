from datetime import date
from sqlalchemy import select
from app.db import Base,engine,SessionLocal
from app.models import Role,User,Bid,WorkflowTemplate,WorkflowStep,StepKind,Contact,FormTemplate
from app.core.security import hash_password
from app.schemas.requests import TenderFeeData,EmdChallanData,EmdBgData,FinancialDocumentsData,PowerOfAttorneyData,DeclarationData,HRDocumentsData

Base.metadata.create_all(engine)
role_names=["BID_TEAM","APPROVER","PACE_COORDINATOR","ADMIN"]
demo=[("member@bidease.com","Team Member","BID_TEAM"),("approver@bidease.com","Approver","APPROVER"),("admin@bidease.com","Compliance Admin","ADMIN"),("sahil@bidease.com","Sahil","PACE_COORDINATOR"),("aditi@bidease.com","Aditi","PACE_COORDINATOR")]
templates={"TENDER_FEE":("Tender Fee",[("Approval","APPROVAL","APPROVER",[])]),"EMD_CHALLAN":("EMD by Challan",[("Engagement Partner approval","APPROVAL","APPROVER",[]),("Finance approval","APPROVAL","APPROVER",[])]),"EMD_BG":("EMD by Bank Guarantee",[("BG approval","APPROVAL","APPROVER",[]),("OPRS request","ACTION","BID_TEAM",["oprs_reference"]),("Issue Bank Guarantee","ACTION","APPROVER",["bg_number","issue_date","attachment:bg_copy"])]),
"FINANCIAL_DOCUMENTS":("Financial Documents",[("Raise Help Desk request","ACTION","BID_TEAM",["sr_number"]),("Prepare financial documents","ACTION","APPROVER",["attachment:financial_documents"])]),
"POWER_OF_ATTORNEY":("Power of Attorney",[("Primary approval","APPROVAL","APPROVER",[]),("Risk approval","APPROVAL","APPROVER",[])]),
"DECLARATION":("Declaration / Undertaking",[("Upload signed declaration","ACTION","BID_TEAM",["attachment:signed_declaration"])]),
"HR_DOCUMENTS":("HR Documents",[("Prepare HR certificate","ACTION","APPROVER",["attachment:hr_certificate"])])}
form_models={"TENDER_FEE":TenderFeeData,"EMD_CHALLAN":EmdChallanData,"EMD_BG":EmdBgData,"FINANCIAL_DOCUMENTS":FinancialDocumentsData,"POWER_OF_ATTORNEY":PowerOfAttorneyData,"DECLARATION":DeclarationData,"HR_DOCUMENTS":HRDocumentsData}
required_docs={"TENDER_FEE":["generated_challan","checklist"],"EMD_CHALLAN":["generated_challan","checklist"],"EMD_BG":["bg_format","checklist"],"FINANCIAL_DOCUMENTS":["rfp","ca_certificate"],"POWER_OF_ATTORNEY":["poa_format","executed_poa"],"DECLARATION":["required_document_format"],"HR_DOCUMENTS":["rfp"]}
field_options={"documents_required":["Balance Sheet","Turnover Certificate","CA Certificate","Net Worth Certificate","Other"],"declaration_type":["Declaration","Undertaking","Self Declaration","Litigation","Blacklisting"],"certificate_type":["Manpower Certificate","On-Roll Certificate"]}
def field_type(field):
    annotation=str(field.annotation)
    if "date" in annotation:return "date"
    if "bool" in annotation:return "boolean"
    if "int" in annotation or "float" in annotation:return "number"
    if "list" in annotation:return "multi"
    if "Literal" in annotation:return "select"
    return "email" if "EmailStr" in annotation else "text"
with SessionLocal() as db:
    roles={r.name:r for r in db.scalars(select(Role)).all()}
    for name in role_names:
        if name not in roles:r=Role(name=name);db.add(r);roles[name]=r
    db.flush()
    for email,name,role in demo:
        existing=db.scalar(select(User).where(User.email==email))
        if not existing:db.add(User(email=email,full_name=name,password_hash=hash_password("Demo123!"),role=roles[role]))
        else:existing.role=roles[role]
    db.flush()
    for typ,(name,steps) in templates.items():
        t=db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.request_type==typ))
        if not t:t=WorkflowTemplate(request_type=typ,name=name,is_active=True);db.add(t);db.flush()
        else:t.name=name;t.is_active=True
        current_steps=[s for s in t.steps if s.version==t.version]
        if not current_steps:
            for i,(step_name,kind,role,fields) in enumerate(steps,1):db.add(WorkflowStep(template_id=t.id,version=t.version,step_order=i,name=step_name,step_kind=StepKind(kind),assigned_role=role,requires_fields=fields))
    for typ,model in form_models.items():
        field_rows=[{"key":key,"label":key.replace("_"," ").title(),"section":"Request","type":field_type(field),"required":field.is_required(),"options":field_options.get(key,[])} for key,field in model.model_fields.items()]
        form=db.scalar(select(FormTemplate).where(FormTemplate.request_type==typ))
        if not form:db.add(FormTemplate(request_type=typ,display_name=templates[typ][0],fields=field_rows,required_documents=required_docs[typ]))
        else:
            if not form.fields:form.fields=field_rows
            if typ in {"TENDER_FEE","EMD_CHALLAN","EMD_BG","FINANCIAL_DOCUMENTS","POWER_OF_ATTORNEY","DECLARATION"}:form.required_documents=required_docs[typ]
            if typ=="FINANCIAL_DOCUMENTS":form.fields=[field for field in form.fields if field.get("key")!="purpose"]
            if typ=="POWER_OF_ATTORNEY":form.fields=[field for field in form.fields if field.get("key") not in {"purpose","signatory_designation"}]
            if typ=="DECLARATION":
                form.fields=[field for field in form.fields if field.get("key")!="subject"]
                for field in form.fields:
                    if field.get("key")=="declaration_type":field["options"]=field_options["declaration_type"]
    # Retain the former prototype placeholders for history, but hide them from
    # current routing so only the named Step 3 contacts receive mail notices.
    legacy_names={"Finance Team","Declaration Contact One","Declaration Contact Two","Compliance Desk","HR Primary"}
    for old_contact in db.scalars(select(Contact).where(Contact.name.in_(legacy_names))).all():
        old_contact.is_active=False
    contact_rows=[]
    for request_type,contact_type,names in [
        ("FEE","PROCESSING",["Sahil","Aditi"]),
        ("EMD","PROCESSING",["Sahil","Aditi"]),
        ("PACE","PROCESSING",["Sahil","Aditi"]),
        ("BANK_GUARANTEE","PROCESSING",["Sahil","Aditi"]),
        ("BANK_GUARANTEE","VETTING",["Sambhavya Shanker"]),
        ("BANK_GUARANTEE","OPERATIONS",["Poorvi Kulkarni"]),
        ("FINANCIAL_DOCUMENTS","PRIMARY",["Karan Nailwal","Gunjan Aggarwal"]),
        ("POWER_OF_ATTORNEY","PRIMARY",["Surbhi Agarwal"]),
        ("POWER_OF_ATTORNEY","RISK",["Tarun Tangri"]),
        ("DECLARATION","PRIMARY",["Dharmender Verma","Apoorva Chowdhury"]),
        ("DECLARATION","CC",["Rashmi Grover","Shikha Mendiratta"]),
        ("HR_DOCUMENTS","PRIMARY",["Natasha P Nath","Varthika Gautam"]),
        ("HR_DOCUMENTS","CC",["Ruchika Kohli Thandani"]),
    ]:
        for contact_name in names:
            contact_rows.append((request_type,contact_type,contact_name))
    for typ,contact_type,name in contact_rows:
        contact=db.scalar(select(Contact).where(Contact.request_type==typ,Contact.contact_type==contact_type,Contact.name==name))
        if not contact:
            db.add(Contact(request_type=typ,contact_type=contact_type,name=name,email=None,is_active=True))
        else:
            contact.is_active=True
    member=db.scalar(select(User).where(User.email=="member@bidease.com"))
    demo_bid=db.scalar(select(Bid).where(Bid.rfp_reference=="DEMO-RFP-2027-001"))
    demo_values={"client_name":"National Infrastructure Authority","department":"Public Sector","rfp_published_date":date(2026,12,1),"project_title":"Regional Transport Modernization","prebid_query_deadline":date(2026,12,12),"prebid_meeting_date":date(2026,12,15),"submission_deadline":date(2027,1,10),"tender_opening_date":date(2027,1,11),"prebid_meeting_na":False,"prebid_query_na":False,"client_address":"Sector 18, New Delhi, India"}
    if not demo_bid:
        db.add(Bid(rfp_reference="DEMO-RFP-2027-001",created_by=member.id,**demo_values))
    else:
        for key,value in demo_values.items():
            if getattr(demo_bid,key) is None:
                setattr(demo_bid,key,value)
    db.commit()
print("BidEase demo users, workflows and form templates seeded.")
