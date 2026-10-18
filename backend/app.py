"""Core REST API for bid management and compliance workflows."""
from __future__ import annotations

import enum, hashlib, os, secrets, shutil, uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./bid_management.db')
JWT_SECRET=os.getenv('JWT_SECRET','development-secret-change-before-deployment')
if JWT_SECRET == 'development-secret-change-before-deployment' and os.getenv('APP_ENV') == 'production':
    raise RuntimeError('Set JWT_SECRET before production startup')
JWT_ALGORITHM='HS256'; JWT_MINUTES=int(os.getenv('JWT_EXPIRE_MINUTES','480'))
engine=create_engine(DATABASE_URL, connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal=sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase): pass

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True); email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(160)); password_hash: Mapped[str]=mapped_column(String(255)); role: Mapped[str]=mapped_column(String(40),default='Bid Executive')
    active: Mapped[bool]=mapped_column(Boolean,default=True); created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class Tender(Base):
    __tablename__='tenders'
    id: Mapped[int]=mapped_column(primary_key=True); tender_code: Mapped[str]=mapped_column(String(80),unique=True,index=True)
    title: Mapped[str]=mapped_column(String(250)); client: Mapped[str]=mapped_column(String(200)); department: Mapped[str]=mapped_column(String(160),default='')
    description: Mapped[str]=mapped_column(Text,default=''); tender_value: Mapped[str]=mapped_column(String(40),default='')
    submission_deadline: Mapped[date|None]=mapped_column(Date,nullable=True); opening_date: Mapped[date|None]=mapped_column(Date,nullable=True)
    owner_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True); priority: Mapped[str]=mapped_column(String(20),default='Medium')
    status: Mapped[str]=mapped_column(String(40),default='Draft'); notes: Mapped[str]=mapped_column(Text,default='')
    fee_required: Mapped[bool]=mapped_column(Boolean,default=False); emd_required: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc)); updated_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc))
class ComplianceItem(Base):
    __tablename__='compliance_items'
    id: Mapped[int]=mapped_column(primary_key=True); tender_id: Mapped[int]=mapped_column(ForeignKey('tenders.id',ondelete='CASCADE'),index=True)
    category: Mapped[str]=mapped_column(String(100)); title: Mapped[str]=mapped_column(String(240)); required_fields: Mapped[str]=mapped_column(Text,default='[]')
    data_json: Mapped[str]=mapped_column(Text,default='{}'); required_attachments: Mapped[str]=mapped_column(Text,default='[]')
    owner_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True); due_date: Mapped[date|None]=mapped_column(Date,nullable=True)
    owner: Mapped[User|None]=relationship(foreign_keys=[owner_id])
    status: Mapped[str]=mapped_column(String(40),default='Missing'); notes: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class Document(Base):
    __tablename__='documents'
    id: Mapped[int]=mapped_column(primary_key=True); tender_id: Mapped[int]=mapped_column(ForeignKey('tenders.id',ondelete='CASCADE'),index=True)
    compliance_id: Mapped[int|None]=mapped_column(ForeignKey('compliance_items.id'),nullable=True); filename: Mapped[str]=mapped_column(String(255)); storage_name: Mapped[str]=mapped_column(String(255),unique=True)
    content_type: Mapped[str]=mapped_column(String(120)); size: Mapped[int]=mapped_column(Integer); version: Mapped[int]=mapped_column(Integer,default=1)
    uploader_id: Mapped[int]=mapped_column(ForeignKey('users.id')); verification_status: Mapped[str]=mapped_column(String(30),default='Pending review')
    expires_on: Mapped[date|None]=mapped_column(Date,nullable=True); uploaded_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class Task(Base):
    __tablename__='tasks'
    id: Mapped[int]=mapped_column(primary_key=True); tender_id: Mapped[int]=mapped_column(ForeignKey('tenders.id',ondelete='CASCADE'),index=True)
    title: Mapped[str]=mapped_column(String(250)); owner_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    due_date: Mapped[date|None]=mapped_column(Date,nullable=True); priority: Mapped[str]=mapped_column(String(20),default='Medium'); status: Mapped[str]=mapped_column(String(30),default='Open')
class Approval(Base):
    __tablename__='approvals'
    id: Mapped[int]=mapped_column(primary_key=True); tender_id: Mapped[int]=mapped_column(ForeignKey('tenders.id',ondelete='CASCADE'),index=True)
    compliance_id: Mapped[int|None]=mapped_column(ForeignKey('compliance_items.id'),nullable=True); actor_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    action: Mapped[str]=mapped_column(String(40)); comments: Mapped[str]=mapped_column(Text,default=''); created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    entity: Mapped[str]=mapped_column(String(80)); entity_id: Mapped[int]=mapped_column(Integer); action: Mapped[str]=mapped_column(String(80)); details: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class Notification(Base):
    __tablename__='notifications'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True); title: Mapped[str]=mapped_column(String(220)); body: Mapped[str]=mapped_column(Text)
    read: Mapped[bool]=mapped_column(Boolean,default=False); created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class LoginIn(BaseModel): email:str; password:str
