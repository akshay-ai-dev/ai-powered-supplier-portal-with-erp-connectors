"""Docling conversion and a small geometry layer over Docling's parsed text cells.

Docling (local, no network) converts the PDF. We keep two things from it:
  * the DoclingDocument (headings, tables, page structure, markdown for review), and
  * the parsed text-line and word cells with their page number and bounding box.

The positional cells let the rules pair labels with values that Docling's reading
order separates (e.g. a row of labels whose values are printed under/next to them)
and read table columns by header position.
"""

from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

PACKING_TITLE_RE = re.compile(
    r"packing\s*(slip|list)|delivery\s*note|shipping\s*(list|notice|manifest)|dispatch\s*note|despatch\s*note",
    re.I,
)
INVOICE_TITLE_RE = re.compile(
    r"^\s*((commercial|pro\s*-?\s*forma|tax|customs)\s+)?invoice\s*$", re.I
)
CERT_TITLE_RE = re.compile(r"certificat(e|ion)|test\s*report|analysis|conformity|conformance", re.I)


@dataclass
class Word:
    text: str
    page: int
    left: float
    t: float
    r: float
    b: float
    line_id: int = -1  # index of the text line this word came from (-1 = unknown)

    @property
    def h(self):
        return self.b - self.t

    @property
    def xc(self):
        return (self.left + self.r) / 2

    @property
    def yc(self):
        return (self.t + self.b) / 2


@dataclass
class Line(Word):
    words: list = field(default_factory=list)


@dataclass
class Page:
    number: int
    width: float
    height: float
    lines: list
    words: list
    headings: list = field(default_factory=list)
    page_type: str = "unknown"
    docling_tables: int = 0


@dataclass
class Layout:
    source_file: str
    pages: list
    page_count: int
    text_layer: bool
    ocr_used: bool
    markdown: str = ""
    docling_table_count: int = 0

    def lines(self, pages=None):
        for p in self.pages:
            if pages is None or p.number in pages:
                yield from p.lines


# --------------------------------------------------------------------------- conversion

_CONVERTERS = {}


def get_converter(ocr: bool):
    """Build (once) a Docling converter. Table structure on; OCR only for image-only PDFs."""
    if ocr not in _CONVERTERS:
        from docling.datamodel.backend_options import ThreadedDoclingParseBackendOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True, generate_parsed_pages=True)
        # One native docling-parse worker: its multi-threaded page decoding intermittently raised
        # access violations (pdf_parsers.pyd) on Windows. All other backend options stay default.
        backend_opts = ThreadedDoclingParseBackendOptions(parser_threads=1)
        conv = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=opts, backend_options=backend_opts
                )
            }
        )
        conv.initialize_pipeline(InputFormat.PDF)  # load layout/table models now, not inside timing
        _CONVERTERS[ocr] = conv
    return _CONVERTERS[ocr]


def has_text_layer(pdf_path) -> bool:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return all(
            len(pdf[i].get_textpage().get_text_range().strip()) >= 20 for i in range(len(pdf))
        )
    finally:
        pdf.close()


def convert_pdf(pdf_path):
    """Run Docling and build the Layout. Returns (layout, timings)."""
    pdf_path = Path(pdf_path)
    text_layer = has_text_layer(pdf_path)
    t0 = time.perf_counter()
    conv = get_converter(ocr=not text_layer)
    t1 = time.perf_counter()
    res = conv.convert(pdf_path)
    t2 = time.perf_counter()
    layout = build_layout(res, pdf_path.name, text_layer)
    t3 = time.perf_counter()
    return layout, {
        "converterInitSeconds": round(t1 - t0, 3),
        "conversionSeconds": round(t2 - t1, 3),
        "layoutSeconds": round(t3 - t2, 3),
    }


def _bbox_top_left(rect, page_height):
    bb = rect.to_bounding_box().to_top_left_origin(page_height=page_height)
    return bb.l, bb.t, bb.r, bb.b


