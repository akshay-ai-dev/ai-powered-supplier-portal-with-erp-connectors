"""Compare an extracted shipped quantity with a PO quantity supplied by the user/portal.

The PO quantity is never read from the packing list. A comparison is only made when
the PO line can be matched to the shipped line(s) safely: same item (or a document with
exactly one item) and the same unit of measure. Otherwise the result is
'cannot_compare' with the reasons, never a guessed 'mismatch'.
"""

from __future__ import annotations

from fields import norm_key, normalize_unit


def compare_po_quantity(extraction: dict, po_quantity, po_unit, po_item=None) -> dict:
    result = {
        "status": "cannot_compare",  # match | over_shipped | under_shipped | cannot_compare
        "poQuantity": po_quantity,
        "poUnit": normalize_unit(po_unit),
        "poItem": po_item,
        "shippedQuantity": None,
        "shippedUnit": None,
        "difference": None,
        "matchedLines": [],
        "issues": [],
    }
    try:
        po_q = float(po_quantity)
    except (TypeError, ValueError):
        result["issues"].append("PO quantity is missing or not a number.")
        return result
    if not result["poUnit"]:
        result["issues"].append("PO unit of measure is required for a safe comparison.")
        return result

    lines = [it for it in extraction.get("items", []) if it.get("quantityShipped") is not None]
    if not lines and extraction.get("shippedQuantity") is not None:
        # no line table: fall back to the document-level quantity (single, unitemised shipment)
        lines = [{"itemNumber": None, "customerItemNumber": None, "description": None,
                  "quantityShipped": extraction["shippedQuantity"],
                  "unitOfMeasure": extraction.get("unitOfMeasure"), "salesOrder": None}]
    if not lines:
        result["issues"].append("No shipped quantity was extracted.")
        return result

    if po_item:
        key = norm_key(po_item)
        matched = [it for it in lines
                   if key in {norm_key(it.get("itemNumber")), norm_key(it.get("customerItemNumber"))} - {None}]
        if not matched:
            result["issues"].append(f"No shipped line matches PO item '{po_item}'.")
            return result
    else:
        distinct = {norm_key(it.get("itemNumber")) or norm_key(it.get("description")) for it in lines}
        if len(distinct) > 1:
            result["issues"].append(
                f"The document has {len(distinct)} different items; supply the PO item number to compare.")
            return result
        matched = lines

    units = {it.get("unitOfMeasure") for it in matched}
    if None in units:
        result["issues"].append("Shipped unit of measure is not stated on the document.")
        return result
    if len(units) > 1:
        result["issues"].append(f"Matched lines use different units {sorted(units)}.")
        return result
    shipped_unit = units.pop()
    if shipped_unit != result["poUnit"]:
        result["issues"].append(
            f"Units differ (shipped {shipped_unit}, PO {result['poUnit']}); no conversion is assumed.")
        result["shippedUnit"] = shipped_unit
        return result

    shipped = round(sum(it["quantityShipped"] for it in matched), 6)
    result.update(shippedQuantity=shipped, shippedUnit=shipped_unit,
                  difference=round(shipped - po_q, 6),
                  matchedLines=[{k: it.get(k) for k in ("itemNumber", "salesOrder", "quantityShipped",
                                                         "unitOfMeasure")} for it in matched])
    if abs(shipped - po_q) <= 1e-6:
        result["status"] = "match"
    else:
        result["status"] = "over_shipped" if shipped > po_q else "under_shipped"
    if len({it.get("salesOrder") for it in matched}) > 1:
        result["issues"].append("Matched lines span several sales orders; confirm they all belong to this PO.")
    return result
