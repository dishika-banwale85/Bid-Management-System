from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import re
from zipfile import is_zipfile

from openpyxl import load_workbook


FORM_FIELDS = {
    "TENDER_FEE": [
        "client_name", "department", "mobile", "contact_person", "landline", "email",
        "beneficiary_name", "payment_mode", "relevant_rfp_pages", "amount",
        "account_holder_name", "account_number", "branch_name", "ifsc", "branch_code", "micr",
    ],
    "EMD_CHALLAN": [
        "client_name", "department", "mobile", "contact_person", "landline", "email",
        "beneficiary_name", "payment_mode", "relevant_rfp_pages", "amount", "purpose_of_payment",
        "address", "mode_of_approval", "approver_name", "person_responsible_for_refund",
        "refund_date_rfp_page", "account_holder_name", "account_number", "branch_name", "ifsc",
        "branch_code", "micr", "last_emd_submission_date", "expected_refund_date",
    ],
    "EMD_BG": [
        "engagement_code", "beneficiary_address", "mode_of_bg", "current_bg_maturity_date",
        "tender_opening_date", "contract_date", "bg_amount", "contract_value",
        "contract_description", "bg_issued_from", "approved_by",
    ],
}

FIELD_LABELS = {
    "client_name": "Client name", "department": "Department", "mobile": "Mobile",
    "contact_person": "Contact person", "landline": "Landline", "email": "Email",
    "beneficiary_name": "Beneficiary name", "payment_mode": "Payment mode",
    "relevant_rfp_pages": "Relevant RFP pages", "amount": "Amount",
    "account_holder_name": "Account holder name", "account_number": "Account number",
    "branch_name": "Branch name", "ifsc": "IFSC", "branch_code": "Branch code", "micr": "MICR",
    "purpose_of_payment": "Purpose of payment", "address": "Address",
    "mode_of_approval": "Mode of approval", "approver_name": "Approver name",
    "person_responsible_for_refund": "Person responsible for refund",
    "refund_date_rfp_page": "RFP page with refund date",
    "last_emd_submission_date": "Last EMD submission date", "expected_refund_date": "Expected refund date",
    "engagement_code": "Engagement code", "beneficiary_address": "Beneficiary address",
    "mode_of_bg": "Mode of BG", "current_bg_maturity_date": "Current BG maturity date",
    "tender_opening_date": "Tender opening date", "contract_date": "Contract date",
    "bg_amount": "BG amount", "contract_value": "Contract value",
    "contract_description": "Contract description", "bg_issued_from": "BG issued from",
    "approved_by": "Approved by",
}

SYNONYMS = {
    "client_name": ("client name",),
    "department": ("department",),
    "mobile": ("mobile number", "mobile no", "mobile"),
    "contact_person": ("contact person",),
    "landline": ("landline number", "landline"),
    "email": ("email id", "email", "e-mail"),
    "beneficiary_name": ("beneficiary name",),
    "payment_mode": ("payment mode",),
    "relevant_rfp_pages": ("relevant rfp pages", "rfp pages"),
    "amount": ("amount",),
    "account_holder_name": ("account holder name",),
    "account_number": ("account number", "account no", "a/c no"),
    "branch_name": ("branch name",),
    "ifsc": ("ifsc code", "ifsc", "ifsa"),
    "branch_code": ("branch code",),
    "micr": ("micr code", "micr"),
}

_SERIAL_LABELS = {"s no", "serial no", "serial number", "sr no", "no"}


class InvalidChecklist(ValueError):
    """The supplied file is not a readable XLSX workbook."""


def _normalise_label(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^\s*\d+\s*[.)]\s*", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _label_map(request_type: str) -> dict[str, str]:
    fields = FORM_FIELDS[request_type]
    labels: dict[str, str] = {}
    for key in fields:
        labels[_normalise_label(key)] = key
        labels[_normalise_label(FIELD_LABELS.get(key, key.replace("_", " ")))] = key
        for alias in SYNONYMS.get(key, ()):
            labels[_normalise_label(alias)] = key
    return labels


