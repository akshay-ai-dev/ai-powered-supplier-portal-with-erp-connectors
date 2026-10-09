import os
import tempfile

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["EMAIL_ENABLED"] = "false"
os.environ["DEADLINE_CHECK_SECONDS"] = "0"  # tests call process_deadlines directly

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password="Password123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


OK_CHECKS = {"packaging": True, "specification": True, "condition": True, "documentation": True}


def ship(client, po_id, sup, tracking="TRK1", factor=1):
    po = client.get(f"/api/purchase-orders/{po_id}", headers=sup).json()
    items = [
        {"item_code": i["item_code"], "quantity": i["quantity"] // factor or 1} for i in po["items"]
    ]
    r = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"carrier": "DHL", "tracking_no": tracking, "items": items},
    )
    assert r.status_code == 201, r.text
    return r.json()


def arrive(client, sh, insp):
    lines = [
        {"item_code": i["item_code"], "quantity_received": i["quantity_shipped"]}
        for i in sh["items"]
    ]
    r = client.post(f"/api/shipments/{sh['id']}/arrival", headers=insp, json={"lines": lines})
    assert r.status_code == 200, r.text
    return r.json()


def deliver(client, po_id, sup, insp):
    """Full happy path: ship, arrive, approve."""
    sh = arrive(client, ship(client, po_id, sup), insp)
    r = client.post(
        f"/api/shipments/{sh['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_and_validation(client):
    r = client.post(
        "/api/auth/register",
        json={"name": "New Buyer", "email": "nb@x.com", "password": "longenough1", "role": "buyer"},
    )
    assert r.status_code == 201 and r.json()["user"]["role"] == "buyer"
    assert (
        client.post(
            "/api/auth/register",
            json={"name": "Dup", "email": "nb@x.com", "password": "longenough1", "role": "buyer"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/register",
            json={"name": "S", "email": "bad", "password": "short", "role": "buyer"},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/auth/login", json={"email": "nb@x.com", "password": "wrong"}).status_code
        == 401
    )


def test_supplier_registration_creates_profile(client):
    r = client.post(
        "/api/auth/register",
        json={"name": "Acme", "email": "acme@x.com", "password": "longenough1", "role": "supplier"},
    )
    assert r.json()["user"]["supplier_id"]


def test_supplier_cannot_change_profile_email_or_phone(client):
    supplier = login(client, "supplier@demo.com")
    supplier_id = client.get("/api/auth/me", headers=supplier).json()["supplier_id"]
    profile = client.get(f"/api/suppliers/{supplier_id}", headers=supplier).json()

    changed = client.put(
        f"/api/suppliers/{supplier_id}",
        headers=supplier,
        json={
            "supplier_name": profile["supplier_name"],
            "email": "changed@example.com",
            "phone": "+1 555 010 9999",
            "address": profile["address"],
        },
    )
    assert changed.status_code == 400

    unchanged = client.get(f"/api/suppliers/{supplier_id}", headers=supplier).json()
    assert unchanged["email"] == profile["email"]
    assert unchanged["phone"] == profile["phone"]


def test_shipment_tracking_number_is_uppercased_and_rejects_special_characters():
    from pydantic import ValidationError

    from app.schemas import ShipmentCreate

    shipment = ShipmentCreate(
        carrier="DHL",
        tracking_no=" ab-12_cd ",
        items=[{"item_code": "ITEM001", "quantity": 1}],
    )
    assert shipment.tracking_no == "AB-12_CD"

    with pytest.raises(ValidationError, match="tracking_no"):
        ShipmentCreate(
            carrier="DHL",
            tracking_no="AB.12",
            items=[{"item_code": "ITEM001", "quantity": 1}],
        )


def test_rbac(client):
    assert client.get("/api/suppliers").status_code == 401
    sup = login(client, "supplier@demo.com")
    assert client.get("/api/suppliers", headers=sup).status_code == 403
    assert (
        client.get("/api/inventory", headers=sup).status_code == 200
    )  # supplier Dashboard shows stock levels
    insp = login(client, "inspector@demo.com")
    assert (
        client.post(
            "/api/inventory", headers=insp, json={"item_code": "X1", "description": "x"}
        ).status_code
        == 403
    )


def test_po_lifecycle(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    suppliers = client.get("/api/suppliers?q=ABC", headers=buyer).json()
    abc = suppliers[0]["id"]

    po = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc,
            "items": [{"item_code": "ITEM005", "quantity": 4, "unit_price": 100}],
        },
    ).json()
    assert (
        po["status"] == "Draft" and po["total_amount"] == 400 and po["po_number"].startswith("PO")
    )
    # supplier cannot see drafts
    assert client.get(f"/api/purchase-orders/{po['id']}", headers=sup).status_code == 404

    # invalid transition
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Approved"}
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Pending"}
        ).json()["status"]
        == "Pending"
    )
    # supplier can't approve
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=sup, json={"status": "Approved"}
        ).status_code
        == 403
    )

    approved = client.put(
        f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Approved"}
    ).json()
    assert approved["erp_reference"]

    before = client.get("/api/inventory/ITEM005", headers=buyer).json()["stock_quantity"]
    # closing before delivery is rejected
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Closed"}
        ).status_code
        == 400
    )
    insp = login(client, "inspector@demo.com")
    # suppliers can no longer mark delivery themselves: shipment + inspection is the only route
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=sup, json={"delivery_status": "Delivered"}
        ).status_code
        == 400
    )
    deliver(client, po["id"], sup, insp)
    assert (
        client.get(f"/api/purchase-orders/{po['id']}", headers=buyer).json()["delivery_status"]
        == "Delivered"
    )
    assert (
        client.get("/api/inventory/ITEM005", headers=buyer).json()["stock_quantity"] == before + 4
    )
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Closed"}
        ).json()["status"]
        == "Closed"
    )

    dash = client.get("/api/dashboard", headers=sup).json()
    assert dash["role"] == "supplier" and "pending_deliveries" in dash
    assert client.get("/api/dashboard", headers=buyer).json()["supplier_count"] >= 4


def test_purchase_order_rejects_unit_price_below_one(client):
    buyer = login(client, "buyer@demo.com")
    supplier_id = client.get("/api/suppliers", headers=buyer).json()[0]["id"]

    for unit_price in (0, 0.99):
        response = client.post(
            "/api/purchase-orders",
            headers=buyer,
            json={
                "supplier_id": supplier_id,
                "items": [{"item_code": "ITEM005", "quantity": 1, "unit_price": unit_price}],
            },
        )
        assert response.status_code == 422

    accepted = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": supplier_id,
            "items": [{"item_code": "ITEM005", "quantity": 1, "unit_price": 1}],
        },
    )
    assert accepted.status_code == 201


def test_mock_erp(client):
    assert client.get("/mock/sap/materials").json()[0]["MATNR"] == "ITEM001"
    assert client.get("/mock/infor/items").json()[0]["item"] == "ITEM001"
    assert (
        client.post("/mock/sap/purchase-orders", json={"LIFNR": "100001", "ITEMS": []}).status_code
        == 201
    )
    assert (
        client.post("/mock/infor/orders", json={"bpid": "BP-001", "lines": []}).status_code == 201
    )


def test_openapi_tools(client):
    buyer = login(client, "buyer@demo.com")
    assert {t["name"] for t in client.get("/api/mcp/tools").json()} == {
        "get_inventory",
        "search_suppliers",
        "create_purchase_order",
        "get_purchase_order",
        "list_purchase_orders",
        "list_requests",
        "get_request_detail",
        "compare_responses",
        "draft_award",
        "get_erp_documents",
        "check_shipments",
        "draft_request",
        "draft_po_approval",
        "draft_quote",
        "draft_arrival",
        "draft_delivery_approval",
    }
    assert (
        client.post("/api/mcp/get_inventory", headers=buyer, json={"item_code": "ITEM001"}).json()[
            "stock"
        ]
        == 1200
    )
    assert "/api/mcp/get_inventory" in client.get("/openapi.json").json()["paths"]


