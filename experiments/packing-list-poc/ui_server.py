"""Local browser UI for the Supplier Packing-List Pre-Fill POC.

    .\\.venv\\Scripts\\python.exe ui_server.py            # then open http://127.0.0.1:8765/

Standard library only, except DOCX export (python-docx, already installed with Docling). Extraction runs through isolation.convert_isolated
(one child process per PDF, timeout + one retry); PO comparison runs through po_check via
review.py on the supplier's EDITED values. Everything stays on this machine: the server binds
to 127.0.0.1, uploads are written to a temporary folder that is deleted after conversion, and
results live only in memory. Nothing is submitted as a shipment or posted to ERP.

API (JSON):
  GET  /api/health                      -> limits and whether a conversion is running
  POST /api/jobs?filename=<name>.pdf    -> body = raw PDF bytes; 202 {jobId} (409 if busy)
  GET  /api/jobs/<jobId>                -> {status: running|done|failed, elapsedSeconds, result|error}
  POST /api/po-compare                  -> {draft, po} -> recomputed totals + PO comparison
  POST /api/review                      -> {original, draft, po, acknowledged} -> validation, reviewed JSON
                                           (kept for later backend use) and a readable summary
  POST /api/export?format=txt|pdf|docx  -> {reviewed} -> download built from the final edited values
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import review
import summary_export
from isolation import MAX_ATTEMPTS, convert_isolated, is_conversion_error, timeout_from_env

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
JOB_TTL_SECONDS = 3600
MAX_JOBS = 20
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}

FRIENDLY_ATTEMPT = {
    "crash": "The PDF reader stopped unexpectedly while converting this file "
             "(a known, intermittent issue in the PDF parser).",
    "timeout": "Conversion took longer than the time limit.",
    "worker_error": "The file could not be read as a PDF. It may be damaged, password-protected "
                    "or not a real PDF.",
    "no_output": "Conversion finished without producing a result.",
    "invalid_output": "Conversion produced an unreadable result.",
}


def safe_display_name(name):
    """Base name with only harmless characters; used for display, never as a path on disk."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", base).strip(" .") or "upload.pdf"
    return base[:100]


def friendly_failure(result):
    """Turn a conversion_error document into UI-safe text (no stderr tails, no tracebacks)."""
    attempts = result.get("conversionError", {}).get("attempts", [])
    last = attempts[-1] if attempts else {}
    message = FRIENDLY_ATTEMPT.get(last.get("status"), "Conversion failed.")
    return {
        "kind": "conversion_error",
        "message": f"{message} It was tried {len(attempts)} time(s), each in a fresh process.",
        "advice": "Try uploading the file again. If it keeps failing, enter the shipment details manually.",
        "attempts": [{"attempt": a.get("attempt"), "outcome": a.get("status"),
                      "explanation": FRIENDLY_ATTEMPT.get(a.get("status"), a.get("status")),
                      "seconds": a.get("seconds")} for a in attempts],
    }


