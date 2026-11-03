from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.security import create_token
from app.db import get_db
from app.main import app


@pytest.fixture
def authenticated_client(db):
    def override_db():
        yield db["db"]

    app.dependency_overrides[get_db] = override_db
    token = create_token(db["users"]["BID_TEAM"])
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {token}"}
    app.dependency_overrides.clear()


def test_tender_fee_checklist_parses_all_sixteen_fields(authenticated_client):
    client, headers = authenticated_client
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["S.No", "Label", "Value"])
    rows = [
        ("Client Name", "Example Client"),
        ("Department", "Public Works"),
        ("Mobile Number", "+91 98765 43210"),
        ("Contact Person", "Riya Sharma"),
        ("Landline Number", "01123456789"),
        ("Email ID", "  BIDTEAM@EXAMPLE.COM  "),
        ("Beneficiary Name", "Example Authority"),
        ("Payment Mode", "NEFT"),
        ("Relevant RFP Pages", "12-14"),
        ("Amount", "1,50,000"),
        ("Account Holder Name", "Example Authority"),
        ("Account Number", "001234567890"),
        ("Branch Name", "Main Branch"),
        ("IFSC Code", "abcd 0123456"),
        ("Branch Code", "00042"),
        ("MICR Code", "000123456"),
    ]
    for number, (label, value) in enumerate(rows, start=1):
        sheet.append([number, label, value])
    header_sheet = workbook.create_sheet("Header layout")
    header_sheet.append([label for label, _ in rows])
    header_sheet.append([value for _, value in rows])
    output = BytesIO()
    workbook.save(output)

    response = client.post(
        "/requests/parse-checklist",
        data={"request_type": "TENDER_FEE"},
        files={"file": ("checklist.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )

    assert response.status_code == 200
    parsed = response.json()
    assert parsed["status"] == "OK"
    assert parsed["missing"] == []
    assert len(parsed["fields"]) == 16
    assert parsed["fields"]["account_number"] == "001234567890"
    assert parsed["fields"]["ifsc"] == "ABCD0123456"
    assert parsed["fields"]["amount"] == 150000
    assert parsed["fields"]["mobile"] == "9876543210"
    assert parsed["fields"]["email"] == "bidteam@example.com"


def test_parse_checklist_rejects_non_xlsx(authenticated_client):
    client, headers = authenticated_client
    response = client.post(
        "/requests/parse-checklist",
        data={"request_type": "TENDER_FEE"},
        files={"file": ("checklist.txt", b"not an Excel workbook", "text/plain")},
        headers=headers,
    )

    assert response.status_code == 422
    assert "valid .xlsx" in response.json()["message"]
