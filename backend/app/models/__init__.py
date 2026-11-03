import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Text, Boolean, JSON, Enum, UniqueConstraint, Index
from sqlalchemy.types import TypeDecorator
import os, json, base64, hashlib
from cryptography.fernet import Fernet
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.core.config import FERNET_KEY, JWT_SECRET

_raw_key = FERNET_KEY or JWT_SECRET
try:
    _cipher = Fernet(_raw_key.encode())
except Exception:
    _cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_raw_key.encode()).digest()))

class EncryptedJSON(TypeDecorator):
    """Authenticated encryption at rest for form data, including bank account numbers."""
    impl=Text
    cache_ok=True
    def process_bind_param(self,value,dialect):
        return _cipher.encrypt(json.dumps(value,separators=(",",":")).encode()).decode() if value is not None else None
    def process_result_value(self,value,dialect):
        return json.loads(_cipher.decrypt(value.encode()).decode()) if value is not None else None

def now(): return datetime.now(timezone.utc)

class Role(Base):
    __tablename__="roles"
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(30),unique=True,index=True)
    users: Mapped[list["User"]]=relationship(back_populates="role")

class User(Base):
    __tablename__="users"
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    full_name: Mapped[str]=mapped_column(String(160))
    password_hash: Mapped[str]=mapped_column(String(255))
    role_id: Mapped[int]=mapped_column(ForeignKey("roles.id"),index=True)
    role: Mapped[Role]=relationship(back_populates="users")
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)

class BidStatus(str,enum.Enum):
    SUBMITTED="SUBMITTED"
    NOT_SUBMITTED="NOT_SUBMITTED"
    WIN="WIN"
    WITHDRAW="WITHDRAW"
    LOSE="LOSE"


class Bid(Base):
    __tablename__="bids"
    id: Mapped[int]=mapped_column(primary_key=True)
    client_name: Mapped[str]=mapped_column(String(200),index=True)
    department: Mapped[str]=mapped_column(String(160))
    rfp_reference: Mapped[str]=mapped_column(String(120),index=True)
    rfp_published_date: Mapped[datetime|None]=mapped_column(Date,nullable=True)
    project_title: Mapped[str|None]=mapped_column(String(250),nullable=True)
    prebid_meeting_date: Mapped[datetime|None]=mapped_column(Date,nullable=True)
    prebid_query_deadline: Mapped[datetime|None]=mapped_column(Date,nullable=True)
    prebid_meeting_na: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    prebid_query_na: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    client_address: Mapped[str|None]=mapped_column(String(500),nullable=True)
    tender_opening_date: Mapped[datetime]=mapped_column(Date)
    submission_deadline: Mapped[datetime]=mapped_column(Date,index=True)
    status: Mapped[str]=mapped_column(String(40),default="IN_PROGRESS",index=True)
    bid_status: Mapped[BidStatus]=mapped_column(Enum(BidStatus,native_enum=False,create_constraint=True,name="bid_status_values",length=20),default=BidStatus.NOT_SUBMITTED,server_default="NOT_SUBMITTED",nullable=False,index=True)
    created_by: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    deleted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    deleted_by: Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    delete_reason: Mapped[str|None]=mapped_column(Text,nullable=True)
    deleter: Mapped[User|None]=relationship(foreign_keys=[deleted_by])
    requests: Mapped[list["ComplianceRequest"]]=relationship(back_populates="bid")
    rfp_document: Mapped["BidDocument|None"]=relationship(back_populates="bid",cascade="all, delete-orphan",uselist=False)


class BidDocument(Base):
    __tablename__="bid_documents"
    id: Mapped[int]=mapped_column(primary_key=True)
    bid_id: Mapped[int]=mapped_column(ForeignKey("bids.id",ondelete="CASCADE"),unique=True,index=True)
    document_type: Mapped[str]=mapped_column(String(20),default="RFP",server_default="RFP",nullable=False)
    original_name: Mapped[str]=mapped_column(String(255),nullable=False)
    stored_name: Mapped[str]=mapped_column(String(255),unique=True,nullable=False)
    size: Mapped[int]=mapped_column(Integer,nullable=False)
    content_type: Mapped[str]=mapped_column(String(120),nullable=False)
    uploaded_by: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    uploaded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False,index=True)
    bid: Mapped[Bid]=relationship(back_populates="rfp_document")
    uploader: Mapped[User]=relationship(foreign_keys=[uploaded_by])

