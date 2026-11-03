from datetime import datetime,timezone
from typing import Literal,get_args,get_origin
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User,Role,WorkflowTemplate,WorkflowStep,StepKind,FormTemplate,Contact,AuditLog
from app.schemas.admin import REQUEST_TYPES,WorkflowUpdateIn,FormTemplateUpdateIn,ContactAdminIn,UserCreateIn,UserUpdateIn
from app.schemas.requests import TenderFeeData,EmdChallanData,EmdBgData,FinancialDocumentsData,PowerOfAttorneyData,DeclarationData,HRDocumentsData
from app.core.security import require_role,current_user,hash_password
from app.services.trash_service import empty_old_trash

router=APIRouter(prefix="/admin",tags=["admin"])
_FORM_MODELS={"TENDER_FEE":TenderFeeData,"EMD_CHALLAN":EmdChallanData,"EMD_BG":EmdBgData,"FINANCIAL_DOCUMENTS":FinancialDocumentsData,"POWER_OF_ATTORNEY":PowerOfAttorneyData,"DECLARATION":DeclarationData,"HR_DOCUMENTS":HRDocumentsData}


@router.post("/trash/empty")
def empty_bid_trash(db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    removed=empty_old_trash(db,user.id)
    return {"deleted_count":removed}

def _not_found():return HTTPException(404,detail={"error":"not_found","message":"Configuration not found"})
def _workflow_json(db,template):
    steps=db.scalars(select(WorkflowStep).where(WorkflowStep.template_id==template.id,WorkflowStep.version==template.version).order_by(WorkflowStep.step_order)).all()
    return {"request_type":template.request_type,"name":template.name,"is_active":template.is_active,"version":template.version,"steps":[{"id":s.id,"step_order":s.step_order,"name":s.name,"step_kind":s.step_kind.value,"assigned_role":s.assigned_role,"requires_fields":s.requires_fields or []} for s in steps]}

@router.get("/workflows")
def list_workflows(db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    rows=db.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.request_type)).all()
    return [_workflow_json(db,row) for row in rows]

@router.put("/workflows/{request_type}")
def update_workflow(request_type:str,data:WorkflowUpdateIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    raise HTTPException(403,detail={"error":"forbidden","message":"Workflow configuration is read-only"})
    if request_type not in REQUEST_TYPES:raise HTTPException(404,detail={"error":"not_found","message":"Unknown request type"})
    template=db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.request_type==request_type))
    if not template:raise _not_found()
    template.version+=1;template.name=data.name;template.is_active=data.is_active
    for order,step in enumerate(data.steps,1):
        db.add(WorkflowStep(template_id=template.id,version=template.version,step_order=order,name=step.name,step_kind=StepKind(step.step_kind),assigned_role=step.assigned_role,requires_fields=step.requires_fields))
    db.add(AuditLog(user_id=user.id,action="WORKFLOW_TEMPLATE_UPDATED",entity_type="WorkflowTemplate",entity_id=template.id,detail={"request_type":request_type,"version":template.version,"step_count":len(data.steps)}))
    db.commit();db.refresh(template);return _workflow_json(db,template)

