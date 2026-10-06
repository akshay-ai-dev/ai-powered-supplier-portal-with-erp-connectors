# isort: off
from tests.test_api import _approved_po, _register_supplier  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from tests.test_units import arrive, ship, stock, tag, unit_codes, who
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def to_ship(client, headers, po_id):
    r = client.get(f"/api/purchase-orders/{po_id}/to-ship", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def inspected_with_one_faulty(client, qty=10):
    """A unit-level lot of `qty` where the first unit is faulty and the lot is approved anyway."""
    buyer, sup, insp = who(client)
    po_id, sh = ship(client, qty=qty)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    tag(client, insp, sh, codes[0], "Faulty", defect_type="functional", notes="Does not power on")
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    done = client.post(
        f"/api/shipments/{sh['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "override_reason": "One dud is fine"},
    )
    assert done.status_code == 200, done.text
    return po_id, sh, codes


def replace(client, sup, po_id, sh, qty=1, item="ITEM002", **extra):
    return client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={
            "items": [{"item_code": item, "quantity": qty}],
            "unit_inspection": True,
            "replaces_shipment_id": sh["id"],
            **extra,
        },
    )


def test_the_ship_step_lists_the_faulty_units_to_replace(client):
    buyer, sup, insp = who(client)
    po_id, sh, codes = inspected_with_one_faulty(client)

    info = to_ship(client, sup, po_id)
    assert info["progress"] == [
        {"item_code": "ITEM002", "ordered": 10, "accepted": 9, "on_the_way": 0, "left": 1}
    ]
    (entry,) = info["replace"]
    assert (
        entry["shipment_id"] == sh["id"]
        and entry["shipment_no"] == sh["shipment_no"]
        and entry["status"] == "Approved"
    )
    assert entry["items"] == [
        {"item_code": "ITEM002", "short": 1, "replaced": 0, "on_the_way": 0, "outstanding": 1}
    ]
    assert entry["units"] == [
        {
            "code": codes[0],
            "item_code": "ITEM002",
            "status": "Faulty",
            "defect_label": "Functional failure",
            "notes": "Does not power on",
        }
    ]

    # the buyer and the inspector see the same read-only picture; an outsider gets nothing
    for who_ in (buyer, insp):
        assert to_ship(client, who_, po_id)["replace"][0]["shipment_no"] == sh["shipment_no"]
    outsider, _ = _register_supplier(client, "to-ship-outsider@x.com")
    assert client.get(f"/api/purchase-orders/{po_id}/to-ship", headers=outsider).status_code == 404
    assert client.get(f"/api/purchase-orders/{po_id}/to-ship").status_code == 401

    # the shipment itself says what it still owes
    assert client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["owed"] == [
        {"item_code": "ITEM002", "quantity": 1}
    ]


