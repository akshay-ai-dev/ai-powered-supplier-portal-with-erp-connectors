# isort: off
from tests.test_api import login  # noqa: F401  (sets the test environment before the app is imported)
import json
import types

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.errors import DomainError

from extraction_prefill import compare, extractor, rules
from extraction_prefill.schemas import DraftItem, ExtractionDraft, FieldIssue
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def fake_openai(content: str, capture: dict | None = None):
    def create(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )


PDF_BYTES = b"%PDF-1.4 fake pdf bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake png bytes"


def approved_po(client, sup):
    """An Approved PO owned by the demo supplier. The seeded Approved PO is another supplier's, so
    approve one of this supplier's Pending orders if needed (idempotent across tests)."""
    pos = client.get("/api/purchase-orders", headers=sup).json()
    po = next((p for p in pos if p["status"] == "Approved"), None)
    if po is None:
        buyer = login(client, "buyer@demo.com")
        pending = next(p for p in pos if p["status"] == "Pending")
        r = client.put(
            f"/api/purchase-orders/{pending['id']}", headers=buyer, json={"status": "Approved"}
        )
        assert r.status_code == 200, r.text
        po = pending
    return client.get(f"/api/purchase-orders/{po['id']}", headers=sup).json()


# ---- extractor: upload validation (no client / key needed) ------------------------------------
def test_extract_rejects_unsupported_type():
    with pytest.raises(DomainError) as e:
        extractor.extract("notes.txt", b"hello", "text/plain")
    assert e.value.status_code == 415


def test_extract_rejects_empty_file():
    with pytest.raises(DomainError):
        extractor.extract("pl.pdf", b"", "application/pdf")


def test_extract_rejects_oversize_file():
    with pytest.raises(DomainError) as e:
        extractor.extract("pl.pdf", b"x" * (extractor.MAX_BYTES + 1), "application/pdf")
    assert e.value.status_code == 413


# ---- extractor: mapping + deterministic finalize ----------------------------------------------
def test_extract_maps_response_and_flags_missing_and_ambiguous():
    model_json = json.dumps(
        {
            "ship_date": None,
            "carrier": "FedEx",
            "tracking_numbers": ["1Z999", "1Z999", "  "],
            "shipped_quantity": None,
            "unit_of_measure": "pairs",
            "lot_numbers": [],
            "serial_numbers": [],
            "items": [],
            "references": [],
            "evidence": [{"field": "carrier", "page": 1, "text": "Ship Via FedEx"}],
            "field_issues": [
                {
                    "field": "shipped_quantity",
                    "severity": "review",
                    "code": "multiple_items",
                    "message": "several items",
                }
            ],
        }
    )
    draft = extractor.extract(
        "pl.pdf", PDF_BYTES, "application/pdf", client=fake_openai(model_json)
    )
    assert draft["tracking_numbers"] == ["1Z999"]
    assert draft["unit_of_measure"] == "PR"
    codes = {(i["field"], i["code"]) for i in draft["field_issues"]}
    assert ("ship_date", "not_found") in codes
    assert ("lot_numbers", "not_found") in codes
    assert ("shipped_quantity", "not_found") not in codes  # already flagged multiple_items
    # unit was present ("pairs" -> "PR"), so no missing-unit issue is added
    assert sum(1 for i in draft["field_issues"] if i["field"] == "unit_of_measure") == 0


