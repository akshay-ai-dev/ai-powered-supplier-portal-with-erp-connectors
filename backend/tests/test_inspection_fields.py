# isort: off
from tests.test_api import _register_supplier  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from tests.test_units import arrive, ship, tag, unit_codes, who
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def add_field(client, headers, sh, **body):
    body = {
        "label": "Voltage",
        "type": "number",
        "unit_label": "V",
        "min_value": 11.5,
        "max_value": 12.5,
        **body,
    }
    return client.post(f"/api/shipments/{sh['id']}/fields", headers=headers, json=body)


def readings(client, headers, sh, code, **body):
    return client.put(f"/api/shipments/{sh['id']}/units/{code}", headers=headers, json=body)


def test_a_field_added_during_inspection_applies_to_every_unit(client):
    buyer, sup, insp = who(client)
    other_sup, _ = _register_supplier(client, "other-fields@x.com")
    _, sh = ship(client, qty=6)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    assert (
        tag(client, insp, sh, codes[0], "OK").status_code == 200
    )  # tested before the field existed

    assert add_field(client, sup, sh).status_code == 403
    assert add_field(client, buyer, sh).status_code == 403
    created = add_field(client, insp, sh)
    assert (
        created.status_code == 201
        and created.json()["label"] == "Voltage"
        and created.json()["required"] is False
    )
    fid = str(created.json()["id"])
    assert add_field(client, insp, sh).status_code == 400  # same name twice

    listing = client.get(f"/api/shipments/{sh['id']}/units", headers=insp).json()
    assert [f["label"] for f in listing["fields"]] == ["Voltage"] and listing["fields"][0][
        "tolerance"
    ] == "11.5 to 12.5 V"
    first = client.get(f"/api/units/{codes[0]}", headers=insp).json()
    assert (
        first["field_values"][0]["value"] is None and first["field_values"][0]["result"] is None
    )  # "not recorded"

    # a number inside the tolerance passes; outside it the unit cannot be OK
    ok = readings(client, insp, sh, codes[1], result="OK", readings={fid: "12.0"}).json()
    assert (
        ok["status"] == "OK"
        and ok["field_values"][0]["value"] == 12.0
        and ok["field_values"][0]["result"] == "pass"
    )
    out = readings(client, insp, sh, codes[2], result="OK", readings={fid: 13.1})
    assert out.status_code == 400 and "Voltage failed" in out.json()["detail"]
    bad = readings(
        client,
        insp,
        sh,
        codes[2],
        result="Faulty",
        defect_type="out_of_tolerance",
        readings={fid: 13.1},
    ).json()
    assert (
        bad["status"] == "Faulty"
        and bad["field_values"][0]["result"] == "fail"
        and bad["defect_label"] == "Measurement out of tolerance"
    )
    assert readings(client, insp, sh, codes[3], readings={fid: "abc"}).status_code == 400
    assert (
        readings(client, insp, sh, codes[3], readings={"99999": 1}).status_code == 400
    )  # not a field of this shipment
    saved = readings(
        client, insp, sh, codes[3], readings={fid: 12.2}
    ).json()  # readings can be saved before the result
    assert saved["status"] == "Received" and saved["field_values"][0]["value"] == 12.2

    # a Pass/Fail field fails the unit when marked fail; a Text field never does
    seal = add_field(client, insp, sh, label="Seal intact", type="pass_fail").json()["id"]
    note = add_field(client, insp, sh, label="Batch no.", type="text").json()["id"]
    r = readings(
        client, insp, sh, codes[4], result="OK", readings={str(seal): "fail", str(note): "B-7"}
    )
    assert r.status_code == 400 and "Seal intact failed" in r.json()["detail"]
    r = readings(
        client, insp, sh, codes[4], result="OK", readings={str(seal): "pass", str(note): "B-7"}
    ).json()
    assert r["status"] == "OK" and {v["label"]: v["result"] for v in r["field_values"]} == {
        "Voltage": None,
        "Seal intact": "pass",
        "Batch no.": "pass",
    }
    # an OK unit cannot be edited into a failing value without changing its result
    assert readings(client, insp, sh, codes[4], readings={str(seal): "fail"}).status_code == 400

    # others cannot see this shipment's fields
    assert client.get(f"/api/shipments/{sh['id']}/fields", headers=other_sup).status_code == 404
    assert len(client.get(f"/api/shipments/{sh['id']}/fields", headers=sup).json()) == 3


