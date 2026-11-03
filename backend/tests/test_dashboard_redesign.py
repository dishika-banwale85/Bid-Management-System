from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import create_token
from app.db import get_db
from app.main import app
from app.models import Bid, ComplianceRequest, RequestStatus


def _client(db):
    session = db["db"]

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _headers(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def test_dashboard_counts_drafts_but_drafts_route_keeps_them(db):
    session = db["db"]
    draft = ComplianceRequest(
        bid_id=db["bid"].id,
        type="TENDER_FEE",
        status=RequestStatus.DRAFT,
        created_by=db["users"]["BID_TEAM"].id,
        form_data={"client_name": "Private draft"},
    )
    session.add(draft)
    session.commit()
    client = _client(db)
    try:
        headers = _headers(db["users"]["BID_TEAM"])
        dashboard = client.get("/dashboard", headers=headers)
        assert dashboard.status_code == 200
        payload = dashboard.json()
        assert payload["kpis"]["requests"]["value"] == 1
        assert payload["requests"] == 1
        assert any(row["request_type"] == "TENDER_FEE" and row["count"] == 1 for row in payload["requests_by_type"])
        drafts = client.get("/requests?mine=true&status=DRAFT", headers=headers)
        assert drafts.status_code == 200
        assert any(row["id"] == draft.id for row in drafts.json()["items"])
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)


def test_dashboard_kpi_matches_bids_page_filters_and_role_visibility(db):
    session = db["db"]
    other = Bid(
        client_name="Other Client",
        department="Operations",
        rfp_reference="OTHER-1",
        tender_opening_date=date.today() + timedelta(days=30),
        submission_deadline=date.today() + timedelta(days=35),
        created_by=db["users"]["APPROVER"].id,
    )
    session.add(other)
    session.commit()
    client = _client(db)
    try:
        filters = {"date_from": "2020-01-01", "date_to": "2035-12-31", "tab": "all"}
        team_headers = _headers(db["users"]["BID_TEAM"])
        approver_headers = _headers(db["users"]["APPROVER"])
        dashboard = client.get("/dashboard", params=filters, headers=team_headers).json()
        bids = client.get("/bids", params=filters, headers=team_headers).json()
        assert dashboard["kpis"]["bids"]["value"] == len(bids)
        assert len(bids) == 1
        approver_dashboard = client.get("/dashboard", params=filters, headers=approver_headers).json()
        assert approver_dashboard["kpis"]["bids"]["value"] == 2
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)


def test_dashboard_query_count_is_bounded_as_bids_grow(db):
    session = db["db"]
    client = _client(db)
    headers = _headers(db["users"]["APPROVER"])
    engine = session.get_bind()

    def count_queries():
        counter = {"selects": 0}

        def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                counter["selects"] += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            response = client.get("/dashboard", params={"date_from": "2020-01-01", "date_to": "2035-12-31"}, headers=headers)
            assert response.status_code == 200
            return counter["selects"]
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)

    try:
        count_before = count_queries()
        for index in range(8):
            session.add(Bid(
                client_name=f"Bulk Client {index}", department="Ops", rfp_reference=f"BULK-{index}",
                tender_opening_date=date.today() + timedelta(days=30),
                submission_deadline=date.today() + timedelta(days=35),
                created_by=db["users"]["BID_TEAM"].id,
            ))
        session.commit()
        count_after = count_queries()
        assert count_after == count_before
        assert count_after <= 10
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
