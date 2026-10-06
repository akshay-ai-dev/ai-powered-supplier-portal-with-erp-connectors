"""Output schema and value normalisation rules for packing-list extraction.

Everything here is a pure function so it can be unit-tested without Docling.
No network calls, no LLMs: every decision is a readable rule.
"""

from __future__ import annotations

import re
from datetime import date

EXTRACTOR_VERSION = "0.2.0"

CORE_FIELDS = (
    "shipDate",
    "carrier",
    "trackingNumbers",
    "shippedQuantity",
    "unitOfMeasure",
    "lotNumbers",
    "serialNumbers",
)


def empty_result(source_file: str) -> dict:
    """The JSON draft returned for every document. Missing values stay null / []."""
    return {
        "sourceFile": source_file,
        "extractorVersion": EXTRACTOR_VERSION,
        "shipDate": None,
        "carrier": None,
        "trackingNumbers": [],
        "shippedQuantity": None,
        "unitOfMeasure": None,
        "lotNumbers": [],
        "serialNumbers": [],
        "sublots": [],
        "items": [],
        "quantitySummary": [],
        "references": {},
        "shippingDetails": {
            "serviceLevel": None,
            "shipMethodRaw": None,
            "freightTerms": [],
            "packageCount": None,
            "packages": [],
        },
        "rawValues": {},
        "fieldIssues": [],
        "evidence": {},
        "document": {},
        "timings": {},
    }


def make_issue(field, code, message, severity="review", raw=None, page=None) -> dict:
    """severity: 'review' = supplier must check; 'warning' = missing/weak; 'info' = note."""
    issue = {"field": field, "severity": severity, "code": code, "message": message}
    if raw is not None:
        issue["rawValue"] = raw
    if page is not None:
        issue["page"] = page
    return issue


# --------------------------------------------------------------------------- numbers

_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?|[-+]?\.\d+")


def parse_number(text):
    """'1,500.00' -> 1500.0, '750.0000' -> 750.0. Returns None if no number."""
    if text is None:
        return None
    s = str(text).strip()
    # European style 1.500,25
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", s):
        s = s.replace(".", "").replace(",", ".")
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def is_number_token(text) -> bool:
    return bool(re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?", str(text).strip()))


# --------------------------------------------------------------------------- units

_UNIT_ALIASES = {
    "PR": {"PR", "PRS", "PAIR", "PAIRS", "PAIR(S)", "PR(S)"},
    "SF": {"SF", "SQFT", "SQ FT", "SQ.FT.", "SQ. FT.", "FT2", "SQUARE FEET", "SQUARE FOOT"},
    "EA": {"EA", "EACH", "PC", "PCS", "PCE", "PIECE", "PIECES", "PIECE(S)", "UNIT", "UNITS", "UNIT(S)"},
    "LB": {"LB", "LBS", "LB(S)", "POUND", "POUNDS"},
    "KG": {"KG", "KGS", "KILOGRAM", "KILOGRAMS"},
    "BOX": {"BOX", "BOXES", "BX"},
    "CS": {"CS", "CASE", "CASES"},
    "CTN": {"CTN", "CTNS", "CARTON", "CARTONS"},
    "RL": {"RL", "ROLL", "ROLLS"},
    "FT": {"FT", "FEET", "FOOT", "LF"},
    "M": {"M", "METER", "METERS", "METRE", "METRES"},
    "L": {"L", "LTR", "LITER", "LITRE", "LITERS", "LITRES"},
    "GAL": {"GAL", "GALLON", "GALLONS"},
    "MG": {"MG", "MGS", "MILLIGRAM", "MILLIGRAMS"},
    "G": {"G", "GR", "GRAM", "GRAMS"},
    "UG": {"UG", "MCG", "µG", "MICROGRAM", "MICROGRAMS"},
    "ML": {"ML", "MILLILITER", "MILLILITRE", "MILLILITERS", "MILLILITRES"},
    "OZ": {"OZ", "OUNCE", "OUNCES"},
    "SET": {"SET", "SETS"},
    "KIT": {"KIT", "KITS"},
}
_UNIT_LOOKUP = {alias: canon for canon, aliases in _UNIT_ALIASES.items() for alias in aliases}


def normalize_unit(raw):
    """Map a unit spelling to a canonical code. Unknown units are returned upper-cased."""
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip().upper()).strip(" .:")
    if not s:
        return None
    return _UNIT_LOOKUP.get(s, _UNIT_LOOKUP.get(s.replace(" ", ""), s))