def test_a_required_field_gates_ok_bulk_and_the_decision(client):
    buyer, sup, insp = who(client)
    _, sh = ship(client, qty=4)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    tag(client, insp, sh, codes[0], "OK")  # before the field
    fid = str(
        add_field(
            client,
            insp,
            sh,
            label="Weight",
            unit_label="g",
            min_value=95,
            max_value=105,
            required=True,
        ).json()["id"]
    )

    no_value = tag(client, insp, sh, codes[1], "OK")
    assert (
        no_value.status_code == 400
        and "Weight" in no_value.json()["detail"]
        and "required" in no_value.json()["detail"]
    )
    bulk = client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    ).json()
    assert (
        bulk["updated"] == 0
        and bulk["skipped_count"] == 3
        and "required" in bulk["skipped"][0]["reason"]
    )

    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert rep["ready"] is False and any(
        "3 received unit(s) still need a result" in b for b in rep["blockers"]
    )
    # set the weight on every unit at once; the unit that was OK already passes with it, one that fails is skipped
    ok_all = client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "set_field", "field_id": int(fid), "item_code": "ITEM002", "value": 100},
    ).json()
    assert ok_all["updated"] == 4 and ok_all["skipped_count"] == 0
    skipped = client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "set_field", "field_id": int(fid), "codes": [codes[0]], "value": 500},
    ).json()
    assert skipped["updated"] == 0 and "Set the result to Faulty" in skipped["skipped"][0]["reason"]
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/units/bulk",
            headers=insp,
            json={"action": "set_field", "item_code": "ITEM002", "value": 1},
        ).status_code
        == 400
    )  # needs field_id

    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "ok", "all_pending": True},
    )
    # a required field added late leaves tested units "not recorded" and blocks the lot until it is filled
    late = int(add_field(client, insp, sh, label="Colour", type="text", required=True).json()["id"])
    rep = client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()
    assert (
        rep["ready"] is False
        and "'Colour' (required) is missing on 4 unit(s)" in rep["blockers"][0]
    )
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "approve"}
        ).status_code
        == 400
    )
    client.post(
        f"/api/shipments/{sh['id']}/units/bulk",
        headers=insp,
        json={"action": "set_field", "field_id": late, "item_code": "ITEM002", "value": "Blue"},
    )
    assert client.get(f"/api/shipments/{sh['id']}/report", headers=insp).json()["ready"] is True
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/inspection", headers=insp, json={"decision": "approve"}
        ).json()["status"]
        == "Approved"
    )
    assert add_field(client, insp, sh, label="Too late").status_code == 400  # the lot is decided


def test_rename_remove_and_the_type_lock(client):
    _, sup, insp = who(client)
    _, sh = ship(client, qty=2)
    arrive(client, insp, sh)
    code = unit_codes(client, insp, sh)[0]
    fid = add_field(client, insp, sh, label="Lenght").json()["id"]
    url = f"/api/shipments/{sh['id']}/fields/{fid}"

    fixed = client.patch(
        url,
        headers=insp,
        json={"label": "Length", "unit_label": "mm", "min_value": 99, "max_value": 101},
    ).json()
    assert fixed["label"] == "Length" and fixed["unit_label"] == "mm" and fixed["min_value"] == 99
    assert client.patch(url, headers=sup, json={"label": "x"}).status_code == 403
    assert (
        client.patch(url, headers=insp, json={"min_value": 200}).status_code == 400
    )  # min above max
    assert (
        client.patch(url, headers=insp, json={"type": "text"}).json()["type"] == "text"
    )  # allowed while nothing is recorded
    assert client.delete(url, headers=insp).status_code == 200
    assert client.get(f"/api/shipments/{sh['id']}/fields", headers=insp).json() == []

    fid = add_field(client, insp, sh, label="Length").json()["id"]
    readings(client, insp, sh, code, readings={str(fid): 100.2})
    url = f"/api/shipments/{sh['id']}/fields/{fid}"
    assert client.delete(url, headers=insp).status_code == 400  # a value was recorded
    assert client.patch(url, headers=insp, json={"type": "text"}).status_code == 400
    assert (
        client.patch(url, headers=insp, json={"max_value": 101.5}).status_code == 200
    )  # tolerance may still change


