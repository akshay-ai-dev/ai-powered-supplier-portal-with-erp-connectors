# isort: off
from tests.test_api import (
    _approved_po,
    _in,
    _register_supplier,
    _set_deadline_in_db,
    login,
)  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


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


def start(client, headers, number):
    return turn(client, headers, None, str(number))


def pick(resp, text):
    """Key of the option whose label contains `text`."""
    return next(o["key"] for o in resp["options"] if text.lower() in o["label"].lower())


def history(client, headers, req_id):
    return client.get(f"/api/requirements/{req_id}", headers=headers).json()["history"]


def test_menu_depends_on_the_role(client):
    def labels(email):
        r = client.get("/api/assistant/menu", headers=login(client, email))
        return [o["label"] for o in r.json()["options"]]

    buyer_menu = ["New requirement", "Award a supplier", "Approve a purchase order"]
    assert labels("buyer@demo.com") == buyer_menu
    assert labels("admin@demo.com") == buyer_menu
    assert labels("supplier@demo.com") == ["Submit a quote", "Ship an order"]
    assert labels("inspector@demo.com") == [
        "Confirm a delivery arrived",
        "Verify and approve a delivery",
        "Latest requirements",
        "Check shipments",
        "Check stock",
    ]
    assert client.get("/api/assistant/menu").status_code == 401

    # a role cannot enter a flow that is not in its menu, even by crafting the state
    buyer = login(client, "buyer@demo.com")
    r = client.post(
        "/api/assistant/step",
        headers=buyer,
        json={"state": {"flow": "submit_quote", "values": {}}, "input": "1"},
    )
    assert r.status_code == 403
    sup = login(client, "supplier@demo.com")
    assert (
        client.post(
            "/api/assistant/step",
            headers=sup,
            json={"state": {"flow": "new_requirement", "values": {}}, "input": "1"},
        ).status_code
        == 403
    )
    for flow in ("award_supplier", "approve_po"):
        assert (
            client.post(
                "/api/assistant/step",
                headers=sup,
                json={"state": {"flow": flow, "values": {}}, "input": "1"},
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/api/assistant/step",
            headers=buyer,
            json={"state": {"flow": "nope", "values": {}}, "input": "1"},
        ).status_code
        == 400
    )


def test_new_requirement_conversation_creates_the_same_record_as_the_form(client):
    buyer = login(client, "buyer@demo.com")
    before = len(client.get("/api/requirements", headers=buyer).json())

    r = start(client, buyer, 1)
    assert r["kind"] == "choice" and r["step"] == "item" and r["options"][0]["key"] == "1"
    r = turn(client, buyer, r["state"], "1")  # something else: describe it
    assert r["step"] == "title"
    r = turn(client, buyer, r["state"], "Assistant widgets")
    assert r["step"] == "quantity"

    # bad answers re-ask the same question without losing progress
    for bad in ("abc", "0", "-3", "2.5"):
        r = turn(client, buyer, r["state"], bad)
        assert r["step"] == "quantity" and r["error"], bad
    r = turn(client, buyer, r["state"], "25")
    assert r["step"] == "target_price" and r["controls"]["skip"]

    # "back" returns to the previous question; "cancel" leaves without saving
    r = turn(client, buyer, r["state"], "back")
    assert r["step"] == "quantity"
    r = turn(client, buyer, r["state"], "25")
    r = say(client, buyer, r, "#", "#")  # skip price and date
    assert r["step"] == "erp"
    r = turn(client, buyer, r["state"], "1")  # SAP
    assert r["step"] == "audience"
    r = turn(client, buyer, r["state"], "1")  # open to all
    assert r["step"] == "deadline"
    assert [o["label"] for o in r["options"]][:2] == ["In 7 days", "In 3 days"]
    r = turn(client, buyer, r["state"], "1")
    assert r["step"] == "description"
    r = turn(client, buyer, r["state"], "#")
    assert r["stage"] == "summary" and r["controls"]["confirm"]
    shown = {s["label"]: s["value"] for s in r["summary"]}
    assert (
        shown["What you need"] == "Assistant widgets"
        and shown["Quantity"] == "25"
        and shown["ERP"] == "SAP"
    )

    # nothing is saved until the user confirms
    assert len(client.get("/api/requirements", headers=buyer).json()) == before
    done = turn(client, buyer, r["state"], "#")
    assert done["stage"] == "menu" and done["result"]["label"].endswith("created")
    req_id = int(done["result"]["href"].rsplit("/", 1)[1])

    req = client.get(f"/api/requirements/{req_id}", headers=buyer).json()
    assert (req["title"], req["quantity"], req["erp"], req["open_to_all"]) == (
        "Assistant widgets",
        25,
        "sap",
        1,
    )
    assert req["quote_deadline"] is not None and req["target_price"] is None
    created = next(h for h in history(client, buyer, req_id) if h["action"] == "create")
    assert created["channel"] == "assistant"

    # cancel at any point leaves nothing behind
    r = say(client, buyer, start(client, buyer, 1), "1", "Will be cancelled", "5")
    r = turn(client, buyer, r["state"], "*")
    assert r["stage"] == "menu" and r["state"] is None
    assert len(client.get("/api/requirements", headers=buyer).json()) == before + 1


