"""Buyer-assistant tools (SRS §6.1): list_requests, get_request_detail, compare_responses, draft_award."""
import os
import tempfile
from datetime import date, timedelta

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("EMAIL_ENABLED", "false")
os.environ.setdefault("DEADLINE_CHECK_SECONDS", "0")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ranking import rank_quotes


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, email, role):
    r = client.post("/api/auth/register", json={"name": email.split("@")[0], "email": email, "password": "longenough1", "role": role})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest.fixture(scope="module")
def quoted(client):
    """A request needed in 10 days with three responses: on time (12.00), late but cheapest (11.50), on time (13.00)."""
    buyer = _register(client, "assist-buyer@x.com", "buyer")
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Pump", "item_code": "ITEM003", "quantity": 10, "needed_by": _day(10), "erp": "sap", "open_to_all": True},
    ).json()
    for email, price, lead in (("on-time@x.com", 12.0, 3), ("late@x.com", 11.5, 20), ("pricier@x.com", 13.0, 2)):
        sup = _register(client, email, "supplier")
        r = client.put(f"/api/requirements/{req['id']}/quote", headers=sup, json={"unit_price": price, "lead_time_days": lead})
        assert r.status_code in (200, 201), r.text
    return buyer, req


def test_ranking_puts_on_time_suppliers_first():
    req = {"needed_by": "2026-01-10", "quantity": 2}
    quotes = [
        {"id": 1, "supplier_id": 1, "supplier_name": "Late", "unit_price": 1.0, "lead_time_days": 30, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": 2, "supplier_id": 2, "supplier_name": "Dear", "unit_price": 5.0, "lead_time_days": 1, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": 3, "supplier_id": 3, "supplier_name": "Cheap", "unit_price": 4.0, "lead_time_days": 5, "created_at": "2026-01-01T00:00:00+00:00"},
    ]
    ranked = rank_quotes(req, quotes)
    assert [r["supplier_name"] for r in ranked] == ["Cheap", "Dear", "Late"]
    assert [r["rank"] for r in ranked] == [1, 2, 3]
    assert ranked[0]["total_price"] == 8.0 and ranked[0]["promised_date"] == "2026-01-06"
    assert ranked[2]["meets_need_by"] is False


def test_compare_responses_ranks_in_code(client, quoted):
    buyer, req = quoted
    r = client.post("/api/mcp/compare_responses", headers=buyer, json={"req_number": req["req_number"]})
    assert r.status_code == 200, r.text
    ranking = r.json()["ranking"]
    assert [x["unit_price"] for x in ranking] == [12.0, 13.0, 11.5]
    assert [x["meets_need_by"] for x in ranking] == [True, True, False]
    assert ranking[0]["total_price"] == 120.0


def test_draft_award_saves_nothing_until_confirmed(client, quoted):
    buyer, req = quoted
    draft = client.post("/api/mcp/draft_award", headers=buyer, json={"req_number": req["req_number"].lower()}).json()
    assert draft["saved"] is False
    assert draft["proposed"]["unit_price"] == 12.0
    assert draft["erp_call"] == {
        "erp": "sap", "operation": "Create purchase order", "supplier_name": draft["proposed"]["supplier_name"],
        "item_code": "ITEM003", "quantity": 10, "unit_price": 12.0, "total_price": 120.0,
    }
    after = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()
    assert after["po_number"] is None and after["stage"] == "Quoted"

    # the buyer confirms in the app: the normal award endpoint creates the PO
    confirm = draft["confirm"]
    assert confirm["path"] == f"/api/requirements/{req['id']}/award"
    awarded = client.post(confirm["path"], headers=buyer, json=confirm["body"]).json()
    assert awarded["po_number"] and awarded["stage"] == "Awarded"
    assert client.post("/api/mcp/draft_award", headers=buyer, json={"req_number": req["req_number"]}).status_code == 400


def test_draft_award_needs_responses(client):
    buyer = _register(client, "assist-empty@x.com", "buyer")
    req = client.post("/api/requirements", headers=buyer, json={"title": "Nothing yet", "quantity": 1}).json()
    r = client.post("/api/mcp/draft_award", headers=buyer, json={"req_number": req["req_number"]})
    assert r.status_code == 400 and "no responses" in r.json()["detail"]


def test_list_requests_and_detail_are_scoped(client, quoted):
    buyer, req = quoted
    other = _register(client, "assist-other@x.com", "buyer")
    mine = client.post("/api/mcp/list_requests", headers=buyer, json={}).json()
    assert req["req_number"] in [x["req_number"] for x in mine]
    assert client.post("/api/mcp/list_requests", headers=other, json={}).json() == []
    assert client.post("/api/mcp/list_requests", headers=buyer, json={"status": "cancelled"}).json() == []

    detail = client.post("/api/mcp/get_request_detail", headers=buyer, json={"req_number": req["req_number"]}).json()
    assert len(detail["responses"]) == 3 and detail["po_number"]
    assert {"invitations", "threads", "history", "shipments"} <= detail.keys()
    assert client.post("/api/mcp/get_request_detail", headers=other, json={"req_number": req["req_number"]}).status_code == 404
    assert client.post("/api/mcp/get_request_detail", headers=buyer, json={"req_number": "REQ9999"}).status_code == 404


def test_tools_are_registered_on_the_mcp_server(client):
    names = {t["name"] for t in client.get("/api/mcp/tools").json()}
    assert {"list_requests", "get_request_detail", "compare_responses", "draft_award"} <= names