class RequestStatus(str,enum.Enum): DRAFT="DRAFT"; SUBMITTED="SUBMITTED"; IN_APPROVAL="IN_APPROVAL"; REJECTED="REJECTED"; COMPLETED="COMPLETED"
class StepStatus(str,enum.Enum): PENDING="PENDING"; ACTIVE="ACTIVE"; APPROVED="APPROVED"; REJECTED="REJECTED"; DONE="DONE"; SKIPPED="SKIPPED"
class StepKind(str,enum.Enum): APPROVAL="APPROVAL"; ACTION="ACTION"

class ComplianceRequest(Base):
    __tablename__="compliance_requests"
    id: Mapped[int]=mapped_column(primary_key=True)
    bid_id: Mapped[int]=mapped_column(ForeignKey("bids.id",ondelete="CASCADE"),index=True)
    type: Mapped[str]=mapped_column(String(40),index=True)
    status: Mapped[RequestStatus]=mapped_column(Enum(RequestStatus,native_enum=False,length=20),default=RequestStatus.DRAFT,index=True)
    form_data: Mapped[dict]=mapped_column(EncryptedJSON(),default=dict)
    created_by: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    refund_received_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    bid: Mapped[Bid]=relationship(back_populates="requests")
    creator: Mapped[User]=relationship(foreign_keys=[created_by])
    documents: Mapped[list["Document"]]=relationship(back_populates="request",cascade="all, delete-orphan")
    steps: Mapped[list["RequestStep"]]=relationship(back_populates="request",cascade="all, delete-orphan")

class WorkflowTemplate(Base):
    __tablename__="workflow_templates"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_type: Mapped[str]=mapped_column(String(40),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(120))
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    version: Mapped[int]=mapped_column(Integer,default=1)
    steps: Mapped[list["WorkflowStep"]]=relationship(back_populates="template",cascade="all, delete-orphan",order_by="WorkflowStep.step_order")

class WorkflowStep(Base):
    __tablename__="workflow_steps"
    id: Mapped[int]=mapped_column(primary_key=True)
    template_id: Mapped[int]=mapped_column(ForeignKey("workflow_templates.id",ondelete="CASCADE"),index=True)
    version: Mapped[int]=mapped_column(Integer,default=1,index=True)
    step_order: Mapped[int]=mapped_column(Integer)
    name: Mapped[str]=mapped_column(String(120))
    step_kind: Mapped[StepKind]=mapped_column(Enum(StepKind,native_enum=False,length=20))
    assigned_role: Mapped[str]=mapped_column(String(30),index=True)
    requires_fields: Mapped[list]=mapped_column(JSON,default=list)
    template: Mapped[WorkflowTemplate]=relationship(back_populates="steps")
    __table_args__=(UniqueConstraint("template_id","version","step_order"),)

class FormTemplate(Base):
    __tablename__="form_templates"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_type: Mapped[str]=mapped_column(String(40),unique=True,index=True)
    display_name: Mapped[str]=mapped_column(String(120))
    fields: Mapped[list]=mapped_column(JSON,default=list)
    required_documents: Mapped[list]=mapped_column(JSON,default=list)
    updated_by: Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class RequestStep(Base):
    __tablename__="request_steps"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_id: Mapped[int]=mapped_column(ForeignKey("compliance_requests.id",ondelete="CASCADE"),index=True)
    step_id: Mapped[int]=mapped_column(ForeignKey("workflow_steps.id"),index=True)
    attempt: Mapped[int]=mapped_column(Integer,default=1)
    status: Mapped[StepStatus]=mapped_column(Enum(StepStatus,native_enum=False,length=20),default=StepStatus.PENDING,index=True)
    acted_by: Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    acted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    comment: Mapped[str|None]=mapped_column(Text,nullable=True)
    extra_data: Mapped[dict]=mapped_column(JSON,default=dict)
    request: Mapped[ComplianceRequest]=relationship(back_populates="steps")
    workflow_step: Mapped[WorkflowStep]=relationship()
    actor: Mapped[User|None]=relationship(foreign_keys=[acted_by])
    __table_args__=(UniqueConstraint("request_id","attempt","step_id"),Index("ix_request_steps_attempt_status","request_id","attempt","status"))