def test_requirement_from_inventory_item_choose_suppliers_and_custom_deadline(client):
    buyer = login(client, "buyer@demo.com")
    r = start(client, buyer, 1)
    r = turn(client, buyer, r["state"], "ITEM002")  # typing narrows the list
    assert r["filter"] == "ITEM002" and all("ITEM002" in o["label"] for o in r["options"])
    r = turn(client, buyer, r["state"], pick(r, "ITEM002"))
    assert r["step"] == "quantity"  # no title question: the item's description is used
    r = say(client, buyer, r, "4", "9.5", "2031-01-31", "2")  # qty, target price, needed by, Infor
    assert r["step"] == "audience"
    r = turn(client, buyer, r["state"], "3")  # choose suppliers
    assert r["step"] == "suppliers" and r["kind"] == "multichoice"
    first = r["options"][0]["label"]
    r = turn(client, buyer, r["state"], "1")
    assert r["step"] == "deadline"
    r = turn(client, buyer, r["state"], "3")  # custom
    assert r["step"] == "deadline_at"
    assert turn(client, buyer, r["state"], "2020-01-01 10:00")["error"]
    r = turn(
        client, buyer, r["state"], "2099-01-01 10:00", tz=120
    )  # local time is UTC-2... offset 120 min west
    assert r["step"] == "description"
    r = turn(client, buyer, r["state"], "Need it fast", tz=120)
    shown = {s["label"]: s["value"] for s in r["summary"]}
    assert shown["Invited suppliers"] == first and shown["Deadline at"].startswith(
        "2099-01-01 10:00"
    )
    done = turn(client, buyer, r["state"], "#")
    req = client.get(
        f"/api/requirements/{done['result']['href'].rsplit('/', 1)[1]}", headers=buyer
    ).json()
    assert (
        req["item_code"] == "ITEM002"
        and req["erp"] == "infor"
        and req["description"] == "Need it fast"
    )
    assert (
        req["quote_deadline"].startswith("2099-01-01T12:00:00")
        and not req["open_to_all"]
        and len(req["invites"]) == 1
    )
    assert req["target_price"] == 9.5 and req["needed_by"] == "2031-01-31"


def test_long_lists_page_with_9(client):
    buyer = login(client, "buyer@demo.com")
    for i in range(10):
        client.post(
            "/api/inventory",
            headers=buyer,
            json={
                "item_code": f"PAGE{i:02d}",
                "description": f"Paging item {i}",
                "stock_quantity": 1,
            },
        )
    r = start(client, buyer, 1)
    assert len(r["options"]) == 8 and r["controls"]["more"]
    first_page = [o["label"] for o in r["options"]]
    r2 = turn(client, buyer, r["state"], "9")
    assert [o["label"] for o in r2["options"]] != first_page and r2["state"]["page"] == 1
    chosen = turn(client, buyer, r2["state"], "7")  # a number on page 2 picks that option
    assert chosen["error"] is None and chosen["step"] in ("title", "quantity")
    nothing = turn(client, buyer, r["state"], "zzzz-no-match")
    assert nothing["error"] and nothing["filter"] == ""


