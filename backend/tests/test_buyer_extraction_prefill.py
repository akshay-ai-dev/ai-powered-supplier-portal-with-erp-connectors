# isort: off
from tests.test_api import login  # noqa: F401  (sets the test environment before the app is imported)
import json
import types
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.errors import DomainError

from extraction_prefill import buyer_extractor, buyer_rules
from extraction_prefill.buyer_schemas import RequirementDraft, RequirementDraftItem
from extraction_prefill.schemas import FieldIssue
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

ENDPOINT = "/api/extraction-prefill/requirements"


def _model_json(**over) -> str:
    base = {
        "title": None,
        "description": None,
        "quantity": None,
        "target_price": None,
        "needed_by": None,
        "quote_deadline": None,
        "items": [],
        "references": [],
        "evidence": [],
        "field_issues": [],
    }
    base.update(over)
    return json.dumps(base)


# ---- extractor: upload validation (no client / key needed) ------------------------------------
def test_buyer_extract_rejects_unsupported_type():
    with pytest.raises(DomainError) as e:
        buyer_extractor.extract("notes.txt", b"hello", "text/plain")
    assert e.value.status_code == 415


def test_buyer_extract_rejects_empty_file():
    with pytest.raises(DomainError):
        buyer_extractor.extract("req.pdf", b"", "application/pdf")


def test_buyer_extract_rejects_oversize_file():
    with pytest.raises(DomainError) as e:
        buyer_extractor.extract("req.pdf", b"x" * (buyer_extractor.MAX_BYTES + 1), "application/pdf")
    assert e.value.status_code == 413