def test_mcp_endpoint_requires_auth(client):
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_requirement_to_delivery_flow(client):
    buyer, abc = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    other = client.post(
        "/api/auth/register",
        json={
            "name": "Other Co",
            "email": "other@x.com",
            "password": "longenough1",
            "role": "supplier",
        },
    ).json()
    oth = {"Authorization": f"Bearer {other['access_token']}"}

    assert (
        client.post(
            "/api/requirements", headers=abc, json={"title": "x", "quantity": 1}
        ).status_code
        == 403
    )
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Servo motors", "item_code": "ITEM003", "quantity": 10, "target_price": 500},
    ).json()
    assert req["stage"] == "Open" and req["req_number"].startswith("REQ")

    # suppliers see open requirements, and quotes are private between them
    assert any(r["id"] == req["id"] for r in client.get("/api/requirements", headers=abc).json())
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=buyer,
            json={"unit_price": 1, "lead_time_days": 1},
        ).status_code
        == 403
    )
    q1 = client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=abc,
        json={"unit_price": 480, "lead_time_days": 7},
    ).json()
    assert q1["my_quote"]["unit_price"] == 480 and "quotes" not in q1
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=oth,
        json={"unit_price": 450, "lead_time_days": 14},
    )

    detail = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()
    assert detail["stage"] == "Quoted" and len(detail["quotes"]) == 2
    abc_quote = next(q for q in detail["quotes"] if q["unit_price"] == 480)

    awarded = client.post(
        f"/api/requirements/{req['id']}/award", headers=buyer, json={"quote_id": abc_quote["id"]}
    ).json()
    assert awarded["stage"] == "Awarded" and awarded["po_number"]
    # losing supplier is told it lost and cannot see the PO
    lost = client.get(f"/api/requirements/{req['id']}", headers=oth).json()
    assert lost["my_quote"]["status"] == "Rejected" and lost["po_id"] is None
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=oth,
            json={"unit_price": 1, "lead_time_days": 1},
        ).status_code
        == 400
    )

    # winner ships via the PO flow; requirement stage follows
    po_id = awarded["po_id"]
    client.put(f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Approved"})
    insp = login(client, "inspector@demo.com")
    sh = ship(client, po_id, abc)
    assert client.get(f"/api/requirements/{req['id']}", headers=abc).json()["stage"] == "In Transit"
    sh = arrive(client, sh, insp)
    client.post(
        f"/api/shipments/{sh['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS},
    )
    assert (
        client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["stage"] == "Delivered"
    )


def test_cancel_requirement(client):
    buyer = login(client, "buyer@demo.com")
    req = client.post(
        "/api/requirements", headers=buyer, json={"title": "Temp", "quantity": 2}
    ).json()
    assert (
        client.post(f"/api/requirements/{req['id']}/cancel", headers=buyer).json()["stage"]
        == "Cancelled"
    )
    assert client.post(f"/api/requirements/{req['id']}/cancel", headers=buyer).status_code == 400


def test_buyers_are_isolated_from_each_other(client):
    b1 = login(client, "buyer@demo.com")
    r = client.post(
        "/api/auth/register",
        json={"name": "Buyer Two", "email": "b2@x.com", "password": "longenough1", "role": "buyer"},
    ).json()
    b2 = {"Authorization": f"Bearer {r['access_token']}"}

    req = client.post(
        "/api/requirements", headers=b1, json={"title": "Private need", "quantity": 5}
    ).json()
    po = client.post(
        "/api/purchase-orders",
        headers=b1,
        json={
            "supplier_id": 1,
            "items": [{"item_code": "ITEM001", "quantity": 1, "unit_price": 1}],
        },
    ).json()

    # other buyer: not in lists, not fetchable, cannot act
    assert all(x["id"] != req["id"] for x in client.get("/api/requirements", headers=b2).json())
    assert client.get(f"/api/requirements/{req['id']}", headers=b2).status_code == 404
    assert client.post(f"/api/requirements/{req['id']}/cancel", headers=b2).status_code == 404
    assert (
        client.post(
            f"/api/requirements/{req['id']}/award", headers=b2, json={"quote_id": 1}
        ).status_code
        == 404
    )
    assert client.get("/api/purchase-orders", headers=b2).json() == []
    assert client.get(f"/api/purchase-orders/{po['id']}", headers=b2).status_code == 404
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=b2, json={"status": "Pending"}
        ).status_code
        == 404
    )
    d2 = client.get("/api/dashboard", headers=b2).json()
    assert d2["open_orders"] == 0 and d2["orders_by_status"] == {}

    # owner and every supplier still see the open requirement
    assert client.get(f"/api/requirements/{req['id']}", headers=b1).status_code == 200
    sup = login(client, "supplier@demo.com")
    supplier_requirements = client.get("/api/requirements", headers=sup).json()
    visible_req = next(x for x in supplier_requirements if x["id"] == req["id"])
    from app.db import connect

    conn = connect()
    try:
        buyer_name = conn.execute(
            "SELECT u.name FROM users u JOIN requirements r ON r.created_by = u.id WHERE r.id = ?",
            (req["id"],),
        ).fetchone()["name"]
    finally:
        conn.close()
    assert visible_req["buyer_name"] == buyer_name
    supplier_id = client.get("/api/auth/me", headers=sup).json()["supplier_id"]
    supplier_name = client.get(f"/api/suppliers/{supplier_id}", headers=b1).json()["supplier_name"]
    assert visible_req["supplier_name"] == supplier_name
    assert (
        client.get(f"/api/requirements/{req['id']}", headers=sup).json()["supplier_name"]
        == supplier_name
    )


def test_emails_only_show_own_mail(client, monkeypatch):
    from app.services import mailbox

    def m(id_, to, subject):
        return {
            "ID": id_,
            "Subject": subject,
            "From": {"Address": "erp@x"},
            "To": [{"Address": to}],
            "Snippet": "",
            "Created": "2026-01-01T00:00:00Z",
            "Text": "body",
            "Date": "2026-01-01T00:00:00Z",
        }

    box = [
        m("1", "buyer@demo.com", "For buyer"),
        m("2", "sales@abc-industrial.example", "For ABC"),
        m("3", "b2@x.com", "For buyer two"),
    ]

    def fake(path, params=None):
        if path.endswith("/search"):
            return {"messages": box}  # a leaky Mailpit search: the app must still filter
        return next(x for x in box if x["ID"] == path.rsplit("/", 1)[1])

    monkeypatch.setattr(mailbox, "_mailpit", fake)
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    assert [e["subject"] for e in client.get("/api/emails", headers=buyer).json()] == ["For buyer"]
    # supplier receives mail sent to the company address as well
    assert [e["subject"] for e in client.get("/api/emails", headers=sup).json()] == ["For ABC"]
    assert client.get("/api/emails/1", headers=buyer).status_code == 200
    assert client.get("/api/emails/2", headers=buyer).status_code == 404
    assert client.get("/api/emails/3", headers=sup).status_code == 404
    assert client.get("/api/emails").status_code == 401


def test_admin_users_sync_and_reset(client):
    admin, buyer = login(client, "admin@demo.com"), login(client, "buyer@demo.com")

    # admin-only surface
    assert client.get("/api/admin/users", headers=buyer).status_code == 403
    assert (
        client.post(
            "/api/auth/register",
            json={"name": "Sneaky", "email": "s@x.com", "password": "longenough1", "role": "admin"},
        ).status_code
        == 422
    )
    users = client.get("/api/admin/users", headers=admin).json()
    assert {"admin", "buyer", "supplier"} <= {u["role"] for u in users}
    assert all(u["email"] != "mcp-service@erp.local" for u in users)
    assert client.get("/api/dashboard", headers=admin).json()["role"] == "admin"

    # create, disable, re-enable
    new = client.post(
        "/api/admin/users",
        headers=admin,
        json={"name": "Ops", "email": "ops@x.com", "password": "longenough1", "role": "buyer"},
    ).json()
    login(client, "ops@x.com", "longenough1")
    assert (
        client.patch(f"/api/admin/users/{new['id']}", headers=admin, json={"active": False}).json()[
            "active"
        ]
        == 0
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "ops@x.com", "password": "longenough1"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/admin/users/{new['id']}", headers=admin, json={"active": True}
        ).status_code
        == 200
    )
    me = next(u for u in users if u["email"] == "admin@demo.com")
    assert (
        client.patch(
            f"/api/admin/users/{me['id']}", headers=admin, json={"active": False}
        ).status_code
        == 400
    )

    # a disabled user's existing token stops working
    t = login(client, "ops@x.com", "longenough1")
    client.patch(f"/api/admin/users/{new['id']}", headers=admin, json={"active": False})
    assert client.get("/api/auth/me", headers=t).status_code == 401

    # ERP sync by buyer, both ERPs
    assert client.post("/api/erp/sync/sap", headers=buyer).json()["items_updated"] >= 8
    assert client.post("/api/erp/sync/infor", headers=buyer).status_code == 200
    assert client.post("/api/erp/sync/nope", headers=buyer).status_code == 404

    # reset needs explicit confirmation, keeps the acting admin logged in, restores seed state
    assert (
        client.post("/api/admin/reset", headers=admin, json={"confirm": "yes"}).status_code == 400
    )
    assert client.get("/api/purchase-orders", headers=buyer).json()  # data exists before reset
    assert (
        client.post("/api/admin/reset", headers=admin, json={"confirm": "RESET"}).status_code == 200
    )
    assert client.get("/api/auth/me", headers=admin).status_code == 200
    stats = client.get("/api/admin/stats", headers=admin).json()
    assert sum(stats["orders_by_status"].values()) == 3 and not any(
        u["email"] == "ops@x.com" for u in client.get("/api/admin/users", headers=admin).json()
    )


def test_agent_actions_are_flagged(client):
    buyer = login(client, "buyer@demo.com")
    web_po = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": 1,
            "items": [{"item_code": "ITEM001", "quantity": 1, "unit_price": 1}],
        },
    ).json()
    agent_po = client.post(
        "/api/mcp/create_purchase_order",
        headers=buyer,
        json={"supplier_id": 1, "item_code": "ITEM001", "quantity": 2},
    ).json()
    assert web_po["created_via"] == "web" and agent_po["created_via"] == "agent-api"

    # audit history records the channel per action; a later human action on the same PO shows as web
    client.put(f"/api/purchase-orders/{agent_po['id']}", headers=buyer, json={"status": "Pending"})
    hist = client.get(f"/api/purchase-orders/{agent_po['id']}", headers=buyer).json()["history"]
    assert [(h["action"], h["channel"]) for h in hist] == [
        ("status", "web"),
        ("create", "agent-api"),
    ]

    # the channel never leaks into later web requests
    assert (
        client.get(f"/api/purchase-orders/{web_po['id']}", headers=buyer).json()["history"][0][
            "channel"
        ]
        == "web"
    )
    # suppliers get no audit history
    sup = login(client, "supplier@demo.com")
    assert "history" not in client.get(f"/api/purchase-orders/{agent_po['id']}", headers=sup).json()