def test_submit_quote_conversation_and_visibility(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    other, other_id = _register_supplier(client, "other-assistant@x.com")
    mine = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Assistant quote me", "quantity": 7, "open_to_all": True},
    ).json()
    only_other = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Assistant other only", "quantity": 2, "supplier_ids": [other_id]},
    ).json()
    closed = client.post(
        "/api/requirements",
        headers=buyer,
        json={
            "title": "Assistant closed",
            "quantity": 2,
            "open_to_all": True,
            "quote_deadline": _in(48),
        },
    ).json()
    _set_deadline_in_db(closed["id"], _in(-1))

    r = start(client, sup, 1)
    assert r["step"] == "requirement"
    labels = [o["label"] for o in r["options"]]
    assert any(f"REQ{2000 + mine['id']}" in lb for lb in labels)
    assert not any(f"REQ{2000 + only_other['id']}" in lb for lb in labels)  # not invited
    assert not any(f"REQ{2000 + closed['id']}" in lb for lb in labels)  # deadline passed
    other_labels = [o["label"] for o in start(client, other, 1)["options"]]
    assert any(f"REQ{2000 + only_other['id']}" in lb for lb in other_labels)

    r = turn(client, sup, r["state"], f"REQ{2000 + mine['id']}")
    r = turn(client, sup, r["state"], "1")
    assert r["step"] == "unit_price"
    assert turn(client, sup, r["state"], "-1")["error"]
    r = say(client, sup, r, "12.5", "3", "Can deliver in 3 days")
    assert r["stage"] == "summary"
    done = turn(client, sup, r["state"], "#")
    assert done["result"]["label"].startswith("Quote sent")

    quote = client.get(f"/api/requirements/{mine['id']}", headers=buyer).json()["quotes"][0]
    assert (quote["unit_price"], quote["lead_time_days"], quote["message"]) == (
        12.5,
        3,
        "Can deliver in 3 days",
    )
    assert (
        next(h for h in history(client, buyer, mine["id"]) if h["action"] == "quote")["channel"]
        == "assistant"
    )

    # a state edited by hand cannot reach a requirement the supplier was never offered
    sneaky = {
        "flow": "submit_quote",
        "values": {
            "requirement": only_other["id"],
            "unit_price": 1,
            "lead_time_days": 1,
            "message": None,
        },
    }
    r = client.post("/api/assistant/step", headers=sup, json={"state": sneaky, "input": "#"})
    assert r.status_code == 400 and "out of date" in r.json()["detail"]


