"""Compare a reviewed shipped quantity against the purchase order, using backend PO data only.

The caller passes the PO (as returned by the shipments/PO service) and the reviewed shipped quantity;
no client-supplied PO quantity is trusted. The result is advisory for the supplier before submit —
the shipment-create endpoint still enforces the authoritative per-item limit.

This system's PO/inventory items carry no unit of measure, so a unit can never be matched against the
PO. Rather than claim a false match, every comparison states that units were not verified; a quantity
that cannot be attributed to a single PO line (several items, or no single shipped total) is reported
as "cannot_compare" instead of a guessed result.
"""

_NO_UNIT = "PO has no unit of measure on record; compared by quantity only (unit not verified)."


def _distinct_items(po: dict) -> dict[str, float]:
    totals: dict[str, float] = {}
    for it in po.get("items", []):
        code = str(it["item_code"]).strip().upper()
        totals[code] = totals.get(code, 0) + (it.get("quantity") or 0)
    return totals


def compare_quantity(
    po: dict, shipped_quantity: float | None, item_code: str | None = None
) -> dict:
    """Return {status, reason, item_code, po_quantity, shipped_quantity, difference, unit_note}."""
    result = {
        "status": "cannot_compare",
        "reason": "",
        "item_code": None,
        "po_quantity": None,
        "shipped_quantity": shipped_quantity,
        "difference": None,
        "unit_note": _NO_UNIT,
    }
    totals = _distinct_items(po)
    if shipped_quantity is None:
        result["reason"] = (
            "No single shipped quantity to compare (several items or not found in the document). "
            "Review each item line against the order."
        )
        return result
    if not totals:
        result["reason"] = "The purchase order has no items."
        return result

    if item_code:
        key = item_code.strip().upper()
        if key not in totals:
            result["reason"] = f"{item_code} is not on this purchase order."
            return result
    elif len(totals) == 1:
        key = next(iter(totals))
    else:
        result["reason"] = (
            "This order has several items, so a single shipped quantity cannot be matched to one line. "
            "Pick the item, or review per line."
        )
        return result

    po_qty = totals[key]
    diff = shipped_quantity - po_qty
    status = "match" if diff == 0 else ("over_shipped" if diff > 0 else "under_shipped")
    result.update(
        {
            "status": status,
            "reason": "",
            "item_code": key,
            "po_quantity": po_qty,
            "difference": diff,
        }
    )
    return result