def test_a_replacement_shipment_links_back_and_both_reports_show_the_pair(client):
    buyer, sup, insp = who(client)
    po_id, sh, codes = inspected_with_one_faulty(client)

    assert replace(client, sup, po_id, sh, qty=2).status_code == 400  # only one unit is owed
    wrong_item = replace(client, sup, po_id, sh, item="ITEM003")
    assert wrong_item.status_code == 400
    r = replace(client, sup, po_id, sh, qty=1)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert (
        rep["replaces_shipment_id"] == sh["id"] and rep["replaces_shipment_no"] == sh["shipment_no"]
    )
    assert rep["items"][0]["quantity_shipped"] == 1 and rep["unit_level"] is True

    # the original now points forward, and nothing is owed twice
    orig = client.get(f"/api/shipments/{sh['id']}", headers=sup).json()
    assert (
        orig["replaced_by"]
        == [{"id": rep["id"], "shipment_no": rep["shipment_no"], "status": "Shipped"}]
        and orig["owed"] == []
    )
    info = to_ship(client, sup, po_id)
    assert (
        info["replace"] == []
        and info["progress"][0]["on_the_way"] == 1
        and info["progress"][0]["left"] == 0
    )
    assert (
        replace(client, sup, po_id, sh).status_code == 400
    )  # already covered by the one on the way

    # the notification names the shipment it replaces
    assert any(
        sh["shipment_no"] in n["message"] and "replaces" in n["message"]
        for n in client.get("/api/notifications", headers=insp).json()
    )
    assert any(
        sh["shipment_no"] in n["message"]
        for n in client.get("/api/notifications", headers=buyer).json()
    )

    # both reports show the pair, live
    arrive(client, insp, rep)
    tag(client, insp, rep, unit_codes(client, insp, rep)[0], "OK")
    before = stock(client, buyer)
    assert (
        client.post(
            f"/api/shipments/{rep['id']}/inspection", headers=insp, json={"decision": "approve"}
        ).json()["status"]
        == "Approved"
    )
    assert stock(client, buyer) == before + 1

    for headers in (sup, buyer, insp):
        original_report = client.get(f"/api/shipments/{sh['id']}/report", headers=headers).json()
        assert (
            original_report["frozen"] is True and original_report["totals"]["faulty"] == 1
        )  # the frozen numbers never change
        assert original_report["replacement"]["replaces"] is None
        (back,) = original_report["replacement"]["replaced_by"]
        assert (
            back["shipment_no"] == rep["shipment_no"]
            and back["status"] == "Approved"
            and back["shipped"] == 1
            and back["accepted"] == 1
            and back["quality_accuracy"] == 100.0
        )
        assert original_report["replacement"]["owed"] == [
            {"item_code": "ITEM002", "short": 1, "replaced": 1, "on_the_way": 0, "outstanding": 0}
        ]

        replacement_report = client.get(
            f"/api/shipments/{rep['id']}/report", headers=headers
        ).json()
        replaces = replacement_report["replacement"]["replaces"]
        assert replaces["shipment_no"] == sh["shipment_no"] and replaces["status"] == "Approved"
        assert [u["code"] for u in replaces["units"]] == [codes[0]] and replaces["units"][0][
            "defect_label"
        ] == "Functional failure"
        assert replacement_report["replacement"]["replaced_by"] == []

    po = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()
    assert po["delivery_status"] == "Delivered" and po["invoice_hold"] == 0
    assert to_ship(client, buyer, po_id)["progress"][0]["accepted"] == 10


def test_a_rejected_replacement_puts_the_units_back_on_the_list(client):
    buyer, sup, insp = who(client)
    po_id, sh, _ = inspected_with_one_faulty(client)
    first = replace(client, sup, po_id, sh).json()
    arrive(client, insp, first)
    code = unit_codes(client, insp, first)[0]
    tag(client, insp, first, code, "Faulty", defect_type="cosmetic")
    client.post(
        f"/api/shipments/{first['id']}/units/{code}/photo",
        headers=insp,
        files={"file": ("dent.jpg", b"\xff\xd8\xff photo", "image/jpeg")},
    )
    rejected = client.post(
        f"/api/shipments/{first['id']}/inspection",
        headers=insp,
        json={"decision": "reject", "reason": "Still faulty"},
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "Rejected"

    # the rejected replacement now carries what the original owed, so the list shows one entry, not two
    info = to_ship(client, sup, po_id)
    assert [e["shipment_no"] for e in info["replace"]] == [first["shipment_no"]]
    assert (
        info["replace"][0]["items"]
        == [{"item_code": "ITEM002", "short": 1, "replaced": 0, "on_the_way": 0, "outstanding": 1}]
        and info["replace"][0]["units"] == []
    )
    assert client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["owed"] == [
        {"item_code": "ITEM002", "quantity": 1}
    ]  # the original owes it again

    second = replace(client, sup, po_id, first)
    assert (
        second.status_code == 201 and second.json()["replaces_shipment_no"] == first["shipment_no"]
    )
    arrive(client, insp, second.json())
    tag(client, insp, second.json(), unit_codes(client, insp, second.json())[0], "OK")
    assert (
        client.post(
            f"/api/shipments/{second.json()['id']}/inspection",
            headers=insp,
            json={"decision": "approve"},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["delivery_status"]
        == "Delivered"
    )
    assert to_ship(client, sup, po_id)["replace"] == []


def test_a_whole_rejected_lot_is_replaced_in_full(client):
    buyer, sup, insp = who(client)
    po_id, sh = ship(client, qty=4)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    for c in codes[:2]:
        tag(client, insp, sh, c, "Faulty", defect_type="dimensional")
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    client.post(
        f"/api/shipments/{sh['id']}/units/{codes[0]}/photo",
        headers=insp,
        files={"file": ("a.jpg", b"\xff\xd8\xff x", "image/jpeg")},
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "reject", "reason": "Half are wrong"},
        ).status_code
        == 200
    )

    (entry,) = to_ship(client, sup, po_id)["replace"]
    assert entry["status"] == "Rejected" and entry["items"][0]["outstanding"] == 4
    assert replace(client, sup, po_id, sh, qty=5).status_code == 400
    assert replace(client, sup, po_id, sh, qty=4).status_code == 201