def test_saved_fields_start_the_next_shipment_of_that_item(client):
    buyer, sup, insp = who(client)
    item = "TPL-WIDGET"
    client.post(
        "/api/inventory",
        headers=buyer,
        json={"item_code": item, "description": "Template test", "stock_quantity": 0},
    )
    _, first = ship(client, qty=2, item=item)
    arrive(client, insp, first)
    assert (
        add_field(client, insp, first, save_template=True).status_code == 400
    )  # needs an item to belong to
    assert (
        add_field(client, insp, first, item_code="ITEM999").status_code == 400
    )  # not part of this shipment
    saved = add_field(
        client, insp, first, label="Voltage", item_code=item, save_template=True, required=True
    )
    assert saved.status_code == 201 and saved.json()["item_code"] == item

    templates = client.get(
        "/api/inspection-fields/templates", headers=insp, params={"item_code": item}
    ).json()
    assert [(t["label"], t["required"]) for t in templates] == [("Voltage", True)]
    assert (
        client.get("/api/inspection-fields/templates", headers=sup).json() == []
    )  # not the supplier's business

    _, second = ship(client, qty=1, item=item)
    copied = client.get(f"/api/shipments/{second['id']}/fields", headers=insp).json()
    assert [
        (f["label"], f["item_code"], f["required"], f["min_value"], f["max_value"]) for f in copied
    ] == [("Voltage", item, True, 11.5, 12.5)]
    _, other = ship(client, qty=1, item="ITEM003")
    assert (
        client.get(f"/api/shipments/{other['id']}/fields", headers=insp).json() == []
    )  # other items are not affected

    assert (
        client.delete(
            f"/api/inspection-fields/templates/{templates[0]['id']}", headers=sup
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/inspection-fields/templates/{templates[0]['id']}", headers=insp
        ).status_code
        == 200
    )
    _, third = ship(client, qty=1, item=item)
    assert client.get(f"/api/shipments/{third['id']}/fields", headers=insp).json() == []
    assert (
        len(client.get(f"/api/shipments/{second['id']}/fields", headers=insp).json()) == 1
    )  # shipments already created keep theirs


def test_csv_carries_the_custom_fields_and_the_report_summarises_them(client):
    buyer, sup, insp = who(client)
    _, sh = ship(client, qty=5)
    arrive(client, insp, sh)
    codes = unit_codes(client, insp, sh)
    fid = add_field(client, insp, sh).json()["id"]

    header = client.get(f"/api/shipments/{sh['id']}/units.csv", headers=insp).text.splitlines()[0]
    assert header.endswith(f",f_{fid}_Voltage")
    col = f"f_{fid}_Voltage"
    bad = f"code,result,{col}\n{codes[0]},OK,12.0\n{codes[1]},OK,15\n"
    r = client.post(
        f"/api/shipments/{sh['id']}/units/import",
        headers=insp,
        files={"file": ("r.csv", bad.encode(), "text/csv")},
    )
    assert (
        r.status_code == 400
        and "row 3" in r.json()["detail"]
        and "Voltage failed" in r.json()["detail"]
    )
    assert (
        client.get(f"/api/units/{codes[0]}", headers=insp).json()["status"] == "Received"
    )  # nothing was saved
    good = f"code,result,defect_type,{col}\n{codes[0]},OK,,12.0\n{codes[1]},Faulty,out_of_tolerance,15\n{codes[2]},OK,,11.8\n{codes[3]},OK,,12.4\n{codes[4]},OK,,\n"
    assert (
        client.post(
            f"/api/shipments/{sh['id']}/units/import",
            headers=insp,
            files={"file": ("r.csv", good.encode(), "text/csv")},
        ).json()["updated"]
        == 5
    )

    rep = client.get(
        f"/api/shipments/{sh['id']}/report", headers=sup
    ).json()  # the supplier sees the field results
    volt = rep["fields"][0]
    assert (
        volt["label"],
        volt["units"],
        volt["recorded"],
        volt["not_recorded"],
        volt["passed"],
        volt["failed"],
    ) == ("Voltage", 5, 4, 1, 3, 1)
    assert (volt["min"], volt["max"], volt["average"]) == (11.8, 15.0, 12.8) and volt[
        "tolerance"
    ] == "11.5 to 12.5 V"
    assert rep["faulty_units"][0]["failed_fields"] == [
        {"label": "Voltage", "value": 15.0, "unit_label": "V", "tolerance": "11.5 to 12.5 V"}
    ]

    # accuracy 80% is below the threshold; approving needs a reason, and the frozen report keeps the field statistics
    approve = client.post(
        f"/api/shipments/{sh['id']}/inspection",
        headers=insp,
        json={"decision": "approve", "override_reason": "Voltage drift accepted by the buyer"},
    )
    assert approve.status_code == 200
    frozen = client.get(f"/api/shipments/{sh['id']}/report", headers=buyer).json()
    assert (
        frozen["frozen"] is True
        and frozen["fields"][0]["failed"] == 1
        and frozen["quality_accuracy"] == 80.0
    )
    assert client.get(f"/api/shipments/{sh['id']}/units.csv", headers=sup).status_code == 200
