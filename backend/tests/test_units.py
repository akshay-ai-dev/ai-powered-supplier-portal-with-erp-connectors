# isort: off
from tests.test_api import (
    _approved_po,
    _register_supplier,
    login,
)  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def who(client):
    return (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
    )


def ship(client, qty=10, item="ITEM002", units=True):
    buyer, sup, insp = who(client)
    _, po_id = _approved_po(client, buyer, sup, item=item, qty=qty)
    sh = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": item, "quantity": qty}], "unit_inspection": units},
    )
    assert sh.status_code == 201, sh.text
    return po_id, sh.json()


def unit_codes(client, headers, sh, **params):
    r = client.get(
        f"/api/shipments/{sh['id']}/units", headers=headers, params={"limit": 200, **params}
    )
    assert r.status_code == 200, r.text
    return [u["code"] for u in r.json()["units"]]


def arrive(client, insp, sh, scan=None):
    """Scan the given codes (default: all) and confirm arrival."""
    for code in scan if scan is not None else unit_codes(client, insp, sh):
        assert (
            client.post(f"/api/shipments/{sh['id']}/units/{code}/receive", headers=insp).status_code
            == 200
        )
    r = client.post(f"/api/shipments/{sh['id']}/arrival", headers=insp, json={})
    assert r.status_code == 200, r.text
    return r.json()


def tag(client, headers, sh, code, result, **extra):
    body = {
        "result": result,
        **(
            {"defect_type": "cosmetic"} if result == "Faulty" and "defect_type" not in extra else {}
        ),
        **extra,
    }
    return client.put(f"/api/shipments/{sh['id']}/units/{code}", headers=headers, json=body)


def stock(client, headers, item="ITEM002"):
    return client.get(f"/api/inventory/{item}", headers=headers).json()["stock_quantity"]


def test_shipping_creates_unique_qr_codes_and_labels(client, monkeypatch):
    buyer, sup, insp = who(client)
    _, sh = ship(client, qty=10)
    assert sh["unit_level"] is True and sh["unit_counts"] == {"Shipped": 10}
    codes = unit_codes(client, sup, sh)
    assert (
        codes == [f"{sh['shipment_no']}-ITEM002-{n:04d}" for n in range(1, 11)]
        and len(set(codes)) == 10
    )

    labels = client.get(f"/api/shipments/{sh['id']}/labels", headers=sup).json()
    assert [u["code"] for u in labels["units"]] == codes and labels["po_number"].startswith("PO")
    assert client.get(f"/api/shipments/{sh['id']}/labels", headers=insp).status_code == 200
    assert (
        client.get(f"/api/shipments/{sh['id']}/labels", headers=buyer).status_code == 404
    )  # labels are for the shipper and the warehouse

    # opting out keeps the existing lot-level flow
    _, plain = ship(client, qty=4, units=False)
    assert plain["unit_level"] is False and "unit_counts" not in plain
    assert client.get(f"/api/shipments/{plain['id']}/units", headers=insp).status_code == 400

    # a cap protects the database from a shipment of a million units
    monkeypatch.setattr(settings, "inspection_max_units", 5)
    _, po_id = _approved_po(client, buyer, sup, item="ITEM002", qty=10)
    r = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM002", "quantity": 10}], "unit_inspection": True},
    )
    assert r.status_code == 400 and "at most 5 units" in r.json()["detail"]