def build_layout(res, source_file, text_layer) -> Layout:
    doc = res.document
    headings_by_page, tables_by_page, items_by_page = {}, {}, {}
    for item, _lvl in doc.iterate_items():
        if not getattr(item, "prov", None):
            continue
        pno = item.prov[0].page_no
        label = str(getattr(item, "label", ""))
        if "table" in label:
            tables_by_page[pno] = tables_by_page.get(pno, 0) + 1
        elif hasattr(item, "text"):
            items_by_page.setdefault(pno, []).append(item)
            if "section_header" in label or "title" in label:
                headings_by_page.setdefault(pno, []).append(item.text)

    pages = []
    for p in res.pages:
        pno = p.page_no  # Docling page numbers are 1-based
        h, w = p.size.height, p.size.width
        pp = p.parsed_page
        lines, words = [], []
        if pp is not None and pp.textline_cells:
            for c in pp.textline_cells:
                if c.text.strip():
                    lines.append(Line(c.text.strip(), pno, *_bbox_top_left(c.rect, h)))
            for c in pp.word_cells:
                if c.text.strip():
                    words.append(Word(c.text.strip(), pno, *_bbox_top_left(c.rect, h)))
        else:
            # no parsed cells: fall back to Docling text items with provenance boxes.
            for it in items_by_page.get(pno, []):
                bb = it.prov[0].bbox.to_top_left_origin(page_height=h)
                lines.append(Line(it.text.strip(), pno, bb.l, bb.t, bb.r, bb.b))
        words = link_words(lines, words)
        lines.sort(key=lambda x: (round(x.t), x.left))
        pages.append(
            Page(
                pno,
                w,
                h,
                lines,
                words,
                headings_by_page.get(pno, []),
                docling_tables=tables_by_page.get(pno, 0),
            )
        )

    classify_pages(pages)
    return Layout(
        source_file,
        pages,
        len(pages),
        text_layer,
        ocr_used=not text_layer,
        markdown=doc.export_to_markdown(),
        docling_table_count=sum(tables_by_page.values()),
    )


def _approx_words(line):
    toks = line.text.split()
    if not toks:
        return []
    total = sum(len(t) for t in toks) + len(toks) - 1
    unit = (line.r - line.left) / max(total, 1)
    out, x = [], line.left
    for t in toks:
        out.append(Word(t, line.page, x, line.t, x + unit * len(t), line.b))
        x += unit * (len(t) + 1)
    return out


def link_words(lines, words):
    """Attach words to their text lines. OCR pages (Docling's OCR adds text lines but no word
    cells) get estimated word boxes so tables can still be read by column position."""
    if not words:
        words = [w_ for ln in lines for w_ in _approx_words(ln)]
    for ln in lines:
        ln.words = []
    _attach_words(lines, words)
    return words


def _attach_words(lines, words):
    for w_ in words:
        best, best_ov = None, 0.0
        for idx, ln in enumerate(lines):
            ov = overlap(w_.left, w_.r, ln.left, ln.r) * overlap(w_.t, w_.b, ln.t, ln.b)
            if ov > best_ov:
                best, best_ov = (idx, ln), ov
        if best is not None:
            w_.line_id = best[0]
            best[1].words.append(w_)
    for ln in lines:
        ln.words.sort(key=lambda x: x.left)


def classify_pages(pages):
    """Page type from the top-most title on the page; untitled pages inherit the previous type."""
    prev = "unknown"
    for p in pages:
        top = [ln for ln in p.lines if ln.t < p.height * 0.3]
        top.sort(key=lambda x: x.t)
        cand = [(ln.t, ln.text) for ln in top if len(ln.text) < 60]
        ptype = None
        for _t, text in cand:
            if PACKING_TITLE_RE.search(text):
                ptype = "packing"
                break
            if CERT_TITLE_RE.search(text) and not re.search(r":\s*\S", text):
                ptype = "certificate"
                break
            if INVOICE_TITLE_RE.match(text):
                ptype = "invoice"  # an invoice page must not inherit 'packing' from the page before
                break
        if ptype is None:
            for text in p.headings:
                if PACKING_TITLE_RE.search(text):
                    ptype = "packing"
                    break
                if CERT_TITLE_RE.search(text):
                    ptype = "certificate"
                    break
                if re.search(r"\binvoice\b", text, re.I) and not re.search(r":\s*\S", text):
                    ptype = "invoice"
                    break
        p.page_type = ptype or prev
        prev = p.page_type


# --------------------------------------------------------------------------- geometry helpers


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def group_rows(items, tol=None):
    """Cluster items whose vertical centres are close into rows (top to bottom)."""
    if not items:
        return []
    if tol is None:
        tol = 0.45 * statistics.median([i.h for i in items])
    rows = []
    for it in sorted(items, key=lambda x: x.yc):
        if rows and abs(it.yc - rows[-1]["yc"]) <= tol:
            rows[-1]["items"].append(it)
            n = len(rows[-1]["items"])
            rows[-1]["yc"] += (it.yc - rows[-1]["yc"]) / n
        else:
            rows.append({"yc": it.yc, "items": [it]})
    return [sorted(r["items"], key=lambda x: x.left) for r in rows]