class UserCreate(BaseModel): email:str; name:str; password:str=Field(min_length=12); role:str='Bid Executive'
class SignupIn(BaseModel): email:EmailStr; name:str=Field(min_length=1,max_length=160); password:str=Field(min_length=12,max_length=1024)
class TenderIn(BaseModel):
    tender_code:str; title:str; client:str; department:str=''; description:str=''; tender_value:str=''; submission_deadline:date|None=None; opening_date:date|None=None; owner_id:int|None=None; priority:str='Medium'; status:str='Draft'; notes:str=''; fee_required:bool=False; emd_required:bool=False
class TenderPatch(BaseModel):
    title:str|None=None; client:str|None=None; department:str|None=None; description:str|None=None; tender_value:str|None=None; submission_deadline:date|None=None; opening_date:date|None=None; owner_id:int|None=None; priority:str|None=None; status:str|None=None; notes:str|None=None; fee_required:bool|None=None; emd_required:bool|None=None
class CompliancePatch(BaseModel): owner_id:int|None=None; due_date:date|None=None; status:str|None=None; notes:str|None=None; data_json:dict[str,Any]|None=None
class TaskIn(BaseModel): title:str; owner_id:int|None=None; due_date:date|None=None; priority:str='Medium'
class ActionIn(BaseModel): action:str; comments:str=''
class ContactIn(BaseModel): name:str; responsibility:str; email:str=''; phone:str=''; category:str='General'
class ContactPatch(BaseModel): name:str|None=None; responsibility:str|None=None; email:str|None=None; phone:str|None=None; category:str|None=None
class ProfilePatch(BaseModel): name:str=Field(min_length=1,max_length=160)
class NotificationPatch(BaseModel): read:bool=True

# PBKDF2 is the default for new accounts to avoid bcrypt's native backend
# version/length incompatibilities. Keep bcrypt available for existing hashes.
pwd=CryptContext(schemes=['pbkdf2_sha256','bcrypt'],deprecated='auto'); oauth=OAuth2PasswordBearer(tokenUrl='/api/auth/token')
def dbdep():
    db=SessionLocal()
    try: yield db
    finally: db.close()
def current_user(token:str=Depends(oauth),db:Session=Depends(dbdep)):
    try: uid=int(jwt.decode(token,JWT_SECRET,algorithms=[JWT_ALGORITHM])['sub'])
    except (JWTError,KeyError,ValueError): raise HTTPException(401,'Invalid or expired token')
    user=db.get(User,uid)
    if not user or not user.active: raise HTTPException(401,'Account is unavailable')
    return user
ROLES={'Admin','Bid Manager','Bid Executive','Reviewer/Approver','Finance','HR','Read-only Viewer'}
def require(*roles):
    def check(user:User=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,'Your role cannot perform this action')
        return user
    return check
def log(db,user,entity,eid,action,details=''):
    db.add(AuditLog(user_id=user.id if user else None,entity=entity,entity_id=eid,action=action,details=details))
def notify(db,user_id,title,body):
    if user_id: db.add(Notification(user_id=user_id,title=title,body=body))
def get_tender(db,tid):
    t=db.get(Tender,tid)
    if not t: raise HTTPException(404,'Tender not found')
    return t

# Checklist blueprint. Required fields are sourced from the user's supplied brief; contact routing is editable data.
CHECKLIST=[
 ('Tender Fee / Bid Processing Fee — Non-refundable',['Client Name','Department','Mobile Number','Contact Person','Landline Number','Email ID','Beneficiary Name','Payment Mode','Relevant Pages of RFP','Amount','Account Holder Name','Account Number','Branch Name','IFSC Code','Branch Code','MICR Code'],['Generated Challan','RFP','EP Approval']),
 ('EMD — Bank Guarantee',['Engagement Code','Address of Beneficiary','Mode of BG','Current BG Maturity Date','Tender Opening Date','Contract Date','BG Amount','Contract Value','Contract Description','BG To be Issued From','Approved By'],[]),
 ('EMD — Generated Challan',['Client Name','Department','Mobile Number','Contact Person','Landline Number','Email ID','Beneficiary Name','Payment Mode','Relevant Pages of RFP','Amount','Account Holder Name','Account Number','Branch Name','IFSC Code','Branch Code','MICR Code','Address','Mode of Approval','Approver Name','Purpose of Payment','Last Submission Date of EMD','Expected Refund Date','Relevant Page No. of RFP having Refund Date','Name of Responsible Person for Refund'],['Generated Challan','RFP','EP Approval']),
 ('Bank Guarantee workflow',['Approval email to Shambhavya Shanker (Sambhavya.Shanker@in.ey.com) using RFP format','OPRS request raised using approved format','Operations email to Poorvi Kulkarni (Poorvi.Kulkarni@in.ey.com)'],[]),
 ('Financial Documents',['IN Help Desk request under RFP / Bids','Request details','Service Request number','Finance communication with Karan Nailwal (Karan.Nailwal@in.ey.com) and Gunjan Aggarwal (Gunjan1.Agarwal@in.ey.com)'],[]),
 ('Power of Attorney',['RFP-required format','Primary approval from Sunayana Tewari','Secondary Risk approval from Tarun Tangri','Responsible approvers','Supporting documents'],[]),
 ('Declaration / Undertakings / Self Declaration',['RFP-required format','Recipients: Sandeep Anand and Shikha Mendiratta','Mandatory CC: Rashmi Grover','Documents','Approval status'],[]),
 ('HR Documents',['Manpower / On-Roll Certificate','Primary recipient: Varthika Gautam','Mandatory CC: Ruchika Kohli Thandani','Uploaded evidence','Completion status'],[]),
]
def create_checklist(db,t: Tender):
    for cat,fields,attachments in CHECKLIST:
        if cat.startswith('Tender Fee') and not t.fee_required: continue
        if cat.startswith('EMD') and not t.emd_required: continue
        db.add(ComplianceItem(tender_id=t.id,category=cat,title=cat,required_fields=__import__('json').dumps(fields),required_attachments=__import__('json').dumps(attachments)))
        db.flush()
        db.add(Task(tender_id=t.id,title=f'Complete {cat}',due_date=t.submission_deadline,priority=t.priority))

