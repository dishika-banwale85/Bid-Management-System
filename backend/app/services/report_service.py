from io import BytesIO
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from app.models import Bid,ComplianceRequest,RequestStep
from app.services.access_service import get_active_bid

def bid_summary_pdf(db,bid_id,admin=False,visible_request_ids=None):
    bid=get_active_bid(db,bid_id)
    if not bid:return None
    buf=BytesIO();pdf=canvas.Canvas(buf,pagesize=letter);y=750
    def line(text):
        nonlocal y
        if y<50:pdf.showPage();y=750
        pdf.drawString(45,y,str(text)[:110]);y-=18
    line(f"BidEase · Bid #{bid.id} Summary");line(f"Client: {bid.client_name} | Department: {bid.department}");line(f"RFP: {bid.rfp_reference} | Opening: {bid.tender_opening_date} | Deadline: {bid.submission_deadline}");line("")
    visible = set(visible_request_ids) if visible_request_ids is not None else None
    for req in sorted(bid.requests,key=lambda r:r.id):
        if visible is not None and req.id not in visible:
            continue
        line(f"Request #{req.id} · {req.type} · {req.status.value}")
        fd=req.form_data or {};amount=fd.get("amount",fd.get("bg_amount"))
        if amount is not None:line(f"Amount: {amount}")
        if "account_number" in fd:line("Account: "+(str(fd["account_number"]) if admin else "•"*max(0,len(str(fd["account_number"]))-4)+str(fd["account_number"])[-4:]))
        for st in sorted(req.steps,key=lambda s:(s.attempt,s.workflow_step.step_order)):
            if st.acted_at:line(f"Approval history: {st.workflow_step.name} · {st.actor.full_name if st.actor else 'System'} · {st.status.value} · {st.acted_at:%Y-%m-%d}")
    pdf.save();buf.seek(0);return buf

def requests_xlsx(rows,admin=False):
    wb=Workbook();ws=wb.active;ws.title="Requests";headers=["Request ID","Bid ID","Client","Request Type","Status","Created","Amount","Account Number"]
    ws.append(headers)
    for h in ws[1]:h.font=Font(bold=True)
    for r in rows:
        d=r.form_data or {};acc=d.get("account_number","");acc=acc if admin else ("•"*max(0,len(str(acc))-4)+str(acc)[-4:] if acc else "")
        ws.append([r.id,r.bid_id,r.bid.client_name if r.bid else "",r.type,r.status.value,r.created_at.replace(tzinfo=None),d.get("amount",d.get("bg_amount")),acc])
    for col in ws.columns:
        letter=col[0].column_letter;ws.column_dimensions[letter].width=min(48,max(12,max((len(str(c.value or "")) for c in col),default=8)+2))
    for cell in ws["F"][1:]:cell.number_format="yyyy-mm-dd hh:mm"
    for cell in ws["G"][1:]:cell.number_format="#,##0.00"
    buf=BytesIO();wb.save(buf);buf.seek(0);return buf

def refunds_xlsx(rows,admin=False):
    wb=Workbook();ws=wb.active;ws.title="Refund Tracker";ws.append(["Request ID","Bid ID","Client","Amount","Expected Refund Date","Status","Days Overdue"])
    for h in ws[1]:h.font=Font(bold=True)
    today=date.today()
    for r in rows:
        due=(r.form_data or {}).get("expected_refund_date");due=date.fromisoformat(str(due)[:10]) if due else None
        ws.append([r.id,r.bid_id,r.bid.client_name if r.bid else "",(r.form_data or {}).get("amount"),(due.isoformat() if due else ""),"RECEIVED" if r.refund_received_at else "PENDING",max(0,(today-due).days) if due and not r.refund_received_at else 0])
    for h in ws[1]:h.font=Font(bold=True)
    for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(38,max(12,max((len(str(c.value or "")) for c in col),default=8)+2))
    buf=BytesIO();wb.save(buf);buf.seek(0);return buf
