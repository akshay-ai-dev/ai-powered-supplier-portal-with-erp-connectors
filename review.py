"""Supplier-review logic for the browser UI (pure functions, no web code).

The UI sends the supplier's *edited* draft here. This module:
  * normalises edited values (units, lists, numbers, dates),
  * recomputes the document-level shipped quantity from edited item lines, using the same
    rule as the extractor (one item and one unit -> sum; otherwise null, never mixed),
  * validates PO entries and runs po_check.compare_po_quantity on the EDITED draft,
  * validates a finished review and builds the reviewed JSON (local POC only).

Nothing here submits a shipment or talks to ERP.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime, timezone

from fields import norm_key, normalize_unit
from po_check import compare_po_quantity

LIST_FIELDS = ("trackingNumbers", "lotNumbers", "serialNumbers")
SCALAR_FIELDS = ("shipDate", "carrier", "shippedQuantity", "unitOfMeasure")
REVIEWED_STATUS = "reviewed_locally_not_submitted"
MAX_IDENTIFIER_LENGTH = 60


def _clean_str(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _to_number(value):
    """Return (number_or_None, error_or_None). Empty means null, never zero."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, bool):
        return None, "must be a number"
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None, "must be a number"
    if number != number or number in (float("inf"), float("-inf")):
        return None, "must be a finite number"
    if number < 0:
        return None, "cannot be negative"
    return number, None


def _clean_list(values):
    out = []
    for v in values or []:
        text = _clean_str(v)
        if text and text not in out:
            out.append(text)
    return out


def normalize_draft(draft):
    """Copy of the edited draft with cleaned values and normalised units. Returns (draft, errors)."""
    d = copy.deepcopy(draft or {})
    errors = []
    d["carrier"] = _clean_str(d.get("carrier"))
    d["shipDate"] = _clean_str(d.get("shipDate"))
    d["unitOfMeasure"] = normalize_unit(_clean_str(d.get("unitOfMeasure")))
    qty, err = _to_number(d.get("shippedQuantity"))
    if err:
        errors.append({"field": "shippedQuantity", "message": f"Shipped quantity {err}."})
    d["shippedQuantity"] = qty
    for f in LIST_FIELDS:
        d[f] = _clean_list(d.get(f))
    items = []
    for idx, it in enumerate(d.get("items") or []):
        it = dict(it)
        q, err = _to_number(it.get("quantityShipped"))
        if err:
            errors.append({"field": f"items[{idx}].quantityShipped",
                           "message": f"Line {idx + 1}: shipped quantity {err}."})
        it["quantityShipped"] = q
        it["unitOfMeasure"] = normalize_unit(_clean_str(it.get("unitOfMeasure")))
        items.append(it)
    d["items"] = items
    return d, errors


def recompute_totals(draft):
    """Apply the extractor's aggregation rule to edited item lines (in place) and return a note.

    One distinct item in one unit -> shippedQuantity is the sum of its lines.
    Several items or several units -> shippedQuantity is null (products/units are never mixed).
    Without item lines the supplier's own document-level quantity is kept.
    """
    lines = [it for it in draft.get("items", []) if it.get("quantityShipped") is not None]
    if not draft.get("items"):
        return {"source": "document", "message": None}
    draft["quantitySummary"] = _quantity_summary(lines)
    if not lines:
        draft["shippedQuantity"] = None
        return {"source": "items", "message": "No item line has a shipped quantity."}
    products = {norm_key(it.get("itemNumber")) or norm_key(it.get("description")) for it in lines}
    units = {it.get("unitOfMeasure") for it in lines}
    if len(products) == 1 and len(units) == 1:
        draft["shippedQuantity"] = round(sum(it["quantityShipped"] for it in lines), 6)
        draft["unitOfMeasure"] = next(iter(units))
        return {"source": "items", "message": None}
    draft["shippedQuantity"] = None
    draft["unitOfMeasure"] = next(iter(units)) if len(units) == 1 else None
    if len(units) > 1:
        return {"source": "items", "message": "Item lines use different units; no single total."}
    return {"source": "items",
            "message": f"{len(products)} different products; no single total (compare per item)."}


def _quantity_summary(lines):
    """Per item and unit totals of the EDITED lines (same shape as the extractor's quantitySummary)."""
    summary = {}
    for it in lines:
        key = (it.get("itemNumber") or it.get("description"), it.get("unitOfMeasure"))
        s = summary.setdefault(key, {"itemNumber": it.get("itemNumber"),
                                     "description": None if it.get("itemNumber") else it.get("description"),
                                     "unit": it.get("unitOfMeasure"), "quantityShipped": 0.0, "lineCount": 0,
                                     "salesOrders": []})
        s["quantityShipped"] = round(s["quantityShipped"] + it["quantityShipped"], 6)
        s["lineCount"] += 1
        if it.get("salesOrder") and it["salesOrder"] not in s["salesOrders"]:
            s["salesOrders"].append(it["salesOrder"])
    return list(summary.values())