app=FastAPI(title='Bid Management & Compliance API',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
Base.metadata.create_all(engine)
@app.get('/api/health')
def health(): return {'status':'ok','database':'connected'}
@app.post('/api/auth/register',status_code=201)
def register(data:UserCreate,db:Session=Depends(dbdep)):
    if db.scalar(select(User.id)): raise HTTPException(403,'Initial registration is closed; ask an administrator')
    if data.role not in ROLES: raise HTTPException(422,'Unknown role')
    email=data.email.strip().casefold()
    if db.scalar(select(User.id).where(User.email==email)): raise HTTPException(409,'Account already exists. Please log in.')
    u=User(email=email,name=data.name.strip(),password_hash=pwd.hash(data.password),role='Admin'); db.add(u); db.commit(); return {'id':u.id,'email':u.email,'role':u.role}
@app.post('/api/auth/signup',status_code=201)
def signup(data:SignupIn,db:Session=Depends(dbdep)):
    email=str(data.email).strip().casefold()
    user=User(email=email,name=data.name.strip(),password_hash=pwd.hash(data.password),role='Bid Executive')
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Account already exists. Please log in.')
    return auth_response(user)
def auth_response(user:User):
    token=jwt.encode({'sub':str(user.id),'exp':datetime.now(timezone.utc)+timedelta(minutes=JWT_MINUTES)},JWT_SECRET,algorithm=JWT_ALGORITHM)
    return {'access_token':token,'token_type':'bearer','user':{'id':user.id,'name':user.name,'email':user.email,'role':user.role}}
@app.post('/api/auth/token')
def login(form:OAuth2PasswordRequestForm=Depends(),db:Session=Depends(dbdep)):
    u=db.scalar(select(User).where(User.email==form.username.strip().casefold()))
    try: valid=bool(u and pwd.verify(form.password,u.password_hash))
    except (ValueError,TypeError): valid=False
    if not valid: raise HTTPException(401,'Invalid email or password.')
    return auth_response(u)
@app.get('/api/auth/me')
def me(u:User=Depends(current_user)): return {'id':u.id,'name':u.name,'email':u.email,'role':u.role}
@app.patch('/api/auth/me')
def update_me(data:ProfilePatch,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    u.name=data.name.strip(); db.commit(); return {'id':u.id,'name':u.name,'email':u.email,'role':u.role}
@app.get('/api/users')
def users(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    return [{'id':x.id,'name':x.name,'email':x.email,'role':x.role,'active':x.active} for x in db.scalars(select(User)).all()]
@app.get('/api/users/assignable')
def assignable_users(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    eligible={'Admin','Bid Manager','Bid Executive','Reviewer/Approver'}
    return [{'id':x.id,'name':x.name,'email':x.email,'role':x.role} for x in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all() if x.role in eligible]
@app.post('/api/users',status_code=201)
def add_user(data:UserCreate,db:Session=Depends(dbdep),u:User=Depends(require('Admin'))):
    if data.role not in ROLES: raise HTTPException(422,'Unknown role')
    if db.scalar(select(User).where(User.email==data.email.lower())): raise HTTPException(409,'Email already exists')
    x=User(email=data.email.lower(),name=data.name,password_hash=pwd.hash(data.password),role=data.role); db.add(x); db.flush(); log(db,u,'user',x.id,'created',x.role); db.commit(); return {'id':x.id,'email':x.email,'role':x.role}
@app.get('/api/tenders')
def tenders(q:str='',status_filter:str='',db:Session=Depends(dbdep),u:User=Depends(current_user)):
    stmt=select(Tender).order_by(Tender.submission_deadline.asc().nullslast())
    if q: stmt=stmt.where((Tender.title.ilike(f'%{q}%'))|(Tender.client.ilike(f'%{q}%'))|(Tender.tender_code.ilike(f'%{q}%')))
    if status_filter: stmt=stmt.where(Tender.status==status_filter)
    result=[]
    for t in db.scalars(stmt).all():
        owner=db.get(User,t.owner_id) if t.owner_id else None
        result.append({**tender_json(t),'owner_name':owner.name if owner else None,'owner_role':owner.role if owner else None})
    return result
def tender_json(t):
    return {'id':t.id,'tender_code':t.tender_code,'title':t.title,'client':t.client,'department':t.department,'description':t.description,'tender_value':t.tender_value,'submission_deadline':t.submission_deadline,'opening_date':t.opening_date,'owner_id':t.owner_id,'priority':t.priority,'status':t.status,'notes':t.notes,'fee_required':t.fee_required,'emd_required':t.emd_required,'created_at':t.created_at}
@app.post('/api/tenders',status_code=201)
def add_tender(data:TenderIn,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive'))):
    if db.scalar(select(Tender).where(Tender.tender_code==data.tender_code)): raise HTTPException(409,'Tender ID already exists')
    if data.owner_id is not None:
        if u.role not in {'Admin','Bid Manager'}: raise HTTPException(403,'Only an administrator or bid manager can assign a tender owner')
        owner=db.get(User,data.owner_id)
        if not owner or not owner.active: raise HTTPException(422,'Select an active user as tender owner')
    t=Tender(**data.model_dump()); db.add(t); db.flush(); create_checklist(db,t); log(db,u,'tender',t.id,'created','Compliance checklist generated')
    if t.owner_id and t.owner_id!=u.id: notify(db,t.owner_id,'Tender assigned to you',f'{t.tender_code} · {t.title}')
    db.commit(); db.refresh(t); return tender_json(t)
@app.get('/api/tenders/{tid}')
def tender_detail(tid:int,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    t=get_tender(db,tid); owner=db.get(User,t.owner_id) if t.owner_id else None; return {**tender_json(t),'owner_name':owner.name if owner else None,'owner_role':owner.role if owner else None,'compliance':[compliance_json(c) for c in db.scalars(select(ComplianceItem).where(ComplianceItem.tender_id==tid)).all()],'tasks':[task_json(x) for x in db.scalars(select(Task).where(Task.tender_id==tid)).all()]}
@app.patch('/api/tenders/{tid}')
def patch_tender(tid:int,data:TenderPatch,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive'))):
    t=get_tender(db,tid)
    changes=data.model_dump(exclude_unset=True)
    if 'owner_id' in changes:
        if u.role not in {'Admin','Bid Manager'}: raise HTTPException(403,'Only an administrator or bid manager can assign a tender owner')
        new_owner_id=changes['owner_id']; owner=db.get(User,new_owner_id) if new_owner_id is not None else None
        if new_owner_id is not None and (not owner or not owner.active): raise HTTPException(422,'Select an active user as tender owner')
        if new_owner_id!=t.owner_id:
            old_owner=t.owner_id; t.owner_id=new_owner_id
            log(db,u,'tender',tid,'owner reassigned',f'{old_owner or "Unassigned"} -> {new_owner_id or "Unassigned"}')
            if owner and owner.id!=u.id: notify(db,owner.id,'Tender assigned to you',f'{t.tender_code} · {t.title}')
        changes.pop('owner_id')
    for k,v in changes.items(): setattr(t,k,v)
    if t.status=='Ready for Submission':
        blockers=readiness(db,tid)['blockers']
        if blockers: raise HTTPException(409,detail={'message':'Tender has outstanding submission blockers','blockers':blockers})
    log(db,u,'tender',tid,'updated'); db.commit(); db.refresh(t); return tender_json(t)
@app.delete('/api/tenders/{tid}',status_code=204)
def delete_tender(tid:int,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager'))):
    t=get_tender(db,tid); log(db,u,'tender',tid,'deleted'); db.delete(t); db.commit()
def compliance_json(c):
    import json
    return {'id':c.id,'tender_id':c.tender_id,'category':c.category,'title':c.title,'required_fields':json.loads(c.required_fields),'data':json.loads(c.data_json),'required_attachments':json.loads(c.required_attachments),'owner_id':c.owner_id,'owner_name':c.owner.name if c.owner else None,'due_date':c.due_date,'status':c.status,'notes':c.notes}
@app.get('/api/tenders/{tid}/compliance')
def list_compliance(tid:int,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    get_tender(db,tid); return [compliance_json(x) for x in db.scalars(select(ComplianceItem).where(ComplianceItem.tender_id==tid)).all()]
@app.patch('/api/compliance/{cid}')
def patch_compliance(cid:int,data:CompliancePatch,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive','Finance','HR'))):
    c=db.get(ComplianceItem,cid)
    if not c: raise HTTPException(404,'Compliance item not found')
    changes=data.model_dump(exclude_unset=True)
    previous_status=c.status
    if 'owner_id' in changes:
        if u.role not in {'Admin','Bid Manager'}: raise HTTPException(403,'Only an administrator or bid manager can assign a compliance owner')
        new_owner_id=changes['owner_id']
        if new_owner_id is not None:
            owner=db.get(User,new_owner_id)
            if not owner or not owner.active: raise HTTPException(422,'Select an active user as compliance owner')
        if new_owner_id!=c.owner_id:
            c.owner_id=new_owner_id
            if new_owner_id and new_owner_id!=u.id: notify(db,new_owner_id,'Compliance item assigned to you',c.title)
        changes.pop('owner_id')
    if changes.get('status')=='Not Required':
        if u.role not in {'Admin','Bid Manager'}: raise HTTPException(403,'Only an administrator or bid manager can mark a requirement not applicable')
        reason=changes.get('notes',c.notes).strip()
        if not reason: raise HTTPException(422,'A reason is required when a requirement is marked not applicable')
    for k,v in changes.items():
        if k=='data_json': c.data_json=__import__('json').dumps(v)
        elif k=='status' and v not in {'Not Required','Not Started','Missing','In Progress'}: raise HTTPException(400,'Use the review workflow to change approval status')
        else: setattr(c,k,v)
    if c.status!=previous_status: log(db,u,'compliance',cid,'status changed',f'{previous_status} -> {c.status}: {c.notes}')
    else: log(db,u,'compliance',cid,'updated')
    db.commit(); return compliance_json(c)
@app.post('/api/tenders/{tid}/tasks',status_code=201)
def add_task(tid:int,data:TaskIn,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive'))):
    get_tender(db,tid); x=Task(tender_id=tid,**data.model_dump()); db.add(x); db.flush(); log(db,u,'task',x.id,'assigned'); db.commit(); return task_json(x)
def task_json(x): return {'id':x.id,'tender_id':x.tender_id,'title':x.title,'owner_id':x.owner_id,'due_date':x.due_date,'priority':x.priority,'status':x.status}
@app.get('/api/tasks')
def tasks(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    return [task_json(t) for t in db.scalars(select(Task).order_by(Task.due_date.asc().nullslast())).all()]
@app.post('/api/compliance/{cid}/submit-review')
def submit_review(cid:int,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive'))):
    c=db.get(ComplianceItem,cid)
    if not c: raise HTTPException(404,'Compliance item not found')
    if c.status=='Not Required': raise HTTPException(409,'This requirement is marked not applicable')
    if c.status=='Pending Approval': raise HTTPException(409,'This requirement is already awaiting review')
    missing=missing_for_item(db,c)
    if missing: raise HTTPException(409,detail={'message':'Complete required fields and attachments before review','missing':missing})
    c.status='Pending Approval'; db.add(Approval(tender_id=c.tender_id,compliance_id=cid,actor_id=u.id,action='Submitted for review')); log(db,u,'compliance',cid,'submitted for review')
    reviewers=db.scalars(select(User).where(User.active.is_(True),User.role.in_(['Admin','Reviewer/Approver']))).all()
    for reviewer in reviewers:
        if reviewer.id!=u.id: notify(db,reviewer.id,'Compliance approval requested',f'{c.title} · Tender #{c.tender_id}')
    db.commit(); return compliance_json(c)
@app.post('/api/compliance/{cid}/approval')
def act_approval(cid:int,data:ActionIn,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Reviewer/Approver'))):
    c=db.get(ComplianceItem,cid)
    if not c: raise HTTPException(404,'Compliance item not found')
    tender=get_tender(db,c.tender_id)
    if c.status!='Pending Approval': raise HTTPException(409,'This requirement is not awaiting approval')
    if tender.owner_id==u.id and u.role!='Admin': raise HTTPException(403,'Tender owners cannot approve their own submission')
    if data.action not in {'Approved','Rejected','Changes Requested'}: raise HTTPException(422,'Unsupported approval action')
    if data.action in {'Rejected','Changes Requested'} and not data.comments.strip(): raise HTTPException(422,'A comment is required for this decision')
    if data.action=='Approved':
        missing=missing_for_item(db,c)
        if missing: raise HTTPException(409,detail={'message':'Cannot approve an incomplete requirement','missing':missing})
    c.status=data.action; db.add(Approval(tender_id=c.tender_id,compliance_id=cid,actor_id=u.id,action=data.action,comments=data.comments)); log(db,u,'compliance',cid,data.action,data.comments)
    recipient=c.owner_id or tender.owner_id
    if recipient and recipient!=u.id: notify(db,recipient,f'Compliance {data.action.lower()}',f'{c.title} · Tender #{c.tender_id}'+(f' · {data.comments}' if data.comments else ''))
    db.commit(); return compliance_json(c)
@app.get('/api/tenders/{tid}/approvals')
def approvals(tid:int,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    get_tender(db,tid); return [{'id':a.id,'compliance_id':a.compliance_id,'actor_id':a.actor_id,'action':a.action,'comments':a.comments,'created_at':a.created_at} for a in db.scalars(select(Approval).where(Approval.tender_id==tid).order_by(Approval.created_at.desc())).all()]
@app.get('/api/approvals/pending')
def pending_approvals(db:Session=Depends(dbdep),u:User=Depends(require('Admin','Reviewer/Approver'))):
    rows=db.execute(select(ComplianceItem,Tender).join(Tender,Tender.id==ComplianceItem.tender_id).where(ComplianceItem.status=='Pending Approval').order_by(ComplianceItem.due_date.asc().nullslast())).all()
    return [{'id':c.id,'tender_id':t.id,'tender_code':t.tender_code,'tender_title':t.title,'title':c.title,'category':c.category,'owner_id':c.owner_id,'due_date':c.due_date,'status':c.status} for c,t in rows]
@app.post('/api/tenders/{tid}/documents',status_code=201)
async def upload(tid:int,file:UploadFile=File(...),compliance_id:int|None=None,db:Session=Depends(dbdep),u:User=Depends(require('Admin','Bid Manager','Bid Executive','Finance','HR'))):
    get_tender(db,tid); maxbytes=int(os.getenv('MAX_UPLOAD_MB','20'))*1024*1024
    allowed={'.pdf','.doc','.docx','.xls','.xlsx','.png','.jpg','.jpeg'}; suffix=Path(file.filename or '').suffix.lower()
    if suffix not in allowed: raise HTTPException(415,'Unsupported document type')
    raw=await file.read(maxbytes+1)
    if not raw or len(raw)>maxbytes: raise HTTPException(413,'File is empty or exceeds upload limit')
    if compliance_id and (not (c:=db.get(ComplianceItem,compliance_id)) or c.tender_id!=tid): raise HTTPException(422,'Compliance item does not belong to tender')
    root=Path(os.getenv('UPLOAD_DIR','./uploads')).resolve(); root.mkdir(parents=True,exist_ok=True); name=f'{uuid.uuid4().hex}{suffix}'; target=(root/name).resolve()
    if root not in target.parents: raise HTTPException(400,'Invalid file path')
    target.write_bytes(raw); d=Document(tender_id=tid,compliance_id=compliance_id,filename=Path(file.filename or 'document').name,storage_name=name,content_type=file.content_type or 'application/octet-stream',size=len(raw),uploader_id=u.id); db.add(d); db.flush(); log(db,u,'document',d.id,'uploaded',d.filename); db.commit()
    # Uploads remain pending review; file presence never grants approval.
    return {'id':d.id,'filename':d.filename,'size':d.size,'verification_status':d.verification_status,'uploaded_at':d.uploaded_at}
@app.get('/api/documents/{did}/download')
def download(did:int,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    from fastapi.responses import FileResponse
    d=db.get(Document,did)
    if not d: raise HTTPException(404,'Document not found')
    root=Path(os.getenv('UPLOAD_DIR','./uploads')).resolve(); target=(root/d.storage_name).resolve()
    if root not in target.parents or not target.is_file(): raise HTTPException(404,'Stored file not found')
    return FileResponse(target,filename=d.filename,media_type=d.content_type)
@app.get('/api/dashboard')
def dashboard(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    today=date.today(); tend=db.scalars(select(Tender)).all(); items=db.scalars(select(ComplianceItem)).all(); tasks_=db.scalars(select(Task)).all()
    blockers=[c for c in items if c.status not in {'Approved','Complete','Not Required'}]
    return {'total_tenders':len(tend),'active_bids':sum(t.status not in {'Submitted','Won','Lost','Cancelled'} for t in tend),'submitted_bids':sum(t.status=='Submitted' for t in tend),'pending_approvals':sum(c.status=='Pending Approval' for c in items),'incomplete_compliance':len(blockers),'upcoming_deadlines':sum(t.submission_deadline and today<=t.submission_deadline<=today+timedelta(days=14) for t in tend),'overdue_tasks':sum(x.due_date and x.due_date<today and x.status!='Complete' for x in tasks_),'compliance_percent':round(100*(len(items)-len(blockers))/len(items)) if items else 0,'pipeline':[{'status':s,'count':sum(t.status==s for t in tend)} for s in ['Draft','In Progress','Ready for Submission','Submitted','Won','Lost']],'recent_activity':[{'entity':a.entity,'entity_id':a.entity_id,'action':a.action,'details':a.details,'created_at':a.created_at} for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(8)).all()]}
def readiness(db,tid):
    t=get_tender(db,tid); cs=db.scalars(select(ComplianceItem).where(ComplianceItem.tender_id==tid)).all(); docs=db.scalars(select(Document).where(Document.tender_id==tid)).all(); blockers=[]
    import json
    for c in cs:
        if c.status=='Not Required': continue
        if c.status!='Approved': blockers.append({'requirement':c.title,'owner_id':c.owner_id,'due_date':str(c.due_date) if c.due_date else None,'approval_status':c.status,'reason':'Approval incomplete'})
        for reason in missing_for_item(db,c): blockers.append({'requirement':c.title,'owner_id':c.owner_id,'due_date':str(c.due_date) if c.due_date else None,'approval_status':c.status,'reason':reason})
    return {'tender_id':t.id,'tender_code':t.tender_code,'ready':len(blockers)==0,'blockers':blockers}
def missing_for_item(db,c):
    import json
    fields=json.loads(c.required_fields); values=json.loads(c.data_json); missing=[]
    if c.status=='Not Required': return missing
    missing.extend(f'Missing field: {key}' for key in fields if not str(values.get(key,'')).strip())
    docs=db.scalars(select(Document).where(Document.compliance_id==c.id)).all()
    for req in json.loads(c.required_attachments):
        if not any(req.casefold() in d.filename.casefold() and d.verification_status!='Rejected' for d in docs): missing.append(f'Missing attachment: {req}')
    for d in docs:
        if d.expires_on and d.expires_on<date.today(): missing.append(f'Expired document: {d.filename}')
    return missing
@app.get('/api/tenders/{tid}/readiness')
def tender_readiness(tid:int,db:Session=Depends(dbdep),u:User=Depends(current_user)): return readiness(db,tid)
@app.get('/api/reports/readiness.csv')
def readiness_csv(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    import csv,io
    from fastapi.responses import StreamingResponse
    out=io.StringIO(); w=csv.writer(out); w.writerow(['Tender ID','Tender','Ready','Blocker','Owner ID','Due Date','Approval Status'])
    for t in db.scalars(select(Tender)).all():
        r=readiness(db,t.id)
        if not r['blockers']: w.writerow([t.tender_code,t.title,'Yes','','','',''])
        for b in r['blockers']: w.writerow([t.tender_code,t.title,'No',b['requirement']+' — '+b['reason'],b['owner_id'],b['due_date'],b['approval_status']])
    return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=bid-readiness.csv'})
@app.get('/api/notifications')
def notifications(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    rows=db.scalars(select(Notification).where(Notification.user_id==u.id).order_by(Notification.created_at.desc()).limit(100)).all()
    return {'unread_count':sum(not n.read for n in rows),'items':[{'id':n.id,'title':n.title,'body':n.body,'read':n.read,'created_at':n.created_at} for n in rows]}
@app.patch('/api/notifications/{nid}')
def mark_notification(nid:int,data:NotificationPatch,db:Session=Depends(dbdep),u:User=Depends(current_user)):
    n=db.get(Notification,nid)
    if not n or n.user_id!=u.id: raise HTTPException(404,'Notification not found')
    n.read=data.read; db.commit(); return {'id':n.id,'read':n.read}
@app.post('/api/notifications/read-all')
def mark_all_notifications(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    rows=db.scalars(select(Notification).where(Notification.user_id==u.id,Notification.read.is_(False))).all()
    for n in rows: n.read=True
    db.commit(); return {'updated':len(rows)}
@app.get('/api/admin/compliance-contacts')
def contacts(db:Session=Depends(dbdep),u:User=Depends(current_user)):
    return [{'id':x.id,'name':x.name,'responsibility':x.responsibility,'email':x.email,'phone':x.phone,'category':x.category} for x in db.scalars(select(Contact)).all()]
class Contact(Base):
    __tablename__='contacts'
    id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(160)); responsibility:Mapped[str]=mapped_column(Text); email:Mapped[str]=mapped_column(String(250),default=''); phone:Mapped[str]=mapped_column(String(80),default=''); category:Mapped[str]=mapped_column(String(80),default='General')
@app.post('/api/admin/compliance-contacts',status_code=201)
def add_contact(data:ContactIn,db:Session=Depends(dbdep),u:User=Depends(require('Admin'))):
    x=Contact(**data.model_dump()); db.add(x); db.commit(); db.refresh(x); return {'id':x.id,'name':x.name,'responsibility':x.responsibility,'email':x.email,'phone':x.phone,'category':x.category}
@app.patch('/api/admin/compliance-contacts/{contact_id}')
def update_contact(contact_id:int,data:ContactPatch,db:Session=Depends(dbdep),u:User=Depends(require('Admin'))):
    x=db.get(Contact,contact_id)
    if not x: raise HTTPException(404,'Contact not found')
    for key,value in data.model_dump(exclude_unset=True).items(): setattr(x,key,value)
    db.commit(); db.refresh(x)
    return {'id':x.id,'name':x.name,'responsibility':x.responsibility,'email':x.email,'phone':x.phone,'category':x.category}

# Contact is declared after the initial metadata setup; create its table too.
Base.metadata.create_all(engine)
with SessionLocal() as seed_db:
    source_contacts=[
        ('Shambhavya Shanker','Approval using the RFP format for Bank Guarantee requests. The displayed PDF email spelling is Sambhavya.Shanker@in.ey.com.','Bank Guarantee','Sambhavya.Shanker@in.ey.com'),
        ('Poorvi Kulkarni','Operations coordination for Bank Guarantee requests','Bank Guarantee','Poorvi.Kulkarni@in.ey.com'),
        ('Karan Nailwal','Finance coordination for RFP/Bids financial document requests','Financial Documents','Karan.Nailwal@in.ey.com'),
        ('Gunjan Aggarwal','Finance coordination for RFP/Bids financial document requests','Financial Documents','Gunjan1.Agarwal@in.ey.com'),
        ('Sunayana Tewari','Primary Power of Attorney approval','Power of Attorney','sunayana.tewari@in.ey.com'),
        ('Tarun Tangri','Secondary Risk team approval for Power of Attorney','Power of Attorney','tarun.tangri@in.ey.com'),
        ('Sandeep Anand','Declaration / undertaking recipient','Declarations','Sandeep.Anand@in.ey.com'),
        ('Shikha Mendiratta','Declaration / undertaking recipient','Declarations','Shikha.Mendiratta@in.ey.com'),
        ('Rashmi Grover','Mandatory CC contact for declarations as specified in the RFP','Declarations','rashmi.grover@in.ey.com'),
        ('Varthika Gautam','Primary contact for Manpower / On-Roll Certificate','HR Documents','Varthikaa.Gautam@in.ey.com'),
        ('Ruchika Kohli Thandani','Mandatory CC contact for HR documents as specified in the RFP','HR Documents','ruchika.thadhani@in.ey.com'),
        ('Nisha Mansuri','Compliance-related queries and assistance','Compliance Queries','Nisha.Mansuri@in.ey.com'),
        ('Chirag Aggarwal','Compliance-related queries and assistance','Compliance Queries','Chirag.Agarwal1@in.ey.com'),
        ('Sahil','Compliance-related queries and assistance. The PDF lists this name with Mohit.Kumar11@in.ey.com; verify the identity before contacting.','Compliance Queries','Mohit.Kumar11@in.ey.com'),
    ]
    existing={x.name.casefold():x for x in seed_db.scalars(select(Contact)).all()}
    for name,responsibility,category,email in source_contacts:
        contact=existing.get(name.casefold())
        if contact is None:
            seed_db.add(Contact(name=name,responsibility=responsibility,category=category,email=email,phone=''))
        else:
            # Fill source email only where no value has been configured already.
            if not contact.email: contact.email=email
            if name=='Sahil' and 'verify the identity' not in contact.responsibility:
                contact.responsibility=responsibility
    seed_db.commit()

# Keep existing tenders aligned with the PDF-backed checklist while preserving entered values.
with SessionLocal() as checklist_db:
    aliases={
        'Relevant RFP Page Containing Refund Date':'Relevant Page No. of RFP having Refund Date',
        'RFP-format request prepared':'Approval email to Shambhavya Shanker (Sambhavya.Shanker@in.ey.com) using RFP format',
        'Forwarded to Operations':'Operations email to Poorvi Kulkarni (Poorvi.Kulkarni@in.ey.com)',
        'SR number':'Service Request number',
        'Finance team communication':'Finance communication with Karan Nailwal (Karan.Nailwal@in.ey.com) and Gunjan Aggarwal (Gunjan1.Agarwal@in.ey.com)',
        'Primary approval':'Primary approval from Sunayana Tewari',
        'Secondary Risk team approval':'Secondary Risk approval from Tarun Tangri',
        'Recipients':'Recipients: Sandeep Anand and Shikha Mendiratta',
        'Mandatory CC contacts':'Mandatory CC: Rashmi Grover',
        'Primary recipient':'Primary recipient: Varthika Gautam',
        'Mandatory CC contact':'Mandatory CC: Ruchika Kohli Thandani',
    }
    for tender in checklist_db.scalars(select(Tender)).all():
        present={x.category:x for x in checklist_db.scalars(select(ComplianceItem).where(ComplianceItem.tender_id==tender.id)).all()}
        for category,fields,attachments in CHECKLIST:
            if category.startswith('Tender Fee') and not tender.fee_required: continue
            if category.startswith('EMD') and not tender.emd_required: continue
            item=present.get(category)
            if item is None:
                item=ComplianceItem(tender_id=tender.id,category=category,title=category)
                checklist_db.add(item); checklist_db.flush()
            old_values=__import__('json').loads(item.data_json or '{}')
            for old,new in aliases.items():
                if old in old_values and new not in old_values: old_values[new]=old_values.pop(old)
            item.required_fields=__import__('json').dumps(fields)
            item.required_attachments=__import__('json').dumps(attachments)
            item.data_json=__import__('json').dumps(old_values)
    checklist_db.commit()
