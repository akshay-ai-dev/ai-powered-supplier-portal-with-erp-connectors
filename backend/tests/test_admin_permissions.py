# isort: off
from tests.test_api import _approved_po, login  # sets the test environment first
from fastapi.testclient import TestClient
from app.main import app
# isort: on

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("creator_email", ["buyer@demo.com", "admin@demo.com"])
def test_admin_cannot_change_deadlines_or_attach_requirement_files(client, creator_email):
    admin = login(client, "admin@demo.com")
    creator = login(client, creator_email)
    deadline = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    created = client.post(
        "/api/requirements",
        headers=creator,
        json={"title": "Admin permission checks", "quantity": 1, "quote_deadline": deadline},
    )
    assert created.status_code == 201, created.text
    saved_deadline = created.json()["quote_deadline"]
    url = f"/api/requirements/{created.json()['id']}"

    for value in (None, (datetime.now(UTC) + timedelta(days=4)).isoformat()):
        denied = client.put(f"{url}/deadline", headers=admin, json={"quote_deadline": value})
        assert denied.status_code == 403, denied.text
        assert client.get(url, headers=admin).json()["quote_deadline"] == saved_deadline

    denied = client.post(
        f"{url}/attachments",
        headers=admin,
        files={"file": ("drawing.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert denied.status_code == 403, denied.text
    assert client.get(url, headers=admin).json()["attachments"] == []

    if creator_email == "buyer@demo.com":
        assert (
            client.put(
                f"{url}/deadline", headers=creator, json={"quote_deadline": None}
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"{url}/attachments",
                headers=creator,
                files={"file": ("drawing.pdf", b"%PDF-1.4 fake", "application/pdf")},
            ).status_code
            == 201
        )


def test_admin_cannot_reset_buyer_inspector_password(client):
    admin = login(client, "admin@demo.com")
    buyer = login(client, "buyer@demo.com")
    email = "admin-permissions-inspector@x.com"
    created = client.post(
        "/api/team",
        headers=buyer,
        json={"name": "Buyer inspector", "email": email, "password": "original-password"},
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    for changes in (
        {"password": "admin-password"},
        {"password": "admin-password", "name": "Changed", "active": False},
    ):
        denied = client.patch(f"/api/admin/users/{uid}", headers=admin, json=changes)
        assert denied.status_code == 403, denied.text
        assert (
            client.post(
                "/api/auth/login", json={"email": email, "password": "original-password"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": email, "password": "admin-password"}
            ).status_code
            == 401
        )
        inspector = next(u for u in client.get("/api/team", headers=buyer).json() if u["id"] == uid)
        assert inspector["name"] == "Buyer inspector" and inspector["active"] is True

    assert (
        client.patch(
            f"/api/team/{uid}", headers=buyer, json={"password": "buyer-password"}
        ).status_code
        == 200
    )
    login(client, email, "buyer-password")

    company = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "name": "Company inspector",
            "email": "admin-permissions-company@x.com",
            "role": "inspector",
            "password": "original-password",
        },
    )
    assert company.status_code == 201, company.text
    assert (
        client.patch(
            f"/api/admin/users/{company.json()['id']}",
            headers=admin,
            json={"password": "admin-password"},
        ).status_code
        == 200
    )
    login(client, "admin-permissions-company@x.com", "admin-password")


def test_admin_cannot_access_private_buyer_supplier_conversations(client):
    admin = login(client, "admin@demo.com")
    buyer = login(client, "buyer@demo.com")
    supplier = login(client, "supplier@demo.com")
    sid = client.get("/api/auth/me", headers=supplier).json()["supplier_id"]
    created = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Private conversation", "quantity": 1, "supplier_ids": [sid]},
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    url = f"/api/requirements/{rid}"
    messages_url = f"{url}/messages"
    assert (
        client.post(
            messages_url, headers=supplier, json={"body": "Private supplier question"}
        ).status_code
        == 201
    )

    assert client.get(messages_url, headers=admin, params={"supplier_id": sid}).status_code == 403
    assert client.get(messages_url, headers=admin).status_code == 403
    assert (
        client.post(
            messages_url,
            headers=admin,
            json={"body": "Admin reply", "supplier_id": sid},
        ).status_code
        == 403
    )
    detail = client.get(url, headers=admin)
    assert detail.status_code == 200
    assert detail.json()["threads"] == [] and detail.json()["unread_messages"] == 0
    listing = client.get("/api/requirements", headers=admin).json()
    assert next(r for r in listing if r["id"] == rid)["unread_messages"] == 0

    # Denied admin access neither marks the supplier's message read nor adds a reply.
    detail = client.get(url, headers=buyer).json()
    assert detail["threads"][0]["unread"] == 1 and detail["unread_messages"] == 1
    thread = client.get(messages_url, headers=buyer, params={"supplier_id": sid}).json()
    assert [m["body"] for m in thread["messages"]] == ["Private supplier question"]
    assert (
        client.post(
            messages_url, headers=buyer, json={"body": "Private buyer reply", "supplier_id": sid}
        ).status_code
        == 201
    )
    thread = client.get(messages_url, headers=supplier).json()
    assert [m["body"] for m in thread["messages"]] == [
        "Private supplier question",
        "Private buyer reply",
    ]


def test_admin_cannot_access_inventory_or_shipments(client):
    admin = login(client, "admin@demo.com")
    buyer = login(client, "buyer@demo.com")
    supplier = login(client, "supplier@demo.com")
    inspector = login(client, "inspector@demo.com")
    items = client.get("/api/inventory", headers=buyer)
    assert items.status_code == 200
    code = items.json()[0]["item_code"]
    for method, path, body in (
        ("GET", "/api/inventory", None),
        ("GET", f"/api/inventory/{code}", None),
        (
            "POST",
            "/api/inventory",
            {"item_code": "ADMIN-DENIED", "description": "Denied", "stock_quantity": 1},
        ),
        ("PUT", f"/api/inventory/{code}", {"stock_quantity": 999}),
        ("DELETE", f"/api/inventory/{code}", None),
        ("POST", "/api/mcp/get_inventory", {"item_code": code}),
    ):
        denied = client.request(method, path, headers=admin, json=body)
        assert denied.status_code == 403, (path, denied.text)

    _, po_id = _approved_po(client, buyer, supplier, item="ITEM001", qty=1)
    created = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=supplier,
        json={"items": [{"item_code": "ITEM001", "quantity": 1}], "unit_inspection": True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    for path in (
        "/api/shipments",
        f"/api/shipments/{sid}",
        f"/api/purchase-orders/{po_id}/shipments",
        f"/api/purchase-orders/{po_id}/to-ship",
        f"/api/shipments/{sid}/units",
        f"/api/shipments/{sid}/report",
        f"/api/shipments/{sid}/labels",
        f"/api/shipments/{sid}/fields",
    ):
        denied = client.get(path, headers=admin)
        assert denied.status_code == 403, (path, denied.text)
    assert (
        client.post(
            f"/api/shipments/{sid}/inspection", headers=admin, json={"decision": "approve"}
        ).status_code
        == 403
    )
    for headers in (buyer, supplier, inspector):
        assert client.get("/api/inventory", headers=headers).status_code == 200
        assert client.get(f"/api/shipments/{sid}", headers=headers).status_code == 200
    req_id = client.get(f"/api/purchase-orders/{po_id}", headers=admin).json()["requirement_id"]
    req_number = client.get(f"/api/requirements/{req_id}", headers=admin).json()["req_number"]
    detail = client.post(
        "/api/mcp/get_request_detail", headers=admin, json={"req_number": req_number}
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["shipments"] == []


def test_admin_requirement_names_follow_stage(client):
    from app.db import get_conn

    admin = login(client, "admin@demo.com")
    buyer = login(client, "buyer@demo.com")
    supplier = login(client, "supplier@demo.com")
    buyer_name = client.get("/api/auth/me", headers=buyer).json()["name"]
    sid = client.get("/api/auth/me", headers=supplier).json()["supplier_id"]
    supplier_name = client.get(f"/api/suppliers/{sid}", headers=buyer).json()["supplier_name"]
    opened = client.post(
        "/api/requirements", headers=buyer, json={"title": "Names before award", "quantity": 1}
    ).json()

    def row(rid):
        return next(
            r for r in client.get("/api/requirements", headers=admin).json() if r["id"] == rid
        )

    assert row(opened["id"])["buyer_name"] == buyer_name
    assert row(opened["id"])["supplier_name"] is None
    client.put(
        f"/api/requirements/{opened['id']}/quote",
        headers=supplier,
        json={"unit_price": 5, "lead_time_days": 2},
    )
    assert row(opened["id"])["stage"] == "Quoted"
    assert row(opened["id"])["supplier_name"] is None

    req, po_id = _approved_po(client, buyer, supplier, qty=1)
    orders = client.get("/api/purchase-orders", headers=admin)
    assert orders.status_code == 200
    assert next(po for po in orders.json() if po["id"] == po_id)["buyer_name"] == buyer_name
    for stage, po_status, delivery_status in (
        ("Awarded", "Approved", "Not Shipped"),
        ("In Transit", "Approved", "In Transit"),
        ("Delivered", "Approved", "Delivered"),
        ("Rejected", "Approved", "Rejected"),
        ("Closed", "Closed", "Delivered"),
    ):
        with get_conn() as conn:
            conn.execute(
                "UPDATE purchase_orders SET status = ?, delivery_status = ? WHERE id = ?",
                (po_status, delivery_status, po_id),
            )
        result = row(req["id"])
        assert result["stage"] == stage
        assert result["buyer_name"] == buyer_name
        assert result["supplier_name"] == (
            supplier_name if stage in ("Awarded", "In Transit", "Closed") else None
        )


def test_admin_can_have_only_one_active_token(client):
    from app.db import get_conn

    admin = login(client, "admin@demo.com")

    def create(name):
        return client.post("/api/tokens", headers=admin, json={"name": name, "scope": "read"})

    first = create("Admin token")
    assert first.status_code == 201, first.text
    denied = create("Second admin token")
    assert denied.status_code == 400 and "one active token" in denied.json()["detail"]
    assert (
        sum(t["status"] == "active" for t in client.get("/api/tokens", headers=admin).json()) == 1
    )
    assert client.delete(f"/api/tokens/{first.json()['id']}", headers=admin).status_code == 200
    replacement = create("Replacement admin token")
    assert replacement.status_code == 201, replacement.text
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_tokens SET expires_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=1)).isoformat(), replacement.json()["id"]),
        )
    assert create("After expiry").status_code == 201
    assert create("Still limited").status_code == 400