def is_known_unit(raw) -> bool:
    if raw is None:
        return False
    s = re.sub(r"\s+", " ", str(raw).strip().upper()).strip(" .:")
    return s in _UNIT_LOOKUP or s.replace(" ", "") in _UNIT_LOOKUP


_QTY_UNIT_RE = re.compile(r"^\s*(?P<num>[-+]?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>[A-Za-z][A-Za-z().]*)?")


def parse_quantity_with_unit(text):
    """'750.0000 SF Net Weight' -> (750.0, 'SF', '750.0000 SF'). Unit only if it is a known unit."""
    if not text:
        return None, None, None
    m = _QTY_UNIT_RE.match(str(text))
    if not m:
        return None, None, None
    qty = parse_number(m.group("num"))
    unit = m.group("unit")
    if unit and not is_known_unit(unit):
        unit = None
    raw = m.group(0).strip() if unit else m.group("num")
    return qty, normalize_unit(unit), raw


# --------------------------------------------------------------------------- dates

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")]
    )
    for m in names
}


def _year(y: str):
    yi = int(y)
    if len(y) == 2:
        return 2000 + yi if yi < 70 else 1900 + yi, True
    return yi, False


def _safe_date(y, m, d):
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_date(raw, prefer="MDY"):
    """Parse a document date without guessing silently.

    Returns dict(iso, raw, ambiguous, alternatives, notes) or None if not a date.
    Numeric dates where both day and month are <= 12 are flagged ambiguous;
    `prefer` decides which reading is put in `iso` (MDY for US documents).
    """
    if raw is None:
        return None
    s = str(raw).strip().strip(":").strip()
    notes = []

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        iso = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return iso and {"iso": iso, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}

    # 01-Oct-20, 26 Aug 2022, 16-JAN-2024
    m = re.search(r"\b(\d{1,2})[\s\-./]+([A-Za-z]{3,9})\.?[\s\-./,]+(\d{2,4})\b", s)
    if m and m.group(2).lower() in _MONTHS:
        y, two = _year(m.group(3))
        if two:
            notes.append("two-digit year interpreted as %d" % y)
        iso = _safe_date(y, _MONTHS[m.group(2).lower()], int(m.group(1)))
        return iso and {"iso": iso, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}

    # January 16, 2024 / Aug 26 2022
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})\b", s)
    if m and m.group(1).lower() in _MONTHS:
        y, two = _year(m.group(3))
        if two:
            notes.append("two-digit year interpreted as %d" % y)
        iso = _safe_date(y, _MONTHS[m.group(1).lower()], int(m.group(2)))
        return iso and {"iso": iso, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}

    # 2/7/2024, 04/11/2025, 16.01.24
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        y, two = _year(m.group(3))
        if two:
            notes.append("two-digit year interpreted as %d" % y)
        mdy = _safe_date(y, a, b)
        dmy = _safe_date(y, b, a)
        if mdy and not dmy:
            return {"iso": mdy, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}
        if dmy and not mdy:
            return {"iso": dmy, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}
        if mdy and dmy:
            if mdy == dmy:
                return {"iso": mdy, "raw": s, "ambiguous": False, "alternatives": [], "notes": notes}
            first, second = (mdy, dmy) if prefer == "MDY" else (dmy, mdy)
            notes.append("numeric date could be month/day or day/month; %s reading used" % prefer)
            return {"iso": first, "raw": s, "ambiguous": True, "alternatives": [second], "notes": notes}
    return None


# --------------------------------------------------------------------------- carriers

_CARRIERS = [
    ("FedEx", re.compile(r"\bfed\s*-?\s*ex|\bfdx|federal\s+express", re.I)),
    ("UPS", re.compile(r"\bups(?!\w*\s*store)|united\s+parcel", re.I)),
    ("USPS", re.compile(r"\busps\b|postal\s+service", re.I)),
    ("DHL", re.compile(r"\bdhl", re.I)),
    ("TNT", re.compile(r"\btnt\b", re.I)),
    ("Purolator", re.compile(r"\bpurolator", re.I)),
    ("Canada Post", re.compile(r"canada\s+post", re.I)),
    ("OnTrac", re.compile(r"\bontrac", re.I)),
]
_SERVICE_RE = re.compile(
    r"(standard\s+overnight|priority\s+overnight|first\s+overnight|2\s*-?\s*day|next\s+day(\s+air)?|"
    r"ground|gnd|express|economy|freight|air|ocean|sea)", re.I)
_COLLECTION_RE = re.compile(r"\b(collection|customer\s+pick\s*-?\s*up|will\s+call|pick\s*-?\s*up)\b", re.I)
FREIGHT_TERM_RE = re.compile(
    r"\b(freight\s+)?(collect|prepaid|pre-paid|ppd|third\s+party|3rd\s+party)\b", re.I)


