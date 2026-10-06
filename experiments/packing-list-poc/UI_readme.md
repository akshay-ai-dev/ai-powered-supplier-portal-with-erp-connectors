# Browser Review UI — Handoff Guide

This guide covers the **local browser UI** of the Supplier Packing-List Pre-Fill POC: what it does,
how to run it, how the code is organised, and how it could later connect to the portal.

For the extraction pipeline (Docling and the rules), the draft JSON contract, models, evaluation
results and environment setup, see [README.md](README.md). This guide links to it rather than
repeating it.

---

## 1. What the UI does and does not do

**It does:**
- Let a user upload **one packing-list PDF** with optional PO details (quantity, unit, item / part no.).
- Run the existing extraction pipeline on it, on this machine, and show progress while it runs.
- Show every extracted field. Values that are missing or flagged "needs review" are highlighted
  and listed first.
- Show the **evidence** for each value: the page, the text it was read from, and the rule that read it.
- Let the user correct values: ship date, carrier, tracking, lot and serial numbers, and the
  shipped quantity and unit on each item line.
- Recalculate the **PO comparison** from the edited values after each change.
- On **Finish review (local)**, check the edits and show a readable shipment summary that can be
  downloaded as **PDF, DOCX or TXT**.

**It does not:**
- Submit a shipment, post anything to ERP, or call any external service. Finish review is a
  **local POC action only**.
- Accept images (PNG/JPG). The UI, the server and the pipeline accept **PDF only**.
- Store anything permanently. Results live in server memory, and the uploaded file is deleted
  after conversion.
- Provide logins, multiple users or several conversions at once.
- Let users add or delete item lines, or edit boxes/packages (packages are read-only).
- Highlight evidence on a page image. Evidence is shown as text only.

---

## 2. Setup, start and stop (Windows)