def test_the_link_must_point_at_an_inspected_shipment_on_the_same_order(client):
    buyer, sup, insp = who(client)
    po_id, sh, _ = inspected_with_one_faulty(client)
    other_po, other_sh = ship(client, qty=3)

    assert (
        replace(client, sup, po_id, {"id": other_sh["id"]}).status_code == 400
    )  # a shipment on another order
    assert replace(client, sup, po_id, {"id": 999999}).status_code == 400
    in_flight = replace(client, sup, other_po, other_sh, qty=1)
    assert (
        in_flight.status_code == 400 and "not been inspected" in in_flight.json()["detail"]
    )  # nothing to replace before it is inspected
    # a shipment that lost nothing has nothing to replace
    arrive(client, insp, other_sh)
    client.post(
        f"/api/shipments/{other_sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    assert (
        client.post(
            f"/api/shipments/{other_sh['id']}/inspection",
            headers=insp,
            json={"decision": "approve"},
        ).status_code
        == 200
    )
    clean = replace(client, sup, other_po, other_sh, qty=1)
    assert clean.status_code == 400
    # linking is optional: the same short quantity can still be shipped without it
    plain = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM002", "quantity": 1}], "unit_inspection": True},
    )
    assert (
        plain.status_code == 201
        and plain.json()["replaces_shipment_id"] is None
        and plain.json()["replaced_by"] == []
    )
    # only the supplier ships
    assert (
        client.post(
            f"/api/purchase-orders/{po_id}/shipments",
            headers=buyer,
            json={
                "items": [{"item_code": "ITEM002", "quantity": 1}],
                "replaces_shipment_id": sh["id"],
            },
        ).status_code
        == 403
    )


def test_a_lot_level_shipment_that_arrived_short_can_be_topped_up_with_a_link(client):
    buyer, sup, insp = who(client)
    _, po_id = _approved_po(client, buyer, sup, qty=10)
    sh = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM002", "quantity": 10}]},
    ).json()
    assert sh["unit_level"] is False
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/arrival",
            headers=insp,
            json={"lines": [{"item_code": "ITEM002", "quantity_received": 7}]},
        ).status_code
        == 200
    )
    ok = {"packaging": True, "specification": True, "condition": True, "documentation": True}
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection",
            headers=insp,
            json={"decision": "approve", "checks": ok},
        ).status_code
        == 200
    )

    (entry,) = to_ship(client, sup, po_id)["replace"]
    assert entry["items"][0]["outstanding"] == 3 and entry["units"] == []
    top_up = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM002", "quantity": 3}], "replaces_shipment_id": sh["id"]},
    )
    assert top_up.status_code == 201 and top_up.json()["replaces_shipment_no"] == sh["shipment_no"]
    assert (
        client.get(f"/api/shipments/{sh['id']}", headers=sup).json()["replaced_by"][0][
            "shipment_no"
        ]
        == top_up.json()["shipment_no"]
    )
