# SPL — Supplier/Document Packing-List Extraction for the Buyer Requirement form

This package adds **one authenticated endpoint** that lets a **buyer** upload a
document (PDF or image) and get back a **draft** of the fields the extractors could
read, so the frontend can pre-fill the **New requirement** form. The buyer reviews
and edits the draft, then submits the requirement through the **existing**
`POST /api/requirements` flow.

> The draft call is **extraction only**. It never creates a requirement, attaches
> a file, writes to the database, or posts to the ERP.

- **PDF** → the Docling rule-based extractor (`supplier_packing_list/pdf`), run in an **isolated child
  process** so a native Docling crash can never take down the API.
- **PNG/JPEG/WEBP** → the OpenAI Structured-Outputs extractor (`supplier_packing_list/image`).

Both paths are normalised into the one `DraftExtraction` response.

---

## Endpoint

```
POST /api/requirements/extract-draft
Content-Type: multipart/form-data
Authorization: Bearer <JWT>            # a buyer (or admin) token
```

| Part   | Type | Required | Notes |
|--------|------|----------|-------|
| `file` | file | yes      | PDF, PNG, JPEG, or WEBP. Max **10 MB** (`SPL_MAX_UPLOAD_BYTES`). |

- **Auth / roles:** any logged-in **buyer** or **admin**. No token → `401`.
  Supplier / inspector → `403`.
- **Validation:** the file is checked by **both** its extension **and** its actual
  content bytes. A PNG renamed `.pdf` (or any content/extension-family mismatch) is
  rejected. The image path additionally does a full decode and rejects animated or
  decompression-bomb images.
- **No `po_id` / shipment inputs.** Those belonged to the earlier supplier-shipment
  design and were removed — a requirement is being *created*, so there is no PO yet.

### Response `200` — `DraftExtraction`

```jsonc
{
  "sourceType": "pdf",                 // "pdf" | "image"
  "sourceFile": "packing-list.pdf",
  "status": "extracted",               // "extracted" | "conversion_error" (PDF only)
  "shipDate": "2026-02-10",            // ISO date or null
  "shipDateInferred": false,           // true if taken from a generic document date (PDF)
  "carrier": "FedEx",                  // or null
  "trackingNumbers": ["1Z999AA10123456784"],
  "shippedQuantity": 400,              // number or null
  "unitOfMeasure": "EA",              // PDF only; null for images
  "lotNumbers": ["LOT-7"],
  "serialNumbers": [],
  "items": [                           // PDF line items (as read); [] for images
    {"itemNumber": "ITEM001", "quantityShipped": 400, "unitOfMeasure": "EA"}
  ],
  "fieldIssues": [                     // things to review before submitting
    {"field": "serialNumbers", "severity": "info", "code": "not_found",
     "message": "No serialNumbers found in the document."}
  ],
  "evidence": { "shipDate": [ {"page": 1, "text": "Ship Date 02/10/2026", "rule": "ship-date label"} ] },
  "conversionError": null,             // set only when status == "conversion_error"
  "extractor": {"type": "pdf", "version": "0.2.0", "model": null},
  "warnings": []
}
```

Image example (six-field schema; no unit, no evidence):

```jsonc
{
  "sourceType": "image",
  "sourceFile": "packing-list.png",
  "status": "extracted",
  "shipDate": "2026-03-01",
  "shipDateInferred": false,
  "carrier": "UPS",
  "trackingNumbers": ["1Z1"],
  "shippedQuantity": 12,
  "unitOfMeasure": null,
  "lotNumbers": ["L1"],
  "serialNumbers": [],
  "items": [],
  "fieldIssues": [
    {"field": "serialNumbers", "severity": "info", "code": "not_found",
     "message": "No serialNumbers was found in the image."}
  ],
  "evidence": {},
  "conversionError": null,
  "extractor": {"type": "image", "version": "2.0", "model": "gpt-4o"},
  "warnings": ["Image extraction does not capture a unit of measure. Confirm the unit before relying on any quantity comparison."]
}
```

`fieldIssues[].severity`: `review` = please confirm this value · `warning` =
missing/weak · `info` = note.

### Errors (portal `{"detail": "..."}` shape)

| Status | When |
|--------|------|
| `400` | No file / empty file |
| `401` | No / invalid token |
| `403` | Not a buyer or admin |
| `413` | File over the size limit |
| `415` | Extension not PDF/PNG/JPEG/WEBP |
| `422` | Unreadable/corrupt file, or content ≠ extension family |
| `502` | OpenAI upstream failure (image path) |
| `503` | `OPENAI_API_KEY` not configured (image path) |