class Document(Base):
    __tablename__="documents"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_id: Mapped[int]=mapped_column(ForeignKey("compliance_requests.id",ondelete="CASCADE"),index=True)
    category: Mapped[str]=mapped_column(String(60),index=True)
    document_type: Mapped[str]=mapped_column(String(60),default="OTHER",index=True)
    filename: Mapped[str]=mapped_column(String(255))
    stored_name: Mapped[str]=mapped_column(String(255),unique=True)
    content_type: Mapped[str]=mapped_column(String(120))
    version: Mapped[int]=mapped_column(Integer,default=1)
    uploaded_by: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    request: Mapped[ComplianceRequest]=relationship(back_populates="documents")
    uploader: Mapped[User]=relationship(foreign_keys=[uploaded_by])
    __table_args__=(Index("ix_docs_request_category_version","request_id","category","version"),)

class Contact(Base):
    __tablename__="contacts"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_type: Mapped[str|None]=mapped_column(String(40),nullable=True,index=True)
    contact_type: Mapped[str]=mapped_column(String(30),default="PRIMARY",index=True)
    name: Mapped[str]=mapped_column(String(160))
    designation: Mapped[str|None]=mapped_column(String(160),nullable=True)
    department: Mapped[str|None]=mapped_column(String(160),nullable=True)
    email: Mapped[str|None]=mapped_column(String(255),nullable=True)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)

class EmailLog(Base):
    __tablename__="email_logs"
    id: Mapped[int]=mapped_column(primary_key=True)
    to: Mapped[str]=mapped_column(Text)
    cc: Mapped[str]=mapped_column(Text,default="")
    subject: Mapped[str]=mapped_column(String(255))
    template: Mapped[str]=mapped_column(String(100))
    status: Mapped[str]=mapped_column(String(32),index=True)
    error: Mapped[str|None]=mapped_column(Text,nullable=True)
    related_request_id: Mapped[int|None]=mapped_column(ForeignKey("compliance_requests.id",ondelete="SET NULL"),nullable=True,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Notification(Base):
    __tablename__="notifications"
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    message: Mapped[str]=mapped_column(Text)
    request_id: Mapped[int|None]=mapped_column(ForeignKey("compliance_requests.id",ondelete="CASCADE"),nullable=True,index=True)
    is_read: Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    user: Mapped[User]=relationship()

class AuditLog(Base):
    __tablename__="audit_logs"
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    action: Mapped[str]=mapped_column(String(80),index=True)
    request_id: Mapped[int|None]=mapped_column(ForeignKey("compliance_requests.id",ondelete="SET NULL"),nullable=True,index=True)
    entity_type: Mapped[str]=mapped_column(String(50),default="ComplianceRequest")
    entity_id: Mapped[int]=mapped_column(Integer,index=True)
    old_status: Mapped[str|None]=mapped_column(String(30),nullable=True)
    new_status: Mapped[str|None]=mapped_column(String(30),nullable=True)
    detail: Mapped[dict]=mapped_column(JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)

class ReminderSent(Base):
    __tablename__="reminders_sent"
    id: Mapped[int]=mapped_column(primary_key=True)
    request_id: Mapped[int]=mapped_column(ForeignKey("compliance_requests.id",ondelete="CASCADE"),index=True)
    reminder_key: Mapped[str]=mapped_column(String(120))
    sent_on: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint("request_id","reminder_key"),)

class CaptchaChallenge(Base):
    __tablename__="captcha_challenges"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    answer_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    used_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)

class BidChecklistNA(Base):
    __tablename__="bid_checklist_na"
    bid_id: Mapped[int]=mapped_column(ForeignKey("bids.id",ondelete="CASCADE"),primary_key=True)
    request_type: Mapped[str]=mapped_column(String(40),primary_key=True,index=True)
    marked_by: Mapped[int]=mapped_column(ForeignKey("users.id"),nullable=False,index=True)
    marked_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)