def parse_po(po):
    """Validate PO entries. Returns (po_dict_or_None, errors). None means 'no comparison requested'."""
    po = po or {}
    qty_raw, unit_raw, item_raw = po.get("quantity"), po.get("unit"), po.get("item")
    if all(v in (None, "") or (isinstance(v, str) and not v.strip()) for v in (qty_raw, unit_raw, item_raw)):
        return None, []
    errors = []
    qty, err = _to_number(qty_raw)
    if err or qty is None:
        errors.append({"field": "poQuantity", "message": "PO quantity must be a number greater than zero."})
    elif qty <= 0:
        errors.append({"field": "poQuantity", "message": "PO quantity must be greater than zero."})
    unit = normalize_unit(_clean_str(unit_raw))
    if not unit:
        errors.append({"field": "poUnit", "message": "PO unit is required to compare quantities (e.g. EA, PR, SF)."})
    return ({"quantity": qty, "unit": unit, "item": _clean_str(item_raw)} if not errors else None), errors


def compare_with_po(draft, po):
    """Normalise the edited draft, recompute totals, and compare with the PO using po_check."""
    norm, errors = normalize_draft(draft)
    totals = recompute_totals(norm)
    po_clean, po_errors = parse_po(po)
    comparison = None
    if po_clean and not errors:
        comparison = compare_po_quantity(norm, po_clean["quantity"], po_clean["unit"], po_clean["item"])
    return {"draft": norm, "totals": totals, "errors": errors + po_errors, "comparison": comparison,
            "poRequested": po_clean is not None or bool(po_errors)}


def _valid_iso_date(text):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or ""):
        return False
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def _issue_key(issue):
    return f"{issue.get('field')}:{issue.get('code')}"


def _corrections(original, reviewed):
    out = []
    for f in SCALAR_FIELDS + LIST_FIELDS:
        if (original or {}).get(f) != reviewed.get(f):
            out.append({"field": f, "extracted": (original or {}).get(f), "reviewed": reviewed.get(f)})
    for idx, (a, b) in enumerate(zip((original or {}).get("items") or [], reviewed.get("items") or [])):
        for f in ("quantityShipped", "unitOfMeasure"):
            if a.get(f) != b.get(f):
                out.append({"field": f"items[{idx}].{f}", "extracted": a.get(f), "reviewed": b.get(f)})
    return out


def finish_review(original, draft, po=None, acknowledged=()):
    """Validate the edited draft. Errors block finishing; warnings are shown but allowed."""
    result = compare_with_po(draft, po)
    norm, errors = result["draft"], list(result["errors"])
    warnings = []
    if norm.get("shipDate") and not _valid_iso_date(norm["shipDate"]):
        errors.append({"field": "shipDate", "message": "Ship date must be a real date in YYYY-MM-DD format."})
    for f in LIST_FIELDS:
        for v in norm[f]:
            if len(v) > MAX_IDENTIFIER_LENGTH:
                errors.append({"field": f, "message": f"'{v[:20]}…' is longer than {MAX_IDENTIFIER_LENGTH} characters."})
    acknowledged = set(acknowledged or ())
    for issue in (original or {}).get("fieldIssues", []):
        if issue.get("severity") == "review" and _issue_key(issue) not in acknowledged:
            errors.append({"field": issue.get("field"),
                           "message": f"Please confirm or correct: {issue.get('message')}"})
    if not norm.get("shipDate"):
        warnings.append({"field": "shipDate", "message": "No ship date entered."})
    if not norm.get("carrier"):
        warnings.append({"field": "carrier", "message": "No carrier entered."})
    if not norm["trackingNumbers"]:
        warnings.append({"field": "trackingNumbers", "message": "No tracking number entered."})
    lines_without_unit = [i + 1 for i, it in enumerate(norm["items"])
                          if it.get("quantityShipped") is not None and not it.get("unitOfMeasure")]
    if lines_without_unit:
        warnings.append({"field": "items", "message": f"Line(s) {lines_without_unit} have no unit; "
                                                      f"they cannot be compared with a PO."})
    if not norm["items"] and norm.get("shippedQuantity") is not None and not norm.get("unitOfMeasure"):
        warnings.append({"field": "unitOfMeasure", "message": "Shipped quantity has no unit."})
    if result["totals"]["message"]:
        warnings.append({"field": "shippedQuantity", "message": result["totals"]["message"]})
    if result["comparison"] and result["comparison"]["status"] == "cannot_compare":
        warnings.append({"field": "poComparison", "message": "PO comparison not possible: "
                                                             + "; ".join(result["comparison"]["issues"])})

    reviewed = None
    if not errors:
        reviewed = {k: v for k, v in norm.items() if k not in ("timings",)}
        reviewed["status"] = REVIEWED_STATUS
        reviewed["review"] = {
            "reviewedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "LOCAL POC review only. Not submitted as a shipment and not posted to ERP.",
            "acknowledgedIssues": sorted(acknowledged),
            "corrections": _corrections(original, norm),
            "po": parse_po(po)[0],
            "poComparison": result["comparison"],
            "warnings": warnings,
        }
    return {"ok": not errors, "errors": errors, "warnings": warnings, "reviewed": reviewed,
            "comparison": result["comparison"], "totals": result["totals"]}