def test_two_items_get_their_own_numbering(client):
    buyer, sup, insp = who(client)
    abc = client.get("/api/auth/me", headers=sup).json()["supplier_id"]
    po = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc,
            "submit": True,
            "items": [
                {"item_code": "ITEM002", "quantity": 3, "unit_price": 5},
                {"item_code": "ITEM003", "quantity": 2, "unit_price": 9},
            ],
        },
    ).json()
    client.put(f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Approved"})
    sh = client.post(
        f"/api/purchase-orders/{po['id']}/shipments",
        headers=sup,
        json={
            "unit_inspection": True,
            "items": [
                {"item_code": "ITEM002", "quantity": 3},
                {"item_code": "ITEM003", "quantity": 2},
            ],
        },
    ).json()
    n = sh["shipment_no"]
    assert unit_codes(client, insp, sh) == [
        f"{n}-ITEM002-0001",
        f"{n}-ITEM002-0002",
        f"{n}-ITEM002-0003",
        f"{n}-ITEM003-0001",
        f"{n}-ITEM003-0002",
    ]
    assert unit_codes(client, insp, sh, item_code="ITEM003") == [
        f"{n}-ITEM003-0001",
        f"{n}-ITEM003-0002",
    ]
    assert unit_codes(client, insp, sh, q="0002") == [f"{n}-ITEM002-0002", f"{n}-ITEM003-0002"]


def test_scanning_at_arrival_counts_received_and_reports_missing(client):
    buyer, sup, insp = who(client)
    _, sh = ship(client, qty=10)
    _, other = ship(client, qty=2)
    codes = unit_codes(client, insp, sh)

    def url(code, verb="receive"):
        return f"/api/shipments/{sh['id']}/units/{code}/{verb}"

    assert client.post(url(codes[0]), headers=sup).status_code == 403
    assert client.post(url(codes[0]), headers=insp).status_code == 200
    dup = client.post(url(codes[0]), headers=insp)
    assert dup.status_code == 400 and "already received" in dup.json()["detail"]
    assert client.post(url("NO-SUCH-CODE"), headers=insp).status_code == 404
    foreign = client.post(url(unit_codes(client, insp, other)[0]), headers=insp)
    assert foreign.status_code == 400 and other["shipment_no"] in foreign.json()["detail"]
    assert (
        client.post(url(codes[0].lower()), headers=insp).status_code == 400
    )  # codes are not case sensitive
    assert (
        client.post(url(codes[0], "unreceive"), headers=insp).json()["counts"]["Shipped"] == 10
    )  # a mis-scan can be undone
    for c in codes[:7]:
        client.post(url(c), headers=insp)
    assert tag(client, insp, sh, codes[0], "OK").status_code == 400  # not arrived yet

    arrived = client.post(f"/api/shipments/{sh['id']}/arrival", headers=insp, json={}).json()
    assert arrived["status"] == "Arrived" and arrived["items"][0]["quantity_received"] == 7
    assert arrived["unit_counts"] == {"Received": 7, "Missing": 3}
    assert any(
        "shortfall" in n["title"] for n in client.get("/api/notifications", headers=sup).json()
    )
    assert (
        client.post(url(codes[0]), headers=insp).status_code == 400
    )  # arrival is closed: a scanned unit cannot be scanned again
    # a unit that was missing at arrival can still be marked present (covered in test_a_missing_unit_can_be_marked_present...)


def test_unit_result_rules(client):
    _, sup, insp = who(client)
    _, sh = ship(client, qty=4)
    arrive(client, insp, sh, scan=unit_codes(client, insp, sh)[:3])
    ok, bad, untested, missing = unit_codes(client, insp, sh)

    assert tag(client, sup, sh, ok, "OK").status_code == 403
    r = tag(client, insp, sh, ok, "OK")
    assert (
        r.status_code == 200
        and r.json()["status"] == "OK"
        and all(c["passed"] for c in r.json()["checks"])
    )
    assert (
        tag(client, insp, sh, bad, "Faulty", defect_type="").status_code == 400
    )  # a defect type is required
    assert tag(client, insp, sh, bad, "Faulty", defect_type="nonsense").status_code == 400
    assert (
        tag(client, insp, sh, bad, "OK", checks={"packaging": False}).status_code == 400
    )  # OK needs every check to pass
    f = tag(
        client,
        insp,
        sh,
        bad,
        "Faulty",
        defect_type="packaging",
        checks={"packaging": False},
        notes="Crushed corner",
    ).json()
    assert (
        f["status"] == "Faulty"
        and f["defect_label"] == "Packaging damage"
        and f["notes"] == "Crushed corner"
    )
    assert [c["passed"] for c in f["checks"] if c["key"] == "packaging"] == [False]
    assert tag(client, insp, sh, missing, "OK").status_code == 400  # never arrived

    # a result can be corrected until the lot is decided, and every change is in the unit's history
    assert tag(client, insp, sh, bad, "OK").json()["status"] == "OK"
    actions = [h["action"] for h in client.get(f"/api/units/{bad}", headers=insp).json()["history"]]
    assert (
        actions.count("test") == 2 and "receive" in actions
    )  # Faulty, then corrected to OK; the refused attempt is not recorded
    assert (
        client.put(
            f"/api/shipments/{sh['id']}/units/{untested}", headers=insp, json={"result": "Maybe"}
        ).status_code
        == 422
    )


def test_bulk_and_csv(client):
    _, sup, insp = who(client)
    _, sh = ship(client, qty=10)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    for c in codes[:2]:
        tag(client, insp, sh, c, "Faulty", defect_type="functional")

    bulk = client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    ).json()
    assert bulk["updated"] == 8 and bulk["counts"] == {
        "OK": 8,
        "Faulty": 2,
    }  # the faulty ones are left alone
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/units/bulk", headers=insp, json={"action": "ok"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/units/bulk",
            headers=sup,
            json={"action": "ok", "all_pending": True},
        ).status_code
        == 403
    )

    csv_text = client.get(f"/api/shipments/{sh['id']}/units.csv", headers=insp).text
    lines = csv_text.strip().splitlines()
    assert len(lines) == 11 and lines[0].startswith(
        "code,item_code,status,result,defect_type,notes,packaging"
    )
    assert (
        client.get(f"/api/shipments/{sh['id']}/units.csv", headers=sup).status_code == 200
    )  # the supplier may download results

    def upload(text, headers=insp):
        return client.post(
            f"/api/shipments/{sh['id']}/units/import",
            headers=headers,
            files={"file": ("r.csv", text.encode(), "text/csv")},
        )

    # all or nothing: one bad row and nothing is saved
    bad = (
        "code,result,defect_type,notes\n"
        + f"{codes[2]},Faulty,cosmetic,scratch\n{codes[3]},Faulty,,no defect given\n{codes[4]},Perhaps,,\n"
    )
    r = upload(bad)
    assert (
        r.status_code == 400
        and "Nothing was imported" in r.json()["detail"]
        and "row 3" in r.json()["detail"]
        and "row 4" in r.json()["detail"]
    )
    assert client.get(f"/api/units/{codes[2]}", headers=insp).json()["status"] == "OK"
    good = (
        "code,result,defect_type,notes,packaging\n"
        + f"{codes[2]},Faulty,cosmetic,scratch,no\n{codes[3]},,,,\n{codes[5]},OK,,,yes\n"
    )
    done = upload(good).json()
    assert done["updated"] == 2 and done["counts"] == {"OK": 7, "Faulty": 3}
    assert client.get(f"/api/units/{codes[2]}", headers=insp).json()["notes"] == "scratch"
    assert upload("result\nOK\n").status_code == 400  # no code column
    assert upload(good, headers=sup).status_code == 403


