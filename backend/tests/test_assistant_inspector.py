# isort: off
from tests.test_api import (
    _approved_po,
    login,
    ship,
    arrive,
)  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def who(client):
    return {
        "buyer": login(client, "buyer@demo.com"),
        "sup": login(client, "supplier@demo.com"),
        "insp": login(client, "inspector@demo.com"),
    }


def turn(client, headers, state=None, text=None, tz=0):
    r = client.post(
        "/api/assistant/step",
        headers=headers,
        json={"state": state, "input": text, "tz_offset": tz},
    )
    assert r.status_code == 200, r.text
    return r.json()


def say(client, headers, resp, *inputs):
    for t in inputs:
        resp = turn(client, headers, resp["state"], t)
    return resp


def pick(resp, text):
    """Key of the option whose label contains `text`."""
    return next(o["key"] for o in resp["options"] if text.lower() in o["label"].lower())


def start(client, headers, title):
    """Open the flow whose menu title contains `title`."""
    menu = turn(client, headers)
    return turn(client, headers, None, pick(menu, title))


def new_shipment(client, who, qty=10, **kw):
    _, po_id = _approved_po(client, who["buyer"], who["sup"], qty=qty)
    return ship(client, po_id, who["sup"], **kw)


def stock(client, headers, code="ITEM002"):
    items = client.get("/api/inventory", headers=headers).json()
    return next(i["stock_quantity"] for i in items if i["item_code"] == code)


def test_inspector_menu_and_boundaries(client, who):
    r = client.get("/api/assistant/menu", headers=who["insp"]).json()
    assert [o["label"] for o in r["options"]] == [
        "Confirm a delivery arrived",
        "Verify and approve a delivery",
        "Latest requirements",
        "Check shipments",
        "Check stock",
    ]
    assert r["ai"] is False  # inspectors have no forms to fill in natural language

    def enter(headers, flow):
        return client.post(
            "/api/assistant/step",
            headers=headers,
            json={"state": {"flow": flow, "values": {}, "page": 0, "filter": ""}, "input": "1"},
        ).status_code

    inspector_flows = (
        "confirm_arrival",
        "approve_delivery",
        "latest_requirements",
        "check_shipments",
        "check_stock",
    )
    for flow in inspector_flows:
        assert enter(who["buyer"], flow) == 403
        assert enter(who["sup"], flow) == 403
    for flow in ("new_requirement", "award_supplier", "approve_po", "submit_quote", "ship_order"):
        assert enter(who["insp"], flow) == 403
    # other roles keep their own menus
    sup_menu = client.get("/api/assistant/menu", headers=who["sup"]).json()["options"]
    assert [o["label"] for o in sup_menu] == ["Submit a quote", "Ship an order"]


def test_confirm_arrival_records_what_was_counted(client, who):
    sh = new_shipment(client, who, qty=10)
    insp = who["insp"]
    r = start(client, insp, "Confirm a delivery arrived")
    assert r["step"] == "shipment"
    r = say(client, insp, r, pick(r, sh["shipment_no"]))
    assert r["step"] == "recv:ITEM002" and "10 were shipped" in r["message"]
    r = say(client, insp, r, "8", "#")  # counted 8, no notes
    assert r["stage"] == "summary"
    assert ("Received ITEM002", "8") in [(s["label"], s["value"]) for s in r["summary"]]
    r = say(client, insp, r, "#")
    assert r["stage"] == "menu" and "shortfall" in r["result"]["label"]
    assert r["result"]["href"] == f"/shipments/{sh['id']}"

    got = client.get(f"/api/shipments/{sh['id']}", headers=insp).json()
    assert got["status"] == "Arrived"
    assert got["items"][0]["quantity_received"] == 8
    # it is no longer waiting to arrive
    again = start(client, insp, "Confirm a delivery arrived")
    assert all(sh["shipment_no"] not in o["label"] for o in again.get("options", []))


def test_arrival_skips_qr_unit_shipments(client, who):
    _, po_id = _approved_po(client, who["buyer"], who["sup"], qty=4)
    r = client.post(
        f"/api/purchase-orders/{po_id}/shipments",
        headers=who["sup"],
        json={"items": [{"item_code": "ITEM002", "quantity": 4}], "unit_inspection": True},
    )
    assert r.status_code == 201, r.text
    unit_shipment = r.json()["shipment_no"]
    resp = start(client, who["insp"], "Confirm a delivery arrived")
    labels = [o["label"] for o in resp.get("options", [])]
    assert all(unit_shipment not in label for label in labels)


