"""Run each PDF conversion in its own child process, with a timeout and one retry.

Docling's native PDF parser (docling-parse) can crash the whole Python process with a
Windows access violation. Running every PDF in a fresh child process means a crash costs
one attempt on one PDF, never the caller or the rest of a batch.

    from isolation import convert_isolated, is_conversion_error
    result, markdown = convert_isolated("samples/pdf-5.pdf")

Protocol: the parent starts ``python -X faulthandler isolation.py --worker <pdf> <payload>``.
The child runs the normal extractor and atomically writes a payload JSON
``{"ok": true, "result": {...}, "markdown": "..."}`` (or ``{"ok": false, "error": {...}}``)
and exits 0. An attempt succeeds only if the child exits 0 AND the payload parses and says ok.

Timeout: DEFAULT_TIMEOUT_S (600 s) per attempt, overridable with the environment variable
PACKING_CONVERT_TIMEOUT_S. The slowest observed real run (a 6-page scanned PDF with OCR,
including model loading) took about 260 s, so 600 s leaves headroom on a slow machine. On
timeout the child's whole process tree is killed (the venv launcher starts a second python).

Retry: at most MAX_ATTEMPTS (2) attempts per PDF, each in a fresh process. If both fail, the
result is an explicit conversion-error document that contains no extracted fields.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_TIMEOUT_S = 600
MAX_ATTEMPTS = 2
STDERR_TAIL_LINES = 25

_WINDOWS_CODES = {
    0xC0000005: "access violation (0xC0000005)",
    0xC00000FD: "stack overflow (0xC00000FD)",
    0xC0000409: "stack buffer overrun / fail-fast (0xC0000409)",
    0xC000001D: "illegal instruction (0xC000001D)",
    0xC0000374: "heap corruption (0xC0000374)",
}
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)\b(\s*[:=]\s*)\S+"
)
_NOISE_RE = re.compile(r"Loading weights|\[INFO\]|UserWarning|return F\.conv")


def timeout_from_env(default=DEFAULT_TIMEOUT_S):
    try:
        value = float(os.environ.get("PACKING_CONVERT_TIMEOUT_S", default))
        return value if value > 0 else default
    except ValueError:
        return default


# --------------------------------------------------------------------------- atomic files


def write_text_atomic(path, text, encoding="utf-8"):
    """Write via a temp file in the same folder, fsync, then rename over the target.
    A crash at any point leaves either the old file or no file, never a partial one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_json_atomic(path, obj):
    # serialise first, so an unserialisable object never touches the target
    write_text_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- parent side


def describe_exit(code):
    if code is None:
        return "no exit code"
    unsigned = code & 0xFFFFFFFF
    if unsigned in _WINDOWS_CODES:
        return _WINDOWS_CODES[unsigned]
    if code < 0 and os.name != "nt":
        return f"killed by signal {-code}"
    return f"exit code {code}"


def _kill_tree(proc):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def _stderr_tail(log_path):
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    kept = [ln for ln in lines if ln.strip() and not _NOISE_RE.search(ln)]
    return [_SECRET_RE.sub(r"\1\2[redacted]", ln)[:300] for ln in kept[-STDERR_TAIL_LINES:]]


def default_worker_argv(pdf_path, payload_path):
    # Run the worker as a module so the vendored package-relative imports resolve
    # without any sys.path manipulation. PACKAGE_ROOT (the directory that holds the
    # ``supplier_packing_list`` package) is put on PYTHONPATH for the child in ``_run_attempt``.
    return [
        sys.executable,
        "-X",
        "faulthandler",
        "-m",
        "supplier_packing_list.pdf.isolation",
        "--worker",
        str(pdf_path),
        str(payload_path),
    ]