def test_ship_order_conversation(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    req, po_id = _approved_po(client, buyer, sup, item="ITEM002", qty=10)
    po_number = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["po_number"]

    r = start(client, sup, 2)
    assert r["step"] == "po"
    r = turn(client, sup, r["state"], po_number)
    r = turn(client, sup, r["state"], "1")
    assert r["step"] == "qty:ITEM002" and r["controls"]["skip"] and "10 still" in r["message"]
    assert turn(client, sup, r["state"], "11")["error"]  # more than ordered
    r = turn(client, sup, r["state"], "3")
    r = say(client, sup, r, "DHL", "#")
    assert r["step"] == "tracking_no" and r["error"]
    invalid_tracking = turn(client, sup, r["state"], "TRK.1")
    assert invalid_tracking["step"] == "tracking_no" and invalid_tracking["error"]
    r = say(client, sup, r, "trk-1_a", "2031-02-01", "Fragile", "#")
    assert r["stage"] == "summary"
    shown = {s["label"]: s["value"] for s in r["summary"]}
    assert (
        shown["Qty ITEM002"] == "3"
        and shown["Tracking number"] == "TRK-1_A"
        and shown["Packing list"] == "(none)"
    )
    done = turn(client, sup, r["state"], "#")
    assert "upload" not in done["result"]
    ship_id = int(done["result"]["href"].rsplit("/", 1)[1])
    ship = client.get(f"/api/shipments/{ship_id}", headers=sup).json()
    assert ship["carrier"] == "DHL" and ship["tracking_no"] == "TRK-1_A" and ship["items"][0]["quantity_shipped"] == 3
    assert not ship.get("unit_level")  # the assistant ships at lot level: no per-unit QR codes
    assert (
        next(
            h
            for h in client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["history"]
            if h["action"] == "ship"
        )["channel"]
        == "assistant"
    )

    # the rest of the order: the default is what is left, and the packing list is handed back to the widget to upload
    r = start(client, sup, 2)
    r = say(client, sup, r, po_number, "1")
    assert "7 still" in r["message"]
    r = say(client, sup, r, "#", "DHL", "TRK2", "#", "#", "attached")
    assert r["stage"] == "summary"
    done = turn(client, sup, r["state"], "#")
    assert done["result"]["upload"].endswith("/files?kind=packing_list")
    assert client.get("/api/shipments", headers=sup).json()[0]["items"][0]["quantity_shipped"] == 7

    # fully shipped: the order is no longer offered
    r = start(client, sup, 2)
    assert po_number not in " ".join(o["label"] for o in r["options"])


def test_submit_errors_keep_the_conversation_and_tampering_is_refused(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    _, po_id = _approved_po(client, buyer, sup, item="ITEM002", qty=5)
    po_number = client.get(f"/api/purchase-orders/{po_id}", headers=buyer).json()["po_number"]

    r = say(client, sup, start(client, sup, 2), po_number, "1", "0", "#", "#", "#", "#", "#")
    assert r["stage"] == "summary"
    r = turn(client, sup, r["state"], "#")  # all quantities zero
    assert r["stage"] == "summary" and "at least one item" in r["error"]
    r = turn(client, sup, r["state"], "0")  # back to the last answer
    assert r["stage"] == "step" and r["step"] == "packing_list"

    state = {
        "flow": "ship_order",
        "values": {
            "po": po_id,
            "qty:ITEM002": 999,
            "carrier": None,
            "tracking_no": None,
            "expected_arrival": None,
            "notes": None,
            "packing_list": None,
        },
    }
    assert (
        client.post(
            "/api/assistant/step", headers=sup, json={"state": state, "input": "#"}
        ).status_code
        == 400
    )
    state["values"]["qty:ITEM002"] = 1
    other, _ = _register_supplier(client, "other-ship@x.com")
    assert (
        client.post(
            "/api/assistant/step", headers=other, json={"state": state, "input": "#"}
        ).status_code
        == 400
    )  # not their order


def test_assistant_is_rate_limited(client, monkeypatch):
    from app import agent_auth as auth

    sup = login(client, "supplier@demo.com")
    monkeypatch.setattr(auth, "RATE_LIMIT", 2)
    auth._hits.clear()
    codes = [client.post("/api/assistant/step", headers=sup, json={}).status_code for _ in range(3)]
    auth._hits.clear()
    assert codes == [200, 200, 429]


def test_award_supplier_conversation(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    rival, rival_id = _register_supplier(client, "rival-award@x.com")
    stranger = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={
                "name": "B7",
                "email": "b7-award@x.com",
                "password": "longenough1",
                "role": "buyer",
            },
        ).json()["access_token"]
    }
    mine = client.post(
        "/api/requirements",
        headers=buyer,
        json={
            "title": "Award via assistant",
            "quantity": 10,
            "open_to_all": True,
            "item_code": "ITEM002",
        },
    ).json()
    no_quotes = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Award nobody quoted", "quantity": 1, "open_to_all": True},
    ).json()
    client.put(
        f"/api/requirements/{mine['id']}/quote",
        headers=sup,
        json={"unit_price": 9, "lead_time_days": 10, "message": "Cheapest"},
    )
    client.put(
        f"/api/requirements/{mine['id']}/quote",
        headers=rival,
        json={"unit_price": 12, "lead_time_days": 2},
    )

    r = start(client, buyer, 2)
    assert r["step"] == "requirement"
    labels = [o["label"] for o in r["options"]]
    assert any(
        f"REQ{2000 + mine['id']}" in lb and "2 quote(s)" in lb and "best 9.00" in lb
        for lb in labels
    )
    assert not any(f"REQ{2000 + no_quotes['id']}" in lb for lb in labels)  # nothing to award
    r = turn(client, buyer, r["state"], f"REQ{2000 + mine['id']}")
    r = turn(client, buyer, r["state"], "1")
    assert r["step"] == "quote" and len(r["options"]) == 2
    assert (
        "lowest price" in r["options"][0]["label"]
        and "90.00 total" in r["options"][0]["label"]
        and "fastest" in r["options"][1]["label"]
    )
    r = turn(client, buyer, r["state"], "2")  # the faster, dearer one wins
    assert r["stage"] == "summary" and "cannot be undone" in r["warning"]
    assert (
        client.get(f"/api/requirements/{mine['id']}", headers=buyer).json()["status"] == "Open"
    )  # not yet
    done = turn(client, buyer, r["state"], "#")
    assert "awarded" in done["result"]["label"] and "created" in done["result"]["label"]

    req = client.get(f"/api/requirements/{mine['id']}", headers=buyer).json()
    assert req["status"] == "Awarded" and req["po_id"]
    assert {q["supplier_name"]: q["status"] for q in req["quotes"]}["rival-award"] == "Accepted"
    po = client.get(f"/api/purchase-orders/{req['po_id']}", headers=buyer).json()
    assert po["supplier_id"] == rival_id and po["status"] == "Pending" and po["total_amount"] == 120
    assert (
        next(h for h in history(client, buyer, mine["id"]) if h["action"] == "award")["channel"]
        == "assistant"
    )
    assert any(
        "awarded" in n["title"] for n in client.get("/api/notifications", headers=sup).json()
    )

    # another buyer is never offered it, and a crafted state cannot reach it
    assert not any(
        f"REQ{2000 + mine['id']}" in o["label"]
        for o in start(client, stranger, 2).get("options", [])
    )
    state = {
        "flow": "award_supplier",
        "values": {"requirement": mine["id"], "quote": req["quotes"][0]["id"]},
    }
    assert (
        client.post(
            "/api/assistant/step", headers=stranger, json={"state": state, "input": "#"}
        ).status_code
        == 400
    )
    # an already awarded requirement is no longer offered
    assert not any(
        f"REQ{2000 + mine['id']}" in o["label"] for o in start(client, buyer, 2).get("options", [])
    )


