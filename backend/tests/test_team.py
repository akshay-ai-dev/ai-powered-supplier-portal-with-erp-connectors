# isort: off
from tests.test_api import _approved_po, login  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from tests.test_units import arrive, tag, unit_codes
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def second_buyer(client, email):
    r = client.post(
        "/api/auth/register",
        json={
            "name": "Buyer " + email.split("@")[0],
            "email": email,
            "password": "longenough1",
            "role": "buyer",
        },
    ).json()
    return {"Authorization": f"Bearer {r['access_token']}"}


def add_inspector(client, buyer, email, name="Warehouse Joe", password="inspector-pass-1"):
    r = client.post(
        "/api/team", headers=buyer, json={"name": name, "email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    return login(client, email, password), r.json()


def ship_for(client, buyer, sup, qty=3, item="ITEM002"):
    _, po_id = _approved_po(client, buyer, sup, item=item, qty=qty)
    sh = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": item, "quantity": qty}], "unit_inspection": True},
    ).json()
    return po_id, sh


def test_a_buyer_creates_and_manages_their_own_inspectors(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    admin, global_insp = login(client, "admin@demo.com"), login(client, "inspector@demo.com")
    other = second_buyer(client, "team-other@x.com")

    made = client.post(
        "/api/team",
        headers=buyer,
        json={"name": "Priya", "email": "Priya.Team@x.com", "password": "inspector-pass-1"},
    )
    assert (
        made.status_code == 201
        and made.json()["role"] == "inspector"
        and made.json()["active"] is True
        and made.json()["email"] == "priya.team@x.com"
    )
    uid = made.json()["id"]
    assert (
        client.post(
            "/api/team",
            headers=buyer,
            json={"name": "Dup", "email": "priya.team@x.com", "password": "inspector-pass-1"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/team",
            headers=buyer,
            json={"name": "Dup", "email": "buyer@demo.com", "password": "inspector-pass-1"},
        ).status_code
        == 409
    )  # emails are unique across all users
    assert (
        client.post(
            "/api/team",
            headers=buyer,
            json={"name": "Short", "email": "short@x.com", "password": "short"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/team",
            headers=buyer,
            json={
                "name": "Role",
                "email": "role@x.com",
                "password": "inspector-pass-1",
                "role": "admin",
            },
        ).json()["role"]
        == "inspector"
    )  # a buyer cannot choose a role

    mine = client.get("/api/team", headers=buyer).json()
    assert [u["email"] for u in mine if u["email"] in ("priya.team@x.com", "role@x.com")] == [
        "priya.team@x.com",
        "role@x.com",
    ]
    assert client.get("/api/team", headers=other).json() == []  # another buyer sees none of them

    # they can sign in, and they know whose inspector they are
    insp = login(client, "priya.team@x.com", "inspector-pass-1")
    me = client.get("/api/auth/me", headers=insp).json()
    assert (
        me["role"] == "inspector"
        and me["owner_name"] == "Vikas Buyer"
        and me["owner_id"] is not None
    )
    assert (
        next(u for u in client.get("/api/admin/users", headers=admin).json() if u["id"] == uid)[
            "owner_name"
        ]
        == "Vikas Buyer"
    )
    assert (
        client.get("/api/admin/users", headers=admin).json()[0].get("owner_id") is None
    )  # company-wide users have no owner

    # rename, reset the password, disable and enable
    assert (
        client.patch(f"/api/team/{uid}", headers=buyer, json={"name": "Priya N"}).json()["name"]
        == "Priya N"
    )
    assert (
        client.patch(
            f"/api/team/{uid}", headers=buyer, json={"password": "new-inspector-pass"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "priya.team@x.com", "password": "inspector-pass-1"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "priya.team@x.com", "password": "new-inspector-pass"}
        ).status_code
        == 200
    )
    assert (
        client.patch(f"/api/team/{uid}", headers=buyer, json={"active": False}).json()["active"]
        is False
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "priya.team@x.com", "password": "new-inspector-pass"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/auth/me", headers=insp).status_code == 401
    )  # an open session stops working too
    assert (
        client.patch(f"/api/team/{uid}", headers=buyer, json={"active": True}).json()["active"]
        is True
    )

    # only the owner manages them; nobody else uses the team API
    assert (
        client.patch(f"/api/team/{uid}", headers=other, json={"name": "Mine now"}).status_code
        == 404
    )
    assert (
        client.patch("/api/team/999999", headers=buyer, json={"active": False}).status_code == 404
    )
    assert (
        client.patch(
            f"/api/team/{client.get('/api/auth/me', headers=global_insp).json()['id']}",
            headers=buyer,
            json={"active": False},
        ).status_code
        == 404
    )  # company inspectors are not theirs
    for headers in (sup, global_insp, admin, insp):
        assert client.get("/api/team", headers=headers).status_code in (401, 403), headers
        assert client.post(
            "/api/team",
            headers=headers,
            json={"name": "X", "email": "x-team@x.com", "password": "inspector-pass-1"},
        ).status_code in (401, 403)
    assert client.get("/api/team").status_code == 401


def test_a_buyers_inspector_works_on_that_buyers_shipments_only(client):
    buyer_a, buyer_b = login(client, "buyer@demo.com"), second_buyer(client, "team-b@x.com")
    sup, global_insp = login(client, "supplier@demo.com"), login(client, "inspector@demo.com")
    ia, _ = add_inspector(client, buyer_a, "ia-scope@x.com")
    ib, _ = add_inspector(client, buyer_b, "ib-scope@x.com")

    po_a, sh_a = ship_for(client, buyer_a, sup)
    po_b, sh_b = ship_for(client, buyer_b, sup)
    req_b = client.get("/api/requirements", headers=buyer_b).json()[0]
    code_a, code_b = (
        unit_codes(client, global_insp, sh_a)[0],
        unit_codes(client, global_insp, sh_b)[0],
    )

    # what A's inspector can see
    assert {s["id"] for s in client.get("/api/shipments", headers=ia).json()} >= {
        sh_a["id"]
    } and sh_b["id"] not in {s["id"] for s in client.get("/api/shipments", headers=ia).json()}
    assert client.get(f"/api/shipments/{sh_a['id']}", headers=ia).status_code == 200
    for path in (
        f"/api/shipments/{sh_b['id']}",
        f"/api/shipments/{sh_b['id']}/units",
        f"/api/shipments/{sh_b['id']}/report",
        f"/api/shipments/{sh_b['id']}/labels",
        f"/api/units/{code_b}",
        f"/api/purchase-orders/{po_b}",
        f"/api/requirements/{req_b['id']}",
        f"/api/shipments/{sh_b['id']}/fields",
    ):
        assert client.get(path, headers=ia).status_code == 404, path
    assert client.post("/api/units/scan", headers=ia, json={"code": code_b}).status_code == 404
    pos = {p["id"] for p in client.get("/api/purchase-orders", headers=ia).json()}
    assert po_a in pos and po_b not in pos
    reqs = client.get("/api/requirements", headers=ia).json()
    assert reqs and all(r["id"] != req_b["id"] for r in reqs)
    all_a = {r["id"] for r in client.get("/api/requirements", headers=buyer_a).json()}
    assert {r["id"] for r in reqs} == all_a  # exactly the buyer's own requirements

    # it can do the whole inspection on its own buyer's shipment, and nothing on the other's
    assert (
        client.post(f"/api/shipments/{sh_b['id']}/units/{code_b}/receive", headers=ia).status_code
        == 404
    )
    assert (
        client.post(f"/api/shipments/{sh_b['id']}/arrival", headers=ia, json={}).status_code == 404
    )
    arrive(client, ia, sh_a)
    assert tag(client, ia, sh_a, code_a, "OK").status_code == 200
    assert (
        client.post(
            f"/api/shipments/{sh_a['id']}/units/bulk",
            headers=ia,
            json={"action": "ok", "all_pending": True},
        ).status_code
        == 200
    )
    done = client.post(
        f"/api/shipments/{sh_a['id']}/inspection", headers=ia, json={"decision": "approve"}
    )
    assert done.status_code == 200 and done.json()["status"] == "Approved"
    assert (
        client.post(
            f"/api/shipments/{sh_b['id']}/inspection", headers=ia, json={"decision": "approve"}
        ).status_code
        == 404
    )

    # B's inspector sees B's work and not A's; the company inspector sees both
    assert client.get(f"/api/shipments/{sh_b['id']}", headers=ib).status_code == 200
    assert client.get(f"/api/shipments/{sh_a['id']}", headers=ib).status_code == 404
    assert client.get(f"/api/units/{code_a}", headers=ib).status_code == 404
    for sh in (sh_a, sh_b):
        assert client.get(f"/api/shipments/{sh['id']}", headers=global_insp).status_code == 200

    # the dashboard counts only that buyer's shipments
    dash_a, dash_b = (
        client.get("/api/dashboard", headers=ia).json(),
        client.get("/api/dashboard", headers=ib).json(),
    )

    def count(buyer, status):
        return len(
            [x for x in client.get("/api/shipments", headers=buyer).json() if x["status"] == status]
        )

    assert dash_a["approved"] == count(buyer_a, "Approved") >= 1 and dash_a["incoming"] == count(
        buyer_a, "Shipped"
    )
    assert dash_b["incoming"] == count(buyer_b, "Shipped") == 1 and dash_b["approved"] == 0
    everyone = client.get("/api/dashboard", headers=global_insp).json()
    assert everyone["approved"] >= dash_a["approved"] and everyone["incoming"] >= dash_b["incoming"]


def test_inspectors_are_told_about_shipments_for_their_own_buyer_and_company_inspectors_about_all(
    client,
):
    buyer_a, buyer_b = login(client, "buyer@demo.com"), second_buyer(client, "team-notify@x.com")
    sup, global_insp = login(client, "supplier@demo.com"), login(client, "inspector@demo.com")
    ia, _ = add_inspector(client, buyer_a, "ia-notify@x.com")
    ib, _ = add_inspector(client, buyer_b, "ib-notify@x.com")

    def titles(h):
        return [n["title"] for n in client.get("/api/notifications", headers=h).json()]

    _, sh_a = ship_for(client, buyer_a, sup)
    incoming = f"Incoming shipment {sh_a['shipment_no']}"
    assert incoming in titles(ia)  # the buyer's own inspector
    assert incoming in titles(global_insp)  # a company inspector, so goods are never stuck
    assert incoming not in titles(ib)  # another buyer's inspector learns nothing about it

    _, sh_b = ship_for(client, buyer_b, sup)
    assert f"Incoming shipment {sh_b['shipment_no']}" in titles(ib)
    assert f"Incoming shipment {sh_b['shipment_no']}" not in titles(ia)

    # a disabled inspector is no longer told anything
    mine = next(
        u
        for u in client.get("/api/team", headers=buyer_a).json()
        if u["email"] == "ia-notify@x.com"
    )
    client.patch(f"/api/team/{mine['id']}", headers=buyer_a, json={"active": False})
    _, sh_a2 = ship_for(client, buyer_a, sup)
    assert f"Incoming shipment {sh_a2['shipment_no']}" in titles(global_insp)


def test_a_buyers_inspector_cannot_change_test_fields_on_another_buyers_shipment(client):
    buyer_a, buyer_b = login(client, "buyer@demo.com"), second_buyer(client, "team-fields@x.com")
    sup = login(client, "supplier@demo.com")
    ia, _ = add_inspector(client, buyer_a, "ia-fields@x.com")
    _, sh_a = ship_for(client, buyer_a, sup)
    _, sh_b = ship_for(client, buyer_b, sup)
    body = {"label": "Voltage", "type": "number", "item_code": "ITEM002"}

    assert (
        client.post(f"/api/shipments/{sh_b['id']}/fields", headers=ia, json=body).status_code == 404
    )
    mine = client.post(f"/api/shipments/{sh_a['id']}/fields", headers=ia, json=body)
    assert mine.status_code == 201
    other = client.post(
        f"/api/shipments/{sh_b['id']}/fields",
        headers=login(client, "inspector@demo.com"),
        json=body,
    ).json()  # a company inspector may
    assert (
        client.patch(
            f"/api/shipments/{sh_b['id']}/fields/{other['id']}",
            headers=ia,
            json={"label": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/shipments/{sh_b['id']}/fields/{other['id']}", headers=ia).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/shipments/{sh_a['id']}/fields/{mine.json()['id']}",
            headers=ia,
            json={"label": "Supply voltage"},
        ).status_code
        == 200
    )


def test_saved_test_fields_stay_with_the_buyer_they_were_saved_for(client):
    buyer_a, buyer_b = login(client, "buyer@demo.com"), second_buyer(client, "team-templates@x.com")
    sup, company = login(client, "supplier@demo.com"), login(client, "inspector@demo.com")
    ia, _ = add_inspector(client, buyer_a, "ia-templates@x.com")
    ib, _ = add_inspector(client, buyer_b, "ib-templates@x.com")
    _, sh_a = ship_for(client, buyer_a, sup)
    saved = client.post(
        f"/api/shipments/{sh_a['id']}/fields",
        headers=ia,
        json={
            "label": "Seal intact",
            "type": "pass_fail",
            "item_code": "ITEM002",
            "save_template": True,
        },
    )
    assert saved.status_code == 201

    def listed(h):
        return [
            t["label"]
            for t in client.get(
                "/api/inspection-fields/templates", headers=h, params={"item_code": "ITEM002"}
            ).json()
        ]

    assert "Seal intact" in listed(ia) and "Seal intact" in listed(company)
    assert "Seal intact" not in listed(ib)  # another buyer's inspector never sees it
    assert client.get("/api/inspection-fields/templates", headers=sup).json() == []

    # the next shipment of that item starts with it for the same buyer, and not for another buyer
    _, next_a = ship_for(client, buyer_a, sup)
    _, next_b = ship_for(client, buyer_b, sup)

    def labels(sh, h):
        return [
            f["label"] for f in client.get(f"/api/shipments/{sh['id']}/fields", headers=h).json()
        ]

    assert "Seal intact" in labels(next_a, ia)
    assert "Seal intact" not in labels(next_b, ib)

    template = next(
        t
        for t in client.get("/api/inspection-fields/templates", headers=company).json()
        if t["label"] == "Seal intact"
    )
    assert (
        client.delete(f"/api/inspection-fields/templates/{template['id']}", headers=ib).status_code
        == 404
    )  # not theirs to remove
    assert (
        client.delete(f"/api/inspection-fields/templates/{template['id']}", headers=ia).status_code
        == 200
    )


def test_a_buyers_inspector_sees_only_that_buyers_suppliers_and_inventory(client):
    buyer_a, buyer_b = login(client, "buyer@demo.com"), second_buyer(client, "team-scope@x.com")
    sup, company = login(client, "supplier@demo.com"), login(client, "inspector@demo.com")
    ia, _ = add_inspector(client, buyer_a, "ia-scope2@x.com")
    ib, _ = add_inspector(client, buyer_b, "ib-scope2@x.com")
    # buyer B works with a supplier that A never has, on an item only B stocks
    only_b = client.post(
        "/api/auth/register",
        json={
            "name": "Only B Supply",
            "email": "only-b-supply@x.com",
            "password": "longenough1",
            "role": "supplier",
        },
    ).json()
    client.post(
        "/api/inventory",
        headers=buyer_b,
        json={"item_code": "SCOPE-B-ONLY", "description": "B's own part", "stock_quantity": 5},
    )
    req = client.post(
        "/api/requirements",
        headers=buyer_b,
        json={
            "title": "B only",
            "item_code": "SCOPE-B-ONLY",
            "quantity": 1,
            "supplier_ids": [only_b["user"]["supplier_id"]],
        },
    ).json()
    po_a, _ = ship_for(client, buyer_a, sup)
    po_b, _ = ship_for(client, buyer_b, sup)

    def names(h):
        return {s["supplier_name"] for s in client.get("/api/suppliers", headers=h).json()}

    assert "Only B Supply" in names(ib) and "Only B Supply" not in names(ia)
    assert "ABC Industrial Supplies" in names(ia) and "ABC Industrial Supplies" in names(ib)
    assert {"Only B Supply", "ABC Industrial Supplies"} <= names(
        company
    ) and "Only B Supply" in names(buyer_a)  # buyers and company inspectors are not narrowed
    assert (
        client.get(f"/api/suppliers/{only_b['user']['supplier_id']}", headers=ia).status_code == 404
    )
    assert (
        client.get(f"/api/suppliers/{only_b['user']['supplier_id']}", headers=ib).status_code == 200
    )

    def codes(h):
        return {i["item_code"] for i in client.get("/api/inventory", headers=h).json()}

    assert (
        "SCOPE-B-ONLY" in codes(ib)
        and "SCOPE-B-ONLY" not in codes(ia)
        and "SCOPE-B-ONLY" in codes(company)
    )
    assert "ITEM002" in codes(ia) and "ITEM002" in codes(ib)  # items both buyers ordered
    assert client.get("/api/inventory/SCOPE-B-ONLY", headers=ia).status_code == 404
    assert client.get("/api/inventory/SCOPE-B-ONLY", headers=ib).status_code == 200
    assert req["id"]

    # the ERP monitor feed: buyers and admins only (inspectors and suppliers are refused)
    def ref(po_id):
        return client.get(
            f"/api/purchase-orders/{po_id}", headers=buyer_a if po_id == po_a else buyer_b
        ).json()["erp_reference"]

    def pos(h):
        return {
            p["EBELN"] for p in client.get("/api/erp-monitor/sap/purchase-orders", headers=h).json()
        }

    assert {ref(po_a), ref(po_b)} <= pos(buyer_a)
    assert {ref(po_a), ref(po_b)} <= pos(login(client, "admin@demo.com"))
    assert client.get("/api/erp-monitor/infor/orders", headers=buyer_a).status_code == 200
    assert client.get("/api/erp-monitor/sap/nonsense", headers=buyer_a).status_code == 404
    for inspector in (ia, ib, company):
        assert (
            client.get("/api/erp-monitor/sap/purchase-orders", headers=inspector).status_code == 403
        )
    assert client.get("/api/erp-monitor/sap/purchase-orders", headers=sup).status_code in (401, 403)
    assert client.get("/api/erp-monitor/sap/purchase-orders").status_code == 401