LABEL_LIKE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .#/&()'\-]{0,35}\s?:(\s|$)")


def looks_like_label(text):
    return bool(LABEL_LIKE_RE.match(text or ""))


@dataclass
class Hit:
    label: str
    value: str
    page: int
    source_text: str
    how: str  # inline | right | below
    line: object = None


def _not_a_header(value):
    """Reject neighbour text that is itself a field label / column header (e.g. 'PO #', 'Terms')."""
    from .fields import label_type  # local import keeps layout.py free of rule imports at load time

    v = value.strip()
    if not v or label_type(v) or _role_of(v):
        return False
    return not re.fullmatch(r"(?i)[a-z .]{1,20}#|terms|date|via|ship\s*via|salesperson", v)


def find_label_values(
    layout,
    label_pattern,
    pages=None,
    inline_without_colon=False,
    allow_right=True,
    allow_below=True,
    validator=None,
):
    """Find values for a label anywhere in the document.

    A label must start a text line. Its value is taken from the same line after the
    separator, else the nearest line to its right on the same row, else the line
    directly below it. The first candidate that is not another label/header and that
    passes `validator` (if given) is used.
    """
    rx = re.compile(
        r"^\s*(?P<label>" + label_pattern + r")(?![A-Za-z/])\s*(?P<sep>[:#])?\s*(?P<rest>.*)$", re.I
    )

    def ok(v):
        return _not_a_header(v) and (validator is None or validator(v))

    hits = []
    for page in layout.pages:
        if pages is not None and page.number not in pages:
            continue
        for ln in page.lines:
            m = rx.match(ln.text)
            if not m:
                continue
            rest = m.group("rest").strip()
            rest = re.sub(r"^[:#\-]\s*", "", rest)
            if rest:
                if (m.group("sep") or inline_without_colon) and (
                    validator is None or validator(rest)
                ):
                    hits.append(Hit(m.group("label"), rest, page.number, ln.text, "inline", ln))
                continue
            if allow_right:
                val = _right_neighbor(page, ln)
                if val is not None and ok(_strip_sep(val.text)):
                    hits.append(
                        Hit(
                            m.group("label"),
                            _strip_sep(val.text),
                            page.number,
                            f"{ln.text} | {val.text}",
                            "right",
                            val,
                        )
                    )
                    continue
            if allow_below:
                val = _below_neighbor(page, ln)
                if val is not None and ok(_strip_sep(val.text)):
                    hits.append(
                        Hit(
                            m.group("label"),
                            _strip_sep(val.text),
                            page.number,
                            f"{ln.text} / {val.text}",
                            "below",
                            val,
                        )
                    )
    return hits


def _strip_sep(text):
    return re.sub(r"^\s*[:#\-]\s*", "", text).strip()


def _right_neighbor(page, ln, max_gap=260):
    cands = [
        o
        for o in page.lines
        if o is not ln
        and o.left >= ln.r - 2
        and o.left - ln.r <= max_gap
        and abs(o.yc - ln.yc) <= 0.6 * max(o.h, ln.h)
    ]
    if not cands:
        return None
    o = min(cands, key=lambda x: x.left)
    if looks_like_label(o.text) and not o.text.lstrip().startswith(":"):
        return None
    return o


def _below_neighbor(page, ln):
    cands = [
        o
        for o in page.lines
        if o is not ln
        and o.t >= ln.b - 1.5
        and o.t - ln.b <= 1.6 * ln.h
        and overlap(o.left - 4, o.r + 4, ln.left, ln.r) > 0
    ]
    if not cands:
        return None
    o = min(cands, key=lambda x: (x.t, abs(x.left - ln.left)))
    if looks_like_label(o.text):
        return None
    return o


def right_neighbor_text(page, ln):
    o = _right_neighbor(page, ln)
    return o.text if o else None


# --------------------------------------------------------------------------- tables by header position