The UI uses the same Python environment as the pipeline. Create it as described in
[README.md §4 Setup](README.md#4-setup-windows-powershell): Python 3.11 venv in `.venv`, installed
from `requirements-lock.txt`. No extra packages are needed for the UI.
- The server uses only the Python standard library.
- DOCX export uses `python-docx`, which is already installed as a Docling dependency and pinned in
  the lock file.
- PDF export uses a small writer built into `summary_export.py`.

**Start:**
```powershell
cd C:\packing-list-poc
.\.venv\Scripts\python.exe ui_server.py
```
Then open **http://127.0.0.1:8765/** in a browser.

- **Another port:** `.\.venv\Scripts\python.exe ui_server.py --port 8780`, then open
  `http://127.0.0.1:8780/`.
- **`--host`:** this option exists, but keep the default `127.0.0.1`. Binding to another address
  would expose the UI to the network, and it has no authentication.
- **Conversion time limit:** each conversion attempt may take up to 600 s. Set the environment
  variable `PACKING_CONVERT_TIMEOUT_S` before starting the server to change this.

**Stop:** press **Ctrl+C** in the console window running the server.

**Use the venv's Python.** On the original machine, plain `python` on the PATH is Python 3.10 and
does not have the packages. For VS Code, the workspace file `.vscode/settings.json` points the
editor at `.venv\Scripts\python.exe`. If the editor shows "Import could not be resolved", run
**Python: Select Interpreter** and choose `.venv`.

---

## 3. User flow

### 3.1 Upload
- The user chooses or drops a PDF and can fill in **PO quantity**, **PO unit** and
  **PO item / part no.**. These come from the PO, never from the document.
- **Checks in the browser:** a file is chosen, the name ends in `.pdf`, the file is not empty, and
  it is no larger than the limit from `/api/health` (25 MB). If any PO field is filled in, the
  quantity must be > 0 and the unit is required.
- **Checks on the server:** the same, plus the file must start with a `%PDF-` header.

### 3.2 Processing
- A spinner, an elapsed-seconds counter and three steps are shown: upload, Docling conversion,
  extraction.
- The **Extract** button and the file input are disabled while a conversion runs. The server also
  refuses a second upload (HTTP 409).
- After 180 s a "still working" note appears. Scanned PDFs (OCR) can take about 3 minutes.
- Leaving the page during processing asks for confirmation.
- **If conversion fails,** an error card shows a plain message and advice. "Attempt details" lists
  each attempt (crash, timeout, unreadable file…). Python tracebacks are never shown in the
  browser; they appear only in the server console.

### 3.3 Reviewing flags and evidence
- **Summary line:** file name, page count, "scanned (OCR used)" if applicable, and processing time.
  Badges show how many flags are still open and how many values were not found.
- **"Needs your attention" list:**
  - **Needs review** issues (for example an ambiguous date). Each one must be ticked
    **Mark checked**, or corrected and then ticked, before the user can finish.
  - **Missing / warning** issues, shown for information only.
- **Field badges:** Needs review, Confirmed, Missing, Edited, Extracted.
- **Evidence:** every field, every item line and every attention item has an **Evidence** button.
  It opens a side drawer listing page, rule and source text. If nothing was found, the drawer says
  so and suggests entering the value manually.

### 3.4 Editing values
- **Ship date:** text field in `YYYY-MM-DD`. Below it the UI shows the value as printed on the
  document and the date spelled out (for example "read as 16 January 2024"), so there is no
  ambiguity between day and month formats.
- **Carrier:** free text, with the value as printed shown below it.
- **Shipped quantity / unit:** editable only when the draft has **no item lines**. With item lines,
  the total is read-only and calculated from them:
  - one product in one unit gives the sum of its lines;
  - several products or several units give no single total, never a mixed sum.
- **Tracking / lot / serial numbers:** shown as chips that can be added and removed. Values longer
  than 60 characters and duplicates are rejected.
- **Item lines:** the shipped quantity and unit can be edited per line. Edited rows are highlighted.
- **Boxes / packages:** read-only table. Box quantities are never added to item totals.

### 3.5 PO comparison (warnings)
- The side panel keeps the PO fields. On every edit, the browser sends the **edited** draft to
  `/api/po-compare`. The server normalises units (for example "pairs" becomes PR), recalculates
  totals and runs `po_check`.
- **Statuses shown:**
  - **Matches the PO**
  - **Over-shipped**
  - **Under-shipped**
  - **Cannot compare**, for example because the units differ, there are several products and no
    PO item, or a unit is missing
  - **Not requested**, when no PO is entered
  - **Check the highlighted values**, when an entry is invalid
- Shipped, PO and difference are shown when a comparison is possible, plus any detail messages.
- **Over- or under-shipping does not block** finishing. It is reported in the summary. "Cannot
  compare" is added as a warning. Invalid PO entries (quantity not > 0, missing unit) **do block**
  finishing.

### 3.6 Finish review (local)
**Finish review (local)** sends the original draft, the edited draft, the PO entries and the
checked issues to `/api/review`.

**Blocking errors** keep the dialog in "Please fix these before finishing":
- a "needs review" issue that is not ticked;
- a negative or non-numeric quantity;
- a ship date that is not a real `YYYY-MM-DD` date;
- an identifier longer than 60 characters;
- invalid PO entries.

**Warnings** are shown but allowed:
- no ship date, carrier or tracking number;
- item lines without a unit;
- no single total;
- PO "cannot compare".

### 3.7 Readable summary and downloads
When the review is valid, the dialog shows:
- the notice "Local POC only: this reviewed draft has not been submitted as a shipment and not
  posted to ERP";
- a summary headed **"Reviewed draft — not submitted to ERP"**:
  - **Shipment:** ship date, carrier, shipped quantity, unit, tracking numbers, lot numbers, serial
    numbers;
  - **Item lines:** line, item, description, shipped quantity and unit, lot numbers, serial numbers;
  - **PO result** (when a PO was entered): PO quantity, item, result, compared quantity, difference,
    details;
  - **Review notes:** each correction (`old → new`), each flag the supplier checked, each warning;
  - **"Not provided"** for every missing value.
- buttons **Download PDF**, **Download DOCX** and **Download TXT**. The files are named
  `<source-name>-reviewed-draft.<ext>`, and each is labelled "Reviewed draft — not submitted to ERP".

The summary, PDF, DOCX and TXT are all built by the same function on the server
(`summary_export.build_summary`) from the same final edited values. A lot or serial number on an
item line is shown only if it is still in the final document-level list.

The structured reviewed JSON (`"status": "reviewed_locally_not_submitted"` plus a `review` block)
is kept in the page for future backend use. It is **not shown** to the supplier and is not offered
as a download.

**Upload another PDF** returns to the upload screen. It asks first if there are unsaved edits.

---

## 4. Files and their roles

| File | Role |
|---|---|
| [ui_server.py](ui_server.py) | Local HTTP server and JSON API (standard library `ThreadingHTTPServer`, binds to `127.0.0.1:8765`). Validates uploads, runs one background conversion job at a time through `isolation.convert_isolated`, keeps jobs in memory, turns failures into plain messages, serves the files in `web/`, and calls `review.py` and `summary_export.py`. The conversion function can be swapped in for tests (`App(convert=...)`). |
| [review.py](review.py) | Review logic as pure functions, with no web code. `normalize_draft` cleans the edited values and normalises units. `recompute_totals` recalculates totals from the edited item lines. `parse_po` validates PO entries. `compare_with_po` runs `po_check` on the edited draft. `finish_review` returns errors and warnings and builds the reviewed JSON with `corrections`. |
| [summary_export.py](summary_export.py) | `build_summary(reviewed)` produces the readable summary (labels and display strings). `render_txt`, `render_pdf` (built-in writer, Helvetica) and `render_docx` (`python-docx`) produce the files. `export(reviewed, fmt)` returns the file bytes, content type and file name, and refuses anything that is not a finished review. |
| [web/index.html](web/index.html) | Page structure and static text: upload card, processing card, error card, review sections, PO side panel, Finish card, evidence drawer, finish dialog, unit suggestions (`<datalist id="unit-list">`). |
| [web/styles.css](web/styles.css) | All styling. Colour tokens are on `:root`; sections are marked with `/* ---------- name ---------- */` comments; responsive breakpoints at 1060 px, 860 px and 700 px. |
| [web/app.js](web/app.js) | All browser logic in plain JavaScript (no build step), in seven numbered sections: state and helpers, API calls, upload and processing, rendering, editing and PO comparison, evidence drawer, Finish review and downloads. Document text is always inserted with `textContent`, never as HTML. |
| [tests/test_ui.py](tests/test_ui.py) | 23 backend tests: PO comparison on edited values, never mixing units or products, finish-review validation, summary and exports, and the HTTP API run on a real local port with a fake converter (no Docling needed). |

The UI also depends on these files, which it uses without changing them: `isolation.py`
(conversion in a child process with timeout and retry), `po_check.py` (PO comparison) and
`fields.py` (unit normalisation). See [README.md §3 File guide](README.md#3-file-guide).

---

## 5. API and request flow

All routes are served by `ui_server.py`. JSON errors always have the shape
`{"error": {"message": "..."}}`. Every response sends `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff` and a Content-Security-Policy that allows only this server's own
files.

| Method & route | Request | Response |
|---|---|---|
| `GET /api/health` | — | `{ok, busy, maxUploadMB, timeoutSecondsPerAttempt, maxAttempts}` |
| `POST /api/jobs?filename=<name>.pdf` | Body: raw PDF bytes (`Content-Type: application/pdf`) | **202** `{jobId, filename}` |
| `GET /api/jobs/<jobId>` | — | `{jobId, filename, status: "running" \| "done" \| "failed", elapsedSeconds}` plus `result` (draft JSON) when done or `error` when failed |
| `POST /api/po-compare` | `{draft, po: {quantity, unit, item}}` | `{totals: {source, message}, errors: [{field, message}], comparison, poRequested, shippedQuantity, unitOfMeasure}` |
| `POST /api/review` | `{original, draft, po, acknowledged: ["<field>:<code>", ...]}` | `{ok, errors, warnings, reviewed, comparison, totals, summary}`. `reviewed` and `summary` are `null` when `ok` is false. |
| `POST /api/export?format=txt\|pdf\|docx` | `{reviewed}` (the `reviewed` object from `/api/review`) | The file, with `Content-Disposition: attachment; filename="<stem>-reviewed-draft.<ext>"` |
| `GET /`, `/index.html`, `/styles.css`, `/app.js` | — | Static files. Only files directly inside `web/` with `.html`, `.css`, `.js` or `.svg` are served; anything else returns 404. |

`comparison` (from `po_check`) has `status` (`match`, `over_shipped`, `under_shipped`,
`cannot_compare`) plus `shippedQuantity`, `shippedUnit`, `poQuantity`, `poUnit`, `difference` and
`issues`. The draft JSON fields (`shipDate`, `carrier`, `trackingNumbers`, `shippedQuantity`,
`unitOfMeasure`, `lotNumbers`, `serialNumbers`, `items`, `evidence`, `fieldIssues`, `rawValues`,
`document`, …) are described in [README.md §6 JSON contract](README.md#6-json-contract-successful-draft).

### Background job flow
1. The browser sends `POST /api/jobs` with the PDF bytes.
2. The server checks the name, size and header and refuses if a job is already running.
3. It writes the bytes to a new temporary folder (`pl-ui-*`) under the fixed name `upload.pdf`, so
   user input never becomes a path.
4. It starts a background thread and answers **202** with a `jobId`.
5. The thread calls `isolation.convert_isolated`. Each PDF is converted in a separate child
   process, with a 600 s timeout per attempt and **2 attempts**. Afterwards it sets the status to
   `done` (adding `sourceFile`) or `failed`, then deletes the temporary folder.
6. The browser polls `GET /api/jobs/<jobId>`: first after 1.5 s, then every 2 s. It gives up after
   5 failed polls in a row or a 404.
7. Finished jobs stay in memory for **1 hour**, and at most **20** are kept. Old jobs are removed
   when a new upload starts. Restarting the server loses all jobs.

### Error handling
| Situation | HTTP | Message shown |
|---|---|---|
| Name does not end in `.pdf`, or no `%PDF-` header | 415 | "Only PDF files are supported…" / "This file does not look like a PDF…" |
| Empty file | 400 | "The selected file is empty." |
| No `Content-Length` | 411 | "Upload size is missing." |
| Larger than 25 MB (JSON bodies: 5 MB) | 413 | "File is too large. The limit is … MB." |
| A conversion is already running | 409 | "Another PDF is still being processed…" |
| Job unknown or expired | 404 | "This processing job no longer exists. Please upload the PDF again." |
| Bad JSON / missing draft | 400 | "Request body must be a JSON object." / "Missing draft." |
| Export: unknown format, or not a finished review | 400 | "Unknown export format…" / "Finish the review first…" |
| Conversion crash, timeout or unreadable PDF | job `failed` | `error = {kind: "conversion_error", message, advice, attempts: [{attempt, outcome, explanation, seconds}]}` |
| Unexpected server error | job `failed` / 500 | `kind: "internal"`; the traceback is printed in the server console only |

In the browser:
- upload errors appear under the form;
- conversion failures appear on the error card;
- PO-comparison errors appear in the PO panel ("Comparison unavailable" or "Check the highlighted
  values");
- errors from Finish review and the downloads appear as a short toast message.

---

## 6. Finish review is local only

Finish review **does not submit a shipment and does not post to ERP**. It:
- validates the edited values;
- builds the reviewed JSON with `"status": "reviewed_locally_not_submitted"` and
  `review.note = "LOCAL POC review only. Not submitted as a shipment and not posted to ERP."`;
- shows the readable summary;
- offers local downloads.

Nothing is written to disk on the server. The UI says this in the top bar ("Local POC · nothing is
submitted"), on the Finish card, in the dialog, and in every exported file.

---

## 7. Where to change things

| What | Where |
|---|---|
| Static page text: headings, hints, button labels, upload and processing notes | `web/index.html` |
| Dynamic text: field names (`LABELS`), PO status labels (`renderPOResult`), attention-list text, toasts, upload checks (`validateUpload`) | `web/app.js` |
| Unit suggestions in the unit fields | `<datalist id="unit-list">` in `web/index.html` |
| Colours, radius, shadow, fonts | CSS variables on `:root` at the top of `web/styles.css` (`--accent`, `--ok`, `--warn`, `--bad`, `--edit`, …) |
| Layout and responsive behaviour | `web/styles.css`: `.results-grid` (main column plus side panel) and the `@media` rules |
| Conversion error wording | `FRIENDLY_ATTEMPT` and `friendly_failure()` in `ui_server.py` |
| Upload limits, job lifetime and count | `MAX_UPLOAD_BYTES`, `MAX_JSON_BYTES`, `JOB_TTL_SECONDS`, `MAX_JOBS` in `ui_server.py` |
| Review rules and messages (what blocks, what warns, 60-character identifier limit) | `finish_review()` and `MAX_IDENTIFIER_LENGTH` in `review.py` |
| Summary wording: banner, notice, "Not provided", field and PO-status labels | `BANNER`, `NOTICE`, `NOT_PROVIDED`, `FIELD_LABELS`, `PO_STATUS` in `summary_export.py` |
| Which values appear in the summary | `build_summary()` and `_review_notes()` in `summary_export.py` (also update the modal in `renderShipmentSummary()` in `web/app.js`) |
| TXT and PDF line layout (shared) | `_text_lines()` in `summary_export.py` |
| PDF fonts, sizes, margins | `_STYLES`, `_PAGE_W`, `_PAGE_H`, `_MARGIN` and `render_pdf()` |
| DOCX layout (headings, tables, header and footer) | `render_docx()` |

After changing behaviour, run the tests (§8). After changing visible text or layout, check the page
in a browser as well; the JavaScript has no automated tests.

---

## 8. Running the tests

```powershell
cd C:\packing-list-poc
.\.venv\Scripts\python.exe -m unittest tests.test_ui -v          # UI backend only (23 tests)
.\.venv\Scripts\python.exe -m unittest discover -s tests         # whole project (66 tests, about 15 s)
```

The UI tests use a fake converter, so they need neither Docling nor model downloads, and they
convert no real PDF. The whole-project run prints simulated "access violation" conversion errors.
These come from `tests/test_isolation.py`, which tests crash handling, and are expected.

---

## 9. Known limitations

- **PDF only.** The browser, the server (name and `%PDF-` header) and the pipeline all reject
  images.
- **One conversion at a time.** A second upload gets HTTP 409. There is no queue and no way to
  cancel. Closing the tab does not stop a running conversion.
- **Slow first step for every upload.** Each PDF is converted in a fresh process, which loads the
  models first (about 17–23 s). Text PDFs take about 25–70 s in total; scanned PDFs (OCR) about
  3 minutes.
- **Nothing is kept.** Jobs live in server memory for at most 1 hour (20 jobs), there is no
  database, and a server restart loses everything. A review in progress exists only in the open
  browser tab.
- **Single user, no login, local only.** The server trusts what the browser sends back (`original`
  for `/api/review`, `reviewed` for `/api/export`). That is acceptable on `127.0.0.1` but not for a
  shared deployment.
- **Editing scope:** item lines cannot be added or deleted, per-item lot and serial lists are not
  editable (only the document-level lists are), and packages are read-only.
- **Evidence is text only.** There is no page image or highlighted region.
- **PDF export character set:** characters outside Windows-1252 print as `?` in the PDF only
  (`→` is written as `->`). TXT and DOCX keep all characters.
- **Browser coverage:** checked manually in Chrome only (desktop width and about 500 px). Firefox
  and Edge are untested, and no scanned PDF has been tested end to end in the browser.
- **Download prompt:** Chrome may ask "download multiple files?" when several exports are
  downloaded quickly one after another.
- Fresh installation and offline operation are unverified for the whole project. See
  [README.md §11](README.md#11-troubleshooting) and [§12](README.md#12-current-status-and-next-steps).

---

## 10. Connecting to the portal backend and image input (later)

These are suggestions for Akshay. **None of this is implemented.** The integration contract for
the extraction output is in [README.md §10](README.md#10-integration-contract-for-the-portal-backend).

**Portal backend**
- **Reuse the logic, replace the server.** `review.py` and `summary_export.py` are plain functions
  without web code. A portal backend can call `compare_with_po`, `finish_review`, `build_summary`
  and `export` directly. `ui_server.py` is a local stand-in and is not meant for production.
- **Keep the original draft on the server.** Today the browser sends `original` and `reviewed` back.
  A backend should store the extracted draft when the job finishes, receive only the user's edits,
  and run `finish_review` and `export` from its own stored copy.
- **Replace the in-memory jobs** with the portal's job queue and storage, so that several users and
  several conversions can run and results survive restarts.
- **Add authentication** and tie each draft to a supplier and a PO. PO quantity, unit and item
  should come from the portal's PO data instead of being typed in.
- **Submission belongs to the portal.** The reviewed JSON (with `review.corrections`,
  `acknowledgedIssues`, `poComparison`, `warnings`) is ready for a backend to store. The actual
  shipment submission and any ERP posting should be a separate, deliberate portal step. This POC
  must not write to ERP.
- **The frontend can largely stay.** `web/app.js` talks only to the six routes in §5. If the portal
  offers the same request and response shapes (or a thin adapter), the screens can be reused or
  ported.

**Samhit's image work**
- The PDF-only restriction lives in four places:
  - `accept` on the file input in `web/index.html`;
  - `validateUpload()` in `web/app.js`;
  - the name and header checks in `_post_job()` in `ui_server.py`;
  - the PDF conversion in `isolation.py`.
- The simplest route is for the image pipeline to produce the **same draft JSON contract**
  ([README.md §6](README.md#6-json-contract-successful-draft)), including `evidence` and
  `fieldIssues`. Then the review screen, PO comparison, Finish review and exports work without
  changes.
- If image evidence includes positions on the page, the evidence drawer (`openEvidence()` in
  `web/app.js`) is the place to show them. Today it shows only page, rule and text.
