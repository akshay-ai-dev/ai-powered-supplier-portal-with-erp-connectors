# Image to JSON: shipment fields

Reads images of shipping documents (PNG, JPEG, static WEBP), sends them to the OpenAI API, and
saves **six shipment fields** per image as JSON:

| Key | Type | Meaning |
|---|---|---|
| `shipDate` | string `YYYY-MM-DD` or `null` | Date the goods were shipped |
| `carrier` | string or `null` | Shipping carrier, such as a parcel service or freight line |
| `trackingNumbers` | list of strings | Carrier tracking numbers |
| `shippedQuantity` | number ≥ 0 or `null` | Quantity shipped |
| `lotNumbers` | list of strings | Lot or batch numbers |
| `serialNumbers` | list of strings | Serial numbers |

There are two ways to use it:

- **Command line (batch):** processes every image in a folder. See sections 1–6.
- **Local web app:** upload one image at a time in your browser. See
  [Web app](#web-app-upload-one-image-in-the-browser).

Both run only on your computer. Your API key stays in the Python backend's `.env` file.

> **Important**
> - Your images are **sent to OpenAI** for processing.
> - **API usage costs money.** Each image is billed according to OpenAI's pricing for the model you use.
> - Requests are sent with `store=False`, which asks OpenAI not to store the response for later
>   retrieval. This does **not** guarantee zero data retention. See OpenAI's data-usage policies.
> - The AI can misread or miss values. **Always check extracted values against the original
>   images** before relying on them.

---

## 1. One-time setup

You need **Python 3.11 or newer**. Check with `python3 --version`.

Open a terminal in the project folder:

```bash
cd /Users/samhiteppanapally/image-to-json-backend
```

Create a virtual environment and install the dependencies. (Skip this if `.venv` already exists.)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You need to run `source .venv/bin/activate` again each time you open a new terminal. Your prompt
shows `(.venv)` when the environment is active.

## 2. Put your API key in `.env`

1. Create an API key at https://platform.openai.com/api-keys.
2. Open the file **`.env`** in the project folder in your editor
   (`/Users/samhiteppanapally/image-to-json-backend/.env`). If it doesn't exist, copy
   `.env.example` to `.env`.
3. Paste your key after the equals sign, with no quotes or spaces, and choose a model:

   ```
   OPENAI_API_KEY=sk-...your key...
   OPENAI_MODEL=gpt-6-luna
   ```

4. Save the file.

Keep your key secret. Never paste it into a chat, an email, a test file, or a git commit.
`.env` is listed in `.gitignore`, so git won't commit it. The program never prints the key.

### Choosing a model

`OPENAI_MODEL` decides which model reads the images. Model names are all lowercase. The model must
support **image input** and **Structured Outputs**. Prices per 1M tokens (input / output):

| Model | Price | Notes |
|---|---|---|
| `gpt-6-luna` | $0.10 / $0.50 | Cheapest current option; may misread small or dense text more often |
| `gpt-6.1-sol` | $2.00 / $10.00 | Used when `OPENAI_MODEL` is not set |
| `gpt-6-astra` | $10.00 / $50.00 | Most capable, most expensive |

Not every account can use every model. If yours can't, the program stops and tells you. The web
backend reads `.env` on every request, so a model change applies without restarting it.

## 3. Put your images in `data/`

Place images anywhere inside the `data` folder. Subfolders, including folders whose names
contain spaces, are fine. Supported: `.png`, `.jpg`, `.jpeg`, `.webp` (not animated). Other files
are ignored. Your original images are never modified.

## 4. Check what will be processed (free)

```bash
python main.py --input-dir data --output-dir outputs_shipments --dry-run
```

This lists the images it found and checks that each can be opened. It makes **no API calls**,
costs nothing, and doesn't need an API key.

## 5. Run the extraction (uses the API and costs money)

```bash
python main.py --input-dir data --output-dir outputs_shipments
```

`outputs_shipments` is also the default, so `python main.py` alone does the same thing.

Images are processed one at a time, with progress like:

```
[1/5] 1_raw_material.jpg ... ok (8.2s) -> outputs_shipments/1_raw_material.jpg.json
```

If a result already exists, the image is **skipped**, so rerunning never pays twice for the same
image. To deliberately process everything again:

```bash
python main.py --input-dir data --output-dir outputs_shipments --overwrite
```

## 6. Where the results go

- One JSON file per image in `outputs_shipments/`, mirroring any subfolders in `data/`. The
  original file extension is kept in the name, so `photo.png` and `photo.jpg` don't collide:
  `data/scans/photo.png` → `outputs_shipments/scans/photo.png.json`.
- `outputs_shipments/batch_summary.json` records, for every image in the last run: status
  (`success`, `failed`, `skipped`, `not_attempted`), any error, the model used, and the
  processing time.

Each result file contains **exactly the six keys**:

```json
{
  "shipDate": "2026-03-04",
  "carrier": "UPS Ground",
  "trackingNumbers": ["1Z999AA10123456784"],
  "shippedQuantity": 120,
  "lotNumbers": ["000123", "LOT-77/B"],
  "serialNumbers": []
}
```

### What the values mean

- **`null`** (for `shipDate`, `carrier`, `shippedQuantity`): the value isn't shown, couldn't be
  read, or was ambiguous.
- **`[]`** (for the three lists): none were found.
- **`shipDate`** is written only when the date is unambiguous. A date like `03/04/2026`, which
  could be March 4 or April 3, becomes `null` unless the document makes the date format clear.
  Invoice, order, and delivery dates are never used.
- **`carrier`** is the company transporting the goods, never the supplier or customer.
- **`shippedQuantity`** is the quantity shipped, never the quantity ordered, a weight, a price,
  or a count of boxes or pallets. Line quantities are added up only if they're clearly shipped
  quantities in the same unit; otherwise it's `null`.
- **Identifiers** are kept exactly as written, as text, so leading zeros (`000123`) and
  punctuation are kept. Duplicates are removed, and invoice, PO, and part numbers are excluded.

The program checks every result before saving it: exactly six keys, a real calendar date in
`YYYY-MM-DD` format, and a quantity that isn't negative. If a check fails, nothing is saved, and
the image shows as `failed` in `batch_summary.json` so the next run retries it.

There are no confidence scores. You must check values yourself.

### Earlier results are kept

Results from the earlier general-extraction version (text, fields, tables, warnings) are still in
`outputs/`, `outputs-luna/`, and `outputs/web/`. Nothing deletes or changes them. The program
won't write shipment results into a folder that contains old-format results. If you try, it
stops with an error and suggests `--output-dir outputs_shipments`.

## Web app: upload one image in the browser

The web app has two parts that run at the same time, each in its own terminal:

- **Backend** (Python, FastAPI) at `http://127.0.0.1:8000`. It holds the API key and calls OpenAI.
- **Frontend** (React, Vite) at `http://127.0.0.1:5173`. This is the page you open. It sends
  requests only to the backend, never to OpenAI, and never sees your API key.

### One-time setup

1. Complete [step 1](#1-one-time-setup) and [step 2](#2-put-your-api-key-in-env) above (Python
   environment and API key). If you set up the project before the web app existed, reinstall the
   Python dependencies to get the web server packages:

   ```bash
   cd /Users/samhiteppanapally/image-to-json-backend
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Install **Node.js 20.19 or newer** (https://nodejs.org) if `node --version` doesn't work.
3. Install the frontend packages:

   ```bash
   cd /Users/samhiteppanapally/image-to-json-backend/frontend
   npm install
   ```

### Starting it: two VS Code terminals

In VS Code, open a terminal (**Terminal → New Terminal**), then click **+** in the terminal
panel to open a second one.

**Terminal 1: backend**

```bash
cd /Users/samhiteppanapally/image-to-json-backend
source .venv/bin/activate
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Wait for `Uvicorn running on http://127.0.0.1:8000`.

**Terminal 2: frontend**

```bash
cd /Users/samhiteppanapally/image-to-json-backend/frontend
npm run dev
```

Wait for `Local: http://127.0.0.1:5173/`.

**Open http://127.0.0.1:5173 in your browser.** Keep both terminals running while you use the
app. To stop either server, click its terminal and press **Ctrl+C**.

After **code** changes (such as a project update), restart the backend: press Ctrl+C in
Terminal 1 and run the command again. Changes to `.env` don't need a restart.

### Using it

1. Check the status badge under the title. It should say **Backend connected · model …**.
2. **Choose an image:** click **Choose image**, or drag an image file onto the dashed box. Only
   one image at a time: PNG, JPEG, or static WEBP, up to 20 MB. A preview, the file name, and
   the size appear. Nothing is sent yet.
3. Click **Extract JSON**. Only this button sends the image to OpenAI, and each click is a paid
   request. A spinner shows while it works, usually under a minute. The button is disabled
   until the request finishes, so you can't submit twice by accident. Failed requests are
   **not** retried automatically.
4. **Results** appear on the right (or below, on narrow screens):
   - The file name, model, and processing time.
   - **Shipment fields:** all six fields, always shown. A missing value says *Not found*, and an
     empty list says *None found*.
   - **JSON:** exactly the six keys.
5. **Copy JSON** copies the six-key JSON to your clipboard. **Download JSON** saves the same
   six-key JSON as `<your image name>.json`, for example `invoice.png.json`.
6. **Clear** removes the image and results so you can start over. Choosing a different image
   also clears the old results.

Each successful web extraction is also saved by the backend in `outputs_shipments/web/`:
`<id>.json` holds the six-key result, and `<id>.meta.json` holds the file name, model, and time.
Uploaded images themselves are not saved.

### Web app troubleshooting

| What you see | What to do |
|---|---|
| "Could not reach the backend…" or "The backend did not respond properly (HTTP 502/504)" | Terminal 1 isn't running or has stopped. Start the backend (see above) and reload the page. |
| "…no OpenAI API key is configured" | Put your key in `/Users/samhiteppanapally/image-to-json-backend/.env` and reload the page. |
| "The backend response did not have the expected shape" | The backend is still running the old code. Restart it (Ctrl+C in Terminal 1, then start it again). |
| Browser can't open `127.0.0.1:5173` | Terminal 2 isn't running. Run `npm run dev` in the `frontend` folder. |
| `Port 5173 is in use` or `address already in use` (port 8000) | An old server is still running, possibly in another terminal tab. Press Ctrl+C there, then start again. Another program, such as a Docker container, may also be using port 8000. |
| `npm: command not found` | Install Node.js from https://nodejs.org, then open a new terminal. |
| `No module named uvicorn` or `fastapi` | Activate the environment (`source .venv/bin/activate`), then run `pip install -r requirements.txt`. |
| "Another extraction is already running" | Wait for the current extraction to finish, then try again. |
| "…is not a supported image" | Use a PNG, JPEG, or static (non-animated) WEBP. Convert other formats first. |
| "The image could not be used: …" | The file is corrupt, animated, or too large in pixels. Try re-saving or exporting it again. |
| "Authentication failed", "model … is not available", "no remaining quota" | The same causes as for the command line. See [Common errors](#common-errors). |

### Web API (for reference)

The frontend uses these backend endpoints. Interactive docs are at
http://127.0.0.1:8000/docs while the backend is running.

| Method and path | Purpose |
|---|---|
| `GET /health` | `{"status": "ok", "model": "...", "api_key_configured": true}`. Never returns the key itself. |
| `POST /api/v1/extractions` | Multipart upload, field name `file`. Waits for extraction. Returns `201 {"id", "download_url", "source_file", "model", "processed_at", "result"}`. `result` holds exactly the six shipment keys, and the other fields are information about the run. |
| `GET /api/v1/extractions/{id}/download` | Only the six-key `result`, as a `.json` file download. |

Errors always look like `{"error": {"code": "...", "message": "..."}}`, using HTTP status
400 (no file), 413 (over 20 MB), 415 (wrong file type), 422 (invalid image), 429 (another
extraction is running; at most 2 run at once), 502 (OpenAI request failed, the result failed
validation, or an account problem), or 503 (API key missing).

## Common errors

| Message | What to do |
|---|---|
| `OPENAI_API_KEY is not set` | Put your key in `.env` (step 2) and save the file. |
| `... contains N result file(s) in the previous (general extraction) format` | You pointed `--output-dir` at a folder of old results, such as `outputs`. Use `--output-dir outputs_shipments`. |
| `Authentication failed (HTTP 401)` | The key is wrong or revoked. Paste the full key again on one line, with no quotes or spaces. |
| `The model '...' is not available to your account` | Change `OPENAI_MODEL` in `.env` to a model your account can use, in lowercase (see "Choosing a model"). |
| `Permission denied (HTTP 403)` | Your project or key isn't allowed to use this model. Check model access and key permissions in the OpenAI dashboard. |
| `no remaining quota or credits (insufficient_quota)` | Add credits or raise your spending limit at https://platform.openai.com/settings/organization/billing. |
| `rate limited (HTTP 429)` | Too many requests too quickly. Wait a minute and rerun; finished images are skipped. |
| `request timed out` / `could not connect` | Check your internet connection and rerun. |
| `the model refused to process this image` | The model declined this image. Check the image; other images continue. |
| `incomplete response` / `failed schema validation` | The answer was cut off, or broke a rule such as a non-date `shipDate` or a negative quantity. Nothing is saved. Rerun that image. |
| `invalid image: ...` | The file is corrupt, animated, empty, too large (over 20 MB or 40 megapixels), or not really a PNG/JPEG/WEBP. |
| `input folder not found` | Check the `--input-dir` path. |
| `command not found: python` | Activate the environment first: `source .venv/bin/activate`. |

For authentication, model, permission, and quota errors, the program **stops making further API
calls**, because every remaining image would fail the same way. Fix the problem and rerun.

## Running the tests

The tests replace every OpenAI call with a fake response, so they need no API key and cost
nothing. They check the schema rules and plumbing, not how accurately a real model reads your
documents:

```bash
python -m pytest
```

Frontend tests, type check, and production build (`fetch` is mocked, so the backend doesn't
need to be running):

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

## Project layout

```
main.py                  command-line entry point (default output folder: outputs_shipments)
app/config.py            settings, .env loading, limits (size, timeout, retries)
app/schemas.py           the six-key JSON Schema sent to OpenAI + matching Pydantic model
app/image_processing.py  finds and validates images, fixes EXIF rotation in memory
app/extraction.py        OpenAI Responses API call with Structured Outputs + extraction rules
app/batch.py             processes images one by one, saves results and summary
app/api.py               local web API used by the frontend (FastAPI)
tests/                   backend tests with mocked API calls
frontend/                React + TypeScript + Vite web app
  src/App.tsx            the page (upload, preview, six fields, JSON, buttons)
  src/api.ts             calls to the backend (relative URLs only) and result types
  src/files.ts           file type and size checks that match the backend's
  src/App.test.tsx       UI tests with mocked backend responses
  vite.config.ts         dev server on 127.0.0.1:5173, forwards /api and /health to :8000
```

Limits and settings are in `app/config.py`: 180-second request timeout, 3 automatic retries
for temporary failures, a 20 MB / 40-megapixel image limit, and `high` image detail.
