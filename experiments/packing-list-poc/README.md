# Supplier Packing-List Pre-Fill — POC
- ▶️ **Demo video:**[Watch the demo](https://srsconsultinc-my.sharepoint.com/:v:/g/personal/saivikram_sake_srsconsultinginc_com/IQBI3om7_3oUToIzrrCsOg9tAXp5NMh3Gi5w_tmrsXtBtqk?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJTdHJlYW1XZWJBcHAiLCJyZWZlcnJhbFZpZXciOiJTaGFyZURpYWxvZy1MaW5rIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXcifX0%3D&e=L2FbBw)


A standalone, local proof of concept that reads a supplier's packing-list **PDF** and produces a
**draft JSON** of shipment details (ship date, carrier tracking numbers, shipped quantity and unit,
lot and serial numbers, line items) for the supplier to review. Every value carries page evidence,
and anything uncertain is flagged instead of guessed.

Handoff document for Akshay and teammates who did not build the POC. Facts below were checked
against the code, tests and saved results on 2026-10-02.

---

## 1. Purpose and where it fits

The intended portal workflow (SRS §6.2, as summarised in the project brief):

1. The supplier uploads a packing-list PDF or image in the portal.
2. Extraction creates a **draft** of the shipment fields.
3. The supplier reviews and corrects the draft.
4. A shipped quantity that differs from the PO quantity is highlighted.
5. Nothing is posted to ERP until the supplier submits.

| Step | Status in this POC |
|---|---|
| PDF input (text-based and scanned) | **Implemented** (command line only) |
| Image input (PNG/JPG photos or scans) | **Not implemented**;
| Draft extraction with evidence and review flags | **Implemented** |
| PO quantity comparison | **Implemented** (`po_check.py`); the PO quantity, unit and item must be supplied by the caller |
| Supplier review/correction UI | **Implemented as a local browser POC** (`ui_server.py` + `web/`, see §5): review, edit, evidence, PO comparison on edited values, readable shipment summary with local PDF/DOCX/TXT download |
| Portal upload, API and ERP posting | **Not implemented**; this POC calls no ERP API and never posts to ERP |

---

## 2. How it works

```
 PDF ──► 1. Text-layer check (pypdfium2) ──► OCR needed only if a page has no text
      ──► 2. Docling conversion (local models: layout, table structure, OCR if scanned)
      ──► 3. Layout model in layout.py: page lines and words with positions, page types
      ──► 4. Extraction rules in extractor.py + fields.py (labels, table columns, formats)
      ──► 5. Draft JSON: values + evidence + fieldIssues   (optional: PO comparison)
      ──► 6. Supplier review/correction          (local browser UI: ui_server.py + web/)
      ──► 7. Supplier submission → portal / ERP  (planned; not part of this POC)
```

Each PDF is converted in its **own child process** (`isolation.py`) with a timeout and one retry,
because Docling's native PDF parser can occasionally crash the process (see §9).

Docling also produces **Markdown** for each document. `evaluate.py` saves it (in
`<out>/docling/*.md`) so people can inspect what the converter saw,
**but the rules do not read the Markdown**. They use richer information: Docling's text-line and
word cells with page numbers and bounding boxes, headings and table counts. That information lets
the rules pair a label with a value printed beside or below it, and read table columns by header
position.

The rules are written in plain Python and inference runs on the local CPU. No LLM, external
inference API or ERP API is used. The only network access expected comes from the model libraries:
initial model downloads and possible model-revision checks may contact Hugging Face (see §7).

---

## 3. File guide

| Path | What it does |
|---|---|
| `app.py` | Command line: extract **one PDF** to JSON, optionally with a PO comparison. Uses isolated conversion. |
| `evaluate.py` | Batch: converts `samples\pdf-*.pdf`, saves each draft, scores it against `expected\pdf-*.json`, and writes `evaluation_report.json`. A failed PDF does not stop the batch. |
| `extractor.py` | Extraction rules: ship date, carrier, references, tracking numbers, table and line items, lots and sublots, serials, boxes/packages, cross-checks and missing-field issues. |
| `fields.py` | JSON skeleton (`empty_result`), number/unit/date/carrier normalisation, identifier classification (e.g. an order number is never a tracking number), lot-value cleaning. |
| `layout.py` | Docling conversion settings (`get_converter`) and the geometry layer: lines, words, rows, label→value lookup, header-based table reading, page typing (packing / certificate / invoice). |
| `isolation.py` | Runs each conversion in a child process, with timeout, one retry, explicit `conversion_error` documents and atomic file writes. |
| `po_check.py` | `compare_po_quantity()`: compares shipped vs PO quantity only for a matching item and the same unit. |
| `review.py` | Review logic for the UI: normalises the supplier's edited values, recomputes totals from edited item lines (one item and one unit → sum, otherwise null), validates PO entries, runs `po_check` on the **edited** draft, and validates "Finish review". |
| `ui_server.py` | Local web server and JSON API (standard library only, binds to `127.0.0.1`). Upload → background job → `isolation.convert_isolated`; serves `web/`; `POST /api/export?format=txt|pdf|docx`. |
| `summary_export.py` | Readable shipment summary of a reviewed draft (final edited values) and its TXT, PDF (built-in writer) and DOCX (`python-docx`) exports. |
| `web\index.html`, `web\styles.css`, `web\app.js` | Browser UI in plain HTML/CSS/JavaScript (no framework, no build step, no CDN). Colours and spacing are CSS variables at the top of `styles.css`. |
| `tests\test_ui.py` | 23 tests: edited-value PO comparison, never mixing units/products, finish-review validation, shipment summary and TXT/PDF/DOCX exports (edited values, "Not provided", ERP label, PDF wrapping), and the HTTP API with a fake converter (upload checks, busy/409, cleanup, friendly errors, path safety, export endpoint). |
| `requirements-lock.txt` | Exact pinned package set (105 packages) of the working Windows environment (see §4). The UI adds no packages. |
| `tests\test_rules.py` | 33 rule tests on synthetic page layouts (no Docling needed). |
| `tests\test_isolation.py` | 10 tests that simulate child crashes, timeouts, retries and atomic-write failures. |
| `samples\pdf-1.pdf` … `pdf-5.pdf` | The five labelled evaluation PDFs (the rules were developed while viewing them). |
| `samples\unseen-1.pdf`, `unseen-2.pdf` | Two later "unseen" PDFs: a 6-page text PDF with invoice and certificate pages, and a 6-page **scanned** PDF. |
| `expected\pdf-1.json` … `pdf-5.json` | Detailed evaluation labels (`checks`). Each check is `verified: true` (fact from the project brief) or `false` (proposed from reading the PDF; awaiting human confirmation). |
| `expected\requirements-only\` | A simpler, human-readable reference per PDF plus `OVERVIEW.md`. Not used by `evaluate.py`. |
| `outputs\final-validation\` | Results of the final validation run of the current code (all 7 PDFs): drafts, Docling Markdown, `evaluation_report.json`, logs. |
| `outputs\unseen-*-baseline.json` | Unseen-PDF results **before** the fixes, kept to show the improvement. |
| `outputs\threads1-evaluation.txt`, `outputs\unseen-*-after-run.log` | Crash traces from docling-parse, kept as evidence for a bug report. |

---

## 4. Setup (Windows PowerShell)

### Python
The working environment uses **Python 3.11.9** (64-bit, Microsoft Store build). Other versions are
untested. Use the `py -3.11` launcher: on the working machine, plain `python` on the PATH is
Python 3.10, which is the wrong version.

### Dependencies: `requirements-lock.txt`
`requirements-lock.txt` lists the exact 105 packages of the working environment, generated with
`pip freeze` from the working `.venv`. It is the smallest specification that reproduces that
environment exactly: pinning only the top-level packages would let the transitive versions drift.
Our code imports only two third-party packages directly, `docling` and `pypdfium2`; everything
else is pulled in by Docling.

| Key package | Version |
|---|---|
| docling / docling-slim | 2.132.0 |
| docling-core | 2.99.0 |
| docling-parse | 7.22.1 |
| docling-ibm-models | 4.0.3 |
| pypdfium2 | 5.13.0 |
| torch | 2.14.1 (CPU-only build) |
| torchvision | 0.29.1 |
| transformers | 5.18.0 |
| rapidocr | 3.9.2 |
| huggingface_hub | 1.33.0 |
| numpy | 2.4.6 |
| pydantic | 2.13.5 |

**CPU PyTorch:** the pinned `torch==2.14.1` is the standard PyPI wheel. On Windows that wheel is the
CPU-only build: in the working environment `torch.__version__` reports `2.14.1+cpu` and
`torch.version.cuda` is `None`. No extra PyTorch index URL is needed, and none should be added
unless a GPU build is wanted. (The PyTorch CPU index would install a package labelled
`2.14.1+cpu`, which would not match the lock file's pin.)

The file is Windows-specific (it pins `pywin32`). pip and setuptools are not listed; the working
venv has `pip==24.0` and `setuptools==84.0.0`.

### Creating the environment
```powershell
cd C:\packing-list-poc
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

What has been checked: `pip check` reports no broken requirements in the working environment, and
`pip install --dry-run --ignore-installed -r requirements-lock.txt` resolves all 105 pins from PyPI
(plus `setuptools 84.0.0` as a dependency), with `torch 2.14.1` taken from the standard PyPI files
host. **A real installation into a fresh virtual environment has not been performed**, so treat
these commands as expected to work, not as verified.

### Models: first download vs. local use
Docling downloads its models from Hugging Face the first time a converter is built; RapidOCR uses
model files kept in its package folder (see §7). On the working machine they were downloaded on
2026-10-01 and are now served from the local cache. Later runs load them from disk (about 17–23 s
per PDF, see §7) and run inference locally. Model downloads and possible model-revision checks may
contact Hugging Face; fully offline operation has not been verified (see §7 and §11).

---

## 5. Running it

All commands assume `cd C:\packing-list-poc`. Set UTF-8 output once per PowerShell session (some
documents contain symbols like ®):

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### Browser review UI (local POC)
```powershell
cd C:\packing-list-poc
.\.venv\Scripts\python.exe ui_server.py
```
Then open **http://127.0.0.1:8765/** in a browser. Stop the server with Ctrl+C. Use `--port 8780`
if 8765 is busy.

The flow:
1. Choose a PDF and optionally enter the PO quantity, unit and item.
2. Wait while it processes: an elapsed-time counter is shown, the Extract button is disabled, and
   the server refuses a second upload while one is running.
3. Review the draft. Missing and "needs review" values are listed first. Every field has an
   **Evidence** button showing the page, source text and rule.
4. Edit or clear values, add or remove tracking, lot and serial numbers, and correct item
   quantities and units.
5. The PO comparison is recalculated from the edited values on every change (`po_check` on the
   server). Different units or different products are never combined.
6. **Finish review (local)**. It is blocked until every "needs review" item is ticked as checked.
   It then shows a readable **shipment summary** built from the supplier's final edited values
   (ship date, carrier, tracking numbers, shipped quantity and unit, item lines, lot and serial
   numbers, PO result, review notes; "Not provided" for missing values), with downloads as
   **PDF, DOCX or TXT** (`<name>-reviewed-draft.<ext>`), each labelled "Reviewed draft — not
   submitted to ERP". The modal and all three files come from the same `summary_export.build_summary`.
   The structured reviewed JSON (`"status": "reviewed_locally_not_submitted"`, corrections, PO
   comparison) is still produced by `/api/review` and kept in the page for a later backend
   integration, but it is no longer shown to the supplier.
   **This is a local POC action: nothing is submitted as a shipment and nothing is posted to ERP.**

How the server is set up:
- **Local only:** it binds to `127.0.0.1` and accepts **PDF only, up to 25 MB**, checked by name
  and by the `%PDF-` file header.
- **Uploads:** each upload is stored under a random name in a temporary folder that is deleted
  after conversion, and results are kept only in server memory (for up to one hour).
- **Errors:** conversion errors, timeouts and server errors are shown as plain messages; Python
  tracebacks are printed only in the server console.
- **Dependencies:** none beyond `requirements-lock.txt`. The server uses the Python standard
  library; DOCX export uses `python-docx` (already installed as a Docling dependency and pinned in
  the lock file). The PDF export uses a small built-in writer (standard Helvetica font), so no PDF
  library was added; characters outside Windows-1252 print as `?` in the PDF only.

### Extract one PDF (command line)
```powershell
.\.venv\Scripts\python.exe app.py samples\pdf-5.pdf                                  # print JSON
.\.venv\Scripts\python.exe app.py samples\pdf-5.pdf --out outputs\my-run\pdf-5.json  # write JSON
```

### With PO context (quantity, unit and item come from the PO/portal, never from the PDF)
```powershell
.\.venv\Scripts\python.exe app.py samples\pdf-5.pdf --out outputs\my-run\pdf-5.json --po-qty 42 --po-unit PR --po-item 10Y1532-9.75A
```
`--po-item` is required whenever the document contains several different items; `--po-unit` is
always required for a comparison.

### Run the tests (66 tests, about 17 s, no Docling conversion)
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
A line `CONVERSION ERROR ... access violation` appears during the run: it comes from a test that
deliberately simulates a crash. The final line should be `OK`.

### Evaluate the five labelled PDFs into a new folder
```powershell
.\.venv\Scripts\python.exe -X faulthandler evaluate.py --out outputs\eval-YYYYMMDD
```
Always pass a **new** `--out` folder. Without `--out`, results go to `outputs\extractions\`,
`outputs\docling\` and `outputs\evaluation_report.json`. On the working machine this takes about
4 minutes (each PDF loads the models in its own process). `evaluate.py` only picks up
`samples\pdf-*.pdf`; the unseen PDFs are run with `app.py`.

### Exit codes
| Command | Code | Meaning |
|---|---|---|
| `app.py` | 0 | Draft produced |
| `app.py` | 2 | Conversion failed twice (a `conversion_error` document is written or printed); **also** used by argparse for bad arguments or a missing PDF file, so check stderr |
| `evaluate.py` | 0 | All PDFs converted |
| `evaluate.py` | 1 | At least one PDF had a conversion error (the others were still processed), or no `pdf-*.pdf` was found |

### Conversion errors, timeouts, retries and logs
- Each attempt is a fresh child process: `python -X faulthandler isolation.py --worker <pdf> <payload>`.
- **Timeout:** 600 s per attempt (`DEFAULT_TIMEOUT_S` in `isolation.py`). Override it per session,
  for example `$env:PACKING_CONVERT_TIMEOUT_S = "1200"`. On timeout the whole child process tree is killed.
- **Retry:** a crash, timeout, Python error or missing/invalid output triggers one more attempt in a
  new process.
- **Two failures:** you get a document with `"status": "conversion_error"`, the PDF path and every
  attempt (status, reason, exit code, seconds, last lines of its output with secret-looking values
  redacted). It contains **no extracted fields**. `evaluate.py` saves it as
  `<out>\extractions\<name>.conversion-error.json` and removes an older `<name>.json` in that folder.
- **Logs:** `evaluate.py` keeps every attempt's log in `<out>\logs\<name>.attempt<N>.log`.
  `app.py` keeps child logs only inside the failure document (output tail); on success they are
  discarded.
- All output files are written atomically (temp file → rename), so a crash cannot leave a partial JSON.

---

## 6. JSON contract (successful draft)

Top-level keys, in order: `sourceFile`, `extractorVersion`, `shipDate`, `carrier`, `trackingNumbers`,
`shippedQuantity`, `unitOfMeasure`, `lotNumbers`, `serialNumbers`, `sublots`, `items`,
`quantitySummary`, `references`, `shippingDetails`, `rawValues`, `fieldIssues`, `evidence`,
`document`, `timings`, plus `poComparison` when `--po-qty` is given.

| Field | Type | Meaning |
|---|---|---|
| `shipDate` | ISO date string or `null` | Only from a ship-date label, or (flagged) from the document date when no ship-date label exists. Numerically ambiguous dates are flagged. |
| `carrier` | string or `null` | Normalised name (e.g. `FedEx`, `UPS`); unknown carriers are kept as written (flagged `info`). `null` for customer collection (flagged). |
| `trackingNumbers` | array of strings | From tracking labels and columns only. Order, invoice, shipping and box numbers are never used. |
| `shippedQuantity` | number or `null` | Total for **one item in one unit**. `null` with issue `multiple_items` or `mixed_units` when a single total would mix products or units. |
| `unitOfMeasure` | string or `null` | Normalised unit code (e.g. `PR`, `SF`, `EA`, `MG`); `null` if not printed (flagged). |
| `lotNumbers`, `serialNumbers` | arrays of strings | Ambiguous values (e.g. `(280)` under "Serial/Lot#") are **not** included; they are flagged instead. |
| `sublots` | array | Sublot ID, parent lot, quantity, unit, page, item. |
| `items` | array | One entry per shipped line: item/customer part, description, sales order, ordered/required/shipped/outstanding/backordered quantities kept separate, unit, lots, sublots, pages. Lines repeated on later pages are merged once (flagged `info`). |
| `quantitySummary` | array | Shipped total per item and unit, for per-item PO comparison. |
| `references` | object | Classified identifiers that are **not** tracking numbers: `purchaseOrders`, `salesOrders`, `packingSlips`, `internalShippingNumbers`, `accountNumbers`, etc. (`value`, `label`, `page`). |
| `shippingDetails` | object | `serviceLevel`, `shipMethodRaw`, `freightTerms`, `packageCount`, `packages` (box rows: number, quantity, weight, tracking; never added to item quantities). |
| `rawValues` | object | Values as printed, before normalisation. |
| `fieldIssues` | array | `{field, severity, code, message, rawValue?, page?}`. Severity is `review` (supplier must check), `warning` (missing or weak) or `info` (note). |
| `evidence` | object | Per field: `[{page, text, rule}]`, i.e. where each value came from. |
| `document` | object | `pageCount`, `pageTypes`, `textLayer`, `ocrUsed`, `doclingTableCount`, `datePreference`. |
| `timings` | object | `converterInitSeconds`, `conversionSeconds`, `layoutSeconds`, `extractionSeconds`, `totalSeconds`, `isolation.attempts[]`. |

**Null and empty:** a missing single value is `null`, a missing list is `[]`, and each missing core
field gets a `not_found` issue (`warning`; `info` for serial numbers). Identifiers stay strings
(leading zeros preserved).

**`status`:** a successful draft currently has **no** top-level `status` field. Only failures carry
`"status": "conversion_error"`. (The `requirements-only` reference files use
`"status": "draft_for_supplier_review"`; the backend may want to add that to successful drafts.)

**`poComparison`** (only with `--po-qty`): `status` (`match` | `over_shipped` | `under_shipped` |
`cannot_compare`), `poQuantity`, `poUnit`, `poItem`, `shippedQuantity`, `shippedUnit`, `difference`,
`matchedLines`, `issues`. It returns `cannot_compare`, never a guessed mismatch, when the unit is
missing or different, no line matches the PO item, or several items exist and no `--po-item` was
given.

### Example (abridged from `outputs\final-validation\extractions\pdf-5.json`)
```json
{
  "sourceFile": "pdf-5.pdf",
  "extractorVersion": "0.2.0",
  "shipDate": "2024-01-16",
  "carrier": "UPS",
  "trackingNumbers": [],
  "shippedQuantity": 42.0,
  "unitOfMeasure": "PR",
  "lotNumbers": ["2401"],
  "serialNumbers": [],
  "sublots": [
    {"sublotNumber": "US310197", "lotNumber": "2401", "quantity": 6.5, "unit": "PR", "page": 3, "itemNumber": "10Y1532-9.75A"}
  ],
  "items": [
    {"itemNumber": "10Y1532-9.75A", "quantityOrdered": 42.0, "quantityShipped": 42.0, "quantityBackordered": 0.0,
     "unitOfMeasure": "PR", "quantitySource": "shipped column"}
  ],
  "references": {"purchaseOrders": [{"value": "PR3412522", "label": "Purchase Order #", "page": 1}],
                 "internalShippingNumbers": [{"value": "0041709", "label": "Shipping Number", "page": 2}]},
  "fieldIssues": [
    {"field": "items", "severity": "info", "code": "repeated_line_merged",
     "message": "Line 10Y1532-9.75A qty 42.0 on page(s) [3] repeats page(s) [2]; counted once."}
  ],
  "evidence": {"shipDate": [{"page": 2, "text": "Ship Date: | 1/16/2024", "rule": "ship-date label (right)"}]},
  "document": {"pageCount": 3, "pageTypes": {"1": "certificate", "2": "packing", "3": "packing"},
               "textLayer": true, "ocrUsed": false}
}
```
The real file lists six sublots (summing to 42 PR); the `items` entry and `document` are shortened here.

**Multiple items (unseen-1):** two 1,000 mg lines. `shippedQuantity` is `null`, `unitOfMeasure` is
`"MG"`, the issue `multiple_items` is raised, and `quantitySummary` holds one entry per line. A PO
comparison then needs `--po-item`.

---

## 7. Models and infrastructure

Configured in `layout.get_converter()`:
`PdfPipelineOptions(do_ocr=<only when the PDF has no text layer>, do_table_structure=True, generate_parsed_pages=True)`;
docling-parse backend with
`parser_threads=1`; Docling 2.132.0 defaults otherwise (device `auto`, 4 threads,
`enable_remote_services=False`).

| Stage | Used for | Model and revision | Checkpoint file (this machine) | Size |
|---|---|---|---|---|
| Layout | every PDF | `docling-project/docling-layout-heron` (RT-DETRv2 via Transformers), revision `main` = commit `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | `C:\Users\Lenovo\.cache\huggingface\hub\models--docling-project--docling-layout-heron\snapshots\8f39ad3c…\model.safetensors` | 163.71 MB |
| Table structure | every PDF | TableFormer v1, `ACCURATE` mode, `docling-project/docling-models` revision `v2.3.0` = commit `fc0f2d45e2218ea24bce5045f58a389aed16dc23` | `…\models--docling-project--docling-models\snapshots\fc0f2d45…\model_artifacts\tableformer\accurate\tableformer_accurate.safetensors` | 202.90 MB |
| OCR detection | scanned PDFs only | RapidOCR 3.9.2, PyTorch backend, PP-OCRv6 det small | `C:\packing-list-poc\.venv\Lib\site-packages\rapidocr\models\PP-OCRv6_det_small.pth` | 9.77 MB |
| OCR recognition | scanned PDFs only | PP-OCRv6 rec small + `ppocrv6_dict.txt` (0.07 MB) | `…\rapidocr\models\PP-OCRv6_rec_small.pth` | 20.34 MB |
| OCR angle classifier | scanned PDFs only | PP-OCR mobile v2.0 cls | `…\rapidocr\models\ch_ptocr_mobile_v2.0_cls_mobile.pth` | 0.56 MB |

OCR is switched on only when `pypdfium2` finds fewer than 20 characters of text on any page. Docling
"auto" OCR resolves to RapidOCR on PyTorch here because onnxruntime and EasyOCR are not installed.

| Size summary (each file counted once) | |
|---|---|
| Checkpoints loaded for a text PDF | 366.61 MB |
| Additional checkpoints for a scanned PDF | 30.74 MB (397.35 MB in total) |
| Hugging Face folders (`docling-layout-heron` 163.81 MB, `docling-models` 341.64 MB, which includes the **unused** `tableformer_fast.safetensors`, 138.72 MB) | 505.45 MB |
| `rapidocr\models` folder (includes **unused** `.onnx` copies, about 30.3 MB) | 61.02 MB |
| **Total on disk for this POC** | **566.47 MB** |

On this machine the Hugging Face cache stores real files in one snapshot per repository (no
symlinks), so nothing is counted twice. Two other models in the same cache
(`sentence-transformers/all-MiniLM-L6-v2`, `cross-encoder/ms-marco-MiniLM-L6-v2`) are not used by
this POC.

**Hardware:** Intel Core i5-1035G1 (4 cores / 8 threads, 1.0 GHz base), 7.8 GB RAM, Windows 10
19045, no GPU (`torch 2.14.1+cpu`, CUDA unavailable). Inference runs on 4 CPU threads.

**Measured latency (final validation, models already cached, one child process per PDF):**

| PDF | Pages | OCR | Model load from disk | Docling conversion | Rules | Wall time per PDF |
|---|---|---|---|---|---|---|
| pdf-1 | 5 | no | 18.8 s | 18.2 s | 0.03 s | 39.6 s |
| pdf-2 | 1 | no | 17.3 s | 5.6 s | 0.02 s | 24.7 s |
| pdf-3 | 2 | no | 19.9 s | 50.7 s | 0.02 s | 72.6 s |
| pdf-4 | 2 | no | 18.3 s | 12.8 s | 0.03 s | 33.2 s |
| pdf-5 | 3 | no | 21.5 s | 21.9 s | 0.03 s | 45.2 s |
| unseen-1 | 6 | no | 16.6 s | 48.4 s | 0.04 s | 67.7 s |
| unseen-2 | 6 | **yes** | 23.4 s | 141.1 s | 0.03 s | 168.9 s |

First-time model downloads are **not** included in these figures; the models were downloaded on
2026-10-01. Some earlier runs of the same PDFs on this machine took up to about twice as long; the
cause of that variation was not determined.

**Network:** no external inference API or ERP API is used. The project code makes no HTTP requests
and holds no API keys, and Docling's remote services are disabled. Initial model downloads and
possible model-revision checks may contact Hugging Face: the layout model is requested at revision
`main`, and no offline setting (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `artifacts_path`) is
configured. **Fully offline operation has not been verified.**

---

## 8. Evaluation results

Final validation of the current code (`outputs\final-validation\`, 2026-10-02):

- All **7 PDFs** converted on the **first attempt**, every exit code was 0, and there were **no**
  Windows crash events (`pdf_parsers.pyd`).
- Every draft was identical (apart from timings) to the previously validated results.
- The retry and conversion-error path was **not** exercised by this run; it is covered by the 10
  isolation tests.

Scores on the five labelled PDFs:

| Checks | Correct | Correctly flagged ambiguous | Incorrect | Missing |
|---|---|---|---|---|
| **20 verified** (facts from the project brief) | 19 | 1 | 0 | 0 |
| **41 unverified** (proposed from reading the PDFs, awaiting confirmation) | 36 | 5 | 0 | 0 |

"Correctly flagged ambiguous" means the label required the value to be flagged for supplier review
rather than asserted. Examples: `(280)` under Serial/Lot#, the ship date `2/7/2024`, customer
collection with no carrier, and multiple items with no single total.

**These scores do not show accuracy on new documents.** The rules were developed while viewing
these five PDFs, and most labels are still unconfirmed. On the two unseen PDFs the first version
missed the line items (and, for the scanned one, six of seven tracking numbers). After general
fixes both are correct, but two documents are not a representative test.

---

## 9. Known limitations and safe handling

| Situation | What the POC does | What the supplier should do |
|---|---|---|
| Ambiguous numeric date (e.g. `2/7/2024`) | Uses month/day for US-address documents (day/month for UK/EU), flags `ambiguous_date` with both readings | Confirm the date |
| No ship-date label | Uses the document date, flagged `inferred_from_document_date` | Confirm or correct it |
| Unit not printed | `unitOfMeasure: null`, flagged `unit_not_stated`; the PO comparison returns `cannot_compare` | Enter the unit |
| Several products or units | `shippedQuantity: null` with `multiple_items` / `mixed_units`; per-line quantities in `items` and `quantitySummary` | Review per line |
| Repeated pages / box breakdowns | Repeated lines counted once; box quantities kept in `shippingDetails.packages` and never added to item totals | Check against the PO |
| Ambiguous identifiers (e.g. `FED EX# 149752137`, `(280)`) | Not used as tracking/lot/serial numbers; flagged `review` | Enter the correct value if one exists |
| Scanned PDFs | OCR (RapidOCR); much slower (about 140 s for 6 pages); text positions are estimated per word | Review more carefully |
| PO unit or item mismatch | `cannot_compare` with the reason; no conversion between units is assumed | Correct the unit or item |
| Image files (PNG/JPG) | Not supported yet |
| Native crash in docling-parse (intermittent Windows access violation in `pdf_parsers.pyd`, docling-parse 7.22.1) | Contained: the child process is retried once; after two failures an explicit `conversion_error` is returned | Re-upload or enter manually |
| Very slow documents | Default **600 s** timeout per attempt; override with `PACKING_CONVERT_TIMEOUT_S` | Retry later or enter manually |

The native crash is **contained, not fixed**. What was observed: an intermittent access violation
inside `pdf_parsers.pyd` (docling-parse's native module) during Docling's page cleanup, the step
that releases a finished page's parser backend. The exact cause is unconfirmed. Setting
`parser_threads=1` did not prevent it, and a PDF that crashes on both attempts gets no draft.

**Reviewing a draft:** every field should be shown with its evidence (page and source text) and its
`fieldIssues`. Items with `review` severity must be confirmed or corrected by the supplier before
submission. `warning` items mean a value is missing, `info` items are notes, and empty or `null`
values mean "not found", never "zero".

---

## 10. Integration contract (for the portal backend)

**Input:** the uploaded PDF, plus PO context from the portal: PO quantity, PO unit and PO item
(line) number.

**Output:** the draft JSON (§6), with `evidence` and `fieldIssues`, and `poComparison` when PO
context was provided. On failure: the `conversion_error` document (no extracted fields).

**Boundary:** the POC only **proposes** a draft. The supplier reviews and corrects it, and only the
supplier's submission may create or update records. This POC uses no ERP API or external inference
API and never posts to ERP; its only expected network access is model downloads and possible
model-revision checks against Hugging Face (§7).

| | Current (this POC) | Planned |
|---|---|---|
| Interface | Command line (`app.py`) and a local browser UI with a small JSON API (`ui_server.py`: `POST /api/jobs`, `GET /api/jobs/<id>`, `POST /api/po-compare`, `POST /api/review`, `POST /api/export`) | Portal upload page and backend API calling the same extraction, with authentication and persistent storage |
| Execution | One child process per PDF; models load each time (about 17–23 s) | Likely a long-running worker that keeps models loaded, still with crash isolation (to be designed) |
| Result status | No `status` on an extracted draft; `conversion_error` on failure; the UI's reviewed JSON has `"status": "reviewed_locally_not_submitted"` plus a `review` block (corrections, acknowledged issues, PO comparison) | Backend stores the draft and the supplier's corrections and decides the official status |
| PO highlight | `poComparison.status` and `difference`; the UI shows match / over-shipped / under-shipped / cannot-compare from the **edited** values | Same rules in the portal UI | |

Python callers can use `isolation.convert_isolated(pdf_path)` → `(result, markdown)` and
`isolation.is_conversion_error(result)`, then `po_check.compare_po_quantity(result, qty, unit, item)`.

---

## 11. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| First run is very slow or fails while fetching models | Docling downloads its models from Hugging Face on first use. Check internet access; models are cached in `%USERPROFILE%\.cache\huggingface\hub`. For offline use, test `$env:HF_HUB_OFFLINE = "1"` (not yet verified for this POC). |
| Every PDF takes 20 s or more even if small | Normal: each child process loads the models (about 17–23 s on a 4-core laptop CPU). |
| Scanned PDF takes minutes | OCR on CPU (about 140 s for 6 pages measured). Close other heavy programs. |
| `conversion_error` with `timeout` | Raise `$env:PACKING_CONVERT_TIMEOUT_S` (seconds) and rerun. |
| `conversion_error` with `access violation (0xC0000005)` | Native docling-parse crash. Rerun that PDF; check `<out>\logs\` (evaluation) or the `stderrTail` in the error document. The Windows Event Viewer (Application log, event 1000) names `pdf_parsers.cp311-win_amd64.pyd`. |
| `pip install -r requirements-lock.txt` cannot find a version | Check the venv was created with `py -3.11` (64-bit) on Windows; the lock file pins Python 3.11 / Windows wheels, and plain `python` on the working machine is 3.10. |
| `UnicodeEncodeError` when printing | Run `$env:PYTHONIOENCODING = "utf-8"` first. |
| Evaluation results mixed with old ones | Always use a new folder: `evaluate.py --out outputs\eval-<date>`. |
| `evaluate.py` prints "not scored" | `expected\pdf-N.json` is missing; restore the label files. |
| UI: "Cannot reach the local server" | `ui_server.py` was closed; start it again and reload the page. |
| UI: port 8765 already in use | Start with another port: `ui_server.py --port 8780`, then open `http://127.0.0.1:8780/`. |
| UI: "Another PDF is still being processed" | Only one conversion runs at a time; wait for it to finish (the other tab shows its progress). |

---

## 12. Current status and next steps

**Status:** extraction for packing-list PDFs (text-based and scanned) works locally on the seven
test documents. Results carry evidence and review flags, PO comparison is safe (`cannot_compare`
rather than guessed mismatches), and a native crash costs at most one PDF. A local browser UI
supports the full review flow up to a readable shipment summary with PDF/DOCX/TXT downloads
(local only). There are 66 unit tests, all passing.

**Next steps:**
1. **Portal integration** of the review flow: authentication, persistent drafts and corrections,
   and a real supplier-submission step owned by the portal backend (no ERP write from this POC).
3. **Independent evaluation** on a new set of packing lists that the rules were not developed on.
4. **Confirm the 41 proposed labels** in `expected\pdf-*.json` (set `verified: true` after checking).
5. **Fresh-install check:** install from `requirements-lock.txt` into a clean venv and run the tests (§4).
6. **Offline check:** verify operation with no network (`HF_HUB_OFFLINE=1` or a local `artifacts_path`).
7. Report the docling-parse crash upstream (traces in `outputs\threads1-evaluation.txt`).