def _cell_text(cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
            text = format(number.quantize(Decimal(1)), "f") if number == number.to_integral_value() else format(number.normalize(), "f")
        except InvalidOperation:
            text = str(value)
        number_format = str(getattr(cell, "number_format", "") or "")
        if number == number.to_integral_value() and re.fullmatch(r"0+", number_format):
            text = text.zfill(len(number_format))
        return text
    return str(value).strip()


def _clean_value(field: str, cell):
    value = _cell_text(cell).strip()
    if not value:
        return None
    if field == "mobile":
        digits = re.sub(r"\D", "", value)
        return digits[-10:] if digits else None
    if field in {"account_number", "micr", "branch_code"}:
        digits = re.sub(r"\D", "", value)
        return digits or None
    if field == "ifsc":
        return re.sub(r"\s+", "", value).upper()
    if field in {"amount", "bg_amount", "contract_value"}:
        amount = re.sub(r"(?i)\b(?:rs\.?|inr)\b", "", value)
        amount = re.sub(r"[^0-9.\-]", "", amount)
        try:
            number = Decimal(amount)
        except InvalidOperation:
            return None
        return int(number) if number == number.to_integral_value() else float(number)
    if field == "email":
        return value.lower()
    return value


def validate_xlsx(raw: bytes, filename: str):
    if Path(filename or "").suffix.lower() != ".xlsx" or not raw.startswith(b"PK") or not is_zipfile(BytesIO(raw)):
        raise InvalidChecklist("Please upload a valid .xlsx Excel checklist.")
    try:
        return load_workbook(BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise InvalidChecklist("This Excel checklist is corrupt or cannot be opened. Please choose a valid .xlsx file.") from exc


def parse_checklist_xlsx(raw: bytes, filename: str, request_type: str) -> dict:
    if request_type not in FORM_FIELDS:
        raise ValueError("Checklist parsing is supported for Tender Fee, EMD by Challan and EMD by Bank Guarantee.")

    workbook = validate_xlsx(raw, filename)
    labels = _label_map(request_type)
    fields: dict[str, object] = {}
    try:
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows()]
            for row_index, row in enumerate(rows):
                matches = [(index, labels[_normalise_label(cell.value)]) for index, cell in enumerate(row)
                           if _normalise_label(cell.value) in labels]
                nonempty = [cell for cell in row if _cell_text(cell).strip()]
                nonlabel_count = sum(1 for cell in nonempty
                                     if _normalise_label(cell.value) not in labels
                                     and _normalise_label(cell.value) not in _SERIAL_LABELS)

                # A row made mostly of labels is a header; its values are in the next row.
                is_header = len(matches) >= 2 and nonlabel_count <= 1
                if is_header and row_index + 1 < len(rows):
                    value_row = rows[row_index + 1]
                    for column, field in matches:
                        if column < len(value_row):
                            cleaned = _clean_value(field, value_row[column])
                            if cleaned is not None:
                                fields[field] = cleaned
                    continue

                for column, field in matches:
                    value_cell = None
                    for candidate in row[column + 1:]:
                        if _cell_text(candidate).strip():
                            if _normalise_label(candidate.value) not in labels:
                                value_cell = candidate
                            break
                    if value_cell is None and row_index + 1 < len(rows) and column < len(rows[row_index + 1]):
                        value_cell = rows[row_index + 1][column]
                    if value_cell is not None:
                        cleaned = _clean_value(field, value_cell)
                        if cleaned is not None:
                            fields[field] = cleaned
    except Exception as exc:
        raise InvalidChecklist("This Excel checklist is corrupt or cannot be opened. Please choose a valid .xlsx file.") from exc
    finally:
        workbook.close()

    missing_keys = [key for key in FORM_FIELDS[request_type] if key not in fields]
    status = "NONE" if not fields else "PARTIAL" if missing_keys else "OK"
    return {
        "status": status,
        "fields": fields,
        "missing": [FIELD_LABELS.get(key, key.replace("_", " ").title()) for key in missing_keys],
    }