def test_lookup_by_code_respects_visibility(client):
    buyer, sup, insp = who(client)
    admin = login(client, "admin@demo.com")
    other_sup, _ = _register_supplier(client, "other-units@x.com")
    stranger = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={
                "name": "B9",
                "email": "b9-units@x.com",
                "password": "longenough1",
                "role": "buyer",
            },
        ).json()["access_token"]
    }
    _, sh = ship(client, qty=3)
    arrive(client, insp, sh)
    code = unit_codes(client, insp, sh)[0]
    tag(client, insp, sh, code, "OK")

    assert client.get(f"/api/units/{code}", headers=admin).status_code == 403
    assert client.post("/api/units/scan", headers=admin, json={"code": code}).status_code == 403
    for headers in (insp, sup, buyer):
        r = client.get(
            f"/api/units/{code.lower()}", headers=headers
        )  # the code resolves in any letter case
        assert r.status_code == 200 and r.json()["shipment"]["shipment_no"] == sh["shipment_no"], (
            headers
        )
    assert client.get(f"/api/units/{code}", headers=other_sup).status_code == 404
    assert client.get(f"/api/units/{code}", headers=stranger).status_code == 404
    assert client.get("/api/units/UNKNOWN-0001", headers=insp).status_code == 404
    scanned = client.post("/api/units/scan", headers=insp, json={"code": f"  {code}  "}).json()
    assert (
        scanned["code"] == code
        and scanned["status"] == "OK"
        and scanned["tested_by"]
        and scanned["can_test"] is True
    )  # the lot is Arrived and not yet decided
    assert client.get(f"/api/shipments/{sh['id']}/units", headers=other_sup).status_code == 404
    assert client.get(f"/api/shipments/{sh['id']}/report", headers=stranger).status_code == 404