def test_buyers_can_add_and_edit_inventory(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    body = {
        "item_code": "new-item_1",
        "description": "Test widget",
        "stock_quantity": 25,
        "warehouse": "WH-9",
    }
    assert client.post("/api/inventory", json=body).status_code == 401
    created = client.post("/api/inventory", headers=buyer, json=body)
    assert created.status_code == 201
    item = created.json()
    assert (
        item["item_code"] == "NEW-ITEM_1"
        and item["source"] == "manual"
        and item["stock_quantity"] == 25
    )
    assert client.post("/api/inventory", headers=buyer, json=body).status_code == 409  # duplicate
    assert (
        client.post(
            "/api/inventory", headers=buyer, json={**body, "item_code": "bad code!"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/inventory", headers=buyer, json={**body, "item_code": "X2", "stock_quantity": -1}
        ).status_code
        == 422
    )

    upd = client.put(
        "/api/inventory/new-item_1", headers=buyer, json={"stock_quantity": 40, "warehouse": "WH-1"}
    ).json()
    assert (
        upd["stock_quantity"] == 40
        and upd["warehouse"] == "WH-1"
        and upd["description"] == "Test widget"
    )
    assert (
        client.put("/api/inventory/NOPE", headers=buyer, json={"stock_quantity": 1}).status_code
        == 404
    )
    assert (
        client.put("/api/inventory/NEW-ITEM_1", headers=sup, json={"stock_quantity": 1}).status_code
        == 404
    )  # not in the supplier's own inventory
    # usable straight away in a PO
    assert (
        client.post(
            "/api/purchase-orders",
            headers=buyer,
            json={
                "supplier_id": 1,
                "items": [{"item_code": "NEW-ITEM_1", "quantity": 1, "unit_price": 1}],
            },
        ).status_code
        == 201
    )


def test_inventory_delete_rules(client):
    b1, admin, sup = (
        login(client, "buyer@demo.com"),
        login(client, "admin@demo.com"),
        login(client, "supplier@demo.com"),
    )
    r = client.post(
        "/api/auth/register",
        json={
            "name": "Buyer Del",
            "email": "bdel@x.com",
            "password": "longenough1",
            "role": "buyer",
        },
    ).json()
    b2 = {"Authorization": f"Bearer {r['access_token']}"}

    def mk(h, code):
        return client.post(
            "/api/inventory",
            headers=h,
            json={"item_code": code, "description": "d", "stock_quantity": 1},
        ).json()

    mk(b1, "DEL-A")
    mk(b1, "DEL-USED")
    mk(b2, "DEL-B")

    rows = {i["item_code"]: i for i in client.get("/api/inventory", headers=b1).json()}
    assert (
<<<<<<< HEAD
        rows["DEL-A"]["can_delete"]
        and not rows["DEL-B"]["can_delete"]
        and not rows["ITEM001"]["can_delete"]
    )
    assert client.get("/api/inventory", headers=admin).status_code == 403
=======
        rows["DEL-A"]["can_delete"] and "DEL-B" not in rows and rows["ITEM001"]["can_delete"]
    )  # the ERP items belong to the demo buyer
    assert client.get("/api/inventory", headers=admin).json()[0][
        "can_delete"
    ]  # admin may delete any
>>>>>>> main

    # someone else's item is not in your inventory; an owned item still in use cannot go
    assert client.delete("/api/inventory/DEL-B", headers=b1).status_code == 404
    assert client.delete("/api/inventory/DEL-A", headers=sup).status_code == 404
    assert (
        client.delete("/api/inventory/ITEM001", headers=b1).status_code == 409
    )  # seeded POs use it
    assert client.delete("/api/inventory/NOPE", headers=b1).status_code == 404

    # in use by a PO -> blocked even for the creator; also blocked when a requirement references it
    client.post(
        "/api/purchase-orders",
        headers=b1,
        json={
            "supplier_id": 1,
            "items": [{"item_code": "DEL-USED", "quantity": 1, "unit_price": 1}],
        },
    )
    used = client.delete("/api/inventory/del-used", headers=b1)
    assert used.status_code == 409 and "1 purchase order" in used.json()["detail"]
    mk(b1, "DEL-REQ")
    client.post(
        "/api/requirements", headers=b1, json={"title": "t", "item_code": "DEL-REQ", "quantity": 1}
    )
    assert client.delete("/api/inventory/DEL-REQ", headers=b1).status_code == 409

    # creator deletes an unused item; admin cannot delete someone else's
    assert client.delete("/api/inventory/del-a", headers=b1).json() == {"deleted": "DEL-A"}
    assert client.get("/api/inventory/DEL-A", headers=b1).status_code == 404
    assert client.delete("/api/inventory/DEL-B", headers=admin).status_code == 403
    assert client.get("/api/inventory/DEL-B", headers=b2).status_code == 200


def test_buyers_and_suppliers_have_separate_inventories(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")

    def codes(h):
        return {i["item_code"]: i for i in client.get("/api/inventory", headers=h).json()}

    assert (
        "ITEM001" in codes(buyer) and codes(sup) == {}
    )  # a supplier starts with an empty inventory
    # the same item code may exist once per owner
    body = {"item_code": "ITEM001", "description": "Our bolts", "stock_quantity": 7}
    assert client.post("/api/inventory", headers=sup, json=body).status_code == 201
    assert client.post("/api/inventory", headers=sup, json=body).status_code == 409
    mine = codes(sup)
    assert (
        list(mine) == ["ITEM001"] and mine["ITEM001"]["can_edit"] and mine["ITEM001"]["can_delete"]
    )
    assert codes(buyer)["ITEM001"]["description"] != "Our bolts"  # the buyer's row is untouched

    upd = client.put("/api/inventory/ITEM001", headers=sup, json={"stock_quantity": 3}).json()
    assert upd["stock_quantity"] == 3 and codes(buyer)["ITEM001"]["stock_quantity"] != 3
    assert client.delete("/api/inventory/ITEM001", headers=sup).status_code == 200
    assert "ITEM001" in codes(buyer)


def test_inventory_edit_is_restricted_to_owner(client):
    b1, admin = login(client, "buyer@demo.com"), login(client, "admin@demo.com")
    r = client.post(
        "/api/auth/register",
        json={
            "name": "Buyer Edit",
            "email": "bedit@x.com",
            "password": "longenough1",
            "role": "buyer",
        },
    ).json()
    b2 = {"Authorization": f"Bearer {r['access_token']}"}
    client.post(
        "/api/inventory",
        headers=b1,
        json={"item_code": "EDIT-1", "description": "mine", "stock_quantity": 5},
    )

    rows = {i["item_code"]: i for i in client.get("/api/inventory", headers=b2).json()}
    assert "EDIT-1" not in rows and "ITEM001" not in rows  # b2 has their own (empty) inventory
    assert {i["item_code"]: i for i in client.get("/api/inventory", headers=b1).json()}["EDIT-1"][
        "can_edit"
    ]

    assert (
        client.put("/api/inventory/EDIT-1", headers=b2, json={"stock_quantity": 99}).status_code
        == 404
    )
    assert (
        client.put("/api/inventory/ITEM001", headers=b1, json={"stock_quantity": 99}).json()[
            "stock_quantity"
        ]
        == 99
    )  # ERP-loaded items belong to the demo buyer, who may edit them
    assert (
        client.put("/api/inventory/EDIT-1", headers=b1, json={"stock_quantity": 9}).json()[
            "stock_quantity"
        ]
        == 9
    )
    assert (
        client.put("/api/inventory/EDIT-1", headers=admin, json={"stock_quantity": 10}).status_code
        == 403
    )
    assert client.get("/api/inventory/EDIT-1", headers=b1).json()["stock_quantity"] == 9


def _register_supplier(client, email):
    r = client.post(
        "/api/auth/register",
        json={
            "name": email.split("@")[0],
            "email": email,
            "password": "longenough1",
            "role": "supplier",
        },
    ).json()
    return {"Authorization": f"Bearer {r['access_token']}"}, r["user"]["supplier_id"]


def test_invitations_limit_who_sees_a_requirement(client):
    buyer, abc = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    abc_id = client.get("/api/auth/me", headers=abc).json()["supplier_id"]
    outsider, _ = _register_supplier(client, "outsider@x.com")
    invitee, invitee_id = _register_supplier(client, "invitee@x.com")

    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Invite test", "quantity": 2, "supplier_ids": [abc_id]},
    ).json()
    assert [i["supplier_id"] for i in req["invites"]] == [abc_id]

    # invited supplier sees and can quote; others get 404 everywhere and never see it listed
    assert any(r["id"] == req["id"] for r in client.get("/api/requirements", headers=abc).json())
    assert all(
        r["id"] != req["id"] for r in client.get("/api/requirements", headers=outsider).json()
    )
    assert client.get(f"/api/requirements/{req['id']}", headers=outsider).status_code == 404
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=outsider,
            json={"unit_price": 1, "lead_time_days": 1},
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=abc,
            json={"unit_price": 5, "lead_time_days": 2},
        ).status_code
        == 200
    )

    # only the owner can invite more; the new invitee then gets access
    assert (
        client.post(
            f"/api/requirements/{req['id']}/invite",
            headers=outsider,
            json={"supplier_ids": [invitee_id]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/requirements/{req['id']}/invite", headers=buyer, json={"supplier_ids": [9999]}
        ).status_code
        == 400
    )
    after = client.post(
        f"/api/requirements/{req['id']}/invite",
        headers=buyer,
        json={"supplier_ids": [invitee_id, abc_id]},
    ).json()
    assert (
        len(after["invites"]) == 2
        and next(i for i in after["invites"] if i["supplier_id"] == abc_id)["quoted"]
    )
    assert client.get(f"/api/requirements/{req['id']}", headers=invitee).status_code == 200
    # suppliers never see who else was invited
    assert "invites" not in client.get(f"/api/requirements/{req['id']}", headers=invitee).json()

    # unknown ERP rejected
    assert (
        client.post(
            "/api/requirements", headers=buyer, json={"title": "x", "quantity": 1, "erp": "oracle"}
        ).status_code
        == 422
    )


def test_award_routes_the_po_to_the_requirements_erp(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    req = client.post(
        "/api/requirements", headers=buyer, json={"title": "LN part", "quantity": 4, "erp": "infor"}
    ).json()
    assert req["erp"] == "infor"
    quote = client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=sup,
        json={"unit_price": 10, "lead_time_days": 3},
    )
    assert quote.status_code == 200
    qid = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quotes"][0]["id"]
    po_id = client.post(
        f"/api/requirements/{req['id']}/award", headers=buyer, json={"quote_id": qid}
    ).json()["po_id"]
    assert client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["erp"] == "infor"
    approved = client.put(
        f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Approved"}
    ).json()
    assert approved["erp_reference"].startswith("LN-")
    assert any(
        o["ref"] == approved["po_number"]
        for o in client.get("/mock/infor/orders").json()
        if "ref" in o
    )


def test_attachments(client):
    buyer, other_buyer_tok = (
        login(client, "buyer@demo.com"),
        client.post(
            "/api/auth/register",
            json={"name": "B3", "email": "b3@x.com", "password": "longenough1", "role": "buyer"},
        ).json()["access_token"],
    )
    other_buyer = {"Authorization": f"Bearer {other_buyer_tok}"}
    abc = login(client, "supplier@demo.com")
    abc_id = client.get("/api/auth/me", headers=abc).json()["supplier_id"]
    outsider, _ = _register_supplier(client, "outsider2@x.com")
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "With drawing", "quantity": 1, "supplier_ids": [abc_id]},
    ).json()

    def up(h, name, data, ct="application/pdf"):
        return client.post(
            f"/api/requirements/{req['id']}/attachments",
            headers=h,
            files={"file": (name, data, ct)},
        )

    ok = up(buyer, "../../drawing v2.pdf", b"%PDF-1.4 fake")
    assert (
        ok.status_code == 201
        and ok.json()["filename"] == "drawing v2.pdf"
        and ok.json()["size"] == 13
    )  # path parts stripped
    att_id = ok.json()["id"]

    # validation: type whitelist, empty, size limit, not the owner, not a buyer
    assert up(buyer, "evil.html", b"<script>", "text/html").status_code == 415
    assert up(buyer, "x.exe", b"MZ", "application/octet-stream").status_code == 415
    assert up(buyer, "empty.pdf", b"").status_code == 400
    assert up(buyer, "big.pdf", b"0" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert up(other_buyer, "steal.pdf", b"x").status_code == 404
    assert up(abc, "sup.pdf", b"x").status_code == 403

    # who may download: owner and invited supplier yes; other buyer and non-invited supplier no
    dl = client.get(f"/api/attachments/{att_id}/download", headers=abc)
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 fake"
    assert (
        dl.headers["content-type"] == "application/octet-stream"
        and dl.headers["x-content-type-options"] == "nosniff"
    )
    assert (
        dl.headers["content-disposition"].startswith("attachment;")
        and "drawing%20v2.pdf" in dl.headers["content-disposition"]
    )
    assert client.get(f"/api/attachments/{att_id}/download", headers=buyer).status_code == 200
    assert client.get(f"/api/attachments/{att_id}/download", headers=other_buyer).status_code == 404
    assert client.get(f"/api/attachments/{att_id}/download", headers=outsider).status_code == 404
    assert client.get(f"/api/attachments/{att_id}/download").status_code == 401

    # attachments are listed on the detail for the buyer and the invited supplier
    assert (
        client.get(f"/api/requirements/{req['id']}", headers=abc).json()["attachments"][0]["id"]
        == att_id
    )

    # only the owner can delete, and only while open
    assert client.delete(f"/api/attachments/{att_id}", headers=abc).status_code == 403
    assert client.delete(f"/api/attachments/{att_id}", headers=other_buyer).status_code == 404
    assert client.delete(f"/api/attachments/{att_id}", headers=buyer).status_code == 200
    assert client.get(f"/api/attachments/{att_id}/download", headers=buyer).status_code == 404
    client.post(f"/api/requirements/{req['id']}/cancel", headers=buyer)
    assert up(buyer, "late.pdf", b"x").status_code == 400


def test_open_to_all_suppliers(client):
    buyer = login(client, "buyer@demo.com")
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "For everyone", "quantity": 3, "open_to_all": True, "supplier_ids": [1]},
    ).json()
    assert req["open_to_all"] == 1 and req["invites"] == []  # supplier_ids ignored when open to all

    # every supplier sees it, including one who registers AFTER it was posted
    late, _ = _register_supplier(client, "late-joiner@x.com")
    for tok in (login(client, "supplier@demo.com"), late):
        assert any(
            r["id"] == req["id"] for r in client.get("/api/requirements", headers=tok).json()
        )
        assert (
            client.put(
                f"/api/requirements/{req['id']}/quote",
                headers=tok,
                json={"unit_price": 2, "lead_time_days": 1},
            ).status_code
            == 200
        )
    assert client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quote_count"] == 2
    assert (
        client.post(
            f"/api/requirements/{req['id']}/invite", headers=buyer, json={"supplier_ids": [1]}
        ).status_code
        == 400
    )

    # a restricted requirement can be widened later, only by its owner
    other = client.post(
        "/api/auth/register",
        json={"name": "B4", "email": "b4@x.com", "password": "longenough1", "role": "buyer"},
    ).json()["access_token"]
    restricted = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Restricted", "quantity": 1, "supplier_ids": [1]},
    ).json()
    outsider, _ = _register_supplier(client, "outsider3@x.com")
    assert client.get(f"/api/requirements/{restricted['id']}", headers=outsider).status_code == 404
    assert (
        client.post(
            f"/api/requirements/{restricted['id']}/open-to-all",
            headers={"Authorization": f"Bearer {other}"},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/requirements/{restricted['id']}/open-to-all", headers=buyer).json()[
            "open_to_all"
        ]
        == 1
    )
    assert client.get(f"/api/requirements/{restricted['id']}", headers=outsider).status_code == 200

    # closed requirements can't be widened
    client.post(f"/api/requirements/{restricted['id']}/cancel", headers=buyer)
    assert (
        client.post(f"/api/requirements/{restricted['id']}/open-to-all", headers=buyer).status_code
        == 400
    )