# ---- extractor: dispatch (PDF file part / image_url part), strict schema ----------------------
def test_buyer_extract_sends_pdf_as_file_part_with_strict_schema():
    capture: dict = {}
    buyer_extractor.extract("req.pdf", PDF_BYTES, "application/pdf", client=fake_openai("{}", capture))
    assert capture["response_format"]["json_schema"]["strict"] is True
    assert capture["response_format"]["json_schema"]["name"] == "requirement_draft"
    file_part = next(p for p in capture["messages"][1]["content"] if p["type"] == "file")
    assert file_part["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_buyer_extract_sends_image_as_image_url_part():
    capture: dict = {}
    buyer_extractor.extract("req.png", PNG_BYTES, "image/png", client=fake_openai("{}", capture))
    img_part = next(p for p in capture["messages"][1]["content"] if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


# ---- extractor: mapping, missing/ambiguous flags, draft shaping -------------------------------
def test_buyer_extract_maps_fields_and_flags_missing():
    draft = buyer_extractor.extract(
        "req.pdf",
        PDF_BYTES,
        "application/pdf",
        client=fake_openai(
            _model_json(
                title="  M8 Hex Bolts  ",
                description="A2-70 stainless, DIN 933",
                quantity=500,
                evidence=[{"field": "title", "page": 1, "text": "M8 Hex Bolts"}],
            )
        ),
    )
    assert draft["title"] == "M8 Hex Bolts"  # trimmed
    assert draft["description"] == "A2-70 stainless, DIN 933"
    assert draft["quantity"] == 500
    codes = {(i["field"], i["code"]) for i in draft["field_issues"]}
    # absent core fields get a "not found" note; present ones do not
    assert ("target_price", "not_found") in codes
    assert ("needed_by", "not_found") in codes
    assert ("quote_deadline", "not_found") in codes
    assert ("title", "not_found") not in codes
    assert ("quantity", "not_found") not in codes


def test_buyer_extract_keeps_model_issue_instead_of_not_found():
    # The model flagged a relative delivery term; finalize must not also add a needed_by "not_found".
    draft = buyer_extractor.extract(
        "req.pdf",
        PDF_BYTES,
        "application/pdf",
        client=fake_openai(
            _model_json(
                title="Widget",
                quantity=10,
                field_issues=[
                    {
                        "field": "needed_by",
                        "severity": "review",
                        "code": "relative_date",
                        "message": "document says 'within 4 weeks'",
                    }
                ],
            )
        ),
    )
    needed = [i for i in draft["field_issues"] if i["field"] == "needed_by"]
    assert len(needed) == 1 and needed[0]["code"] == "relative_date"


def test_buyer_extract_evidence_absent_yields_empty_list():
    draft = buyer_extractor.extract(
        "req.pdf", PDF_BYTES, "application/pdf", client=fake_openai(_model_json(title="Widget"))
    )
    assert draft["evidence"] == []


def test_buyer_extract_evidence_carries_page_and_text():
    draft = buyer_extractor.extract(
        "req.pdf",
        PDF_BYTES,
        "application/pdf",
        client=fake_openai(
            _model_json(
                title="Widget",
                quantity=3,
                evidence=[
                    {"field": "title", "page": 2, "text": "Item: Widget"},
                    {"field": "quantity", "page": 2, "text": "Qty: 3"},
                ],
            )
        ),
    )
    ev = {e["field"]: e for e in draft["evidence"]}
    assert ev["title"]["page"] == 2 and ev["title"]["text"] == "Item: Widget"
    assert ev["quantity"]["page"] == 2


def test_buyer_extract_multiple_items_requires_choice_and_never_combines():
    draft = buyer_extractor.extract(
        "req.pdf",
        PDF_BYTES,
        "application/pdf",
        client=fake_openai(
            _model_json(
                title=None,
                quantity=None,
                items=[
                    {"item_name": "Bolt", "specs": None, "quantity": 100, "unit_of_measure": "EA", "target_price": None},
                    {"item_name": "Nut", "specs": None, "quantity": 200, "unit_of_measure": "EA", "target_price": None},
                ],
                # the model also emits a bare "not found" for quantity (as seen on a live RFQ); the
                # finalize step must drop it so the buyer does not see a duplicate Quantity warning.
                field_issues=[
                    {"field": "quantity", "severity": "warning", "code": "not_found", "message": "x"}
                ],
            )
        ),
    )
    assert draft["title"] is None and draft["quantity"] is None  # nothing picked or summed
    assert len(draft["items"]) == 2
    codes = {(i["field"], i["code"]) for i in draft["field_issues"]}
    # one clear "choose an item" message on the item name, and NO separate quantity warning
    # (previously quantity showed both "multiple_items" and "not found" at once).
    assert ("title", "multiple_items") in codes
    assert [i for i in draft["field_issues"] if i["field"] == "quantity"] == []


# ---- rules (pure) -----------------------------------------------------------------------------
def test_rules_flag_all_missing_core_fields():
    fields = {i.field for i in buyer_rules.finalize(RequirementDraft()).field_issues}
    assert {"title", "quantity", "target_price", "needed_by", "quote_deadline"} <= fields


def test_rules_is_historical_date():
    ref = date(2026, 10, 9)
    assert buyer_rules.is_historical_date("2020-01-01", ref) is True
    assert buyer_rules.is_historical_date("2099-01-01", ref) is False
    assert buyer_rules.is_historical_date("within 4 weeks", ref) is False  # not a date
    assert buyer_rules.is_historical_date(None, ref) is False


def test_rules_flags_past_needed_by_date():
    out = buyer_rules.finalize(
        RequirementDraft(title="Widget", quantity=1, needed_by="2001-01-01")
    )
    assert any(
        i.field == "needed_by" and i.code == "historical_date" for i in out.field_issues
    )


def test_rules_does_not_duplicate_historical_flag():
    draft = RequirementDraft(
        title="Widget",
        quantity=1,
        needed_by="2001-01-01",
        field_issues=[
            FieldIssue(field="needed_by", severity="review", code="historical_date", message="x")
        ],
    )
    out = buyer_rules.finalize(draft)
    hist = [i for i in out.field_issues if i.field == "needed_by" and i.code == "historical_date"]
    assert len(hist) == 1


def test_rules_enforce_single_item_nulls_combined_fields():
    draft = RequirementDraft(
        title="Bolt",
        quantity=100,
        target_price=1.5,
        items=[RequirementDraftItem(item_name="Bolt"), RequirementDraftItem(item_name="Nut")],
    )
    out = buyer_rules.finalize(draft)
    assert out.title is None and out.quantity is None and out.target_price is None
    assert any(i.field == "title" and i.code == "multiple_items" for i in out.field_issues)


def test_rules_single_repeated_item_is_not_multiple():
    draft = RequirementDraft(
        title="Bolt",
        quantity=100,
        items=[RequirementDraftItem(item_name="Bolt"), RequirementDraftItem(item_name="bolt")],
    )
    out = buyer_rules.finalize(draft)
    assert out.title == "Bolt" and out.quantity == 100  # same item name, not multiple
    assert not any(i.code == "multiple_items" for i in out.field_issues)


# ---- quote-deadline time zone: correct offset, DST-aware, local clock preserved ----------------
def _resolve(value, tz):
    return buyer_rules.resolve_quote_deadline(value, tz)


def test_tz_fixed_abbreviation_before_dst():
    # "3:00 pm CST" on a winter date -> -06:00; the local wall-clock digits are preserved, no Z.
    out, issue = _resolve("2023-03-10T15:00:00", "CST")
    assert out == "2023-03-10T15:00:00-06:00" and issue is None


def test_tz_general_zone_is_dst_aware():
    # a bare "ET" resolves to EDT in summer and EST in winter (daylight saving by the deadline's date)
    assert _resolve("2024-09-25T12:00:00", "ET")[0] == "2024-09-25T12:00:00-04:00"
    assert _resolve("2024-01-15T12:00:00", "ET")[0] == "2024-01-15T12:00:00-05:00"


def test_tz_explicit_standard_vs_daylight_honoured():
    assert _resolve("2024-07-01T09:00:00", "EDT")[0] == "2024-07-01T09:00:00-04:00"
    assert _resolve("2024-07-01T09:00:00", "EST")[0] == "2024-07-01T09:00:00-05:00"


def test_tz_utc_and_gmt():
    assert _resolve("2024-05-01T10:00:00", "UTC")[0] == "2024-05-01T10:00:00+00:00"
    assert _resolve("2024-05-01T10:00:00", "GMT")[0] == "2024-05-01T10:00:00+00:00"


def test_tz_unclear_keeps_local_and_flags_review():
    out, issue = _resolve("2024-05-01T23:30:00", None)
    assert out == "2024-05-01T23:30:00"  # naive, not mislabelled UTC
    assert issue is not None and issue.code == "time_zone_unclear" and issue.severity == "review"


def test_tz_strips_model_appended_zone_and_rezones():
    # the model wrongly appended Z to the local time; we strip it and apply the printed zone instead.
    assert _resolve("2023-03-10T15:00:00Z", "CST")[0] == "2023-03-10T15:00:00-06:00"


def test_tz_date_only_is_untouched():
    out, issue = _resolve("2024-08-26", None)
    assert out == "2024-08-26" and issue is None


def test_tz_conversion_crosses_a_calendar_day():
    # 11:30 PM EST -> the UTC instant is 04:30 the NEXT day; the local date stays the 31st.
    out, _ = _resolve("2024-12-31T23:30:00", "EST")
    assert out == "2024-12-31T23:30:00-05:00"
    utc = datetime.fromisoformat(out).astimezone(timezone.utc)
    assert utc.date().isoformat() == "2025-01-01" and utc.hour == 4


def test_finalize_resolves_deadline_zone_and_still_flags_past():
    out = buyer_rules.finalize(
        RequirementDraft(
            title="X", quantity=1, quote_deadline="2023-03-10T15:00:00", quote_deadline_tz="CST"
        )
    )
    assert out.quote_deadline == "2023-03-10T15:00:00-06:00"
    assert any(i.field == "quote_deadline" and i.code == "historical_date" for i in out.field_issues)


def test_finalize_unclear_zone_flags_review_future_deadline():
    out = buyer_rules.finalize(
        RequirementDraft(
            title="X", quantity=1, quote_deadline="2099-05-01T17:00:00", quote_deadline_tz=None
        )
    )
    assert out.quote_deadline == "2099-05-01T17:00:00"
    assert any(i.code == "time_zone_unclear" for i in out.field_issues)


# ---- router: buyer authorization, config, upload errors, draft-only ---------------------------
def test_requirement_extract_requires_buyer_role(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(buyer_extractor, "extract", lambda *a, **k: {"title": "Widget"})
    sup = login(client, "supplier@demo.com")
    r = client.post(ENDPOINT, headers=sup, files={"file": ("req.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 403


def test_requirement_extract_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    r = client.post(ENDPOINT, files={"file": ("req.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 401


def test_requirement_extract_503_without_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    buyer = login(client, "buyer@demo.com")
    r = client.post(
        ENDPOINT, headers=buyer, files={"file": ("req.pdf", PDF_BYTES, "application/pdf")}
    )
    assert r.status_code == 503


def test_requirement_extract_reports_upload_error_visibly(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    buyer = login(client, "buyer@demo.com")
    r = client.post(
        ENDPOINT, headers=buyer, files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


def test_requirement_extract_success_saves_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        buyer_extractor,
        "extract",
        lambda *a, **k: {"title": "M8 Bolts", "quantity": 500, "field_issues": []},
    )
    buyer = login(client, "buyer@demo.com")
    before = len(client.get("/api/requirements", headers=buyer).json())
    r = client.post(
        ENDPOINT, headers=buyer, files={"file": ("req.pdf", PDF_BYTES, "application/pdf")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "M8 Bolts"
    after = len(client.get("/api/requirements", headers=buyer).json())
    assert before == after  # extraction creates no requirement