def test_report_suggestion_override_and_partial_approval(client):
    buyer, sup, insp = who(client)
    before = stock(client, buyer)
    po_id, sh = ship(client, qty=10)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)

    def decide(**body):
        return client.post(f"/api/shipments/{sh['id']}/inspection", headers=insp, json=body)

    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert (
        rep["ready"] is False
        and "10 received unit(s) still need a result" in rep["blockers"][0]
        and rep["suggestion"] is None
    )
    assert decide(decision="approve").status_code == 400  # untested units block the decision

    tag(client, insp, sh, codes[0], "Faulty", defect_type="functional", notes="Does not power on")
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    rep = client.get(
        f"/api/shipments/{sh['id']}/report", headers=sup
    ).json()  # the supplier sees the same report
    assert rep["totals"] == {
        "shipped": 10,
        "received": 10,
        "missing": 0,
        "tested": 10,
        "untested": 0,
        "ok": 9,
        "faulty": 1,
    }
    assert (
        rep["quality_accuracy"] == 90.0
        and rep["fulfilment_accuracy"] == 90.0
        and rep["threshold"] == 95
    )
    assert rep["suggestion"] == "reject" and rep["ready"] is True
    assert rep["defects"] == [
        {"defect_type": "functional", "label": "Functional failure", "count": 1}
    ]
    assert (
        rep["faulty_units"][0]["code"] == codes[0]
        and rep["faulty_units"][0]["notes"] == "Does not power on"
    )
    assert rep["per_item"] == [
        {"item_code": "ITEM002", "shipped": 10, "received": 10, "ok": 9, "faulty": 1, "missing": 0}
    ]

    # going against the suggestion needs a reason; the inspector may still approve the good units
    refused = decide(decision="approve")
    assert (
        refused.status_code == 400
        and "suggests reject" in refused.json()["detail"]
        and "override" in refused.json()["detail"]
    )
    approved = decide(
        decision="approve",
        override_reason="Customer accepts one dud",
        improvement="Test each unit before packing",
    ).json()
    assert (
        approved["status"] == "Approved"
        and approved["override_reason"] == "Customer accepts one dud"
    )
    assert stock(client, buyer) == before + 9  # only the OK units reached stock
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert (
        po["delivery_status"] == "In Transit"
        and po["invoice_hold"] == 1
        and "1 faulty unit" in po["invoice_hold_reason"]
    )
    assert any(
        "1 faulty unit(s) to replace" in n["title"]
        for n in client.get("/api/notifications", headers=sup).json()
    )
    assert any(
        "faulty" in n["message"].lower() and "Functional failure: 1" in n["message"]
        for n in client.get("/api/notifications", headers=buyer).json()
    )

    frozen = client.get(f"/api/shipments/{sh['id']}/report", headers=buyer).json()
    assert (
        frozen["frozen"] is True
        and frozen["decision"] == "approve"
        and frozen["override_reason"] == "Customer accepts one dud"
    )
    assert tag(client, insp, sh, codes[0], "OK").status_code == 400  # locked once decided
    assert client.get(f"/api/shipments/{sh['id']}/report", headers=sup).json() == frozen

    # the supplier replaces only the faulty unit; a second one would exceed the order
    def ship_again(n):
        return client.post(
            f"/api/purchase-orders/{po_id}/shipments",
            headers=sup,
            json={"items": [{"item_code": "ITEM002", "quantity": n}], "unit_inspection": True},
        )

    assert ship_again(2).status_code == 400
    replacement = ship_again(1)
    assert replacement.status_code == 201 and replacement.json()["shipment_no"] != sh["shipment_no"]
    r2 = replacement.json()
    arrive(client, insp, r2)
    tag(client, insp, r2, unit_codes(client, insp, r2)[0], "OK")
    final = client.post(
        f"/api/shipments/{r2['id']}/inspection", headers=insp, json={"decision": "approve"}
    ).json()  # 100% needs no override
    assert final["status"] == "Approved"
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert (
        po["delivery_status"] == "Delivered" and po["invoice_hold"] == 0
    )  # the hold lifts once the order is whole