def test_buyer_supplier_conversation_and_decline(client):
    buyer, abc = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    abc_id = client.get("/api/auth/me", headers=abc).json()["supplier_id"]
    other, other_id = _register_supplier(client, "chatter2@x.com")
    outsider, _ = _register_supplier(client, "chat-outsider@x.com")
    b2 = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={"name": "B5", "email": "b5@x.com", "password": "longenough1", "role": "buyer"},
        ).json()["access_token"]
    }
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Chat", "quantity": 1, "supplier_ids": [abc_id, other_id]},
    ).json()
    url = f"/api/requirements/{req['id']}/messages"

    # supplier asks, buyer sees it as unread and replies; threads are private per supplier
    assert (
        client.post(
            url, headers=abc, json={"body": "  Is 6061 aluminium acceptable?  "}
        ).status_code
        == 201
    )
    listing = client.get("/api/requirements", headers=buyer).json()
    assert next(r for r in listing if r["id"] == req["id"])["unread_messages"] == 1
    detail = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()
    assert [(t["supplier_id"], t["unread"]) for t in detail["threads"]] == [(abc_id, 1)]
    thread = client.get(url, headers=buyer, params={"supplier_id": abc_id}).json()
    assert [m["body"] for m in thread["messages"]] == [
        "Is 6061 aluminium acceptable?"
    ] and not thread["messages"][0]["mine"]
    assert (
        client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["threads"][0]["unread"]
        == 0
    )  # reading clears it
    client.post(url, headers=buyer, json={"body": "Yes, 6061 is fine.", "supplier_id": abc_id})
    assert (
        next(
            r for r in client.get("/api/requirements", headers=abc).json() if r["id"] == req["id"]
        )["unread_messages"]
        == 1
    )
    mine = client.get(url, headers=abc).json()
    assert [(m["sender_role"], m["mine"]) for m in mine["messages"]] == [
        ("supplier", True),
        ("buyer", False),
    ]

    # isolation: other invitee sees an empty thread, outsider / other buyer get 404, buyer must name a supplier
    assert client.get(url, headers=other).json()["messages"] == []
    assert client.get(url, headers=outsider).status_code == 404
    assert client.post(url, headers=outsider, json={"body": "hi"}).status_code == 404
    assert client.get(url, headers=b2, params={"supplier_id": abc_id}).status_code == 404
    assert client.get(url, headers=buyer).status_code == 400
    assert client.post(url, headers=abc, json={"body": "   "}).status_code in (400, 422)
    assert client.post(url, headers=abc, json={"body": "x" * 2001}).status_code == 422

    # decline: withdraws the quote, records the reason for the buyer, shows in the thread, and quoting again undoes it
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=other,
        json={"unit_price": 3, "lead_time_days": 1},
    )
    declined = client.post(
        f"/api/requirements/{req['id']}/decline", headers=other, json={"reason": "No capacity"}
    ).json()
    assert declined["my_decline"] == {"reason": "No capacity"} and declined["my_quote"] is None
    d = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()
    inv = next(i for i in d["invites"] if i["supplier_id"] == other_id)
    assert inv["declined"] and inv["decline_reason"] == "No capacity" and d["quote_count"] == 0
    assert (
        "Declined to quote"
        in client.get(url, headers=buyer, params={"supplier_id": other_id}).json()["messages"][-1][
            "body"
        ]
    )
    assert (
        client.post(f"/api/requirements/{req['id']}/decline", headers=buyer, json={}).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=other,
            json={"unit_price": 4, "lead_time_days": 1},
        ).json()["my_decline"]
        is None
    )

    # after award: the winner keeps talking, the loser can read but not post, a cancelled requirement is closed to all
    qid = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quotes"][0]["id"]
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=abc,
        json={"unit_price": 2, "lead_time_days": 1},
    )
    qid = next(
        q["id"]
        for q in client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quotes"]
        if q["supplier_id"] == abc_id
    )
    aw = client.post(
        f"/api/requirements/{req['id']}/award", headers=buyer, json={"quote_id": qid}
    ).json()
    assert client.post(url, headers=abc, json={"body": "Shipping Monday"}).status_code == 201
    assert client.get(url, headers=other).json()["can_post"] is False
    assert client.post(url, headers=other, json={"body": "why not me"}).status_code == 400
    # the PO knows its requirement, so the conversation can continue from the PO page
    assert (
        client.get(f"/api/purchase-orders/{aw['po_id']}", headers=buyer).json()["requirement_id"]
        == req["id"]
    )

    # open-to-all decline (no invite row yet)
    oa = client.post(
        "/api/requirements", headers=buyer, json={"title": "OA", "quantity": 1, "open_to_all": True}
    ).json()
    client.post(
        f"/api/requirements/{oa['id']}/decline", headers=outsider, json={"reason": "not us"}
    )
    assert client.get(f"/api/requirements/{oa['id']}", headers=buyer).json()["invites"][0][
        "declined"
    ]


