"""Read-only client for SAP S/4HANA OData v2 APIs.

Three modes, chosen with SAP_MODE in the repo-root .env:
  mock     - reads samples/*.json (no network, no key). Default.
  sandbox  - SAP Business Accelerator Hub sandbox (demo data), header `APIKey: <SAP_API_HUB_KEY>`.
  real     - a company's own S/4HANA system: SAP_BASE_URL + SAP_USERNAME / SAP_PASSWORD
             (a technical user the client's SAP admin creates with read-only API access).

Only GET requests exist in this file, so nothing can be created or changed in SAP.
Logs go to stderr, because stdout carries the MCP stdio protocol.
"""

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SANDBOX_BASE_URL = "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap"

SUPPLIER_SERVICE = "API_BUSINESS_PARTNER"
PO_SERVICE = "API_PURCHASEORDER_PROCESS_SRV"


def _load_dotenv() -> None:
    """Load the nearest .env above this folder without overriding real env vars."""
    for folder in [HERE, *HERE.parents]:
        env_file = folder / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.split(" #", 1)[0].strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)
            return


_load_dotenv()

MODE = (os.environ.get("SAP_MODE") or "mock").strip().lower()
TIMEOUT = float(os.environ.get("SAP_TIMEOUT_SECONDS") or 20)


class SapError(Exception):
    """A clear, user-facing error (bad key, SAP down, timeout)."""


def log(message: str) -> None:
    print(f"[sap] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Low-level GET
# ---------------------------------------------------------------------------


def _connection() -> tuple[str, dict, tuple | None]:
    """Return (base_url, headers, basic_auth) for the current mode."""
    headers = {"Accept": "application/json"}
    if MODE == "sandbox":
        # Same names as the repo's .env.example (SAP Business Accelerator Hub section)
        key = (os.environ.get("SAP_API_HUB_KEY") or os.environ.get("SAP_API_KEY") or "").strip()
        if not key or "paste" in key:
            raise SapError("SAP_API_HUB_KEY is missing in .env (copy it from api.sap.com > Show API Key).")
        hub = os.environ.get("SAP_API_HUB_URL", "").rstrip("/")
        base = f"{hub}/s4hanacloud/sap/opu/odata/sap" if hub else SANDBOX_BASE_URL
        return base, {**headers, "APIKey": key}, None
    if MODE == "real":
        base = os.environ.get("SAP_BASE_URL", "").rstrip("/")
        user, pwd = os.environ.get("SAP_USERNAME", ""), os.environ.get("SAP_PASSWORD", "")
        if not (base and user and pwd):
            raise SapError("Real mode needs SAP_BASE_URL, SAP_USERNAME and SAP_PASSWORD in .env.")
        return base, headers, (user, pwd)
    raise SapError(f"Unknown SAP_MODE '{MODE}'. Use mock, sandbox or real.")


def _mock(entity: str) -> list[dict]:
    data = json.loads((HERE / "samples" / f"{entity}.json").read_text(encoding="utf-8"))
    return data["d"]["results"]


def odata_get(service: str, entity: str, params: dict | None = None) -> list[dict]:
    """GET an OData v2 entity set and return its rows (d.results).

    In mock mode the sample file is returned unfiltered; callers filter again in Python,
    so mock and sandbox give the same shape of answer.
    """
    if MODE == "mock":
        log(f"mock  {service}/{entity}")
        return _mock(entity)

    base, headers, auth = _connection()
    url = f"{base}/{service}/{entity}"
    query = {"$format": "json", **(params or {})}
    log(f"GET   {url} {query}")
    started = time.perf_counter()
    try:
        response = httpx.get(url, params=query, headers=headers, auth=auth, timeout=TIMEOUT)
    except httpx.TimeoutException as exc:
        raise SapError(f"SAP did not answer within {TIMEOUT:.0f} s.") from exc
    except httpx.HTTPError as exc:
        raise SapError(f"Could not reach SAP: {exc.__class__.__name__}.") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    limits = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
    log(f"SAP   HTTP {response.status_code} in {elapsed_ms:.0f} ms" + (f" rate-limit headers: {limits}" if limits else ""))

    if response.status_code == 401:
        raise SapError("SAP rejected the credentials (401). Check SAP_API_HUB_KEY / SAP user in .env.")
    if response.status_code == 429:
        wait = response.headers.get("Retry-After", "a few")
        raise SapError(f"SAP rate limit reached (429). Try again in {wait} seconds.")
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise SapError(f"SAP returned HTTP {response.status_code}: {response.text[:200]}")

    body = response.json().get("d", {})
    return body.get("results", [body] if body else [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,10}$")  # e.g. 1018, USSU_V8000; no quotes or spaces


def check_id(value: str, kind: str) -> str:
    """Allow only plain SAP IDs, so nothing can be injected into an OData $filter."""
    value = (value or "").strip()
    if not _SAFE_ID.match(value):
        raise ValueError(f"{kind} must be 1-10 letters, digits, _ or -, got '{value}'.")
    return value


def odata_text(value: str) -> str:
    """Escape a text value for an OData string literal."""
    return value.replace("'", "''")


def clamp_top(top: int, maximum: int = 20) -> int:
    return max(1, min(int(top or 5), maximum))


def sap_date(value: str | None) -> str | None:
    """'/Date(1540771200000)/' -> '2018-10-29'."""
    if not value:
        return None
    match = re.search(r"\d+", value)
    if not match:
        return value
    return datetime.fromtimestamp(int(match.group()) / 1000, tz=UTC).date().isoformat()