A **PDF that fails to convert** returns `200` with `status: "conversion_error"`,
all fields null/empty, and a `review` field issue — never a `5xx` or a crash.

---

## Mapping the draft onto the New requirement form (for the frontend)

The buyer form submits to `POST /api/requirements`. As part of this integration the
requirement model gained five optional **shipping-detail** fields so the draft's
values actually persist (they now show in the Requirements list and the preview):

`RequirementCreate` fields: `title`, `description`, `item_code`, `quantity`,
`target_price`, `needed_by`, `erp`, `quote_deadline`, `open_to_all`,
`supplier_ids`, **`ship_date`**, **`carrier`**, **`tracking_number`**,
**`lot_numbers`**, **`serial_numbers`**.

| New requirement form field | Prefill from draft | Persisted? | Notes |
|----------------------------|--------------------|------------|-------|
| **Ship date** (`ship_date`) | `shipDate` | ✅ | ISO `YYYY-MM-DD`. If `shipDateInferred` is true, flag it for review (it came from a generic document date). |
| **Carrier** (`carrier`) | `carrier` | ✅ | string. |
| **Tracking number** (`tracking_number`) | `trackingNumbers` | ✅ | The draft returns a **list**; the form field is a single string — join with `", "` (or let the buyer pick). |
| **Lot numbers** (`lot_numbers`) | `lotNumbers` | ✅ | list of strings (one per line in the form). |
| **Serial numbers** (`serial_numbers`) | `serialNumbers` | ✅ | list of strings. |
| **Quantity** (`quantity`) | — (see below) | ✅ | The buyer's **requested** quantity. Do **not** auto-fill it from the document's `shippedQuantity`. |
| **Specs and notes** (`description`) | *(optional)* | ✅ | Free text. `unitOfMeasure` (PDF only) has no column — surface it here or as a hint if useful. |
| **New item name** (`title`) | — | ✅ | Not extracted; buyer enters (required). |
| **Item** (`item_code`) | — | ✅ | Not extracted; buyer picks an inventory item or "New item". |
| **Target unit price** (`target_price`) | — | ✅ | Not extracted; buyer enters. |
| **Needed by** (`needed_by`) | — | ✅ | Not extracted. Do **not** use `shipDate` here — it's a shipped date, not a need-by date. |
| **ERP system** (`erp`) | — | ✅ | Buyer selects (sap/infor). |
| **Quote deadline** (`quote_deadline`) | — | ✅ | Buyer selects. |
| Open-to-all / invite | — | ✅ | `open_to_all` + `supplier_ids`. |

### Requested quantity vs. document shipped quantity (important)

The draft's **`shippedQuantity`** is the quantity printed on the uploaded document.
It is **not** the same as the requirement's **`quantity`**, which is what the buyer
is requesting. The backend never writes `shippedQuantity` into `quantity`, and the
`POST /api/requirements` payload has no shipped-quantity field. The frontend must
keep them separate: show `shippedQuantity` only as a read-only hint, and let the
buyer type the requested `quantity` themselves.

Show `fieldIssues` and `warnings` next to the relevant inputs so the buyer confirms
uncertain values. If the buyer wants the uploaded file kept on record, attach it
**after** the requirement is created via the existing
`POST /api/requirements/{req_id}/attachments`.

### Example create payload (after the buyer reviews the draft)

```jsonc
POST /api/requirements
{
  "title": "Hydraulic Pump HP-200",
  "item_code": null,
  "description": "...",
  "quantity": 5,                     // buyer's REQUESTED quantity (not shippedQuantity)
  "target_price": null,
  "needed_by": null,
  "erp": "sap",
  "open_to_all": true,
  "supplier_ids": [],
  "ship_date": "2026-02-10",         // <- draft.shipDate
  "carrier": "FedEx",                // <- draft.carrier
  "tracking_number": "1Z999AA10123456784",  // <- draft.trackingNumbers joined
  "lot_numbers": ["LOT-7", "LOT-8"], // <- draft.lotNumbers
  "serial_numbers": []               // <- draft.serialNumbers
}
```

The create response, `GET /api/requirements/{id}`, and the list all echo these
fields back (`lot_numbers`/`serial_numbers` as JSON arrays), so the Requirements
table and preview render them.

### What is still not persisted