class App:
    """State shared by request handlers. `convert` is injectable for tests."""

    def __init__(self, convert=None, max_upload_bytes=MAX_UPLOAD_BYTES):
        self.convert = convert or (lambda pdf_path: convert_isolated(pdf_path))
        self.max_upload_bytes = max_upload_bytes
        self.jobs = {}
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- jobs
    def busy(self):
        return any(j["status"] == "running" for j in self.jobs.values())

    def _prune(self):
        now = time.time()
        for jid in [j for j, job in self.jobs.items()
                    if job["status"] != "running" and now - job["startedAt"] > JOB_TTL_SECONDS]:
            self.jobs.pop(jid, None)
        finished = sorted((j for j in self.jobs.values() if j["status"] != "running"), key=lambda j: j["startedAt"])
        while len(self.jobs) > MAX_JOBS and finished:
            self.jobs.pop(finished.pop(0)["id"], None)

    def start_job(self, filename, data):
        with self.lock:
            self._prune()
            if self.busy():
                return None
            job = {"id": uuid.uuid4().hex, "filename": filename, "status": "running",
                   "startedAt": time.time(), "finishedAt": None, "result": None, "error": None}
            self.jobs[job["id"]] = job
        work_dir = Path(tempfile.mkdtemp(prefix="pl-ui-"))
        pdf_path = work_dir / "upload.pdf"  # fixed name: user input never becomes a path
        pdf_path.write_bytes(data)
        threading.Thread(target=self._run, args=(job, work_dir, pdf_path), daemon=True).start()
        return job

    def _run(self, job, work_dir, pdf_path):
        try:
            result, _markdown = self.convert(pdf_path)
            if is_conversion_error(result):
                job["error"] = friendly_failure(result)
                job["status"] = "failed"
            else:
                result["sourceFile"] = job["filename"]
                job["result"] = result
                job["status"] = "done"
        except Exception:  # never leak a traceback to the browser; keep it in the server console
            traceback.print_exc()
            job["error"] = {"kind": "internal", "message": "The server hit an unexpected error while "
                                                           "processing this file.",
                            "advice": "Check the server console window for details, then try again."}
            job["status"] = "failed"
        finally:
            job["finishedAt"] = time.time()
            shutil.rmtree(work_dir, ignore_errors=True)

    def job_view(self, job):
        end = job["finishedAt"] or time.time()
        view = {"jobId": job["id"], "filename": job["filename"], "status": job["status"],
                "elapsedSeconds": round(end - job["startedAt"], 1)}
        if job["status"] == "done":
            view["result"] = job["result"]
        elif job["status"] == "failed":
            view["error"] = job["error"]
        return view


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PackingListPOC/1.0"

        def log_message(self, fmt, *args):  # quieter console: method, path, status only
            if not str(args[0]).startswith("GET /api/jobs/"):
                super().log_message(fmt, *args)

        # ---------------------------------------------------------- helpers
        def _send(self, status, body, content_type="application/json; charset=utf-8", download_name=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status, message, **extra):
            self._send(status, {"error": {"message": message, **extra}})

        def _read_body(self, limit):
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                self._error(HTTPStatus.LENGTH_REQUIRED, "Upload size is missing.")
                return None
            length = int(length)
            if length > limit:
                self.close_connection = True
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            f"File is too large. The limit is {limit // (1024 * 1024)} MB.")
                return None
            return self.rfile.read(length)

        def _read_json(self):
            raw = self._read_body(MAX_JSON_BYTES)
            if raw is None:
                return None
            try:
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
                return data
            except (ValueError, UnicodeDecodeError):
                self._error(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
                return None

        # ---------------------------------------------------------- routes
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/health":
                return self._send(HTTPStatus.OK, {
                    "ok": True, "busy": app.busy(), "maxUploadMB": app.max_upload_bytes // (1024 * 1024),
                    "timeoutSecondsPerAttempt": timeout_from_env(), "maxAttempts": MAX_ATTEMPTS})
            if path.startswith("/api/jobs/"):
                job = app.jobs.get(path.rsplit("/", 1)[-1])
                if not job:
                    return self._error(HTTPStatus.NOT_FOUND, "This processing job no longer exists. "
                                                             "Please upload the PDF again.")
                return self._send(HTTPStatus.OK, app.job_view(job))
            if path.startswith("/api/"):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
            name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            target = (WEB_DIR / name).resolve()
            if target.parent != WEB_DIR or target.suffix not in STATIC_TYPES or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "Not found.")
            return self._send(HTTPStatus.OK, target.read_bytes(), STATIC_TYPES[target.suffix])

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/jobs":
                return self._post_job(url)
            if url.path == "/api/export":
                return self._post_export(url)
            if url.path in ("/api/po-compare", "/api/review"):
                data = self._read_json()
                if data is None:
                    return None
                draft = data.get("draft")
                if not isinstance(draft, dict):
                    return self._error(HTTPStatus.BAD_REQUEST, "Missing draft.")
                if url.path == "/api/po-compare":
                    out = review.compare_with_po(draft, data.get("po"))
                    return self._send(HTTPStatus.OK, {k: out[k] for k in ("totals", "errors", "comparison",
                                                                          "poRequested")}
                                      | {"shippedQuantity": out["draft"]["shippedQuantity"],
                                         "unitOfMeasure": out["draft"]["unitOfMeasure"]})
                ack = data.get("acknowledged") if isinstance(data.get("acknowledged"), list) else []
                out = review.finish_review(data.get("original") or {}, draft, data.get("po"), ack)
                out["summary"] = summary_export.build_summary(out["reviewed"]) if out["ok"] else None
                return self._send(HTTPStatus.OK, out)
            return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")

        def _post_export(self, url):
            fmt = parse_qs(url.query).get("format", [""])[0].lower()
            if fmt not in summary_export.EXPORT_FORMATS:
                return self._error(HTTPStatus.BAD_REQUEST, "Unknown export format. Use TXT, PDF or DOCX.")
            data = self._read_json()
            if data is None:
                return None
            try:
                body, content_type, filename = summary_export.export(data.get("reviewed"), fmt)
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception:  # keep tracebacks in the console only
                traceback.print_exc()
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                                   "The file could not be created. Check the server console for details.")
            return self._send(HTTPStatus.OK, body, content_type, download_name=filename)

        def _post_job(self, url):
            name = safe_display_name(parse_qs(url.query).get("filename", [""])[0])
            if not name.lower().endswith(".pdf"):
                return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                                   "Only PDF files are supported in this POC (images are planned separately).")
            if app.busy():
                return self._error(HTTPStatus.CONFLICT, "Another PDF is still being processed. "
                                                        "Please wait for it to finish.")
            data = self._read_body(app.max_upload_bytes)
            if data is None:
                return None
            if not data:
                return self._error(HTTPStatus.BAD_REQUEST, "The selected file is empty.")
            if not data[:1024].lstrip().startswith(b"%PDF-"):
                return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                                   "This file does not look like a PDF (it has no PDF header).")
            job = app.start_job(name, data)
            if job is None:
                return self._error(HTTPStatus.CONFLICT, "Another PDF is still being processed. "
                                                        "Please wait for it to finish.")
            return self._send(HTTPStatus.ACCEPTED, {"jobId": job["id"], "filename": name})

    return Handler


def make_server(app, host="127.0.0.1", port=8765):
    return ThreadingHTTPServer((host, port), make_handler(app))


def main():
    ap = argparse.ArgumentParser(description="Local browser UI for the packing-list POC")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 so the UI stays on this machine")
    args = ap.parse_args()
    server = make_server(App(), args.host, args.port)
    print(f"Packing-list POC UI running at http://{args.host}:{args.port}/  (Ctrl+C to stop)")
    print("Local POC only: nothing is submitted as a shipment or posted to ERP.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