def normalize_carrier(raw):
    """Return (carrier, service_level, note). carrier is None for customer collection."""
    if not raw:
        return None, None, None
    text = re.sub(r"\s+", " ", str(raw)).strip(" :-")
    if _COLLECTION_RE.search(text):
        return None, None, "customer_collection"
    service = None
    sm = _SERVICE_RE.search(text)
    for name, rx in _CARRIERS:
        if rx.search(text):
            if sm:
                service = sm.group(0).upper()
            return name, service, None
    # Not a known parcel carrier: keep the stated name (e.g. a freight forwarder).
    cleaned = re.sub(r"\s*#.*$", "", text).strip()
    return (cleaned or None), None, "carrier_not_in_reference_list"


def known_carrier(text):
    """Name of a recognised parcel carrier mentioned in text, else None."""
    for name, rx in _CARRIERS:
        if rx.search(text or ""):
            return name
    return None


def split_freight_terms(value):
    """'DPL/LOGIFISH FREIGHT Collect' -> ('DPL/LOGIFISH', 'FREIGHT COLLECT')."""
    if not value:
        return value, None
    m = FREIGHT_TERM_RE.search(value)
    if not m:
        return value, None
    term = re.sub(r"\s+", " ", m.group(0)).upper()
    rest = (value[: m.start()] + value[m.end():]).strip(" ,;-")
    if re.search(r"\bfreight$", rest, re.I) and not term.startswith("FREIGHT"):
        rest = re.sub(r"\s*\bfreight$", "", rest, flags=re.I).strip()
        term = "FREIGHT " + term
    return rest, term


# --------------------------------------------------------------------------- identifiers

TRACKING_FORMATS = [
    ("UPS", re.compile(r"1Z[0-9A-Z]{16}")),
    ("FedEx", re.compile(r"\d{12}|\d{15}|\d{20}|\d{22}")),
    ("USPS", re.compile(r"9[1-5]\d{18,20}|[A-Z]{2}\d{9}US")),
    ("DHL", re.compile(r"\d{10}|JJD\d{18}")),
]


def tracking_format_carriers(value):
    """Carriers whose published tracking-number format the value matches."""
    v = re.sub(r"[\s-]", "", str(value)).upper()
    return [name for name, rx in TRACKING_FORMATS if rx.fullmatch(v)]


# Label text -> identifier type. Order matters: first match wins.
LABEL_TYPES = [
    ("tracking", r"tracking\s*(?:no\.?|number|#)?|air\s*waybill|waybill|awb|pro\s*(?:no\.?|number|#)"),
    ("bill_of_lading", r"bill\s*of\s*lading|b/l\s*(?:no\.?|#)?|bol\s*(?:no\.?|#)?"),
    ("purchase_order", r"(?:cust(?:omer)?\.?\s*)?p\.?\s*o\.?(?!\s*box)\s*(?:#|no\.?|number)?|purchase\s*order\s*(?:#|no\.?|number)?"),
    ("sales_order", r"sales\s*order\s*(?:no\.?|#|number)?|s\.?o\.?\s*#|order\s*(?:no\.?|#|number)"),
    ("invoice", r"invoice\s*(?:no\.?|#|number)?"),
    ("packing_slip", r"packing\s*slip\s*(?:no\.?|#|number)?|delivery\s*note\s*(?:no\.?|#)?|our\s*reference"),
    ("internal_shipping", r"shipping\s*(?:no\.?|number)|shipment\s*id(?:\s*no\.?)?|load\s*id(?:\s*no\.?)?|cust\.?\s*ship\s*#"),
    ("customer_reference", r"your\s*reference"),
    ("account", r"account\s*(?:no\.?|#|number)|customer\s*(?:no\.?|#|number)|customer"),
    ("package_count", r"number\s*of\s*packages|no\.?\s*of\s*(?:packages|cartons|boxes|pieces)|total\s*shipping\s*units|packages|cartons"),
    ("freight_terms", r"freight\s*terms|shipping\s*terms|delivery\s*terms|f\.?\s*o\.?\s*b\.?|incoterms?"),
]
_LABEL_TYPE_RES = [(t, re.compile(r"^\s*(?:" + p + r")\s*[:#.]?\s*$", re.I)) for t, p in LABEL_TYPES]


def label_type(label):
    for t, rx in _LABEL_TYPE_RES:
        if rx.match(label or ""):
            return t
    return None


