from typing import Literal
from pydantic import BaseModel,Field,EmailStr,ConfigDict,field_validator

REQUEST_TYPES={"TENDER_FEE","EMD_CHALLAN","EMD_BG","FINANCIAL_DOCUMENTS","POWER_OF_ATTORNEY","DECLARATION","HR_DOCUMENTS","FEE","EMD","PACE","BANK_GUARANTEE"}
ROLES={"BID_TEAM","APPROVER","PACE_COORDINATOR","ADMIN"}
DOC_CATEGORIES={"generated_challan","checklist","bg_format","ca_certificate","final_approval","poa_format","executed_poa","required_document_format","rfp","ep_approval","bg_copy","rfp_format","financial_documents","signed_declaration","hr_certificate"}

class WorkflowStepIn(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    step_kind:Literal["APPROVAL","ACTION"]
    assigned_role:str
    requires_fields:list[str]=Field(default_factory=list)
    @field_validator("assigned_role")
    @classmethod
    def valid_role(cls,value):
        if value not in ROLES:raise ValueError("Unknown workflow role")
        return value

class WorkflowUpdateIn(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    is_active:bool=True
    steps:list[WorkflowStepIn]=Field(min_length=1,max_length=12)

class FormFieldIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    key:str=Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    label:str=Field(min_length=1,max_length=120)
    section:str=Field(min_length=1,max_length=80)
    type:Literal["text","email","number","date","select","multi","textarea","boolean"]="text"
    required:bool=True
    options:list[str]=Field(default_factory=list,max_length=30)
    @field_validator("options")
    @classmethod
    def clean_options(cls,value):
        if any(not x.strip() or len(x)>100 for x in value):raise ValueError("Options must be nonempty and at most 100 characters")
        if len(set(value))!=len(value):raise ValueError("Options must be unique")
        return value

class FormTemplateUpdateIn(BaseModel):
    display_name:str=Field(min_length=2,max_length=120)
    fields:list[FormFieldIn]=Field(min_length=1,max_length=80)
    required_documents:list[str]=Field(default_factory=list,max_length=8)
    @field_validator("required_documents")
    @classmethod
    def validate_documents(cls,value):
        if any(doc not in DOC_CATEGORIES for doc in value):raise ValueError("Unknown required document category")
        if len(set(value))!=len(value):raise ValueError("Required document categories must be unique")
        return value
    @field_validator("fields")
    @classmethod
    def unique_keys(cls,value):
        keys=[field.key for field in value]
        if len(set(keys))!=len(keys):raise ValueError("Field keys must be unique")
        return value

class ContactAdminIn(BaseModel):
    request_type:str|None=None
    contact_type:Literal["PRIMARY","CC","VETTING","OPERATIONS","PROCESSING","RISK","ESCALATION"]
    name:str=Field(min_length=2,max_length=160)
    designation:str|None=Field(default=None,max_length=160)
    department:str|None=Field(default=None,max_length=160)
    email:EmailStr|None=None
    is_active:bool=True
    @field_validator("email",mode="before")
    @classmethod
    def blank_email_is_missing(cls,value):
        return None if isinstance(value,str) and not value.strip() else value
    @field_validator("request_type")
    @classmethod
    def valid_request_type(cls,value):
        if value is not None and value not in REQUEST_TYPES:raise ValueError("Unknown request type")
        return value

class UserCreateIn(BaseModel):
    email:EmailStr
    full_name:str=Field(min_length=2,max_length=160)
    role:str
    password:str=Field(min_length=8,max_length=128)
    @field_validator("role")
    @classmethod
    def valid_role(cls,value):
        if value not in ROLES:raise ValueError("Unknown role")
        return value

class UserUpdateIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=160)
    role:str
    is_active:bool=True
    password:str|None=Field(default=None,min_length=8,max_length=128)
    @field_validator("role")
    @classmethod
    def valid_role(cls,value):
        if value not in ROLES:raise ValueError("Unknown role")
        return value