@router.get("/forms")
def list_forms(db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    rows=db.scalars(select(FormTemplate).order_by(FormTemplate.request_type)).all()
    return [{"request_type":f.request_type,"display_name":f.display_name,"fields":f.fields,"required_documents":f.required_documents,"updated_at":f.updated_at.isoformat() if f.updated_at else None} for f in rows]

@router.get("/forms/{request_type}")
def get_form_for_ui(request_type:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if request_type not in REQUEST_TYPES:raise HTTPException(404,detail={"error":"not_found","message":"Unknown request type"})
    form=db.scalar(select(FormTemplate).where(FormTemplate.request_type==request_type))
    if not form:raise _not_found()
    return {"request_type":form.request_type,"display_name":form.display_name,"fields":form.fields,"required_documents":form.required_documents}

@router.put("/forms/{request_type}")
def update_form(request_type:str,data:FormTemplateUpdateIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    raise HTTPException(403,detail={"error":"forbidden","message":"Form configuration is read-only"})
    if request_type not in REQUEST_TYPES:raise HTTPException(404,detail={"error":"not_found","message":"Unknown request type"})
    form=db.scalar(select(FormTemplate).where(FormTemplate.request_type==request_type))
    if not form:raise _not_found()
    expected=_FORM_MODELS[request_type].model_fields
    supplied={field.key:field for field in data.fields}
    if set(supplied)!=set(expected):raise HTTPException(422,detail={"error":"validation_error","message":"Form fields cannot be added or removed because backend validation is defined for this request type"})
    mismatched=[key for key,model_field in expected.items() if supplied[key].required!=model_field.is_required()]
    if mismatched:raise HTTPException(422,detail={"error":"validation_error","message":"Required field validation is fixed by the request schema","fields":mismatched})
    invalid_options=[]
    for key,model_field in expected.items():
        annotation=model_field.annotation
        if get_origin(annotation) is list:
            args=get_args(annotation);annotation=args[0] if args else annotation
        if get_origin(annotation) is Literal:
            allowed=set(get_args(annotation))
            if not set(supplied[key].options).issubset(allowed):invalid_options.append(key)
    if invalid_options:raise HTTPException(422,detail={"error":"validation_error","message":"Dropdown options must stay within the values accepted by request validation","fields":invalid_options})
    form.display_name=data.display_name;form.fields=[field.model_dump() for field in data.fields];form.required_documents=data.required_documents;form.updated_by=user.id;form.updated_at=datetime.now(timezone.utc)
    db.add(AuditLog(user_id=user.id,action="FORM_TEMPLATE_UPDATED",entity_type="FormTemplate",entity_id=form.id,detail={"request_type":request_type,"required_documents":data.required_documents}))
    db.commit();return {"request_type":form.request_type,"display_name":form.display_name,"fields":form.fields,"required_documents":form.required_documents,"updated_at":form.updated_at.isoformat()}

def _contact_json(c):return {"id":c.id,"request_type":c.request_type,"contact_type":c.contact_type,"name":c.name,"designation":c.designation,"department":c.department,"email":c.email,"is_active":c.is_active}
@router.get("/contacts")
def list_all_contacts(request_type:str|None=None,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    q=select(Contact)
    if request_type:q=q.where(Contact.request_type==request_type)
    return [_contact_json(c) for c in db.scalars(q.order_by(Contact.request_type,Contact.contact_type,Contact.name)).all()]
@router.post("/contacts")
def create_contact(data:ContactAdminIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    contact=Contact(**data.model_dump());db.add(contact);db.flush()
    db.add(AuditLog(user_id=user.id,action="CONTACT_CREATED",entity_type="Contact",entity_id=contact.id,detail={"request_type":contact.request_type,"contact_type":contact.contact_type,"name":contact.name}))
    db.commit();db.refresh(contact);return _contact_json(contact)
@router.put("/contacts/{contact_id}")
def update_contact(contact_id:int,data:ContactAdminIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    contact=db.get(Contact,contact_id)
    if not contact:raise _not_found()
    for key,value in data.model_dump().items():setattr(contact,key,value)
    db.add(AuditLog(user_id=user.id,action="CONTACT_UPDATED",entity_type="Contact",entity_id=contact.id,detail={"request_type":contact.request_type,"contact_type":contact.contact_type,"name":contact.name,"is_active":contact.is_active}))
    db.commit();db.refresh(contact);return _contact_json(contact)
@router.delete("/contacts/{contact_id}")
def deactivate_contact(contact_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    contact=db.get(Contact,contact_id)
    if not contact:raise _not_found()
    contact.is_active=False;db.add(AuditLog(user_id=user.id,action="CONTACT_DEACTIVATED",entity_type="Contact",entity_id=contact.id,detail={"email":contact.email}));db.commit();return {"ok":True}

def _user_json(user:User):return {"id":user.id,"email":user.email,"full_name":user.full_name,"role":user.role.name,"is_active":user.is_active}

@router.get("/users")
def list_users(db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    return [_user_json(row) for row in db.scalars(select(User).join(User.role).order_by(User.role_id,User.email)).all()]

@router.post("/users")
def create_user(data:UserCreateIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    email=str(data.email).lower()
    if db.scalar(select(User.id).where(User.email==email)):raise HTTPException(409,detail={"error":"conflict","message":"A user with this email already exists"})
    role=db.scalar(select(Role).where(Role.name==data.role))
    if not role:raise HTTPException(422,detail={"error":"validation_error","message":"Role is not configured; run seed.py first"})
    created=User(email=email,full_name=data.full_name.strip(),password_hash=hash_password(data.password),role=role,is_active=True)
    db.add(created);db.flush();db.add(AuditLog(user_id=user.id,action="USER_CREATED",entity_type="User",entity_id=created.id,detail={"email":email,"role":role.name}));db.commit();db.refresh(created);return _user_json(created)

@router.put("/users/{user_id}")
def update_user(user_id:int,data:UserUpdateIn,db:Session=Depends(get_db),user:User=Depends(require_role("ADMIN"))):
    target=db.get(User,user_id)
    if not target:raise _not_found()
    if target.id==user.id and not data.is_active:raise HTTPException(422,detail={"error":"validation_error","message":"You cannot deactivate your own account"})
    role=db.scalar(select(Role).where(Role.name==data.role))
    if not role:raise HTTPException(422,detail={"error":"validation_error","message":"Role is not configured; run seed.py first"})
    target.full_name=data.full_name.strip();target.role=role;target.is_active=data.is_active
    if data.password:target.password_hash=hash_password(data.password)
    db.add(AuditLog(user_id=user.id,action="USER_UPDATED",entity_type="User",entity_id=target.id,detail={"email":target.email,"role":role.name,"is_active":target.is_active}));db.commit();db.refresh(target);return _user_json(target)