COLUMN_ROLES = [
    ("tracking", r"tracking"),
    ("package", r"\b(box|carton|package|pkg|parcel|pallet|skid)\s*(number|no\.?|#|id)"),
    ("lot_or_serial", r"serial\s*/\s*lot|lot\s*/\s*serial"),
    ("serial", r"serial"),
    ("lot", r"\b(lot|batch|sublot)\b|lot/sublot"),
    ("shipped", r"\bshipped\b|delivery\s*qty|ship\s*qty|qty\s*ship|delivered"),
    ("required", r"\brequired\b"),
    ("ordered", r"\bordered\b|order\s*qty"),
    ("outstanding", r"outstanding|balance"),
    ("backordered", r"back\s*-?\s*order|\bb/o\b"),
    ("qty", r"^(total\s+)?(qty|quantity)$"),
    ("weight_unit", r"^(lb\s*/\s*kg|kg\s*/\s*lb)$"),
    ("weight", r"weight"),
    ("unit", r"^(unit|uom|u/m|um)$"),
    ("customer_item", r"^(customer\s*part|cust\.?\s*p/?n)"),
    ("item", r"item|part\s*(number|no|#)|product|sku|material|catalog|cat\.?\s*no"),
    ("description", r"description"),
    ("line", r"^(line|ln)(\s*(no|#))?\.?$"),
]
QTY_ROLES = {"shipped", "qty"}
HEADER_KEYWORD_RE = re.compile(
    r"\b(qty|quantity|shipped|ordered|required|outstanding|backordered|tracking)\b|delivery\s*qty",
    re.I,
)


@dataclass
class Column:
    text: str
    role: str
    left: float
    r: float


@dataclass
class Table:
    page: int
    columns: list
    top: float
    bottom: float
    rows: list  # list of list[Word]

    def roles(self):
        return {c.role for c in self.columns} - {"other"}

    def has(self, role):
        return role in self.roles()


def make_phrases(words, gap_factor=0.8):
    """Merge words on the same row into phrases unless separated by a wide gap or they come
    from different text lines (the parser/OCR already split them)."""
    phrases = []
    for row in group_rows(words):
        cur = None
        for w_ in row:
            wl = getattr(w_, "line_id", -1)
            same_line = wl < 0 or getattr(cur, "line_id", -1) < 0 or wl == cur.line_id
            if cur and same_line and w_.left - cur.r <= gap_factor * max(cur.h, w_.h):
                cur = Word(
                    cur.text + " " + w_.text,
                    cur.page,
                    cur.left,
                    min(cur.t, w_.t),
                    w_.r,
                    max(cur.b, w_.b),
                    cur.line_id,
                )
            else:
                if cur:
                    phrases.append(cur)
                cur = Word(w_.text, w_.page, w_.left, w_.t, w_.r, w_.b, wl)
        if cur:
            phrases.append(cur)
    return phrases


def _role_of(text):
    t = re.sub(r"\s+", " ", text.strip(" :*")).lower()
    for role, pat in COLUMN_ROLES:
        if re.search(pat, t, re.I):
            return role
    return None


def _is_header_phrase(text):
    return not re.search(r"\d", text) and len(text) <= 40 and not re.search(r":\s*\S", text)


def find_tables(page):
    """Detect header bands (stacked header phrases) and collect the rows below each one."""
    phrases = make_phrases(page.words)
    anchors = [
        p
        for p in phrases
        if HEADER_KEYWORD_RE.search(p.text)
        and _is_header_phrase(p.text)
        and not p.text.rstrip().endswith(":")
    ]
    tables, used = [], set()
    for a in sorted(anchors, key=lambda x: x.t):
        if id(a) in used:
            continue
        window = [p for p in phrases if a.t - 1.3 * a.h <= p.yc <= a.b + 1.3 * a.h]
        # a header band row contains only header-like phrases (no data values)
        band = [
            p
            for row in group_rows(window)
            if all(_is_header_phrase(x.text) for x in row)
            for p in row
        ]
        if a not in band:
            continue
        cols = _merge_columns(band)
        for c in cols:
            c.role = _role_of(c.text)
        named = [c for c in cols if c.role]
        roles = {c.role for c in named}
        if len(named) < 2 or not (roles & (QTY_ROLES | {"tracking", "ordered", "required"})):
            continue
        # duplicate role names (e.g. two "Item Number" columns) -> keep first, demote others
        seen = set()
        for c in sorted(named, key=lambda x: x.left):
            if c.role in seen:
                c.role = c.role + "_extra"
            seen.add(c.role)
        for p in band:
            used.add(id(p))
        for c in cols:
            if not c.role:
                c.role = (
                    "other"  # unnamed header (e.g. 'Origin'): keeps its text out of other columns
                )
        top = min(p.t for p in band)
        bottom = max(p.b for p in band)
        tables.append(Table(page.number, sorted(cols, key=lambda x: x.left), top, bottom, []))
    for i, tb in enumerate(tables):
        limit = tables[i + 1].top if i + 1 < len(tables) else page.height
        tb.rows = _rows_below(page, tb, limit)
    return tables