def test_agent_read_tools_are_scoped_to_the_acting_buyer(client):
    b1 = login(client, "buyer@demo.com")
    r = client.post(
        "/api/auth/register",
        json={"name": "B6", "email": "b6@x.com", "password": "longenough1", "role": "buyer"},
    ).json()
    b2 = {"Authorization": f"Bearer {r['access_token']}"}
    client.post("/api/requirements", headers=b1, json={"title": "Agent visible", "quantity": 1})
    mine = client.post("/api/mcp/list_requests", headers=b1, json={}).json()
    assert any(x["title"] == "Agent visible" for x in mine)
    assert client.post("/api/mcp/list_requests", headers=b2, json={}).json() == []
    num = next(x["req_number"] for x in mine if x["title"] == "Agent visible")
    assert (
        "responses"
        in client.post(
            "/api/mcp/get_request_detail", headers=b1, json={"req_number": num.lower()}
        ).json()
    )
    assert (
        client.post("/api/mcp/get_request_detail", headers=b2, json={"req_number": num}).status_code
        == 404
    )
    assert (
        client.post(
            "/api/mcp/get_request_detail", headers=b1, json={"req_number": "REQ9999"}
        ).status_code
        == 404
    )
    assert client.post("/api/mcp/list_purchase_orders", headers=b2, json={}).json() == []
    assert client.post("/api/mcp/list_purchase_orders", json={}).status_code == 401


def _approved_po(client, buyer, sup, item="ITEM002", qty=10, price=5, erp="sap"):
    """Requirement -> quote -> award -> approve, so the PO carries the requested ERP."""
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={
            "title": "Fulfil " + item,
            "item_code": item,
            "quantity": qty,
            "erp": erp,
            "open_to_all": True,
        },
    ).json()
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=sup,
        json={"unit_price": price, "lead_time_days": 2},
    )
    qid = client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quotes"][0]["id"]
    po_id = client.post(
        f"/api/requirements/{req['id']}/award", headers=buyer, json={"quote_id": qid}
    ).json()["po_id"]
    client.put(f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Approved"})
    return req, po_id


def test_shipment_approved_releases_stock_in_sap(client):
    buyer, sup, insp = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
    )
    other_sup, _ = _register_supplier(client, "other-shipper@x.com")
    _, po_id = _approved_po(client, buyer, sup, "ITEM002", 10)
    before = client.get("/api/inventory/ITEM002", headers=buyer).json()["stock_quantity"]
    sap_before = next(
        m["LABST"] for m in client.get("/mock/sap/materials").json() if m["MATNR"] == "ITEM002"
    )

    sh = ship(client, po_id, sup, "TRK-SAP-1")
    assert (
        sh["shipment_no"].startswith("SHP") and sh["status"] == "Shipped" and sh["erp_inbound_ref"]
    )
    assert (
        client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["delivery_status"]
        == "In Transit"
    )
    inbound = client.get("/mock/sap/inbound-deliveries").json()
    assert any(
        d["VBELN"] == sh["erp_inbound_ref"] and d["LIFEX"] == sh["shipment_no"] for d in inbound
    )

    # packing list: only the shipping supplier; bad types refused
    def up(h, name, data):
        return client.post(
            f"/api/shipments/{sh['id']}/files",
            headers=h,
            params={"kind": "packing_list"},
            files={"file": (name, data, "application/pdf")},
        )

    assert up(sup, "packing.pdf", b"%PDF list").status_code == 201
    assert up(other_sup, "x.pdf", b"x").status_code == 404
    assert up(sup, "run.exe", b"MZ").status_code == 415
    assert (
        client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["packing_list"]["filename"]
        == "packing.pdf"
    )

    # visibility: owner buyer, own supplier and inspector see it; strangers get 404
    stranger_tok = client.post(
        "/api/auth/register",
        json={"name": "S9", "email": "s9@x.com", "password": "longenough1", "role": "buyer"},
    ).json()["access_token"]
    stranger = {"Authorization": "Bearer " + stranger_tok}
    for h, code in ((buyer, 200), (sup, 200), (insp, 200), (other_sup, 404), (stranger, 404)):
        assert client.get(f"/api/shipments/{sh['id']}", headers=h).status_code == code
    assert any(s["id"] == sh["id"] for s in client.get("/api/shipments", headers=insp).json())
    assert client.get("/api/shipments", headers=stranger).json() == []
    fid = client.get(f"/api/shipments/{sh['id']}", headers=insp).json()["packing_list"]["id"]
    assert client.get(f"/api/shipment-files/{fid}/download", headers=insp).content == b"%PDF list"
    assert client.get(f"/api/shipment-files/{fid}/download", headers=other_sup).status_code == 404

    # inspector rules: nothing before arrival, quantities validated, supplier/buyer cannot inspect
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "approve", "checks": OK_CHECKS},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/arrival",
            headers=sup,
            json={"lines": [{"item_code": "ITEM002", "quantity_received": 10}]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/arrival",
            headers=insp,
            json={"lines": [{"item_code": "ITEM002", "quantity_received": 11}]},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/arrival",
            headers=insp,
            json={"lines": [{"item_code": "NOPE", "quantity_received": 1}]},
        ).status_code
        == 400
    )
    assert arrive(client, sh, insp)["status"] == "Arrived"
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=buyer,
            json={"decision": "approve", "checks": OK_CHECKS},
        ).status_code
        == 403
    )

    # nothing released until approval
    assert client.get("/api/inventory/ITEM002", headers=buyer).json()["stock_quantity"] == before
    done = client.post(
        f"/api/shipments/{sh['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS, "notes": "all good"},
    ).json()
    assert done["status"] == "Approved" and done["erp_movement_ref"]
    assert (
        client.get("/api/inventory/ITEM002", headers=buyer).json()["stock_quantity"] == before + 10
    )
    assert (
        next(
            m["LABST"] for m in client.get("/mock/sap/materials").json() if m["MATNR"] == "ITEM002"
        )
        == sap_before + 10
    )
    assert any(
        m["MBLNR"] == done["erp_movement_ref"] and m["BWART"] == "101"
        for m in client.get("/mock/sap/stock-movements").json()
    )
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["delivery_status"] == "Delivered" and not po["invoice_hold"]
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "approve", "checks": OK_CHECKS},
        ).status_code
        == 400
    )  # already decided
    assert (
        client.put(
            f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Closed"}
        ).json()["status"]
        == "Closed"
    )


def test_rejected_shipment_quarantines_and_holds_invoice_in_infor(client):
    buyer, sup, insp = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
    )
    req, po_id = _approved_po(client, buyer, sup, "ITEM003", 4, 600, erp="infor")
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["erp"] == "infor" and po["erp_reference"].startswith("LN-")
    before = client.get("/api/inventory/ITEM003", headers=buyer).json()["stock_quantity"]
    ln_before = next(
        i["onhand"] for i in client.get("/mock/infor/items").json() if i["item"] == "ITEM003"
    )

    sh = arrive(client, ship(client, po_id, sup, "TRK-LN-1"), insp)
    assert any(
        r["rcno"] == sh["erp_inbound_ref"] for r in client.get("/mock/infor/receipts").json()
    )

    def decide(**kw):
        return client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "reject", **kw}
        )

    def photo(h, name, data):
        return client.post(
            f"/api/shipments/{sh['id']}/files",
            headers=h,
            params={"kind": "photo"},
            files={"file": (name, data, "image/jpeg")},
        )

    # rejecting needs a reason AND at least one image
    assert decide(reason="Housing cracked").status_code == 400  # no photo yet
    assert photo(sup, "p.jpg", b"\xff\xd8x").status_code == 403
    assert photo(insp, "notes.pdf", b"%PDF").status_code == 415
    assert photo(insp, "crack.jpg", b"\xff\xd8\xff photo").status_code == 201
    assert decide(reason="").status_code == 400
    rejected = decide(reason="Housing cracked", notes="see photo").json()
    assert (
        rejected["status"] == "Rejected"
        and rejected["rejection_reason"] == "Housing cracked"
        and len(rejected["photos"]) == 1
    )

    # ERP side effects: quarantine location, no stock added, invoice hold active
    assert any(
        m["location"] == "quarantine" and m["trn"] == rejected["erp_movement_ref"]
        for m in client.get("/mock/infor/stock-movements").json()
    )
    assert (
        next(i["onhand"] for i in client.get("/mock/infor/items").json() if i["item"] == "ITEM003")
        == ln_before
    )
    assert client.get("/api/inventory/ITEM003", headers=buyer).json()["stock_quantity"] == before
    assert any(
        h["orno"] == po["erp_reference"] and h["active"]
        for h in client.get("/mock/infor/invoice-holds").json()
    )
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert (
        po["delivery_status"] == "Rejected"
        and po["invoice_hold"] == 1
        and po["invoice_hold_reason"] == "Housing cracked"
    )
    assert client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["stage"] == "Rejected"
    assert (
        client.put(
            f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Closed"}
        ).status_code
        == 400
    )  # cannot close a rejected delivery

    # supplier's result view: reason and the inspector's photo are visible to them
    seen = client.get(f"/api/shipments/{sh['id']}", headers=sup).json()
    assert (
        seen["rejection_reason"] == "Housing cracked"
        and seen["photos"][0]["filename"] == "crack.jpg"
    )
    assert (
        client.get(
            f"/api/shipment-files/{seen['photos'][0]['id']}/download", headers=sup
        ).status_code
        == 200
    )

    # a replacement shipment is approved: stock released, hold lifted, PO delivered
    replacement = deliver(client, po_id, sup, insp)
    assert replacement["status"] == "Approved"
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["delivery_status"] == "Delivered" and po["invoice_hold"] == 0
    assert not any(
        h["orno"] == po["erp_reference"] and h["active"]
        for h in client.get("/mock/infor/invoice-holds").json()
    )
    assert (
        client.get("/api/inventory/ITEM003", headers=buyer).json()["stock_quantity"] == before + 4
    )