# The directory that contains the top-level ``supplier_packing_list`` package
# (…/backend), so a child started with ``-m supplier_packing_list.pdf.isolation`` can import it.
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _run_attempt(pdf_path, attempt, timeout_s, worker_argv, work_dir, log_dir):
    payload = Path(work_dir) / f"{Path(pdf_path).stem}.attempt{attempt}.payload.json"
    log_path = Path(log_dir) / f"{Path(pdf_path).stem}.attempt{attempt}.log"
    for p in (payload,):
        if p.exists():
            p.unlink()
    record = {
        "attempt": attempt,
        "status": None,
        "reason": None,
        "exitCode": None,
        "seconds": None,
        "log": str(log_path),
    }
    t0 = time.perf_counter()
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(PACKAGE_ROOT), child_env["PYTHONPATH"]]
        if child_env.get("PYTHONPATH")
        else [str(PACKAGE_ROOT)]
    )
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            worker_argv(pdf_path, payload),
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(PACKAGE_ROOT),
            env=child_env,
        )
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            record.update(
                status="timeout", reason=f"exceeded {timeout_s:g} s timeout; process tree killed"
            )
    record["seconds"] = round(time.perf_counter() - t0, 3)
    record["exitCode"] = proc.returncode
    if record["status"] == "timeout":
        record["stderrTail"] = _stderr_tail(log_path)
        return record, None

    data = None
    if payload.exists():
        try:
            data = json.loads(payload.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            record.update(status="invalid_output", reason=f"payload unreadable: {exc}")
    if proc.returncode != 0:
        record.update(status="crash", reason=describe_exit(proc.returncode))
        data = None  # never trust output from a process that did not exit cleanly
    elif record["status"] is None and data is None:
        record.update(status="no_output", reason="child exited 0 but wrote no payload")
    elif record["status"] is None and not data.get("ok"):
        err = data.get("error") or {}
        record.update(
            status="worker_error",
            reason=f"{err.get('type', 'Error')}: {err.get('message', '')}"[:500],
        )
        data = None
    elif record["status"] is None and not isinstance(data.get("result"), dict):
        record.update(status="invalid_output", reason="payload has no result object")
        data = None
    if data is not None and record["status"] is None:
        record["status"] = "ok"
    else:
        record["stderrTail"] = _stderr_tail(log_path)
        data = None
    with contextlib.suppress(OSError):
        payload.unlink()
    return record, data


def conversion_error(pdf_path, attempts, extractor_version=None):
    """Explicit failure document. It deliberately has none of the extracted-field keys."""
    last = attempts[-1] if attempts else {}
    return {
        "sourceFile": Path(pdf_path).name,
        "extractorVersion": extractor_version,
        "status": "conversion_error",
        "conversionError": {
            "pdf": str(pdf_path),
            "message": f"Conversion failed after {len(attempts)} attempt(s); last failure: "
            f"{last.get('status')} - {last.get('reason')}",
            "attempts": attempts,
        },
    }


def is_conversion_error(result):
    return isinstance(result, dict) and result.get("status") == "conversion_error"


def convert_isolated(
    pdf_path, timeout_s=None, max_attempts=MAX_ATTEMPTS, worker_argv=None, log_dir=None
):
    """Return (result, markdown). On failure result is a conversion-error document and markdown is None.

    A successful result is exactly what the in-process extractor returns, plus
    timings["isolation"] with the attempt records.
    """
    timeout_s = timeout_s if timeout_s is not None else timeout_from_env()
    worker_argv = worker_argv or default_worker_argv
    attempts = []
    with tempfile.TemporaryDirectory(prefix="pl-convert-") as work_dir:
        log_dir = Path(log_dir) if log_dir else Path(work_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, max_attempts + 1):
            record, data = _run_attempt(
                pdf_path, attempt, timeout_s, worker_argv, work_dir, log_dir
            )
            if log_dir == Path(work_dir):
                record["log"] = None  # temp log is deleted with the work dir
            attempts.append(record)
            if data is not None:
                result = data["result"]
                result.setdefault("timings", {})["isolation"] = {
                    "attempts": attempts,
                    "attemptCount": len(attempts),
                    "timeoutSeconds": timeout_s,
                }
                return result, data.get("markdown")
    return conversion_error(pdf_path, attempts, _extractor_version()), None


def _extractor_version():
    try:
        from .fields import EXTRACTOR_VERSION

        return EXTRACTOR_VERSION
    except Exception:  # pragma: no cover - fields.py is part of this project
        return None


# --------------------------------------------------------------------------- child side


def _worker(pdf_path, payload_path):
    try:
        from .extractor import extract_pdf, to_json_ready

        result = extract_pdf(Path(pdf_path))
        layout = result.pop("_layout", None)
        payload = {
            "ok": True,
            "result": to_json_ready(result),
            "markdown": layout.markdown if layout is not None else None,
        }
    except Exception as exc:  # report Python-level failures; native crashes end the process
        payload = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
    write_json_atomic(payload_path, payload)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        sys.exit(_worker(sys.argv[2], sys.argv[3]))
    sys.exit("usage: isolation.py --worker <pdf> <payload.json>")