def classify_identifier(value, label=None, column_header=None, carrier=None):
    """Decide what an identifier is from its label/column context and its format.

    Returns dict(type, isTracking, ambiguous, reason). The label decides first;
    format alone never turns an order/invoice/shipping number into a tracking number.
    """
    v = (value or "").strip()
    ctx = (column_header or label or "").strip()
    if not v:
        return {"type": None, "isTracking": False, "ambiguous": False, "reason": "empty value"}
    if FREIGHT_TERM_RE.fullmatch(v) or re.fullmatch(r"(?i)(fob|exw|ddp|dap|fca|cif)\b.*", v):
        return {"type": "freight_terms", "isTracking": False, "ambiguous": False,
                "reason": "value is a freight/delivery term"}
    if not re.search(r"\d", v):
        return {"type": "text", "isTracking": False, "ambiguous": False, "reason": "no digits"}

    ltype = label_type(ctx) if ctx else None
    if column_header and re.search(r"tracking", column_header, re.I):
        ltype = "tracking"
    compact = re.sub(r"[\s-]", "", v)

    if ltype == "tracking":
        fmts = tracking_format_carriers(compact)
        if not re.fullmatch(r"[0-9A-Za-z]{8,35}", compact):
            return {"type": "tracking", "isTracking": False, "ambiguous": True,
                    "reason": "under a tracking label but not a plausible tracking-number shape"}
        if carrier and fmts and carrier not in fmts:
            return {"type": "tracking", "isTracking": True, "ambiguous": True,
                    "reason": f"format looks like {'/'.join(fmts)} but carrier is {carrier}"}
        return {"type": "tracking", "isTracking": True, "ambiguous": False,
                "reason": "labelled as tracking" + (f"; matches {'/'.join(fmts)} format" if fmts else "")}

    if ltype:
        return {"type": ltype, "isTracking": False, "ambiguous": False,
                "reason": f"label '{ctx}' identifies a {ltype.replace('_', ' ')}, not a tracking number"}

    # Carrier name used as a label, e.g. "FED EX# 149752137": could be an account or a tracking number.
    name = known_carrier(ctx) if ctx else None
    if name and re.fullmatch(r"(?i)[a-z .\-]{2,20}#?", ctx):
        fmts = tracking_format_carriers(compact)
        if name in fmts:
            return {"type": "tracking", "isTracking": True, "ambiguous": True,
                    "reason": f"follows '{ctx}' and matches the {name} tracking format; confirm"}
        return {"type": "carrier_reference", "isTracking": False, "ambiguous": True,
                "reason": f"follows '{ctx}' but does not match a {name} tracking format "
                          f"(often a carrier account number)"}

    if re.fullmatch(r"1Z[0-9A-Z]{16}", compact.upper()):
        return {"type": "tracking", "isTracking": True, "ambiguous": True,
                "reason": "unlabelled but matches the UPS 1Z format; confirm"}
    return {"type": "unknown", "isTracking": False, "ambiguous": True,
            "reason": "no label identifies this number"}


def clean_lot_value(raw):
    """Return (lot_id, problem). Strips prefixes like 'Rf:' or 'LOT:'; rejects bare (123)."""
    if raw is None:
        return None, "empty"
    s = str(raw).strip()
    if re.fullmatch(r"\(\s*[\d.,]+\s*\)", s):
        return None, "parenthesised number: may be a quantity or reference, not a lot/serial"
    s = re.sub(r"^(?:(?:lot|batch|sublot|serial|ref|rf)\s*(?:no\.?|number|#)?\s*[:#]\s*)+", "", s, flags=re.I)
    token = s.split()[0].strip(",;") if s.split() else ""
    if not token or not re.search(r"\d", token):
        return None, "no identifier with digits"
    if len(token) > 40:
        return None, "too long for a lot number"
    return token, None


def split_composite_lot(identifier):
    """'US310197LOT2401' -> ('US310197', '2401'): sublot with embedded parent lot."""
    m = re.fullmatch(r"(?P<sub>[A-Z0-9][A-Z0-9-]*?)LOT(?P<lot>[A-Z0-9][A-Z0-9-]*)", identifier or "", re.I)
    if m and re.search(r"\d", m.group("sub")) and re.search(r"\d", m.group("lot")):
        return m.group("sub"), m.group("lot")
    return identifier, None


def is_code_like(text) -> bool:
    """An item/part number: a single token that contains a digit (e.g. NAL31016, 10Y1532-9.75A)."""
    t = (text or "").strip()
    return bool(t) and " " not in t and bool(re.search(r"\d", t)) and len(t) <= 40


def norm_key(text):
    return re.sub(r"[\s\-_.]", "", str(text or "")).upper() or None