def test_shipment_validation_and_role_boundaries(client):
    buyer, sup, insp, admin = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
        login(client, "admin@demo.com"),
    )
    other_sup, _ = _register_supplier(client, "not-my-po@x.com")
    abc_id = client.get("/api/auth/me", headers=sup).json()["supplier_id"]

    # unapproved order cannot ship
    draft = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc_id,
            "items": [{"item_code": "ITEM001", "quantity": 10, "unit_price": 1}],
        },
    ).json()
    body = {"items": [{"item_code": "ITEM001", "quantity": 1}]}
    assert (
        client.post(
            f"/api/purchase-orders/{draft['id']}/shipments", headers=sup, json=body
        ).status_code
        == 404
    )  # drafts are invisible
    client.put(f"/api/purchase-orders/{draft['id']}", headers=buyer, json={"status": "Pending"})
    assert (
        client.post(
            f"/api/purchase-orders/{draft['id']}/shipments", headers=sup, json=body
        ).status_code
        == 400
    )
    client.put(f"/api/purchase-orders/{draft['id']}", headers=buyer, json={"status": "Approved"})

    # only the assigned supplier ships; items and quantities are checked against the PO
    url = f"/api/purchase-orders/{draft['id']}/shipments"
    assert client.post(url, headers=other_sup, json=body).status_code == 404
    assert client.post(url, headers=buyer, json=body).status_code == 403
    assert (
        client.post(
            url, headers=sup, json={"items": [{"item_code": "ITEM009", "quantity": 1}]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            url, headers=sup, json={"items": [{"item_code": "ITEM001", "quantity": 11}]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            url, headers=sup, json={"items": [{"item_code": "ITEM001", "quantity": 0}]}
        ).status_code
        == 422
    )
    assert client.post(url, headers=sup, json={"items": []}).status_code == 422

    # partial shipments: PO only becomes Delivered once everything ordered has been received
    s1 = arrive(client, ship(client, draft["id"], sup, "P1", factor=2), insp)  # ships 5 of 10
    assert (
        client.post(
            url, headers=sup, json={"items": [{"item_code": "ITEM001", "quantity": 6}]}
        ).status_code
        == 400
    )  # 5 already committed
    client.post(
        f"/api/shipments/{s1['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS},
    )
    assert (
        client.get(f"/api/purchase-orders/{draft['id']}", headers=buyer).json()["delivery_status"]
        == "In Transit"
    )
    s2 = ship(client, draft["id"], sup, "P2", factor=2)  # the other 5
    arrive(client, s2, insp)
    client.post(
        f"/api/shipments/{s2['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS},
    )
    assert (
        client.get(f"/api/purchase-orders/{draft['id']}", headers=buyer).json()["delivery_status"]
        == "Delivered"
    )
    assert client.post(url, headers=sup, json=body).status_code == 400  # already delivered

    # the inspector can READ requests, POs, suppliers and inventory, but change nothing
    assert client.get("/api/purchase-orders", headers=insp).status_code == 200
    assert any(
        p["id"] == draft["id"] for p in client.get("/api/purchase-orders", headers=insp).json()
    )  # not limited to one buyer
    assert client.get(f"/api/purchase-orders/{draft['id']}", headers=insp).status_code == 200
    assert client.get("/api/requirements", headers=insp).status_code == 200
    assert client.get("/api/inventory", headers=insp).status_code == 200
    assert client.get("/api/suppliers", headers=insp).status_code == 200
    assert client.get("/api/dashboard", headers=insp).json()["role"] == "inspector"
    assert (
        client.put(
            f"/api/purchase-orders/{draft['id']}", headers=insp, json={"status": "Closed"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/purchase-orders",
            headers=insp,
            json={
                "supplier_id": abc_id,
                "items": [{"item_code": "ITEM001", "quantity": 1, "unit_price": 1}],
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/requirements", headers=insp, json={"title": "x", "quantity": 1}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/inventory", headers=insp, json={"item_code": "INSP-X", "description": "d"}
        ).status_code
        == 403
    )
    assert (
        client.put("/api/inventory/ITEM001", headers=insp, json={"stock_quantity": 1}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/suppliers", headers=insp, json={"supplier_name": "n", "email": "n@x.com"}
        ).status_code
        == 403
    )
    assert client.get("/api/admin/users", headers=insp).status_code == 403
    # admin can create inspectors; public registration cannot
    assert (
        client.post(
            "/api/admin/users",
            headers=admin,
            json={
                "name": "Dock",
                "email": "dock@x.com",
                "password": "longenough1",
                "role": "inspector",
            },
        ).status_code
        == 201
    )
    assert login(client, "dock@x.com", "longenough1")
    assert (
        client.post(
            "/api/auth/register",
            json={"name": "I", "email": "i@x.com", "password": "longenough1", "role": "inspector"},
        ).status_code
        == 422
    )


def test_users_table_is_rebuilt_for_old_databases(tmp_path, monkeypatch):
    """A database created before the 'inspector' role existed keeps its users and accepts inspectors afterwards."""
    import sqlite3

    from app import db
    from app.config import settings

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT, address TEXT, created_at TEXT NOT NULL);
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('buyer','supplier','admin')), supplier_id INTEGER REFERENCES suppliers(id), created_at TEXT NOT NULL);
        INSERT INTO users (name, email, password_hash, role, created_at) VALUES ('Old Buyer', 'old@x.com', 'h', 'buyer', 'now');
        """
    )
    old.commit()
    old.close()
    monkeypatch.setattr(settings, "database_path", path)
    db.init_db()
    db.init_db()  # idempotent
    conn = db.connect()
    try:
        assert (
            conn.execute("SELECT active FROM users WHERE email = 'old@x.com'").fetchone()["active"]
            == 1
        )
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES ('I', 'i@x.com', 'h', 'inspector', 'now')"
        )
        assert (
            conn.execute("SELECT id FROM users WHERE email = 'i@x.com'").fetchone()["id"] == 2
        )  # ids continue after the rebuild
    finally:
        conn.close()


def test_phone_numbers_are_validated(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    sid = client.get("/api/auth/me", headers=sup).json()["supplier_id"]

    def put(phone):
        return client.put(f"/api/suppliers/{sid}", headers=sup, json={"phone": phone})

    for good in [
        "+1 555 010 1234",
        "(555) 010-1234",
        "555.010.1234",
        "+44 20 7946 0958",
        "0123456",
        "  +91-98765-43210  ",
        "",
    ]:
        r = put(good)
        assert r.status_code == 200, (good, r.text)
        assert r.json()["phone"] == good.strip()
    for bad in [
        "abcdefg",
        "call me maybe",
        "555-CALL-NOW",
        "12345",
        "1234567890123456",
        "++15550101234",
        "555+0101234",
        "+1 (555) 010-1234 ext 5",
        "<script>",
        "555 010 1234; DROP TABLE",
    ]:
        r = put(bad)
        assert r.status_code == 422, (bad, r.status_code)
    assert (
        client.get(f"/api/suppliers/{sid}", headers=sup).json()["phone"] == ""
    )  # bad values never reached the database
    assert put(None).status_code == 200  # omitted/None keeps the current value
    assert (
        client.post(
            "/api/suppliers",
            headers=buyer,
            json={"supplier_name": "Phone Co", "email": "p@x.com", "phone": "letters"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/suppliers",
            headers=buyer,
            json={"supplier_name": "Phone Co", "email": "p@x.com", "phone": "+1 555 010 9999"},
        ).status_code
        == 201
    )


def _new_token(client, headers, name="Test laptop", scope="read", days=90):
    r = client.post(
        "/api/tokens", headers=headers, json={"name": name, "scope": scope, "expires_in_days": days}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_api_tokens_lifecycle_and_scopes(client):
    buyer, sup, admin = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "admin@demo.com"),
    )
    other = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={"name": "B7", "email": "b7@x.com", "password": "longenough1", "role": "buyer"},
        ).json()["access_token"]
    }

    # creation rules
    assert client.post("/api/tokens", headers=sup, json={"name": "x"}).status_code == 403
    assert client.post("/api/tokens", json={"name": "x"}).status_code == 401
    assert (
        client.post("/api/tokens", headers=buyer, json={"name": "  ", "scope": "read"}).status_code
        == 400
    )
    assert (
        client.post("/api/tokens", headers=buyer, json={"name": "x", "scope": "admin"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tokens", headers=buyer, json={"name": "x", "expires_in_days": 0}
        ).status_code
        == 422
    )
    made = _new_token(client, buyer, "Claude on my laptop", "read")
    raw = made["token"]
    assert (
        raw.startswith("erp_")
        and made["prefix"] == raw[:10]
        and made["status"] == "active"
        and made["scope"] == "read"
    )

    # the secret is shown once: never in lists, and not stored in plain text
    listing = client.get("/api/tokens", headers=buyer).json()
    assert any(t["id"] == made["id"] for t in listing) and all(
        "token" not in t and "token_hash" not in t for t in listing
    )
    from app.db import connect

    c = connect()
    stored = c.execute(
        "SELECT token_hash, prefix FROM api_tokens WHERE id = ?", (made["id"],)
    ).fetchone()
    c.close()
    assert raw not in stored["token_hash"] and len(stored["token_hash"]) == 64
    assert all(
        t["id"] != made["id"] for t in client.get("/api/tokens", headers=other).json()
    )  # tokens are private to their owner

    # a token acts as its owner on the agent endpoints
    t = _bearer(raw)
    assert (
        client.post("/api/mcp/get_inventory", headers=t, json={"item_code": "ITEM001"}).status_code
        == 200
    )
    client.post("/api/requirements", headers=buyer, json={"title": "Token visible", "quantity": 1})
    assert any(
        r["title"] == "Token visible"
        for r in client.post("/api/mcp/list_requests", headers=t, json={}).json()
    )
    other_tok = _new_token(client, other, "other buyer")["token"]
    assert all(
        r["title"] != "Token visible"
        for r in client.post("/api/mcp/list_requests", headers=_bearer(other_tok), json={}).json()
    )

    # read scope cannot create; write scope can, as the owner, flagged and attributed to the token in the audit trail
    body = {"supplier_id": 1, "item_code": "ITEM001", "quantity": 3}
    assert client.post("/api/mcp/create_purchase_order", headers=t, json=body).status_code == 403
    w = _bearer(_new_token(client, buyer, "Drafting agent", "write")["token"])
    po = client.post("/api/mcp/create_purchase_order", headers=w, json=body).json()
    me = client.get("/api/auth/me", headers=buyer).json()
    assert po["created_via"] == "agent-api" and po["created_by"] == me["id"]
    hist = client.get(f"/api/purchase-orders/{po['id']}", headers=buyer).json()["history"]
    assert "[token: Drafting agent]" in hist[0]["detail"] and hist[0]["channel"] == "agent-api"

    # tokens are useless outside the agent surface: no REST API, no minting tokens, no MCP-less admin actions
    for method, path in (
        ("get", "/api/auth/me"),
        ("get", "/api/purchase-orders"),
        ("get", "/api/tokens"),
        ("get", "/api/admin/users"),
    ):
        assert getattr(client, method)(path, headers=w).status_code == 401, path
    assert (
        client.post(
            "/api/tokens", headers=w, json={"name": "escalate", "scope": "write"}
        ).status_code
        == 401
    )
    assert (
        client.put(
            f"/api/purchase-orders/{po['id']}", headers=w, json={"status": "Pending"}
        ).status_code
        == 401
    )

    # bad credentials
    assert (
        client.post(
            "/api/mcp/get_inventory",
            headers=_bearer("erp_notarealtoken"),
            json={"item_code": "ITEM001"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/mcp/",
            headers=_bearer("erp_notarealtoken"),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/mcp/", headers=t, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
        ).status_code
        != 401
    )  # valid token passes the gate

    # revoking: owner or admin only, immediate, idempotent
    assert client.delete(f"/api/tokens/{made['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/tokens/{made['id']}", headers=buyer).json()["status"] == "revoked"
    assert client.delete(f"/api/tokens/{made['id']}", headers=buyer).json()["status"] == "revoked"
    assert (
        client.post("/api/mcp/get_inventory", headers=t, json={"item_code": "ITEM001"}).status_code
        == 401
    )
    assert (
        client.delete(
            f"/api/tokens/{_new_token(client, other, 'admin will revoke')['id']}", headers=admin
        ).json()["status"]
        == "revoked"
    )

    # admin sees everyone's tokens (with owners); others cannot
    everyone = client.get("/api/admin/tokens", headers=admin).json()
    assert {"Drafting agent", "other buyer"} <= {x["name"] for x in everyone} and all(
        "owner_email" in x for x in everyone
    )
    assert client.get("/api/admin/tokens", headers=buyer).status_code == 403


def test_token_expiry_disabled_users_and_rate_limit(client, monkeypatch):
    buyer, admin = login(client, "buyer@demo.com"), login(client, "admin@demo.com")
    from app import agent_auth
    from app.db import connect

    # expiry
    exp = _new_token(client, buyer, "short lived", days=1)
    e = _bearer(exp["token"])
    assert (
        client.post("/api/mcp/get_inventory", headers=e, json={"item_code": "ITEM001"}).status_code
        == 200
    )
    c = connect()
    c.execute(
        "UPDATE api_tokens SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (exp["id"],)
    )
    c.commit()
    c.close()
    assert (
        client.post("/api/mcp/get_inventory", headers=e, json={"item_code": "ITEM001"}).status_code
        == 401
    )
    assert (
        next(t for t in client.get("/api/tokens", headers=buyer).json() if t["id"] == exp["id"])[
            "status"
        ]
        == "expired"
    )

    # a token stops working the moment its owner is disabled, and resumes when re-enabled
    u = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "name": "Agent Owner",
            "email": "agentowner@x.com",
            "password": "longenough1",
            "role": "buyer",
        },
    ).json()
    owner = login(client, "agentowner@x.com", "longenough1")
    client.post(
        "/api/inventory",
        headers=owner,
        json={"item_code": "ITEM001", "description": "Bolt", "stock_quantity": 1},
    )  # inventory is per owner, so the new buyer stocks the item the agent looks up
    tok = _bearer(_new_token(client, owner, "owner token")["token"])
    assert (
        client.post(
            "/api/mcp/get_inventory", headers=tok, json={"item_code": "ITEM001"}
        ).status_code
        == 200
    )
    client.patch(f"/api/admin/users/{u['id']}", headers=admin, json={"active": False})
    assert (
        client.post(
            "/api/mcp/get_inventory", headers=tok, json={"item_code": "ITEM001"}
        ).status_code
        == 401
    )
    client.patch(f"/api/admin/users/{u['id']}", headers=admin, json={"active": True})
    assert (
        client.post(
            "/api/mcp/get_inventory", headers=tok, json={"item_code": "ITEM001"}
        ).status_code
        == 200
    )

    # active-token cap per user
    cap = login(client, "agentowner@x.com", "longenough1")
    for i in range(9):  # one already exists
        _new_token(client, cap, f"t{i}")
    assert client.post("/api/tokens", headers=cap, json={"name": "one too many"}).status_code == 400

    # rate limit per credential
    monkeypatch.setattr(agent_auth, "RATE_LIMIT", 3)
    agent_auth._hits.clear()
    codes = [
        client.post(
            "/api/mcp/get_inventory", headers=tok, json={"item_code": "ITEM001"}
        ).status_code
        for _ in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]
    other_cred = _bearer(_new_token(client, buyer, "different bucket")["token"])
    assert (
        client.post(
            "/api/mcp/get_inventory", headers=other_cred, json={"item_code": "ITEM001"}
        ).status_code
        == 200
    )  # limits are per credential
    agent_auth._hits.clear()


def test_inspector_sees_everything_but_the_private_chat(client):
    sup, insp = login(client, "supplier@demo.com"), login(client, "inspector@demo.com")
    other = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={"name": "B8", "email": "b8@x.com", "password": "longenough1", "role": "buyer"},
        ).json()["access_token"]
    }
    req = client.post(
        "/api/requirements",
        headers=other,
        json={"title": "Someone else's request", "quantity": 2, "open_to_all": True},
    ).json()
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=sup,
        json={"unit_price": 9, "lead_time_days": 3},
    )
    client.post(
        f"/api/requirements/{req['id']}/messages", headers=sup, json={"body": "private question"}
    )

    # all buyers' requirements are visible, with quotes, but read-only
    assert any(r["id"] == req["id"] for r in client.get("/api/requirements", headers=insp).json())
    detail = client.get(f"/api/requirements/{req['id']}", headers=insp).json()
    assert len(detail["quotes"]) == 1 and detail["threads"] == [] and detail["unread_messages"] == 0
    for path, body in (
        ("cancel", {}),
        ("open-to-all", {}),
        ("invite", {"supplier_ids": [1]}),
        ("award", {"quote_id": detail["quotes"][0]["id"]}),
    ):
        assert (
            client.post(
                f"/api/requirements/{req['id']}/{path}", headers=insp, json=body
            ).status_code
            == 403
        ), path
    # the buyer <-> supplier conversation is not part of what an inspector can read
    assert (
        client.get(
            f"/api/requirements/{req['id']}/messages", headers=insp, params={"supplier_id": 1}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/requirements/{req['id']}/messages",
            headers=insp,
            json={"body": "hi", "supplier_id": 1},
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/requirements/{req['id']}/quote",
            headers=insp,
            json={"unit_price": 1, "lead_time_days": 1},
        ).status_code
        == 403
    )

    # POs of every buyer, and the inventory rows come back without edit/delete rights
    po = client.post(
        "/api/purchase-orders",
        headers=other,
        json={
            "supplier_id": 1,
            "items": [{"item_code": "ITEM001", "quantity": 1, "unit_price": 1}],
        },
    ).json()
    assert any(p["id"] == po["id"] for p in client.get("/api/purchase-orders", headers=insp).json())
    assert client.get(f"/api/purchase-orders/{po['id']}", headers=insp).json()["history"]
    rows = client.get("/api/inventory", headers=insp).json()
    assert rows and not any(r["can_edit"] or r["can_delete"] for r in rows)
    # agents/MCP stay buyer-only
    assert client.post("/api/tokens", headers=insp, json={"name": "x"}).status_code == 403


def test_quality_checklist_shortfall_and_improvement_notice(client):
    buyer, sup, insp = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
    )
    _, po_id = _approved_po(client, buyer, sup, "ITEM006", 10, 7)

    def stock():
        return client.get("/api/inventory/ITEM006", headers=buyer).json()["stock_quantity"]

    before = stock()

    # quantity check: only 8 of 10 arrive; both sides are told about the shortfall
    sh = ship(client, po_id, sup, "Q1")
    arrived = client.post(
        f"/api/shipments/{sh['id']}/arrival",
        headers=insp,
        json={"lines": [{"item_code": "ITEM006", "quantity_received": 8}]},
    ).json()
    assert arrived["items"][0]["quantity_received"] == 8
    sup_notes = " ".join(
        n["title"] + " " + n["message"]
        for n in client.get("/api/notifications", headers=sup).json()
    )
    assert "quantity shortfall" in sup_notes and "received 8 of 10 (short by 2)" in sup_notes
    assert any(
        "shortfall" in h["action"]
        for h in client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["history"]
    )

    # quality check: approving needs all four checks to pass
    def approve(**kw):
        return client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "approve", **kw},
        )

    assert approve().status_code == 400  # no checklist at all
    r = approve(checks={**OK_CHECKS, "condition": False})
    assert r.status_code == 400 and "No visible damage or defects" in r.json()["detail"]
    assert approve(checks={"packaging": True}).status_code == 400
    assert approve(checks={**OK_CHECKS, "colour": True}).status_code == 400  # unknown check
    assert stock() == before  # nothing released by the failed attempts

    # a passing checklist releases what actually arrived; the supplier is told what is still owed
    done = approve(checks=OK_CHECKS).json()
    assert done["status"] == "Approved" and all(q["passed"] is True for q in done["quality"])
    assert stock() == before + 8
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["delivery_status"] == "In Transit"  # not fully delivered: the deal does not close yet
    assert (
        client.put(
            f"/api/purchase-orders/{po_id}", headers=buyer, json={"status": "Closed"}
        ).status_code
        == 400
    )
    sup_notes = " ".join(n["message"] for n in client.get("/api/notifications", headers=sup).json())
    assert "Still to fulfil" in sup_notes and "2 x ITEM006" in sup_notes

    # the supplier ships the remaining 2 and the order completes
    rest = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM006", "quantity": 2}]},
    ).json()
    arrive(client, rest, insp)
    client.post(
        f"/api/shipments/{rest['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "checks": OK_CHECKS},
    )
    assert (
        client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["delivery_status"]
        == "Delivered"
    )
    assert stock() == before + 10

    # improvement notice: failed checks + what to fix reach the supplier, with the required next step
    _, po2 = _approved_po(client, buyer, sup, "ITEM007", 5, 20)
    bad = arrive(client, ship(client, po2, sup, "Q2"), insp)
    client.post(
        f"/api/shipments/{bad['id']}/files",
        headers=insp,
        params={"kind": "photo"},
        files={"file": ("dent.jpg", b"\xff\xd8\xff dent", "image/jpeg")},
    )
    rej = client.post(
        f"/api/shipments/{bad['id']}/inspection",
        headers=insp,
        json={
            "decision": "reject",
            "reason": "Copper wire is kinked",
            "checks": {**OK_CHECKS, "condition": False, "packaging": False},
            "improvement": "Re-wind on proper reels and add protective end caps.",
        },
    ).json()
    assert rej["status"] == "Rejected" and rej["improvement_request"].startswith("Re-wind")
    assert {q["key"]: q["passed"] for q in rej["quality"]}["condition"] is False
    seen = client.get(
        f"/api/shipments/{bad['id']}", headers=sup
    ).json()  # the supplier's result view
    assert seen["improvement_request"] and seen["rejection_reason"] == "Copper wire is kinked"
    note = next(
        n
        for n in client.get("/api/notifications", headers=sup).json()
        if "improvement required" in n["title"]
    )
    for text in (
        "Copper wire is kinked",
        "Packaging intact",
        "No visible damage or defects",
        "Re-wind on proper reels",
        "ship a replacement",
    ):
        assert text in note["message"], text
    assert "Matches specification" not in note["message"]  # only the checks that failed are listed
    assert any(
        "improvement required" in n["title"]
        for n in client.get("/api/notifications", headers=buyer).json()
    )  # the buyer is told too


def _in(hours):
    from datetime import datetime, timedelta

    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _set_deadline_in_db(req_id, iso):
    """Move a deadline around without waiting (tests can't sleep for hours)."""
    from app.db import connect

    c = connect()
    c.execute("UPDATE requirements SET quote_deadline = ? WHERE id = ?", (iso, req_id))
    c.commit()
    c.close()


def test_quote_deadline_is_enforced_and_can_be_extended(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    other_buyer = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={"name": "B9", "email": "b9@x.com", "password": "longenough1", "role": "buyer"},
        ).json()["access_token"]
    }
    body = {"title": "Deadline test", "quantity": 3, "open_to_all": True}

    # creation rules: must be a valid future date-time; naive and Z formats are normalised to UTC
    assert (
        client.post(
            "/api/requirements", headers=buyer, json={**body, "quote_deadline": _in(-1)}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/requirements", headers=buyer, json={**body, "quote_deadline": "next friday"}
        ).status_code
        == 400
    )
    z = client.post(
        "/api/requirements",
        headers=buyer,
        json={**body, "quote_deadline": _in(48).replace("+00:00", "Z")},
    ).json()
    assert (
        z["quote_deadline"].endswith("+00:00")
        and z["quotes_closed"] is False
        and z["stage"] == "Open"
    )
    nodl = client.post(
        "/api/requirements", headers=buyer, json={**body, "quote_deadline": ""}
    ).json()
    assert nodl["quote_deadline"] is None and nodl["quotes_closed"] is False

    req = client.post(
        "/api/requirements", headers=buyer, json={**body, "quote_deadline": _in(72)}
    ).json()
    rid = req["id"]

    def q(price=5):
        return client.put(
            f"/api/requirements/{rid}/quote",
            headers=sup,
            json={"unit_price": price, "lead_time_days": 2},
        )

    assert q().status_code == 200  # before the deadline

    # the deadline passes: stage flips, and every supplier action that changes a quote is refused
    _set_deadline_in_db(rid, _in(-2))
    closed = client.get(f"/api/requirements/{rid}", headers=buyer).json()
    assert closed["quotes_closed"] is True and closed["stage"] == "Quotes closed"
    assert (
        next(r for r in client.get("/api/requirements", headers=sup).json() if r["id"] == rid)[
            "stage"
        ]
        == "Quotes closed"
    )
    for resp in (
        q(6),
        client.delete(f"/api/requirements/{rid}/quote", headers=sup),
        client.post(f"/api/requirements/{rid}/decline", headers=sup, json={"reason": "late"}),
    ):
        assert resp.status_code == 400 and "closed" in resp.json()["detail"].lower()
    assert (
        client.get(f"/api/requirements/{rid}", headers=sup).json()["my_quote"]["unit_price"] == 5
    )  # untouched

    # only the owner extends; past dates and closed requirements are refused; extending reopens quoting
    url = f"/api/requirements/{rid}/deadline"
    assert client.put(url, headers=sup, json={"quote_deadline": _in(24)}).status_code == 403
    assert client.put(url, headers=other_buyer, json={"quote_deadline": _in(24)}).status_code == 404
    assert client.put(url, headers=buyer, json={"quote_deadline": _in(-1)}).status_code == 400
    ext = client.put(url, headers=buyer, json={"quote_deadline": _in(96)}).json()
    assert ext["quotes_closed"] is False and ext["stage"] == "Quoted"
    assert q(4).status_code == 200
    assert any(
        "deadline" in h["action"]
        for h in client.get(f"/api/requirements/{rid}", headers=buyer).json()["history"]
    )
    assert any(
        "Quote deadline updated" in n["title"]
        for n in client.get("/api/notifications", headers=sup).json()
    )

    # clearing removes the limit; the buyer may still award after the deadline has passed
    assert (
        client.put(url, headers=buyer, json={"quote_deadline": None}).json()["quote_deadline"]
        is None
    )
    _set_deadline_in_db(rid, _in(-1))
    qid = client.get(f"/api/requirements/{rid}", headers=buyer).json()["quotes"][0]["id"]
    assert (
        client.post(f"/api/requirements/{rid}/award", headers=buyer, json={"quote_id": qid}).json()[
            "stage"
        ]
        == "Awarded"
    )
    assert (
        client.put(url, headers=buyer, json={"quote_deadline": _in(24)}).status_code == 400
    )  # awarded: nothing to extend


def test_deadline_reminders_and_close_notice(client):
    from app.db import get_conn
    from app.services import requirements as req_svc

    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    quoter, quoter_id = _register_supplier(client, "quoter-dl@x.com")
    decliner, decliner_id = _register_supplier(client, "decliner-dl@x.com")
    silent, silent_id = _register_supplier(client, "silent-dl@x.com")
    abc_id = client.get("/api/auth/me", headers=sup).json()["supplier_id"]

    def titles(h):
        return [n["title"] for n in client.get("/api/notifications", headers=h).json()]

    def tick():
        return _tick(req_svc, get_conn)

    # invited-only RFQ, deadline 30 h away: created outside the 24 h window so the reminder waits
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={
            "title": "Reminder RFQ",
            "quantity": 1,
            "supplier_ids": [quoter_id, decliner_id, silent_id],
            "quote_deadline": _in(30),
        },
    ).json()
    rid = req["id"]
    client.put(
        f"/api/requirements/{rid}/quote",
        headers=quoter,
        json={"unit_price": 2, "lead_time_days": 1},
    )
    client.post(f"/api/requirements/{rid}/decline", headers=decliner, json={"reason": "busy"})
    assert (
        tick() == {"reminded": 0, "closed": 0} or tick()["closed"] == 0
    )  # other tests' RFQs may exist, but not this one
    assert not any(f"REQ{2000 + rid}" in t for t in titles(silent) if "close soon" in t)

    # inside the 24 h window: only suppliers who can still respond and have not quoted are reminded, once
    _set_deadline_in_db(rid, _in(10))
    r1 = tick()
    assert r1["reminded"] >= 1
    assert any("close soon" in t and f"REQ{2000 + rid}" in t for t in titles(silent))
    assert not any(
        "close soon" in t and f"REQ{2000 + rid}" in t for t in titles(quoter)
    )  # already quoted
    assert not any(
        "close soon" in t and f"REQ{2000 + rid}" in t for t in titles(decliner)
    )  # already declined
    assert not any(
        "close soon" in t and f"REQ{2000 + rid}" in t for t in titles(sup)
    )  # never invited
    assert tick()["reminded"] == 0  # not sent twice

    # a deadline that is already under 24 h at creation does not trigger an instant reminder
    soon = client.post(
        "/api/requirements",
        headers=buyer,
        json={
            "title": "Soon RFQ",
            "quantity": 1,
            "supplier_ids": [abc_id],
            "quote_deadline": _in(5),
        },
    ).json()
    tick()
    assert not any("close soon" in t and f"REQ{2000 + soon['id']}" in t for t in titles(sup))

    # extending resets the flags, so a fresh reminder is possible for the new deadline
    _set_deadline_in_db(rid, _in(-1))  # deadline passes
    r2 = tick()
    assert r2["closed"] >= 1
    notice = next(
        n
        for n in client.get("/api/notifications", headers=buyer).json()
        if "Quotes closed" in n["title"] and f"REQ{2000 + rid}" in n["title"]
    )
    assert "1 quote(s) received" in notice["message"]
    assert tick()["closed"] == 0  # once only
    client.put(f"/api/requirements/{rid}/deadline", headers=buyer, json={"quote_deadline": _in(50)})
    _set_deadline_in_db(rid, _in(-1))
    assert tick()["closed"] >= 1  # a new deadline can close (and notify) again


def _tick(req_svc, get_conn):
    with get_conn() as conn:
        return req_svc.process_deadlines(conn)
