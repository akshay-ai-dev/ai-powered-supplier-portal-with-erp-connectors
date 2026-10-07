"""Rule-based packing-list extraction over a Docling layout.

    from extractor import extract_pdf
    draft = extract_pdf("samples/pdf-1.pdf")

Pipeline: Docling conversion (layout.py) -> rules below -> JSON draft (fields.empty_result).
All rules are generic (labels, column headers, value formats); nothing is keyed to a
particular file or supplier. Every extracted value carries page evidence, and anything
that cannot be decided safely is reported in `fieldIssues` instead of being guessed.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .fields import (
    CORE_FIELDS,
    FREIGHT_TERM_RE,
    LABEL_TYPES,
    classify_identifier,
    clean_lot_value,
    empty_result,
    is_code_like,
    is_known_unit,
    make_issue,
    norm_key,
    normalize_carrier,
    normalize_unit,
    parse_date,
    parse_number,
    parse_quantity_with_unit,
    split_composite_lot,
    split_freight_terms,
)
from .layout import (
    QTY_ROLES,
    assign_columns,
    convert_pdf,
    find_label_values,
    find_tables,
    right_neighbor_text,
)

SHIP_DATE_LABEL = (
    r"ship(?:ped|ment|ping)?\s*date|date\s*shipped|dispatch(?:ed)?\s*date|"
    r"despatch\s*date|date\s+of\s+shipment"
)
CARRIER_LABELS = [  # (pattern, value may follow label without a colon)
    (r"carrier(?:\s*/\s*f\.?\s*forward(?:er)?)?|freight\s*forwarder", False),
    (r"ship\s*via|shipped\s*via", True),
    (r"ship(?:ping)?\s*method", False),
    (r"delivery\s*method", False),
]
LOT_LABEL = r"lot\s*(?:no\.?|number|#)|lot|batch\s*(?:no\.?|number|#)?"
SERIAL_LABEL = r"serial\s*(?:no\.?|number|#)|s/n"
QTY_LABEL = r"(?:qty|quantity)\s*shipped|shipped\s*(?:qty|quantity)|total\s*qty|quantity|qty"
ITEM_LABEL = r"item(?:\s*(?:no\.?|number|#))?|part\s*(?:no\.?|number|#)"

GROUP_ROW_RE = re.compile(
    r"^\s*sales\s*order\s*(?:no\.?|#|number)?\s*[:#]\s*(?P<so>[A-Z0-9][\w\-/]*)", re.I
)
YOUR_REF_RE = re.compile(r"your\s*reference\s*[:#]\s*(?P<ref>[A-Z0-9][\w\-/]*)", re.I)
TOTAL_ROW_RE = re.compile(r"\btotals?\b|<<\s*totals\s*>>", re.I)
LOT_ROW_RE = re.compile(
    r"^\s*(?:lot|batch|sublot)\s*(?:number|no\.?|#)?\s*[:#]\s*(?:lot\s*[:#]\s*)?(?P<id>[A-Z0-9][\w\-./]*)",
    re.I,
)
INLINE_LOT_RE = re.compile(r"\blot\s*(?:no\.?|number|#)?\s*[:#]\s*(?P<id>[A-Z0-9][\w\-./]*)", re.I)
BATCH_QTY_RE = re.compile(
    r"batch\s*(?:no\.?|number|#)?\s*[:#]?\s*(?P<id>[A-Z0-9][\w\-./]*?)\s*,?\s*(?:quantity|qty)\s*[:#]?\s*(?P<q>[\d.,]+)",
    re.I,
)
CUST_PN_RE = re.compile(
    r"cust(?:omer)?\.?\s*(?:p/?n|part\s*(?:no\.?|number|#)?)\s*[:#]\s*(?P<pn>\S+)", re.I
)
QTY_INLINE_RE = re.compile(r"\b(?:qty|quantity)\s*[:#]?\s*(?P<q>\d[\d,]*(?:\.\d+)?)", re.I)
CARRIER_REF_RE = re.compile(
    r"(?P<label>fed\s*-?\s*ex|fdx|ups|dhl|usps)\s*(?:#|no\.?|acct\.?|account)\s*[:#]?\s*(?P<num>[0-9A-Z]{6,})",
    re.I,
)
UPS_1Z_RE = re.compile(r"\b1Z[0-9A-Z]{16}\b")
SUBLOT_COUNT_RE = re.compile(r"\b(?:sublot|roll)\s*count\s*[:#]?\s*(?P<n>\d+)\b", re.I)
FREIGHT_VALUE_RE = re.compile(
    r"collect|prepaid|pre-paid|third\s*party|origin|destination|\b(EXW|FOB|FCA|CPT|CIP|DAP|DPU|DDP|DDU|FAS|CFR|CIF)\b",
    re.I,
)

REFERENCE_KEYS = {
    "purchase_order": "purchaseOrders",
    "sales_order": "salesOrders",
    "invoice": "invoices",
    "packing_slip": "packingSlips",
    "internal_shipping": "internalShippingNumbers",
    "customer_reference": "customerReferences",
    "account": "accountNumbers",
    "bill_of_lading": "billsOfLading",
}


class _Ctx:
    def __init__(self, layout):
        self.layout = layout
        self.r = empty_result(layout.source_file)
        self.packing_pages = {p.number for p in layout.pages if p.page_type == "packing"}
        self.packages = []
        self.prefer = _date_preference(layout)

    def issue(self, *a, **k):
        iss = make_issue(*a, **k)
        if iss not in self.r["fieldIssues"]:
            self.r["fieldIssues"].append(iss)

    def evidence(self, fld, page, text, rule):
        ev = {"page": page, "text": text, "rule": rule}
        lst = self.r["evidence"].setdefault(fld, [])
        if ev not in lst:
            lst.append(ev)

    def flagged(self, fld):
        return any(i["field"] == fld for i in self.r["fieldIssues"])


def _date_preference(layout):
    text = "\n".join(ln.text for ln in layout.lines())
    us = re.search(r"\bUSA\b|United States|\b[A-Z]{2},?\s+\d{5}(?:-\d{4})?\b", text)
    eu = re.search(
        r"\b(UNITED KINGDOM|GREAT BRITAIN|ENGLAND|GERMANY|BELGIUM|FRANCE|NETHERLANDS)\b", text, re.I
    )
    return "DMY" if eu and not us else "MDY"


# --------------------------------------------------------------------------- public API


def extract_pdf(pdf_path) -> dict:
    t0 = time.perf_counter()
    layout, conv_t = convert_pdf(pdf_path)
    t1 = time.perf_counter()
    result = extract_from_layout(layout)
    t2 = time.perf_counter()
    result["timings"] = {
        **conv_t,
        "extractionSeconds": round(t2 - t1, 3),
        "totalSeconds": round(t2 - t0, 3),
    }
    result["_layout"] = layout  # removed by callers before saving; kept for markdown export
    return result


def extract_from_layout(layout) -> dict:
    c = _Ctx(layout)
    _ship_date(c)
    _carrier(c)
    _references(c)
    _tracking(c)
    _items_and_quantities(c)
    _packages(c)
    _lots_and_serials(c)
    _missing(c)
    c.r["document"] = {
        "pageCount": layout.page_count,
        "pageTypes": {str(p.number): p.page_type for p in layout.pages},
        "textLayer": layout.text_layer,
        "ocrUsed": layout.ocr_used,
        "doclingTableCount": layout.docling_table_count,
        "datePreference": c.prefer,
    }
    return c.r


# --------------------------------------------------------------------------- ship date


def _ship_date(c):
    def is_date(v):
        return parse_date(v, c.prefer) is not None

    hits = find_label_values(c.layout, SHIP_DATE_LABEL, validator=is_date)
    parsed = [(h, parse_date(h.value, c.prefer)) for h in hits]
    inferred = False
    if not parsed:
        doc_hits = find_label_values(
            c.layout, r"date", pages=c.packing_pages or None, validator=is_date
        )
        parsed = [(h, d) for h in doc_hits if (d := parse_date(h.value, c.prefer))]
        inferred = bool(parsed)
    if not parsed:
        return
    parsed.sort(key=lambda hd: (hd[0].page not in c.packing_pages, hd[0].page))
    h, d = parsed[0]
    c.r["shipDate"] = d["iso"]
    c.r["rawValues"]["shipDate"] = d["raw"]
    for hh, _dd in parsed:
        c.evidence(
            "shipDate",
            hh.page,
            hh.source_text,
            "document date label (no ship-date label found)"
            if inferred
            else f"ship-date label ({hh.how})",
        )
    isos = {dd["iso"] for _, dd in parsed}
    if len(isos) > 1:
        c.issue(
            "shipDate",
            "conflicting_dates",
            f"Different ship dates found: {sorted(isos)}",
            raw=d["raw"],
        )
    if inferred:
        c.issue(
            "shipDate",
            "inferred_from_document_date",
            "No ship-date label; the document DATE was used. Confirm it is the ship date.",
            raw=d["raw"],
            page=h.page,
        )
    if d["ambiguous"]:
        c.issue(
            "shipDate",
            "ambiguous_date",
            f"'{d['raw']}' can be read as {d['iso']} or {d['alternatives'][0]}; "
            f"{c.prefer} assumed from document context.",
            raw=d["raw"],
            page=h.page,
        )
    for n in d["notes"]:
        if "two-digit" in n:
            c.issue("shipDate", "two_digit_year", n, severity="info", raw=d["raw"], page=h.page)


# --------------------------------------------------------------------------- carrier


def _carrier(c):
    found = []
    for pattern, no_colon in CARRIER_LABELS:
        for h in find_label_values(c.layout, pattern, inline_without_colon=no_colon):
            value = h.value
            page = next(p for p in c.layout.pages if p.number == h.page)
            right = right_neighbor_text(page, h.line) if h.how == "inline" else None
            if right and FREIGHT_TERM_RE.fullmatch(right.strip()):
                value = f"{value} {right.strip()}"
            value, term = split_freight_terms(value)
            if term:
                _add_unique(c.r["shippingDetails"]["freightTerms"], term)
                c.evidence(
                    "freightTerms", h.page, h.source_text, "freight term next to ship-via value"
                )
            name, service, note = normalize_carrier(value)
            found.append((pattern, h, value, name, service, note))
    if not found:
        return
    pattern, h, value, name, service, note = found[0]
    c.r["rawValues"]["carrier"] = value
    c.r["shippingDetails"]["shipMethodRaw"] = value
    c.r["shippingDetails"]["serviceLevel"] = service
    c.evidence("carrier", h.page, h.source_text, f"carrier label ({h.how})")
    if note == "customer_collection":
        c.issue(
            "carrier",
            "customer_collection",
            f"Delivery method '{value}' indicates customer collection; no carrier named.",
            raw=value,
            page=h.page,
        )
        return
    c.r["carrier"] = name
    if note == "carrier_not_in_reference_list":
        c.issue(
            "carrier",
            "carrier_not_in_reference_list",
            f"'{name}' is not a recognised parcel carrier; kept as written.",
            severity="info",
            raw=value,
            page=h.page,
        )
    others = {n for _, _, _, n, _, nt in found[1:] if n and nt is None}
    if c.r["carrier"] and others - {c.r["carrier"]}:
        c.issue(
            "carrier",
            "conflicting_carriers",
            f"Other carrier names also appear: {sorted(others)}",
            raw=value,
        )
    for _, hh, _, n, _, _ in found[1:]:
        if n:
            c.evidence("carrier", hh.page, hh.source_text, "secondary carrier mention")


# --------------------------------------------------------------------------- reference numbers


def _contains_digit(value):
    return re.search(r"\d", value)


def _references(c):
    refs = c.r["references"]
    details = c.r["shippingDetails"]
    for ltype, pattern in LABEL_TYPES:
        if ltype == "tracking":
            continue
        if ltype == "freight_terms":
            validator = FREIGHT_VALUE_RE.search
        elif ltype == "package_count":
            validator = parse_number
        else:
            validator = _contains_digit
        for h in find_label_values(c.layout, pattern, validator=validator):
            if ltype == "freight_terms":
                _add_unique(details["freightTerms"], re.sub(r"\s+", " ", h.value).upper())
                c.evidence("freightTerms", h.page, h.source_text, f"label '{h.label}'")
                continue
            if ltype == "package_count":
                n = parse_number(h.value)
                if n and details["packageCount"] is None:
                    details["packageCount"] = int(n) if float(n).is_integer() else n
                    c.evidence(
                        "packageCount",
                        h.page,
                        h.source_text,
                        "package count (never used as product quantity)",
                    )
                continue
            token = re.split(r"[\s,;]+", h.value.strip())[0].strip("*")
            cls = classify_identifier(token, label=h.label)
            if cls["type"] != ltype:
                continue
            key = REFERENCE_KEYS[ltype]
            entry = {"value": token, "label": h.label.strip(), "page": h.page}
            if not any(e["value"] == token for e in refs.setdefault(key, [])):
                refs[key].append(entry)


# --------------------------------------------------------------------------- tracking


def _tracking(c):
    carrier = c.r["carrier"]
    out = c.r["trackingNumbers"]

    def add(value, page, text, rule, cls):
        if cls["isTracking"]:
            if value not in out:
                out.append(value)
            c.evidence("trackingNumbers", page, text, rule)
            if cls["ambiguous"]:
                c.issue(
                    "trackingNumbers",
                    "tracking_needs_confirmation",
                    cls["reason"],
                    raw=value,
                    page=page,
                )
        elif cls["ambiguous"]:
            c.issue(
                "trackingNumbers",
                "unclassified_identifier",
                f"'{text}': {cls['reason']}. Not used as a tracking number.",
                raw=value,
                page=page,
            )

    for page in c.layout.pages:
        for tb in find_tables(page):
            col = next((x for x in tb.columns if x.role == "tracking"), None)
            if not col:
                continue
            for row in tb.rows:
                cells, _ = assign_columns(row, tb.columns)
                for tok in (cells.get("tracking") or "").split():
                    add(
                        tok,
                        page.number,
                        tok,
                        f"value in '{col.text}' column",
                        classify_identifier(tok, column_header=col.text, carrier=carrier),
                    )
    tracking_pattern = dict(LABEL_TYPES)["tracking"]
    for h in find_label_values(c.layout, tracking_pattern):
        tok = h.value.split()[0] if h.value.split() else ""
        add(
            tok,
            h.page,
            h.source_text,
            f"label '{h.label}' ({h.how})",
            classify_identifier(tok, label="tracking number", carrier=carrier),
        )
    for ln in c.layout.lines():
        for m in CARRIER_REF_RE.finditer(ln.text):
            add(
                m.group("num"),
                ln.page,
                ln.text,
                "carrier name followed by a number in free text",
                classify_identifier(m.group("num"), label=m.group("label"), carrier=carrier),
            )
        for m in UPS_1Z_RE.finditer(ln.text):
            add(
                m.group(0),
                ln.page,
                ln.text,
                "UPS 1Z pattern in free text",
                classify_identifier(m.group(0), carrier=carrier),
            )


# --------------------------------------------------------------------------- items, lots, quantities


def _new_item(page, group, page_type):
    return {
        "lineNumber": None,
        "itemNumber": None,
        "customerItemNumber": None,
        "description": None,
        "salesOrder": group.get("salesOrder"),
        "customerReference": group.get("customerReference"),
        "quantityOrdered": None,
        "quantityRequired": None,
        "quantityShipped": None,
        "quantityOutstanding": None,
        "quantityBackordered": None,
        "unitOfMeasure": None,
        "unitRaw": None,
        "quantitySource": None,
        "lots": [],
        "sublots": [],
        "serialNumbers": [],
        "lotOrSerialNumbers": [],
        "weight": None,
        "pages": [page],
        "pageType": page_type,
        "evidence": [],
    }


def _append_desc(item, text, prepend=False):
    text = (text or "").strip()
    if text:
        if not item["description"]:
            item["description"] = text
        elif prepend:
            item["description"] = f"{text} {item['description']}"
        else:
            item["description"] = f"{item['description']} {text}"


def _add_lot(c, item, raw, qty, unit, page, text):
    lot_id, problem = clean_lot_value(raw)
    if problem:
        c.issue(
            "lotNumbers",
            "ambiguous_lot_value",
            f"'{raw}' in a lot column: {problem}.",
            raw=raw,
            page=page,
        )
        return
    sub, parent = split_composite_lot(lot_id)
    if parent:
        if not any(s["sublotNumber"] == sub for s in item["sublots"]):
            item["sublots"].append(
                {
                    "sublotNumber": sub,
                    "lotNumber": parent,
                    "quantity": qty,
                    "unit": unit,
                    "rawValue": lot_id,
                    "page": page,
                }
            )
        _upsert_lot(item, parent, None, None, page)
    else:
        _upsert_lot(item, lot_id, qty, unit, page)
    item["evidence"].append({"page": page, "text": text, "rule": "lot row / lot column"})


def _upsert_lot(item, lot_id, qty, unit, page):
    for lot in item["lots"]:
        if lot["lotNumber"] == lot_id:
            if lot["quantity"] is None and qty is not None:
                lot["quantity"], lot["unit"] = qty, unit
            return
    item["lots"].append({"lotNumber": lot_id, "quantity": qty, "unit": unit, "page": page})


def _implicit_item_number(c, page_no):
    for h in find_label_values(
        c.layout, ITEM_LABEL, pages={page_no}, allow_below=False, allow_right=False
    ):
        tok = h.value.split()[0] if h.value.split() else ""
        if is_code_like(tok):
            return tok, h
    return None, None


def _parse_tables(c):
    """Read every quantity table (found by its header row) on every page, in page order."""
    lines, totals = [], []
    state = {"roles": None, "group": {}, "item": None, "pending": []}
    for page in c.layout.pages:
        for tb in find_tables(page):
            roles = tb.roles()
            if not roles & QTY_ROLES:
                continue
            if roles & {"package", "tracking"}:
                # box/carton breakdown of the shipment: per-package quantities are a split of the
                # line quantity, never extra items
                _parse_package_table(c, tb, page)
                continue
            if roles != state["roles"]:
                state.update(roles=roles, group={}, item=None, pending=[])
            if "item" not in roles:
                num, h = _implicit_item_number(c, page.number)
                cur = state["item"]
                if num and (cur is None or cur["itemNumber"] != num):
                    it = _new_item(page.number, state["group"], page.page_type)
                    it["itemNumber"] = num
                    it["evidence"].append(
                        {
                            "page": page.number,
                            "text": h.source_text,
                            "rule": "item label above a table without an item column",
                        }
                    )
                    for dh in find_label_values(
                        c.layout,
                        r"description",
                        pages={page.number},
                        allow_below=False,
                        allow_right=False,
                    ):
                        _append_desc(it, dh.value)
                        break
                    for lh in find_label_values(
                        c.layout,
                        r"line\s*(?:no\.?|#)",
                        pages={page.number},
                        allow_below=False,
                        allow_right=False,
                    ):
                        it["lineNumber"] = lh.value.replace(" ", "")
                        break
                    lines.append(it)
                    state["item"] = it
            start = len(lines)
            _parse_table_rows(c, tb, page, state, lines, totals)
            _line_numbers_in_item_column(c, tb, lines[start:])
    return lines, totals


def _parse_package_table(c, tb, page):
    for row in tb.rows:
        text = " ".join(w.text for w in row)
        if TOTAL_ROW_RE.search(text):
            continue
        cells, _ = assign_columns(row, tb.columns)
        q, unit, _ = parse_quantity_with_unit(cells.get("shipped") or cells.get("qty"))
        pkg = {
            "packageNumber": (cells.get("package") or "").split()[0]
            if cells.get("package")
            else None,
            "quantity": q,
            "unit": unit,
            "weight": parse_number(cells["weight"]) if cells.get("weight") else None,
            "trackingNumber": (cells.get("tracking") or "").split()[0]
            if cells.get("tracking")
            else None,
            "page": page.number,
            "pageType": page.page_type,
        }
        if q is not None or pkg["trackingNumber"]:
            c.packages.append(pkg)
            c.evidence("packages", page.number, text, "package/box table row")


def _row_kind(tb, row):
    text = " ".join(w.text for w in row)
    if GROUP_ROW_RE.match(text):
        return "group"
    if TOTAL_ROW_RE.search(text):
        return "total"
    if LOT_ROW_RE.match(text):
        return "lot"
    cells, _ = assign_columns(row, tb.columns)
    q, _, _ = parse_quantity_with_unit(cells.get("shipped") or cells.get("qty"))
    return "anchor" if q is not None else "text"


def _row_yc(row):
    return sum(w.yc for w in row) / len(row)


def _anchor_has_own_text(tb, row):
    cells, _ = assign_columns(row, tb.columns)
    item = cells.get("item", "")
    return bool(cells.get("description")) or (bool(item) and not is_code_like(item.split()[0]))


def _belongs_to_next_anchor(i, tb, kinds):
    """A text row printed above a quantity row belongs to it when the quantity row sits in the
    middle of a tall table cell (its own row carries no description) and the text is closer
    to it than to the previous quantity row."""
    rows = tb.rows
    nxt = next((j for j in range(i + 1, len(rows)) if kinds[j] in ("anchor", "group")), None)
    if nxt is None or kinds[nxt] != "anchor":
        return False
    prev = next((j for j in range(i - 1, -1, -1) if kinds[j] in ("anchor", "group")), None)
    if prev is None or kinds[prev] == "group":
        return True
    d_prev, d_next = _row_yc(rows[i]) - _row_yc(rows[prev]), _row_yc(rows[nxt]) - _row_yc(rows[i])
    return d_next < d_prev and not _anchor_has_own_text(tb, rows[nxt])


def _parse_table_rows(c, tb, page, state, lines, totals):
    kinds = [_row_kind(tb, r) for r in tb.rows]
    deferred = []
    for i, row in enumerate(tb.rows):
        if kinds[i] == "text" and _belongs_to_next_anchor(i, tb, kinds):
            deferred.append(row)
            continue
        _parse_row(c, tb, row, page, state, lines, totals)
        if kinds[i] == "anchor" and deferred and state["item"] is not None:
            state["prepend"] = True  # replay bottom-up so prepended text keeps reading order
            for d in reversed(deferred):
                _parse_row(c, tb, d, page, state, lines, totals)
            state["prepend"] = False
            deferred = []
    for d in deferred:  # no quantity row followed: treat as ordinary continuation text
        _parse_row(c, tb, d, page, state, lines, totals)


def _line_numbers_in_item_column(c, tb, new_items):
    """An item column holding 1, 2, ... n (one per line, in order) is a line-number column."""
    nums = [it["itemNumber"] for it in new_items if it["quantityShipped"] is not None]
    if not nums or len(nums) != len([it for it in new_items if it["quantityShipped"] is not None]):
        return
    if nums != [str(k) for k in range(1, len(nums) + 1)]:
        return
    for it in new_items:
        it["lineNumber"] = it["lineNumber"] or it["itemNumber"]
        it["itemNumber"] = None
    c.issue(
        "items",
        "item_column_holds_line_numbers",
        f"Column '{_col_text(tb, 'item')}' on page {tb.page} contains 1..{len(nums)} (line numbers), "
        f"not part numbers.",
        severity="info",
        page=tb.page,
    )


def _parse_row(c, tb, row, page, state, lines, totals):
    text = " ".join(w.text for w in row)
    cells, unassigned = assign_columns(row, tb.columns)
    unit_cell = normalize_unit(cells.get("unit")) if cells.get("unit") else None

    m = GROUP_ROW_RE.match(text)
    if m:
        ref = YOUR_REF_RE.search(text)
        state["group"] = {
            "salesOrder": m.group("so").rstrip(","),
            "customerReference": ref.group("ref") if ref else None,
        }
        state["item"] = None
        return

    qcell = cells.get("shipped") or cells.get("qty")
    q, q_unit, q_raw = parse_quantity_with_unit(qcell)
    unit = unit_cell or q_unit

    if TOTAL_ROW_RE.search(text):
        if q is None and re.search(r"\b(qty|quantity)\b", text, re.I):
            # e.g. "Total Pack List Quantity Shipped: 1,000.00" printed across columns
            nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text.split(":")[-1])
            q = parse_number(nums[-1]) if nums else None
        if q is not None:
            totals.append(
                {
                    "quantity": q,
                    "unit": unit,
                    "page": page.number,
                    "text": text,
                    "pageType": page.page_type,
                }
            )
        lm = INLINE_LOT_RE.search(text)
        if lm and state["item"] is not None:
            _add_lot(c, state["item"], lm.group("id"), q, unit, page.number, text)
            _note_page(state["item"], page.number)
        return

    item = state["item"]
    lm = LOT_ROW_RE.match(text)
    if lm:
        if item is None:
            item = state["item"] = _new_item(page.number, state["group"], page.page_type)
            lines.append(item)
        qty = (
            q
            if q is not None
            else parse_number(m2.group("q"))
            if (m2 := QTY_INLINE_RE.search(text))
            else None
        )
        _add_lot(c, item, lm.group("id"), qty, unit or item["unitOfMeasure"], page.number, text)
        _note_page(item, page.number)
        return

    if q is not None:
        item_cell = cells.get("item", "")
        first = item_cell.split()[0] if item_cell.split() else ""
        lot_cell = cells.get("lot")
        if "item" not in tb.roles() and lot_cell and item is not None:
            _add_lot(c, item, lot_cell.split()[-1], q, unit, page.number, text)
            _note_page(item, page.number)
            return
        if (
            "item" not in tb.roles()
            and item is not None
            and item["quantityShipped"] is None
            and not item["lots"]
        ):
            it = item
        else:
            it = _new_item(page.number, state["group"], page.page_type)
            lines.append(it)
        state["item"] = it
        if is_code_like(first):
            it["itemNumber"] = first
            _append_desc(it, item_cell[len(first) :])
        else:
            _append_desc(it, " ".join(state["pending"]))
            _append_desc(it, item_cell)
        state["pending"] = []
        _append_desc(it, cells.get("description"))
        if cells.get("line"):
            it["lineNumber"] = cells["line"].split()[0]
        it["quantityShipped"] = q
        it["quantitySource"] = "shipped column" if cells.get("shipped") else "quantity column"
        it["unitOfMeasure"] = unit
        it["unitRaw"] = cells.get("unit") or (q_raw if q_unit else None)
        for role, key in (
            ("ordered", "quantityOrdered"),
            ("required", "quantityRequired"),
            ("outstanding", "quantityOutstanding"),
            ("backordered", "quantityBackordered"),
        ):
            if cells.get(role):
                it[key] = parse_number(cells[role])
        if cells.get("customer_item"):
            it["customerItemNumber"] = cells["customer_item"].split()[0]
        if cells.get("weight"):
            it["weight"] = {
                "value": parse_number(cells["weight"]),
                "unit": normalize_unit(cells.get("weight_unit"))
                if cells.get("weight_unit")
                else None,
            }
        if lot_cell:
            _add_lot(c, it, lot_cell, None, unit, page.number, text)
        if cells.get("serial"):
            _add_serial(c, it, cells["serial"], page.number)
        if cells.get("lot_or_serial"):
            _lot_or_serial(c, it, cells["lot_or_serial"], q_raw, page.number, tb)
        left = [w for w in unassigned if w.r <= min(col.l for col in tb.columns)]
        if left:
            lead = " ".join(w.text for w in left)
            it["lineNumber"] = it["lineNumber"] or lead
            c.issue(
                "shippedQuantity",
                "unlabelled_leading_value",
                f"Row starts with unlabelled value '{lead}'; quantity {q_raw} was taken from the "
                f"'{_col_text(tb, 'shipped', 'qty')}' column by position. Confirm.",
                raw=text,
                page=page.number,
            )
        it["evidence"].append({"page": page.number, "text": text, "rule": "quantity table row"})
        return

    # continuation row (no quantity)
    if item is None:
        state["pending"].append(cells.get("item") or cells.get("description") or "")
        return
    sc = SUBLOT_COUNT_RE.search(text)
    if sc:
        item["_printedSublotCount"] = (int(sc.group("n")), page.number, text)
        return
    cm = CUST_PN_RE.search(text)
    if cm:
        item["customerItemNumber"] = cm.group("pn")
    bm = BATCH_QTY_RE.search(text)
    if bm:
        _add_lot(
            c,
            item,
            bm.group("id"),
            parse_number(bm.group("q")),
            item["unitOfMeasure"],
            page.number,
            text,
        )
    if not cm and not bm:
        for role in ("item", "description"):
            _append_desc(item, cells.get(role), prepend=state.get("prepend", False))
        if cells.get("lot"):
            _add_lot(c, item, cells["lot"], None, item["unitOfMeasure"], page.number, text)
        if cells.get("serial"):
            _add_serial(c, item, cells["serial"], page.number)
        if cells.get("lot_or_serial"):
            _lot_or_serial(c, item, cells["lot_or_serial"], None, page.number, tb)
    _note_page(item, page.number)


def _col_text(tb, *roles):
    for col in tb.columns:
        if col.role in roles:
            return col.text
    return "?"


def _note_page(item, page):
    if page not in item["pages"]:
        item["pages"].append(page)


def _add_serial(c, item, raw, page):
    for tok in raw.split():
        sid, problem = clean_lot_value(tok)
        if problem:
            c.issue(
                "serialNumbers",
                "ambiguous_serial_value",
                f"'{tok}' in a serial column: {problem}.",
                raw=tok,
                page=page,
            )
        elif sid not in item["serialNumbers"]:
            item["serialNumbers"].append(sid)


def _lot_or_serial(c, item, raw, qty_raw, page, tb):
    header = _col_text(tb, "lot_or_serial")
    val, problem = clean_lot_value(raw)
    if problem or (qty_raw and norm_key(val) == norm_key(qty_raw)):
        why = problem or "equals the shipped quantity on the same row"
        c.issue(
            "lotNumbers",
            "ambiguous_lot_or_serial",
            f"'{raw}' under '{header}': {why}. Not recorded as a lot or serial number.",
            raw=raw,
            page=page,
        )
        c.issue(
            "serialNumbers",
            "ambiguous_lot_or_serial",
            f"'{raw}' under '{header}': {why}. Not recorded as a lot or serial number.",
            raw=raw,
            page=page,
        )
        return
    if val not in item["lotOrSerialNumbers"]:
        item["lotOrSerialNumbers"].append(val)
    c.issue(
        "lotNumbers",
        "lot_or_serial_unresolved",
        f"'{val}' is under the combined '{header}' column; cannot tell lot from serial.",
        raw=raw,
        page=page,
    )


def _dedupe_items(c, lines):
    """Merge identical lines repeated on different pages of the same shipment."""
    out = []
    for it in lines:
        key = (
            norm_key(it["salesOrder"]),
            norm_key(it["itemNumber"]) or norm_key(it["description"]),
            it["quantityShipped"],
            it["unitOfMeasure"],
        )
        twin = next(
            (o for o in out if o["_key"] == key and not set(o["pages"]) & set(it["pages"])), None
        )
        if twin is None or it["quantityShipped"] is None:
            it["_key"] = key
            out.append(it)
            continue
        for p in it["pages"]:
            _note_page(twin, p)
        for lot in it["lots"]:
            _upsert_lot(twin, lot["lotNumber"], lot["quantity"], lot["unit"], lot["page"])
        for s in it["sublots"]:
            if not any(x["sublotNumber"] == s["sublotNumber"] for x in twin["sublots"]):
                twin["sublots"].append(s)
        for f in (
            "customerItemNumber",
            "description",
            "quantityOrdered",
            "quantityRequired",
            "quantityOutstanding",
            "quantityBackordered",
            "lineNumber",
        ):
            twin[f] = twin[f] if twin[f] is not None else it[f]
        twin["evidence"].extend(it["evidence"])
        c.issue(
            "items",
            "repeated_line_merged",
            f"Line {it['itemNumber'] or it['description']} qty {it['quantityShipped']} on page(s) "
            f"{it['pages']} repeats page(s) {twin['pages'][: -len(it['pages'])]}; counted once.",
            severity="info",
        )
    for it in out:
        it.pop("_key", None)
    return out


def _finalize_item(c, it):
    # lots like 6446-0001 whose prefix is another lot on the same line are sublots of it
    ids = {lot["lotNumber"] for lot in it["lots"]}
    for lot in list(it["lots"]):
        m = re.fullmatch(r"(?P<p>.+?)[-/.](?P<s>\d+)", lot["lotNumber"])
        if m and m.group("p") in ids:
            it["lots"].remove(lot)
            it["sublots"].append(
                {
                    "sublotNumber": lot["lotNumber"],
                    "lotNumber": m.group("p"),
                    "quantity": lot["quantity"],
                    "unit": lot["unit"],
                    "rawValue": lot["lotNumber"],
                    "page": lot["page"],
                }
            )
    for x in it["lots"] + it["sublots"]:
        x["unit"] = x["unit"] or it["unitOfMeasure"]
    label = it["itemNumber"] or it["description"] or "line"
    printed = it.pop("_printedSublotCount", None)
    if printed:
        n, page, text = printed
        if n != len(it["sublots"]):
            c.issue(
                "sublots",
                "sublot_count_mismatch",
                f"{label}: document prints {n} sublots but {len(it['sublots'])} were read.",
                raw=text,
                page=page,
            )
        else:
            c.evidence("sublots", page, text, "printed sublot count agrees")
    if it["quantityShipped"] is None:
        src = (
            it["lots"]
            if it["lots"] and all(x["quantity"] is not None for x in it["lots"])
            else it["sublots"]
        )
        units = {x["unit"] for x in src}
        if src and all(x["quantity"] is not None for x in src) and len(units) == 1:
            it["quantityShipped"] = round(sum(x["quantity"] for x in src), 6)
            it["unitOfMeasure"] = it["unitOfMeasure"] or units.pop()
            it["quantitySource"] = (
                "sum of lot quantities" if src is it["lots"] else "sum of sublot quantities"
            )
    # consistency checks
    for lot in it["lots"]:
        subs = [
            s
            for s in it["sublots"]
            if s["lotNumber"] == lot["lotNumber"] and s["quantity"] is not None
        ]
        if lot["quantity"] is not None and subs and {s["unit"] for s in subs} == {lot["unit"]}:
            tot = round(sum(s["quantity"] for s in subs), 6)
            if abs(tot - lot["quantity"]) > 1e-6:
                c.issue(
                    "sublots",
                    "sublot_total_mismatch",
                    f"{label}: sublots of lot {lot['lotNumber']} sum to {tot}, lot shows {lot['quantity']}.",
                )
    if it["quantityShipped"] is not None:
        top = [x for x in it["lots"] if x["quantity"] is not None]
        if (
            top
            and len(top) == len(it["lots"])
            and {x["unit"] for x in top} == {it["unitOfMeasure"]}
        ):
            tot = round(sum(x["quantity"] for x in top), 6)
            if abs(tot - it["quantityShipped"]) > 1e-6:
                c.issue(
                    "shippedQuantity",
                    "lot_total_mismatch",
                    f"{label}: lot quantities sum to {tot} but line shipped is {it['quantityShipped']}.",
                )
    if (
        it["quantityShipped"] is not None
        and it["quantityOrdered"] is not None
        and it["quantityBackordered"] is not None
        and abs(it["quantityOrdered"] - it["quantityShipped"] - it["quantityBackordered"]) > 1e-6
    ):
        c.issue(
            "items",
            "ordered_shipped_backorder_mismatch",
            f"{label}: ordered {it['quantityOrdered']} != shipped + backordered.",
            severity="warning",
        )


def _items_and_quantities(c):
    lines, totals = _parse_tables(c)
    lines = [it for it in lines if it["quantityShipped"] is not None or it["lots"] or it["sublots"]]
    packing = [it for it in lines if it["pageType"] == "packing"]
    if packing:
        dropped = [it for it in lines if it["pageType"] != "packing"]
        if dropped:
            c.issue(
                "items",
                "non_packing_pages_ignored",
                f"{len(dropped)} quantity row(s) on certificate/other pages were not counted "
                f"(pages {sorted({p for it in dropped for p in it['pages']})}).",
                severity="info",
            )
        lines = packing
    elif lines:
        c.issue(
            "shippedQuantity",
            "quantity_from_non_packing_page",
            "No packing-list page with quantities; lines were read from other pages.",
            severity="warning",
        )
    lines = _dedupe_items(c, lines)
    for it in lines:
        _finalize_item(c, it)
        it.pop("pageType", None)
    c.r["items"] = lines

    for it in lines:
        for s in it["sublots"]:
            c.r["sublots"].append(
                {
                    **{k: s[k] for k in ("sublotNumber", "lotNumber", "quantity", "unit", "page")},
                    "itemNumber": it["itemNumber"],
                }
            )
        for e in it["evidence"]:
            c.evidence("items", e["page"], e["text"], e["rule"])

    # quantity summary per item+unit
    summary = {}
    for it in lines:
        if it["quantityShipped"] is None:
            continue
        k = (it["itemNumber"] or it["description"], it["unitOfMeasure"])
        s = summary.setdefault(
            k,
            {
                "itemNumber": it["itemNumber"],
                "description": None if it["itemNumber"] else it["description"],
                "unit": it["unitOfMeasure"],
                "quantityShipped": 0.0,
                "lineCount": 0,
                "salesOrders": [],
            },
        )
        s["quantityShipped"] = round(s["quantityShipped"] + it["quantityShipped"], 6)
        s["lineCount"] += 1
        if it["salesOrder"]:
            _add_unique(s["salesOrders"], it["salesOrder"])
    c.r["quantitySummary"] = list(summary.values())

    shipped = [it for it in lines if it["quantityShipped"] is not None]
    if not shipped:
        _labelled_quantity_fallback(c)
        return
    items = {norm_key(it["itemNumber"]) or norm_key(it["description"]) for it in shipped}
    units = {it["unitOfMeasure"] for it in shipped}
    if len(units) == 1:
        c.r["unitOfMeasure"] = next(iter(units))
    if len(items) == 1 and len(units) == 1:
        c.r["shippedQuantity"] = round(sum(it["quantityShipped"] for it in shipped), 6)
        c.r["rawValues"]["shippedQuantity"] = [it["quantityShipped"] for it in shipped]
        if len(shipped) > 1:
            c.issue(
                "shippedQuantity",
                "summed_lines",
                f"Total is the sum of {len(shipped)} lines for the same item and unit.",
                severity="info",
            )
    elif len(units) > 1:
        c.issue(
            "shippedQuantity",
            "mixed_units",
            f"Lines use different units {sorted(str(u) for u in units)}; not summed. See items[].",
        )
    else:
        c.issue(
            "shippedQuantity",
            "multiple_items",
            f"{len(shipped)} lines cover {len(items)} different items; a single shipped quantity would mix "
            f"products. See items[] and quantitySummary[] (compare per item).",
        )
    if (c.r["shippedQuantity"] is not None or len(units) == 1) and c.r["unitOfMeasure"] is None:
        c.issue(
            "unitOfMeasure",
            "unit_not_stated",
            "No unit of measure is printed for the shipped quantity; PO comparison needs a unit.",
        )
    # cross-check against printed totals on packing pages
    for t in totals:
        if t["pageType"] != "packing" or c.r["shippedQuantity"] is None:
            continue
        if (t["unit"] in (None, c.r["unitOfMeasure"])) and abs(
            t["quantity"] - c.r["shippedQuantity"]
        ) > 1e-6:
            c.issue(
                "shippedQuantity",
                "printed_total_mismatch",
                f"Printed total {t['quantity']} (page {t['page']}) differs from line total "
                f"{c.r['shippedQuantity']}.",
                raw=t["text"],
                page=t["page"],
            )
        else:
            c.evidence(
                "shippedQuantity", t["page"], t["text"], "printed total agrees with line total"
            )
    for it in shipped:
        for e in it["evidence"][:1]:
            c.evidence("shippedQuantity", e["page"], e["text"], e["rule"])
    _certificate_quantity_check(c)


def _packages(c):
    """Box-level rows: report them, use their count and quantity total only as cross-checks."""
    pkgs = [p for p in c.packages if p["pageType"] == "packing"] or c.packages
    details = c.r["shippingDetails"]
    details["packages"] = [
        {k: p[k] for k in ("packageNumber", "quantity", "unit", "weight", "trackingNumber", "page")}
        for p in pkgs
    ]
    if not pkgs:
        return
    if details["packageCount"] is None:
        details["packageCount"] = len(pkgs)
    qtys = [p["quantity"] for p in pkgs if p["quantity"] is not None]
    if not qtys or len(qtys) != len(pkgs):
        return
    total = round(sum(qtys), 6)
    shipped = c.r["shippedQuantity"]
    if shipped is None:
        c.issue(
            "shippedQuantity",
            "package_quantities_not_used",
            f"Box rows total {total}; they split the shipment by package and are not added to item "
            f"quantities.",
            severity="info",
        )
    elif abs(total - shipped) > 1e-6:
        c.issue(
            "shippedQuantity",
            "package_total_mismatch",
            f"Box/package rows total {total}, but the shipped line quantity is {shipped}.",
            page=pkgs[0]["page"],
        )
    else:
        c.evidence(
            "shippedQuantity",
            pkgs[0]["page"],
            f"{len(pkgs)} package rows total {total}",
            "box/package quantities agree with the line total (not added to it)",
        )


def _labelled_quantities(c, pages=None):
    out = []
    for h in find_label_values(c.layout, QTY_LABEL, pages=pages, validator=parse_number):
        value = h.value
        if h.how == "right" and re.fullmatch(r"[\d.,]+", value.strip()):
            page = next(p for p in c.layout.pages if p.number == h.page)
            nxt = right_neighbor_text(page, h.line)
            if nxt and is_known_unit(nxt):
                value = f"{value} {nxt}"
        q, u, raw = parse_quantity_with_unit(value)
        if q is not None:
            out.append((h, q, u, raw))
    return out


def _labelled_quantity_fallback(c):
    found = _labelled_quantities(c)
    if not found:
        return
    h, q, u, raw = found[0]
    c.r["shippedQuantity"], c.r["unitOfMeasure"] = q, u
    c.r["rawValues"]["shippedQuantity"] = raw
    c.evidence(
        "shippedQuantity",
        h.page,
        h.source_text,
        f"quantity label '{h.label}' (no line table found)",
    )
    c.issue(
        "shippedQuantity",
        "quantity_from_label_only",
        "No quantity table was found; the value comes from a quantity label. Confirm.",
        raw=raw,
        page=h.page,
    )


def _certificate_quantity_check(c):
    cert_pages = {p.number for p in c.layout.pages if p.page_type == "certificate"}
    if not cert_pages or c.r["shippedQuantity"] is None:
        return
    for h, q, u, raw in _labelled_quantities(c, pages=cert_pages):
        if u is not None and u != c.r["unitOfMeasure"]:
            continue
        if abs(q - c.r["shippedQuantity"]) > 1e-6:
            c.issue(
                "shippedQuantity",
                "certificate_quantity_differs",
                f"Certificate page {h.page} states {raw}; packing list total is {c.r['shippedQuantity']}.",
                severity="warning",
                raw=raw,
                page=h.page,
            )
        else:
            c.evidence("shippedQuantity", h.page, h.source_text, "certificate quantity agrees")


# --------------------------------------------------------------------------- lots and serials


def _lots_and_serials(c):
    lots, serials = c.r["lotNumbers"], c.r["serialNumbers"]
    sub_ids = {s["sublotNumber"] for s in c.r["sublots"]}
    for it in c.r["items"]:
        for lot in it["lots"]:
            _add_unique(lots, lot["lotNumber"])
            c.evidence("lotNumbers", lot["page"], lot["lotNumber"], "lot on a shipped line")
        for s in it["serialNumbers"]:
            _add_unique(serials, s)
    for h in find_label_values(
        c.layout, LOT_LABEL, validator=lambda v: clean_lot_value(v)[1] is None
    ):
        lot_id, problem = clean_lot_value(h.value)
        if problem:
            continue
        sub, parent = split_composite_lot(lot_id)
        lot_id = parent or lot_id
        if (
            lot_id in sub_ids
            or re.fullmatch(r"(.+?)[-/.]\d+", lot_id)
            and re.fullmatch(r"(.+?)[-/.]\d+", lot_id).group(1) in lots
        ):
            continue
        if lot_id not in lots:
            if c.r["items"] and h.page not in c.packing_pages:
                # labelled lot that never appears on the packing list: keep, but ask for review
                c.issue(
                    "lotNumbers",
                    "lot_only_on_other_page",
                    f"Lot '{lot_id}' appears only on page {h.page} ({h.label}).",
                    severity="warning",
                    raw=h.value,
                    page=h.page,
                )
            lots.append(lot_id)
        c.evidence("lotNumbers", h.page, h.source_text, f"lot label ({h.how})")
    for h in find_label_values(c.layout, SERIAL_LABEL):
        sid, problem = clean_lot_value(h.value)
        if sid and not problem:
            _add_unique(serials, sid)
            c.evidence("serialNumbers", h.page, h.source_text, "serial-number label")
    for it in c.r["items"]:
        for x in it["lotOrSerialNumbers"]:
            c.evidence("lotNumbers", it["pages"][0], x, "combined serial/lot column (unresolved)")


# --------------------------------------------------------------------------- missing values


def _missing(c):
    for f in CORE_FIELDS:
        v = c.r[f]
        if v in (None, []) and not c.flagged(f):
            sev = "info" if f == "serialNumbers" else "warning"
            c.issue(f, "not_found", f"No {f} found in the document.", severity=sev)


def _add_unique(lst, v):
    if v is not None and v not in lst:
        lst.append(v)


def to_json_ready(result: dict) -> dict:
    """Drop internal objects before saving."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


if __name__ == "__main__":
    import json
    import sys

    for arg in sys.argv[1:]:
        print(json.dumps(to_json_ready(extract_pdf(Path(arg))), indent=2, ensure_ascii=False))
