"""Small deterministic clean-up and validation applied after the model returns.

Only rules that reliably add value without re-guessing the document: tidy the string arrays,
normalise the unit code, and guarantee a field-level warning for every missing core field so the
buyer always sees "not found" rather than a silently blank field. The model is asked to flag
ambiguous values itself; `is_ambiguous_numeric_date` is exposed for tests and belt-and-braces use.
"""

import re

from .schemas import ExtractionDraft, FieldIssue

_UNIT_ALIASES = {
    "EA": {"EA", "EACH", "PC", "PCS", "PCE", "PIECE", "PIECES", "UNIT", "UNITS"},
    "PR": {"PR", "PAIR", "PAIRS"},
    "SF": {"SF", "SQFT", "SQ FT", "SQUARE FEET"},
    "KG": {"KG", "KGS", "KILOGRAM", "KILOGRAMS"},
    "MG": {"MG"},
    "G": {"G", "GRAM", "GRAMS"},
    "LB": {"LB", "LBS", "POUND", "POUNDS"},
    "M": {"M", "METER", "METERS", "METRE", "METRES"},
    "BOX": {"BOX", "BOXES", "BX"},
}
_UNIT_LOOKUP = {alias: canon for canon, aliases in _UNIT_ALIASES.items() for alias in aliases}

# A core field and the severity its "not found" note carries (serial numbers are a soft info note,
# matching the packing-list reference where a missing serial is not a problem).
_MISSING: list[tuple[str, str]] = [
    ("ship_date", "warning"),
    ("carrier", "warning"),
    ("shipped_quantity", "warning"),
    ("unit_of_measure", "warning"),
    ("lot_numbers", "info"),
    ("serial_numbers", "info"),
]

_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})\s*$")

# A gross weight or a package count is never an item quantity. If the model put one in
# shipped_quantity we blank it and say why, so the supplier enters a real item count.
_WEIGHT_UNITS = {"KG", "G", "MG", "LB", "TON", "TONNE", "CBM", "M3"}
_PACKAGING_UNITS = {
    "CTN",
    "CTNS",
    "CARTON",
    "CARTONS",
    "PKG",
    "PKGS",
    "PACKAGE",
    "PACKAGES",
    "PALLET",
    "PALLETS",
    "CONTAINER",
    "CONTAINERS",
}


def normalize_unit(raw: str | None) -> str | None:
    """Map a unit spelling to a canonical code; unknown units are upper-cased, blank -> None."""
    if raw is None:
        return None
    s = raw.strip().upper()
    if not s:
        return None
    return _UNIT_LOOKUP.get(s, _UNIT_LOOKUP.get(s.replace(" ", ""), s))


def clean_list(values: list[str] | None) -> list[str]:
    """Strip, drop empties, de-duplicate while keeping order."""
    out: list[str] = []
    for v in values or []:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def is_ambiguous_numeric_date(raw: str | None) -> bool:
    """True for a purely numeric date whose day and month could be swapped (both <= 12)."""
    if not raw:
        return False
    m = _NUMERIC_DATE.match(raw)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return 1 <= a <= 12 and 1 <= b <= 12 and a != b


def _has_issue(draft: ExtractionDraft, field: str, *codes: str) -> bool:
    return any(i.field == field and (not codes or i.code in codes) for i in draft.field_issues)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def _reject_weight_or_package_quantity(draft: ExtractionDraft) -> None:
    """A gross weight or package/carton count is not an item quantity: blank it and explain."""
    if draft.shipped_quantity is None:
        return
    unit = (draft.unit_of_measure or "").upper()
    if unit in _WEIGHT_UNITS:
        code = "weight_not_item_quantity"
        msg = (
            f"The quantity on the document is a gross weight ({draft.shipped_quantity:g} {unit}), "
            "not an item count. Enter the shipped item quantity if the document states one."
        )
    elif unit in _PACKAGING_UNITS:
        code = "packaging_not_item_quantity"
        msg = (
            f"The document gives a package/carton count ({draft.shipped_quantity:g} {unit}), not an "
            "item quantity. Enter the shipped item quantity if known."
        )
    else:
        return
    draft.shipped_quantity = None
    if not _has_issue(draft, "shipped_quantity", code):
        draft.field_issues.append(
            FieldIssue(field="shipped_quantity", severity="review", code=code, message=msg)
        )


def _fix_mixed_units(draft: ExtractionDraft) -> None:
    """Drop a 'mixed_units' flag when the line items actually share one unit; keep the 'multiple
    items' reason so a blank shipped total is still explained."""
    if not _has_issue(draft, "shipped_quantity", "mixed_units"):
        return
    units = {normalize_unit(it.unit_of_measure) for it in draft.items if it.unit_of_measure}
    if len(units) > 1:
        return  # genuinely mixed; leave it
    draft.field_issues = [
        i
        for i in draft.field_issues
        if not (i.field == "shipped_quantity" and i.code == "mixed_units")
    ]
    codes = {it.item_number for it in draft.items if it.item_number}
    if len(codes) >= 2 and not _has_issue(draft, "shipped_quantity", "multiple_items"):
        draft.field_issues.append(
            FieldIssue(
                field="shipped_quantity",
                severity="review",
                code="multiple_items",
                message="The document lists several different items, so there is no single shipped total. Enter the quantity per line.",
            )
        )


def finalize(draft: ExtractionDraft) -> ExtractionDraft:
    """Tidy arrays, normalise the unit, and ensure a warning exists for every missing core field."""
    draft.tracking_numbers = clean_list(draft.tracking_numbers)
    draft.lot_numbers = clean_list(draft.lot_numbers)
    draft.serial_numbers = clean_list(draft.serial_numbers)
    draft.unit_of_measure = normalize_unit(draft.unit_of_measure)
    if draft.carrier is not None and not draft.carrier.strip():
        draft.carrier = None

    _reject_weight_or_package_quantity(draft)
    _fix_mixed_units(draft)

    for field, severity in _MISSING:
        value = getattr(draft, field)
        # Add a "not found" note only when the field is empty AND the model raised no issue of its
        # own for it (e.g. shipped_quantity already flagged multiple_items, or unit_not_stated),
        # so the buyer never sees two notes for the same field.
        if _is_empty(value) and not _has_issue(draft, field):
            draft.field_issues.append(
                FieldIssue(
                    field=field,
                    severity=severity,  # type: ignore[arg-type]
                    code="not_found",
                    message=f"No {field.replace('_', ' ')} found in the document. Check the file or enter it yourself.",
                )
            )
    return draft