def test_reject_a_failed_lot_and_missing_units_in_the_numbers(client):
    buyer, sup, insp = who(client)
    before = stock(client, buyer)
    po_id, sh = ship(client, qty=10)
    codes = unit_codes(client, insp, sh)
    arrive(client, insp, sh, scan=codes[:8])  # two units never arrived
    for c in codes[:3]:
        tag(client, insp, sh, c, "Faulty", defect_type="dimensional")
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert (
        rep["totals"]["missing"] == 2
        and rep["totals"]["received"] == 8
        and rep["totals"]["ok"] == 5
    )
    assert (
        rep["quality_accuracy"] == 62.5
        and rep["fulfilment_accuracy"] == 50.0
        and rep["suggestion"] == "reject"
    )

    def decide(**b):
        return client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "reject", **b}
        )

    assert decide(reason="Too many failures").status_code == 400  # no photo yet
    photo = client.post(
        f"/api/shipments/{sh['id']}/units/{codes[0]}/photo",
        headers=insp,
        files={"file": ("crack.jpg", b"\xff\xd8\xff photo", "image/jpeg")},
    )
    assert photo.status_code == 201
    assert [
        p["filename"] for p in client.get(f"/api/units/{codes[0]}", headers=insp).json()["photos"]
    ] == ["crack.jpg"]
    assert (
        client.get(f"/api/shipments/{sh['id']}", headers=insp).json()["photos"] == []
    )  # a unit photo is not a lot photo
    assert decide(reason="").status_code == 400
    done = decide(reason="Too many failures", improvement="Fix the tooling").json()
    assert done["status"] == "Rejected" and done["rejection_reason"] == "Too many failures"
    assert stock(client, buyer) == before  # nothing is released
    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["delivery_status"] == "Rejected" and po["invoice_hold"] == 1
    assert any(
        "62.5% accuracy" in n["title"] for n in client.get("/api/notifications", headers=sup).json()
    )
    assert (
        client.get(f"/api/shipments/{sh['id']}/report", headers=sup).json()["decision"] == "reject"
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "reject", "reason": "again"},
        ).status_code
        == 400
    )


def test_a_clean_lot_needs_no_override_and_old_lots_still_use_the_checklist(client):
    buyer, sup, insp = who(client)
    before = stock(client, buyer)
    po_id, sh = ship(client, qty=5)
    arrive(client, insp, sh)
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert rep["quality_accuracy"] == 100.0 and rep["suggestion"] == "approve"
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "approve"}
        ).json()["status"]
        == "Approved"
    )
    assert stock(client, buyer) == before + 5
    assert (
        client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["delivery_status"]
        == "Delivered"
    )

    # a shipment without QR codes keeps the lot-level checklist and has no unit report
    _, plain = ship(client, qty=3, units=False)
    assert (
        client.post(
            f"/api/shipments/{plain['id']}/arrival",
            headers=insp,
            json={"lines": [{"item_code": "ITEM002", "quantity_received": 3}]},
        ).status_code
        == 200
    )
    assert client.get(f"/api/shipments/{plain['id']}/report", headers=insp).status_code == 400
    checks = {"packaging": True, "specification": True, "condition": True, "documentation": True}
    assert (
        client.post(
            f"/api/shipments/{plain['id']}/inspection",
            headers=insp,
            json={"decision": "approve", "checks": checks},
        ).json()["status"]
        == "Approved"
    )