def test_extract_sends_pdf_as_file_part_with_strict_schema():
    capture: dict = {}
    extractor.extract("pl.pdf", PDF_BYTES, "application/pdf", client=fake_openai("{}", capture))
    assert capture["response_format"]["json_schema"]["strict"] is True
    file_part = next(p for p in capture["messages"][1]["content"] if p["type"] == "file")
    assert file_part["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_extract_evidence_absent_yields_empty_list():
    # When the model returns no evidence, the draft carries evidence: [] so the UI shows its
    # "Source location unavailable" fallback rather than inventing a page/coordinate.
    draft = extractor.extract(
        "pl.pdf", PDF_BYTES, "application/pdf", client=fake_openai(json.dumps({"carrier": "UPS"}))
    )
    assert draft["evidence"] == []


def test_extract_sends_image_as_image_url_part():
    capture: dict = {}
    extractor.extract("photo.png", PNG_BYTES, "image/png", client=fake_openai("{}", capture))
    img_part = next(p for p in capture["messages"][1]["content"] if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


# ---- rules -------------------------------------------------------------------------------------
def test_rules_flag_all_missing_core_fields():
    fields = {i.field for i in rules.finalize(ExtractionDraft()).field_issues}
    assert {
        "ship_date",
        "carrier",
        "shipped_quantity",
        "unit_of_measure",
        "lot_numbers",
        "serial_numbers",
    } <= fields


def test_rules_ambiguous_numeric_date():
    assert rules.is_ambiguous_numeric_date("2/7/2024") is True
    assert rules.is_ambiguous_numeric_date("13/7/2024") is False
    assert rules.is_ambiguous_numeric_date("2024-02-07") is False


def test_rules_normalize_unit_and_clean_list():
    assert rules.normalize_unit(" each ") == "EA"
    assert rules.clean_list(["A", "A", " ", "B"]) == ["A", "B"]


def test_rules_weight_is_not_item_quantity():
    out = rules.finalize(ExtractionDraft(shipped_quantity=24430, unit_of_measure="KGS"))
    assert out.shipped_quantity is None
    assert any(i.code == "weight_not_item_quantity" for i in out.field_issues)


def test_rules_package_count_is_not_item_quantity():
    out = rules.finalize(ExtractionDraft(shipped_quantity=150, unit_of_measure="CTNS"))
    assert out.shipped_quantity is None
    assert any(i.code == "packaging_not_item_quantity" for i in out.field_issues)


def test_rules_item_unit_quantity_is_kept():
    out = rules.finalize(ExtractionDraft(shipped_quantity=42, unit_of_measure="pairs"))
    assert out.shipped_quantity == 42 and out.unit_of_measure == "PR"


def test_rules_mixed_units_dropped_when_lines_share_a_unit():
    draft = ExtractionDraft(
        shipped_quantity=None,
        items=[
            DraftItem(item_number="A", unit_of_measure="EA"),
            DraftItem(item_number="B", unit_of_measure="EA"),
        ],
        field_issues=[
            FieldIssue(field="shipped_quantity", severity="review", code="mixed_units", message="x")
        ],
    )
    out = rules.finalize(draft)
    codes = {i.code for i in out.field_issues if i.field == "shipped_quantity"}
    assert "mixed_units" not in codes and "multiple_items" in codes


def test_rules_mixed_units_kept_when_units_really_differ():
    draft = ExtractionDraft(
        shipped_quantity=None,
        items=[
            DraftItem(item_number="A", unit_of_measure="EA"),
            DraftItem(item_number="B", unit_of_measure="KG"),
        ],
        field_issues=[
            FieldIssue(field="shipped_quantity", severity="review", code="mixed_units", message="x")
        ],
    )
    out = rules.finalize(draft)
    assert any(i.code == "mixed_units" for i in out.field_issues)


# ---- compare (pure): backend PO quantity, never a false match ---------------------------------
PO_ONE = {"items": [{"item_code": "ITEM001", "quantity": 100}]}
PO_MULTI = {"items": [{"item_code": "A", "quantity": 5}, {"item_code": "B", "quantity": 7}]}


def test_compare_single_item_match_over_under():
    assert compare.compare_quantity(PO_ONE, 100)["status"] == "match"
    over = compare.compare_quantity(PO_ONE, 120)
    assert (
        over["status"] == "over_shipped" and over["difference"] == 20 and over["po_quantity"] == 100
    )
    under = compare.compare_quantity(PO_ONE, 80)
    assert under["status"] == "under_shipped" and under["difference"] == -20


def test_compare_cannot_compare_cases():
    assert compare.compare_quantity(PO_ONE, None)["status"] == "cannot_compare"  # no single total
    assert compare.compare_quantity(PO_MULTI, 10)["status"] == "cannot_compare"  # several items
    assert compare.compare_quantity(PO_ONE, 100, item_code="ZZZ")["status"] == "cannot_compare"


def test_compare_multi_item_with_explicit_code():
    r = compare.compare_quantity(PO_MULTI, 5, item_code="A")
    assert r["status"] == "match" and r["po_quantity"] == 5


def test_compare_always_states_unit_not_verified():
    assert "unit" in compare.compare_quantity(PO_ONE, 100)["unit_note"].lower()


# ---- router: supplier authorization, PO visibility, draft-only, config, upload errors ---------
def test_extract_requires_supplier_role(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(extractor, "extract", lambda *a, **k: {"carrier": "UPS"})
    buyer = login(client, "buyer@demo.com")
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}",
        headers=buyer,
        files={"file": ("pl.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 403


def test_extract_hides_po_of_other_supplier(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    # a freshly registered supplier owns no PO, so the demo supplier's PO is not visible to them
    tok = client.post(
        "/api/auth/register",
        json={
            "name": "Other Supp",
            "email": "other-supp@x.com",
            "password": "longenough1",
            "role": "supplier",
        },
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {tok}"}
    owner = login(client, "supplier@demo.com")
    po = approved_po(client, owner)
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}",
        headers=other,
        files={"file": ("pl.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 404


def test_extract_success_saves_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        extractor, "extract", lambda *a, **k: {"carrier": "UPS", "tracking_numbers": ["1Z1"]}
    )
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    before = len(client.get(f"/api/purchase-orders/{po['id']}/shipments", headers=sup).json())
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}",
        headers=sup,
        files={"file": ("pl.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["carrier"] == "UPS"
    after = len(client.get(f"/api/purchase-orders/{po['id']}/shipments", headers=sup).json())
    assert before == after  # extraction creates no shipment


def test_extract_503_without_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}",
        headers=sup,
        files={"file": ("pl.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 503


def test_extract_reports_upload_error_visibly(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}",
        headers=sup,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


# ---- compare endpoint: uses backend PO quantity, supplier-only --------------------------------
def test_compare_endpoint_uses_backend_po_quantity(client):
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    code = po["items"][0]["item_code"]
    qty = sum(i["quantity"] for i in po["items"] if i["item_code"] == code)
    match = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}/compare",
        headers=sup,
        json={"shipped_quantity": qty, "item_code": code},
    ).json()
    assert match["status"] == "match" and match["po_quantity"] == qty
    over = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}/compare",
        headers=sup,
        json={"shipped_quantity": qty + 5, "item_code": code},
    ).json()
    assert over["status"] == "over_shipped" and over["difference"] == 5


def test_compare_endpoint_requires_supplier(client):
    buyer = login(client, "buyer@demo.com")
    sup = login(client, "supplier@demo.com")
    po = approved_po(client, sup)
    r = client.post(
        f"/api/extraction-prefill/shipments/{po['id']}/compare",
        headers=buyer,
        json={"shipped_quantity": 1},
    )
    assert r.status_code == 403


# ---- packing-list review persistence: nothing lost to the notes cap, read back, old shipments ----
def _fresh_approved_po(client):
    """A new Approved PO owned by the demo supplier, isolated from other tests' shipment activity."""
    buyer = login(client, "buyer@demo.com")
    sup = login(client, "supplier@demo.com")
    sid = client.get("/api/auth/me", headers=sup).json()["supplier_id"]
    po = client.post(
        "/api/purchase-orders",
        headers=buyer,
        json={
            "supplier_id": sid,
            "items": [{"item_code": "ITEM001", "quantity": 5, "unit_price": 1.0}],
            "submit": True,
        },
    ).json()
    r = client.put(f"/api/purchase-orders/{po['id']}", headers=buyer, json={"status": "Approved"})
    assert r.status_code == 200, r.text
    return client.get(f"/api/purchase-orders/{po['id']}", headers=sup).json(), sup


def _ship(client, sup, po, extra):
    item = po["items"][0]["item_code"]
    body = {"items": [{"item_code": item, "quantity": 1}], "unit_inspection": False, **extra}
    r = client.post(f"/api/purchase-orders/{po['id']}/shipments", headers=sup, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_long_review_and_many_tracking_numbers_round_trip(client):
    po, sup = _fresh_approved_po(client)
    tracking = [
        f"1Z{n:016d}" for n in range(30)
    ]  # 30 numbers: joined far exceeds the 80-char column
    lots = [f"LOT{n:04d}" for n in range(300)]
    serials = [f"SN{n:05d}" for n in range(300)]
    review = {
        "ship_date": "2024-01-16",
        "carrier": "UPS",
        "shipped_quantity": 1,
        "unit_of_measure": "EA",
        "tracking_numbers": tracking,
        "lot_numbers": lots,
        "serial_numbers": serials,
    }
    # the reviewed metadata is much longer than the 1000-char notes limit
    assert len("".join(tracking) + "".join(lots) + "".join(serials)) > 1000
    sh = _ship(
        client,
        sup,
        po,
        {"carrier": "UPS", "tracking_no": tracking[0], "packing_list_review": review},
    )
    got = client.get(f"/api/shipments/{sh['id']}", headers=sup).json()
    r = got["packing_list_review"]
    assert r["tracking_numbers"] == tracking  # all 30 preserved and read back
    assert r["lot_numbers"] == lots and r["serial_numbers"] == serials
    assert (
        r["ship_date"] == "2024-01-16"
        and r["shipped_quantity"] == 1
        and r["unit_of_measure"] == "EA"
    )


def test_shipment_without_review_reads_back_none(client):
    # An old-style shipment (no reviewed draft) still works and reports packing_list_review: null.
    po, sup = _fresh_approved_po(client)
    sh = _ship(client, sup, po, {"carrier": "DHL"})
    got = client.get(f"/api/shipments/{sh['id']}", headers=sup).json()
    assert got["packing_list_review"] is None and got["carrier"] == "DHL"