`unitOfMeasure` (PDF only) and the document's `shippedQuantity` have no dedicated
requirement column by design — `unitOfMeasure` can go into `description`, and
`shippedQuantity` is deliberately kept out of `quantity`. Everything else the
extractors return is now saveable.

---

## Configuration

All values have safe defaults; only the OpenAI key is required for the **image**
path. The key and model are read from the **process environment only** — never from
a committed file, and never logged or returned.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | — | Required for image extraction. 503 if missing. |
| `OPENAI_MODEL` | `gpt-4o` | Shared portal model; used if `SPL_OCR_MODEL` is unset. |
| `SPL_OCR_MODEL` | *(unset)* | Overrides the model for the image path only. |
| `SPL_MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Max upload size. |
| `SPL_MAX_IMAGE_BYTES` | `20971520` (20 MB) | Image decode-size guard. |
| `SPL_MAX_IMAGE_PIXELS` | `40000000` | Decompression-bomb guard. |
| `PACKING_CONVERT_TIMEOUT_S` | `600` | Per-attempt Docling PDF conversion timeout (seconds). |

The model/key never appear in responses or logs (the OpenAI `Settings` dataclass
has `repr=False` on the key). Keep real values in a **git-ignored** `.env`; see the
repo-root `.env.example` for placeholders.

---

## Running it

### Local (no Docker)

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate      # Python 3.11+ (datetime.UTC)
pip install -r requirements.txt                        # includes docling, pillow, …
# image path only:
export OPENAI_API_KEY=sk-...        # or put it in the git-ignored root .env
uvicorn app.main:app --reload
```

The `supplier_packing_list` package sits beside `app` under `backend/`, so it imports with no extra setup.
Docling downloads its layout/table models on the first PDF (hundreds of MB) into the
HuggingFace cache; subsequent runs are fast.

### Docker Compose

`OPENAI_API_KEY` is passed to the `backend` service from the environment / the
git-ignored root `.env` (Compose auto-loads it). Docling models are cached on the
`spl_models` volume (`HF_HOME=/models/huggingface`), so they download once and
survive restarts. The backend has a 4 GB memory limit for Docling's models.

```bash
# put OPENAI_API_KEY (and optionally SPL_OCR_MODEL) in the root .env, then:
docker compose up -d --build backend      # rebuild after dependency/Dockerfile changes
curl localhost:8000/health                 # {"status":"ok"}
```

---

## Architecture

```
router.py      POST /api/requirements/extract-draft  (buyer auth, size/err handling)
  └─ service.py  validate -> dispatch -> normalize  (async, blocking work off-loop)
       ├─ detect.py        extension + magic-byte content check
       ├─ pdf/isolation.py convert_isolated(): child process, timeout + 1 retry,
       │      pdf/{layout,extractor,fields}.py  (Docling rules — vendored from the PoC)
       ├─ image/           image_processing (validate), extraction (OpenAI), schemas
       └─ normalize.py     pdf result | image result -> DraftExtraction
```

- The PDF conversion runs via `python -m supplier_packing_list.pdf.isolation` in a **child process**;
  a native crash costs one attempt, never the API. Temp files are always cleaned up.
- The blocking PDF/image work runs in a threadpool, off the event loop.
- OpenAI is **never** called for PDFs.

### Vendored from the experiments

- `supplier_packing_list/pdf/*` ← `experiments/packing_list_poc_backend` (`fields`, `layout`,
  `extractor`, `isolation`) — only the imports were made package-relative and the
  isolation worker runs as `-m supplier_packing_list.pdf.isolation`; the extraction rules, isolation,
  timeout/retry, and conversion-error contract are unchanged.
- `supplier_packing_list/image/*` ← `experiments/image-to-json-backend/app` (`image_processing`,
  `extraction`, `schemas`) plus a rewritten `config` that reads the key/model from
  the environment only. The experiment's file-writing web layer is **not** vendored.

---

## Tests

```bash
cd backend
pytest supplier_packing_list/tests -q      # just this integration
pytest -q                # portal suite + this integration
```

`supplier_packing_list/tests` mocks Docling and OpenAI, so they run offline with no paid calls.
Coverage: file-type detection (ext + content), PDF/image dispatch, normalization,
missing/ambiguous/inferred fields, buyer access + supplier/inspector `403` + `401`,
invalid/oversized uploads, missing OpenAI key, conversion error, and draft-only
behaviour (no requirement created).
```
