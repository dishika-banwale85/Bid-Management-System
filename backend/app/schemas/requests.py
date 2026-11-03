from datetime import date, datetime
from typing import Literal
from app.models import BidStatus
from zoneinfo import ZoneInfo
from pydantic import AliasChoices, BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator
from typing import Literal

class TenderFeeData(BaseModel):
    model_config=ConfigDict(extra="forbid")
    client_name:str=Field(min_length=1); department:str=Field(min_length=1); mobile:str=Field(pattern=r"^\d{10}$")
    contact_person:str=Field(min_length=1); landline:str=Field(min_length=1); email:EmailStr
    beneficiary_name:str=Field(min_length=1); payment_mode:str=Field(min_length=1); relevant_rfp_pages:str=Field(min_length=1)
    amount:float=Field(gt=0); account_holder_name:str=Field(min_length=1); account_number:str=Field(pattern=r"^\d{9,18}$")
    branch_name:str=Field(min_length=1); ifsc:str=Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$"); branch_code:str=Field(min_length=1); micr:str=Field(pattern=r"^\d{9}$")

class EmdChallanData(TenderFeeData):
    address:str=Field(min_length=1); mode_of_approval:str=Field(min_length=1); approver_name:str=Field(min_length=1)
    purpose_of_payment:str=Field(min_length=1); last_emd_submission_date:date; expected_refund_date:date
    refund_date_rfp_page:str=Field(min_length=1); person_responsible_for_refund:str=Field(min_length=1)
    @model_validator(mode="after")
    def refund_after_submission(self):
        if self.expected_refund_date <= self.last_emd_submission_date: raise ValueError("Expected refund date must be after last EMD submission date")
        return self

class EmdBgData(BaseModel):
    model_config=ConfigDict(extra="forbid")
    engagement_code:str=Field(min_length=1); beneficiary_address:str=Field(min_length=1); mode_of_bg:str=Field(min_length=1)
    current_bg_maturity_date:date; tender_opening_date:date; contract_date:date; bg_amount:float=Field(gt=0)
    contract_value:float=Field(gt=0); contract_description:str=Field(min_length=1); bg_issued_from:str=Field(min_length=1); approved_by:str=Field(min_length=1)
    @model_validator(mode="after")
    def dates_valid(self):
        if self.tender_opening_date is None: raise ValueError("Tender opening date is required")
        if self.current_bg_maturity_date <= self.contract_date: raise ValueError("BG maturity date must be after contract date")
        return self

class FinancialDocumentsData(BaseModel):
    # Ignore legacy draft keys (such as the removed purpose field) on resubmit.
    model_config=ConfigDict(extra="ignore")
    description:str=Field(min_length=1); documents_required:list[Literal["Balance Sheet","Turnover Certificate","CA Certificate","Net Worth Certificate","Other"]]=Field(min_length=1)
    financial_years:str=Field(min_length=1)
class PowerOfAttorneyData(BaseModel):
    # Ignore the removed legacy fields when a saved draft is resubmitted.
    model_config=ConfigDict(extra="ignore")
    signatory_name:str=Field(min_length=1)
    validity_period:int=Field(gt=0); rfp_format_attached:bool
class DeclarationData(BaseModel):
    # Ignore the removed legacy Subject field when resubmitting an existing draft.
    model_config=ConfigDict(extra="ignore")
    declaration_type:Literal["Declaration","Undertaking","Self Declaration","Litigation","Blacklisting"]
    rfp_clause_reference:str=Field(min_length=1)
class HRDocumentsData(BaseModel):
    model_config=ConfigDict(extra="forbid")
    certificate_type:Literal["Manpower Certificate","On-Roll Certificate"]; number_of_employees:int=Field(gt=0); details_required:str=Field(min_length=1)
class OmsPaceRedflagData(BaseModel):
    model_config=ConfigDict(extra="forbid")
    oms_created:Literal["Yes","No"]
    oms_id:str|None=None
    pace_created:Literal["Yes","No"]
    pace_id:str|None=None
    approval_status:Literal["PENDING","APPROVED"]|None=None
    red_flag_status:Literal["INITIATED","NOT_INITIATED"]
    @field_validator("oms_id","pace_id",mode="before")
    @classmethod
    def clean_id(cls,v):
        if v is None:return None
        v=v.strip() if isinstance(v,str) else v
        if not isinstance(v,str) or len(v)>60 or (v and not __import__("re").fullmatch(r"[A-Za-z0-9 /_-]+",v)):raise ValueError("Use up to 60 letters, numbers, spaces, dashes, slashes or underscores")
        return v or None
    @model_validator(mode="after")
    def dependent_fields(self):
        if self.oms_created=="Yes" and not self.oms_id:raise ValueError("OMS ID is required when OMS created is Yes")
        if self.pace_created=="Yes" and (not self.pace_id or not self.approval_status):raise ValueError("PACE ID and Approval are required when PACE created is Yes")
        if self.oms_created=="No" and self.oms_id:raise ValueError("OMS ID must be empty when OMS created is No")
        if self.pace_created=="No" and (self.pace_id or self.approval_status):raise ValueError("PACE fields must be empty when PACE created is No")
        return self

class RequestCreate(BaseModel): bid_id:int; type:Literal["TENDER_FEE","EMD_CHALLAN","EMD_BG","FINANCIAL_DOCUMENTS","POWER_OF_ATTORNEY","DECLARATION","HR_DOCUMENTS","OMS_PACE_REDFLAG"]; form_data:dict=Field(default_factory=dict)
class RequestUpdate(BaseModel): form_data:dict
class LoginIn(BaseModel):
    email:EmailStr
    password:str
    captcha_id:str|None=None
    captcha_answer:str|None=None
    captcha_token:str|None=None