def test_qr_links_open_the_unit_and_only_a_signed_in_inspector_can_inspect(client, monkeypatch):
    buyer, sup, insp = who(client)
    _, sh = ship(client, qty=2)
    code = unit_codes(client, insp, sh)[0]

    # a label holds a link; whatever a scanner or phone hands over resolves to the same unit
    for text in (
        f"https://erp.example.com/units/{code}",
        f"http://192.168.1.44:3000/units/{code.lower()}?utm=x#top",
        f"/units/{code}/",
        f"  {code}  ",
    ):
        r = client.post("/api/units/scan", headers=insp, json={"code": text})
        assert r.status_code == 200 and r.json()["code"] == code, text
    assert (
        client.post(
            "/api/units/scan",
            headers=insp,
            json={"code": "https://erp.example.com/units/NOPE-0001"},
        ).status_code
        == 404
    )

    monkeypatch.setattr(settings, "public_app_url", "https://erp.example.com")
    assert (
        client.get(f"/api/shipments/{sh['id']}/labels", headers=sup).json()["base_url"]
        == "https://erp.example.com"
    )

    # nothing is public: no login, no unit
    assert client.get(f"/api/units/{code}").status_code == 401
    assert client.post("/api/units/scan", json={"code": code}).status_code == 401

    # before arrival the inspector can receive from the unit page; supplier and buyer can read but never act
    assert client.get(f"/api/units/{code}", headers=insp).json()["can_receive"] is True
    for headers in (sup, buyer):
        view = client.get(f"/api/units/{code}", headers=headers).json()
        assert view["can_receive"] is False and view["can_test"] is False
        assert (
            client.post(
                f"/api/shipments/{sh['id']}/units/{code}/receive", headers=headers
            ).status_code
            == 403
        )
    arrive(client, insp, sh)
    for headers in (sup, buyer):
        assert client.get(f"/api/units/{code}", headers=headers).json()["can_test"] is False
        assert tag(client, headers, sh, code, "OK").status_code == 403
    assert client.get(f"/api/units/{code}", headers=insp).json()["can_test"] is True


def test_public_app_url_is_cleaned_up():
    from app.config import _public_url

    assert _public_url("") == ""
    assert _public_url("https://erp.example.com/") == "https://erp.example.com"
    assert _public_url("erp.example.com") == "https://erp.example.com"
    assert _public_url("192.168.1.44:3000") == "http://192.168.1.44:3000"
    assert _public_url(" http://192.168.1.44:3000/ ") == "http://192.168.1.44:3000"
    assert _public_url("localhost:3000") == "http://localhost:3000"


def test_a_missing_unit_can_be_marked_present_until_the_lot_is_decided(client):
    buyer, sup, insp = who(client)
    po_id, sh = ship(client, qty=4)
    codes = unit_codes(client, insp, sh)
    arrive(client, insp, sh, scan=codes[:3])  # the fourth was not scanned: missing

    def unit():
        return client.get(f"/api/units/{codes[3]}", headers=insp).json()

    assert (
        unit()["status"] == "Missing"
        and unit()["can_receive"] is True
        and unit()["can_test"] is False
    )
    assert (
        client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["items"][0][
            "quantity_received"
        ]
        == 3
    )

    def receive(code, headers=insp):
        return client.post(f"/api/shipments/{sh['id']}/units/{code}/receive", headers=headers)

    assert receive(codes[0]).status_code == 400  # a unit that was scanned cannot be received twice
    assert receive(codes[3], sup).status_code == 403 and receive(codes[3], buyer).status_code == 403
    done = receive(codes[3])
    assert done.status_code == 200 and done.json()["unit"]["status"] == "Received"
    assert unit()["status"] == "Received" and unit()["can_test"] is True
    assert (
        client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["items"][0][
            "quantity_received"
        ]
        == 4
    )  # the count follows
    assert any(
        "was found" in n["title"] for n in client.get("/api/notifications", headers=sup).json()
    )

    assert (
        tag(client, insp, sh, codes[3], "OK").status_code == 200
    )  # and it can now be tested like the others
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert (
        rep["totals"]["missing"] == 0
        and rep["totals"]["received"] == 4
        and rep["fulfilment_accuracy"] == 100.0
    )

    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "approve"}
        ).status_code
        == 200
    )
    # once the lot is decided nothing can be received any more
    _, sh2 = ship(client, qty=2)
    codes2 = unit_codes(client, insp, sh2)
    arrive(client, insp, sh2, scan=codes2[:1])
    client.post(
        f"/api/shipments/{sh2['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    client.post(
        f"/api/shipments/{sh2['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "override_reason": "Half is fine"},
    )
    late = client.post(f"/api/shipments/{sh2['id']}/units/{codes2[1]}/receive", headers=insp)
    assert late.status_code == 400 and "decided" in late.json()["detail"]
    assert client.get(f"/api/units/{codes2[1]}", headers=insp).json()["can_receive"] is False