def test_approve_purchase_order_conversation(client):
    buyer, sup = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    stranger = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={
                "name": "B8",
                "email": "b8-approve@x.com",
                "password": "longenough1",
                "role": "buyer",
            },
        ).json()["access_token"]
    }
    abc = client.get("/api/auth/me", headers=sup).json()["supplier_id"]
    pending = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc,
            "items": [{"item_code": "ITEM002", "quantity": 4, "unit_price": 6}],
            "submit": True,
        },
    ).json()
    draft = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc,
            "items": [{"item_code": "ITEM002", "quantity": 1, "unit_price": 6}],
        },
    ).json()

    r = start(client, buyer, 3)
    assert r["step"] == "po"
    labels = [o["label"] for o in r["options"]]
    assert any(
        pending["po_number"] in lb and "24.00 total" in lb and "4 x ITEM002" in lb for lb in labels
    )
    assert not any(
        draft["po_number"] in lb for lb in labels
    )  # only Pending orders can be approved here
    r = turn(client, buyer, r["state"], pending["po_number"])
    r = turn(client, buyer, r["state"], "1")
    assert r["stage"] == "summary" and "cannot be undone" in r["warning"]
    assert (
        client.get(f"/api/purchase-orders/{pending['id']}", headers=buyer).json()["status"]
        == "Pending"
    )
    done = turn(client, buyer, r["state"], "#")
    assert "approved" in done["result"]["label"] and "reference" in done["result"]["label"]

    po = client.get(f"/api/purchase-orders/{pending['id']}", headers=buyer).json()
    assert po["status"] == "Approved" and po["erp_reference"]
    assert next(h for h in po["history"] if h["action"] == "status")["channel"] == "assistant"
    assert any(
        pending["po_number"] in n["title"] and "approved" in n["title"]
        for n in client.get("/api/notifications", headers=sup).json()
    )
    assert not any(
        pending["po_number"] in o["label"] for o in start(client, buyer, 3).get("options", [])
    )

    # other buyers cannot see or approve it, even with a crafted state
    other = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": abc,
            "items": [{"item_code": "ITEM002", "quantity": 1, "unit_price": 6}],
            "submit": True,
        },
    ).json()
    assert not any(
        other["po_number"] in o["label"] for o in start(client, stranger, 3).get("options", [])
    )
    state = {"flow": "approve_po", "values": {"po": other["id"]}}
    assert (
        client.post(
            "/api/assistant/step", headers=stranger, json={"state": state, "input": "#"}
        ).status_code
        == 400
    )
    assert (
        client.get(f"/api/purchase-orders/{other['id']}", headers=buyer).json()["status"]
        == "Pending"
    )