def test_approve_delivery_needs_every_check_to_pass(client, who):
    sh = arrive(client, new_shipment(client, who, qty=10), who["insp"])
    insp = who["insp"]
    before = stock(client, insp)

    # one check answered "No": the summary refuses, nothing changes
    r = start(client, insp, "Verify and approve")
    r = say(client, insp, r, pick(r, sh["shipment_no"]))
    assert r["step"].startswith("check:")
    r = say(client, insp, r, "1", "1", "2", "1", "#")  # condition = No
    assert r["stage"] == "summary" and r["warning"]
    r = say(client, insp, r, "#")
    assert r["stage"] == "summary" and "every check passes" in r["error"]
    assert client.get(f"/api/shipments/{sh['id']}", headers=insp).json()["status"] == "Arrived"
    assert stock(client, insp) == before

    # all "Yes": approved, stock released
    r = start(client, insp, "Verify and approve")
    r = say(client, insp, r, pick(r, sh["shipment_no"]), "1", "1", "1", "1", "#")
    r = say(client, insp, r, "#")
    assert r["stage"] == "menu" and "approved" in r["result"]["label"]
    got = client.get(f"/api/shipments/{sh['id']}", headers=insp).json()
    assert got["status"] == "Approved"
    assert stock(client, insp) == before + 10


def test_cannot_approve_a_delivery_that_has_not_arrived(client, who):
    sh = new_shipment(client, who, qty=5)  # still "Shipped"
    insp = who["insp"]
    # a crafted state that skips the menu: the shipment is not among the offered options, so it is rejected
    full = {
        "flow": "approve_delivery",
        "page": 0,
        "filter": "",
        "values": {
            "shipment": sh["id"],
            "check:packaging": "yes",
            "check:specification": "yes",
            "check:condition": "yes",
            "check:documentation": "yes",
            "notes": None,
        },
    }
    r = client.post("/api/assistant/step", headers=insp, json={"state": full, "input": "#"})
    assert r.status_code == 400
    assert client.get(f"/api/shipments/{sh['id']}", headers=insp).json()["status"] == "Shipped"


def test_latest_requirements_lists_the_newest_five(client, who):
    made = []
    for i in range(6):
        r = client.post(
            "/api/requirements",
            headers=who["buyer"],
            json={"title": f"Latest probe {i}", "quantity": 1, "open_to_all": True, "erp": "sap"},
        )
        assert r.status_code == 201, r.text
        made.append(r.json())
    insp = who["insp"]
    r = start(client, insp, "Latest requirements")
    assert r["step"] == "requirement" and len(r["options"]) == 5
    assert [made[5]["req_number"], made[1]["req_number"]] == [
        r["options"][0]["label"].split(" - ")[0],
        r["options"][4]["label"].split(" - ")[0],
    ]  # newest first, and the oldest of my six is cut off
    assert all(made[0]["req_number"] not in o["label"] for o in r["options"])
    # picking one answers straight away: no summary to confirm
    r = say(client, insp, r, "1")
    assert r["stage"] == "menu"
    assert r["result"]["href"] == f"/requirements/{made[5]['id']}"
    assert made[5]["req_number"] in r["result"]["label"]


def test_check_shipments_by_group(client, who):
    sh = new_shipment(client, who, qty=3, tracking="TRKCHK")
    insp = who["insp"]
    r = start(client, insp, "Check shipments")
    assert r["step"] == "filter" and len(r["options"]) == 5
    r = say(client, insp, r, pick(r, "Incoming"))
    assert r["step"] == "shipment"
    assert sh["shipment_no"] in r["options"][0]["label"]  # newest first
    r = say(client, insp, r, "1")
    assert r["stage"] == "menu" and "TRKCHK" in r["result"]["label"]
    assert r["result"]["href"] == f"/shipments/{sh['id']}"

    # a group with nothing in it says so instead of showing an empty list
    r = start(client, insp, "Check shipments")
    r = say(client, insp, r, pick(r, "Overdue"))
    assert r["stage"] == "menu" and "no shipments" in r["message"].lower()

    # once it has arrived it moves to the inspection group
    arrive(client, sh, insp)
    r = start(client, insp, "Check shipments")
    r = say(client, insp, r, pick(r, "waiting for inspection"))
    assert sh["shipment_no"] in r["options"][0]["label"]


def test_check_stock_searches_items(client, who):
    insp = who["insp"]
    r = start(client, insp, "Check stock")
    assert r["step"] == "item" and any("ITEM002" in o["label"] for o in r["options"])
    r = turn(client, insp, r["state"], "steel")  # typing narrows the list
    assert r["stage"] == "step" and r["options"]
    assert all("steel" in o["label"].lower() for o in r["options"])
    r = say(client, insp, r, "1")
    assert r["stage"] == "menu" and "in stock" in r["result"]["label"]
    assert r["result"]["href"] == "/inventory"