class DecisionIn(BaseModel): comment:str|None=None
class ActionIn(BaseModel): extra_data:dict=Field(default_factory=dict)
class BidIn(BaseModel):
    model_config=ConfigDict(extra="ignore",populate_by_name=True)
    client_name:str=Field(min_length=1,max_length=200)
    department:str|None=Field(default=None,max_length=160)
    rfp_reference:str=Field(validation_alias=AliasChoices("rfp_number","rfp_reference"),min_length=1,max_length=120)
    project_title:str=Field(min_length=1,max_length=250)
    rfp_published_date:date
    submission_deadline:date
    tender_opening_date:date
    prebid_meeting_date:date|None
    prebid_query_deadline:date|None
    prebid_meeting_na:bool=False
    prebid_query_na:bool=False
    client_address:str=Field(min_length=1,max_length=500)
    bid_status:BidStatus=BidStatus.NOT_SUBMITTED

    @field_validator("client_name","rfp_reference","project_title","client_address",mode="before")
    @classmethod
    def trim_required_text(cls,value):
        return value.strip() if isinstance(value,str) else value

    @field_validator("department",mode="before")
    @classmethod
    def trim_department(cls,value):
        return value.strip() if isinstance(value,str) else value

    @field_validator("submission_deadline")
    @classmethod
    def submission_not_in_past(cls,value):
        if value<datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("submission_deadline cannot be before today when creating a bid")
        return value

    @field_validator("tender_opening_date")
    @classmethod
    def opening_not_in_past(cls,value):
        if value<datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("tender_opening_date cannot be before today when creating a bid")
        return value

    @model_validator(mode="after")
    def deadlines(self):
        errors=[]
        if self.prebid_meeting_na:
            self.prebid_meeting_date=None
        elif self.prebid_meeting_date is None:
            errors.append("prebid_meeting_date is required unless prebid_meeting_na is true")
        if self.prebid_query_na:
            self.prebid_query_deadline=None
        elif self.prebid_query_deadline is None:
            errors.append("prebid_query_deadline is required unless prebid_query_na is true")
        if self.rfp_published_date>self.submission_deadline:
            errors.append("rfp_published_date must be on or before submission_deadline")
        if self.submission_deadline>self.tender_opening_date:
            errors.append("tender_opening_date must be on or after submission_deadline")
        for name,value in (("prebid_meeting_date",self.prebid_meeting_date),("prebid_query_deadline",self.prebid_query_deadline)):
            if value and not self.rfp_published_date<=value<=self.submission_deadline:
                errors.append(f"{name} must be between rfp_published_date and submission_deadline")
        if errors:
            raise ValueError("; ".join(errors))
        return self

class BidUpdate(BaseModel):
    model_config=ConfigDict(extra="ignore",populate_by_name=True)
    client_name:str|None=Field(default=None,min_length=1,max_length=200)
    department:str|None=Field(default=None,max_length=160)
    rfp_reference:str|None=Field(default=None,validation_alias=AliasChoices("rfp_number","rfp_reference"),min_length=1,max_length=120)
    project_title:str|None=Field(default=None,min_length=1,max_length=250)
    rfp_published_date:date|None=None
    submission_deadline:date|None=None
    tender_opening_date:date|None=None
    prebid_meeting_date:date|None=None
    prebid_query_deadline:date|None=None
    prebid_meeting_na:bool|None=None
    prebid_query_na:bool|None=None
    client_address:str|None=Field(default=None,max_length=500)
    bid_status:BidStatus|None=None

    @field_validator("client_name","rfp_reference","project_title","client_address","department",mode="before")
    @classmethod
    def trim_optional_text(cls,value):
        return value.strip() if isinstance(value,str) else value

class BidOut(BaseModel):
    id:int
    client_name:str
    department:str|None
    rfp_reference:str
    rfp_number:str
    project_title:str|None
    rfp_published_date:date|None
    submission_deadline:date
    tender_opening_date:date
    prebid_meeting_date:date|None
    prebid_query_deadline:date|None
    prebid_meeting_na:bool
    prebid_query_na:bool
    client_address:str|None
    status:str
    bid_status:BidStatus=BidStatus.NOT_SUBMITTED
    rfp:dict|None=None
    can_manage_bid:bool=False
    request_count:int=0
    completed_count:int=0
    progress:int=0
    checklist_percent:int=0
    missing_count:int=0
    can_delete:bool=False
    can_delete_control:bool=False
    delete_blocked_reason:str|None=None
    draft_request_count:int=0
    submitted_request_count:int=0
    file_count:int=0

class BidDetailOut(BidOut):
    requests:list[dict]
class BidChecklistNAIn(BaseModel):
    request_type:Literal["TENDER_FEE","EMD_CHALLAN","EMD_BG","FINANCIAL_DOCUMENTS","POWER_OF_ATTORNEY","DECLARATION","HR_DOCUMENTS"]
    applicable:bool
class ContactIn(BaseModel):
    request_type:str|None=None
    contact_type:Literal["PRIMARY","CC","VETTING","OPERATIONS","PROCESSING","RISK","ESCALATION"]
    name:str=Field(min_length=2,max_length=160)
    designation:str|None=None
    department:str|None=None
    email:EmailStr|None=None
    is_active:bool=True
    @field_validator("email",mode="before")
    @classmethod
    def blank_contact_email(cls,value):return None if isinstance(value,str) and not value.strip() else value
class RefundReceivedIn(BaseModel): received_date:date