def _merge_columns(band):
    cols = []
    for p in sorted(band, key=lambda x: x.t):
        for c in cols:
            if overlap(p.left, p.r, c["l"], c["r"]) > 0.3 * min(p.r - p.left, c["r"] - c["l"]):
                c["parts"].append(p)
                c["l"], c["r"] = min(c["l"], p.left), max(c["r"], p.r)
                break
        else:
            cols.append({"l": p.left, "r": p.r, "parts": [p]})
    return [
        Column(
            " ".join(x.text for x in sorted(c["parts"], key=lambda z: z.t)), None, c["l"], c["r"]
        )
        for c in cols
    ]


FOOTER_RE = re.compile(r"^\s*(continued|printed\s*:|page\s+\d+)|\bpage\s+\d+\s+of\s+\d+\b", re.I)
# label rows that still belong to a line (lot/batch/customer part/qty/order grouping/totals)
DETAIL_LABEL_RE = re.compile(
    r"^\s*(lot|batch|sublot|serial|cust(omer)?\.?\s*(p/?n|part)|qty|quantity|sales\s*order|your\s*reference|"
    r"total|rf)\b",
    re.I,
)


def _rows_below(page, table, limit, max_gap=45):
    words = [w_ for w_ in page.words if w_.t >= table.bottom - 1 and w_.b <= limit + 1]
    rows, last_b = [], table.bottom
    for row in group_rows(words):
        top = min(w_.t for w_ in row)
        if top - last_b > max_gap:
            break
        phrases = make_phrases(row)
        text = " ".join(w_.text for w_ in row)
        left, right = table.columns[0].left - 6, table.columns[-1].r + 6
        if not any(overlap(w_.left, w_.r, left, right) > 0 for w_ in row):
            break  # nothing within the table's width
        if (
            len(phrases) >= 2
            and all(_is_header_phrase(p.text) for p in phrases)
            and any(_role_of(p.text) for p in phrases)
        ):
            break  # a new (non-quantity) header row starts
        if max(p.r - p.left for p in phrases) > 0.5 * page.width and len(text) > 50:
            break  # paragraph text
        if FOOTER_RE.search(text):
            break  # page footer / "Continued"
        if (
            phrases[0].left < table.columns[0].r
            and looks_like_label(phrases[0].text)
            and not DETAIL_LABEL_RE.match(phrases[0].text)
            and not any(re.fullmatch(r"[\d.,]+", p.text) for p in phrases[1:])
        ):
            break  # e.g. "Country of Origin: ..." starting at the table's left edge after the last line
        rows.append(row)
        last_b = max(w_.b for w_ in row)
    return rows


def _best_column(item, columns):
    best, best_ov = None, 0.0
    for c in columns:
        ov = overlap(item.left, item.r, c.left, c.r)
        if ov > best_ov:
            best, best_ov = c, ov
    return best, best_ov


def assign_columns(row, columns):
    """Map a table row onto header columns. Returns (cells by role, unassigned words).

    Text is assigned phrase by phrase (so left-aligned text under a centred header stays
    together); a phrase is split into words only when every word sits clearly inside a
    column and the words fall in different columns (e.g. '280 F-615-B130-DH').
    """
    cells, unassigned = {}, []

    def put(col, ws):
        cells.setdefault(col.role, []).extend(ws)

    for ph in make_phrases(row):
        ws = [w_ for w_ in row if w_.left >= ph.left - 0.1 and w_.r <= ph.r + 0.1]
        per_word = [_best_column(w_, columns) for w_ in ws]
        if (
            len(ws) > 1
            and all(
                c is not None and ov >= 0.5 * (w_.r - w_.left)
                for w_, (c, ov) in zip(ws, per_word, strict=False)
            )
            and len({id(c) for c, _ in per_word}) > 1
        ):
            for w_, (c, _) in zip(ws, per_word, strict=False):
                put(c, [w_])
            continue
        col, _ = _best_column(ph, columns)
        if col is None:
            # right-aligned numbers can sit slightly outside the header text; allow a small margin
            near = [c for c in columns if overlap(ph.left, ph.r, c.left - 8, c.r + 8) > 0]
            col = near[0] if len(near) == 1 else None
        if (
            col is None
            and not re.fullmatch(r"[\d.,/\-]+", ph.text)
            and columns[0].left - 6 <= ph.left <= columns[-1].r
        ):
            # wrapped text under a narrow, centred header belongs to the table's text column
            col = next((c for c in columns if c.role == "description"), None) or next(
                (c for c in columns if c.role == "item"), None
            )
        if col is None:
            unassigned.extend(ws)
        else:
            put(col, ws)
    return {
        k: " ".join(x.text for x in sorted(v, key=lambda z: z.left)) for k, v in cells.items()
    }, unassigned
