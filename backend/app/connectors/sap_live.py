"""Read-only connection to SAP S/4HANA for the ERP Monitor's live SAP tab.

SAP_MODE in .env picks the source:
  sandbox - SAP Business Accelerator Hub (SAP's demo data). Needs SAP_API_HUB_KEY (api.sap.com > Show API Key).
  real    - a company's own S/4HANA system: SAP_BASE_URL + SAP_USERNAME / SAP_PASSWORD (a read-only technical user).
Empty or anything else switches the live tab off.

Only GET requests exist in this file, so nothing in SAP can be created or changed.
"""

import base64
import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from ..services.errors import DomainError, NotFound

SANDBOX_HUB = "https://sandbox.api.sap.com"
ODATA_PATH = "/s4hanacloud/sap/opu/odata/sap"
TIMEOUT_SECONDS = 20
MAX_ROWS = 20

# view -> (OData service, entity set, fields to show first)
VIEWS = {
    "purchase-orders": (
        "API_PURCHASEORDER_PROCESS_SRV",
        "A_PurchaseOrder",
        [
            "PurchaseOrder",
            "Supplier",
            "CompanyCode",
            "PurchaseOrderType",
            "PurchaseOrderDate",
            "DocumentCurrency",
        ],
    ),
    "suppliers": (
        "API_BUSINESS_PARTNER",
        "A_Supplier",
        [
            "Supplier",
            "SupplierName",
            "SupplierAccountGroup",
            "PurchasingIsBlocked",
            "PostingIsBlocked",
            "CreationDate",
        ],
    ),
    "requisitions": (
        "API_PURCHASEREQ_PROCESS_SRV",
        "A_PurchaseRequisitionItem",
        [
            "PurchaseRequisition",
            "PurchaseRequisitionItem",
            "Material",
            "RequestedQuantity",
            "BaseUnit",
            "Plant",
        ],
    ),
    "goods-receipts": (
        "API_MATERIAL_DOCUMENT_SRV",
        "A_MaterialDocumentHeader",
        [
            "MaterialDocument",
            "MaterialDocumentYear",
            "PostingDate",
            "DocumentDate",
            "InventoryTransactionType",
        ],
    ),
    "supplier-invoices": (
        "API_SUPPLIERINVOICE_PROCESS_SRV",
        "A_SupplierInvoice",
        [
            "SupplierInvoice",
            "FiscalYear",
            "InvoicingParty",
            "InvoiceGrossAmount",
            "DocumentCurrency",
            "PaymentBlockingReason",
        ],
    ),
    "materials": (
        "API_PRODUCT_SRV",
        "A_Product",
        ["Product", "ProductType", "ProductGroup", "BaseUnit", "CreationDate"],
    ),
}


class SapUnavailable(DomainError):
    """SAP is not set up, rejected the call, or did not answer."""

    def __init__(self, message: str):
        super().__init__(message, 503)


def _connection() -> tuple[str, dict]:
    """(base OData URL, request headers) for the current SAP_MODE."""
    mode = os.getenv("SAP_MODE", "").strip().lower()
    headers = {"Accept": "application/json"}
    if mode == "sandbox":
        key = os.getenv("SAP_API_HUB_KEY", "").strip()
        if not key:
            raise SapUnavailable("SAP_API_HUB_KEY is missing in .env.")
        hub = os.getenv("SAP_API_HUB_URL", "").strip().rstrip("/") or SANDBOX_HUB
        return hub + ODATA_PATH, {**headers, "APIKey": key}
    if mode == "real":
        base = os.getenv("SAP_BASE_URL", "").strip().rstrip("/")
        user, pwd = os.getenv("SAP_USERNAME", ""), os.getenv("SAP_PASSWORD", "")
        if not (base and user and pwd):
            raise SapUnavailable(
                "SAP_MODE=real needs SAP_BASE_URL, SAP_USERNAME and SAP_PASSWORD in .env."
            )
        if "/sap/opu/odata" not in base:  # SAP_BASE_URL may be just the host
            base += "/sap/opu/odata/sap"
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
        client = os.getenv("SAP_CLIENT", "").strip()
        if client:
            headers["sap-client"] = client  # which SAP client (mandant) to read from
        return base, headers
    raise SapUnavailable(
        "Live SAP is switched off. Set SAP_MODE=sandbox and SAP_API_HUB_KEY in .env."
    )


def _get(url: str, headers: dict) -> dict:
    """One HTTPS GET to SAP; returns the parsed JSON body."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            if raw[:2] == b"\x1f\x8b":  # SAP's sandbox sends gzip-compressed answers
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SapUnavailable(
                "SAP rejected the credentials (401). Check the key in .env."
            ) from exc
        if exc.code == 429:
            raise SapUnavailable("SAP rate limit reached (429). Try again in a minute.") from exc
        raise SapUnavailable(f"SAP returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SapUnavailable(
            "Could not reach SAP. Check the internet connection and try again."
        ) from exc


def _sap_date(value: str) -> str:
    """'/Date(1540771200000)/' -> '2018-10-29'."""
    match = re.search(r"-?\d+", value)
    return (
        datetime.fromtimestamp(int(match.group()) / 1000, tz=UTC).date().isoformat()
        if match
        else value
    )


def _clean(row: dict, preferred: list[str]) -> dict:
    """Preferred fields first, then the rest; drop OData metadata, links and empty values."""
    out = {}
    for key in preferred + [k for k in row if k not in preferred]:
        value = row.get(key)
        if key.startswith("__") or isinstance(value, dict | list) or value in ("", None):
            continue
        out[key] = (
            _sap_date(value) if isinstance(value, str) and value.startswith("/Date(") else value
        )
        if len(out) >= 10:
            break
    return out


# Plain SAP numbers only, so nothing can be injected into the $filter.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def read(view: str, q: str | None = None) -> list[dict]:
    """The first MAX_ROWS records of one SAP view, read-only. `q` looks up one record by its number."""
    spec = VIEWS.get(view)
    if spec is None:
        raise NotFound("Unknown SAP view")
    service, entity, preferred = spec
    params = {"$format": "json", "$top": MAX_ROWS}
    q = (q or "").strip()
    if q:
        if not _SAFE_ID.match(q):
            raise DomainError("Search with letters, digits, - or _ only (up to 20 characters).")
        params["$filter"] = f"{preferred[0]} eq '{q}'"  # the first field is the record's number
    base, headers = _connection()
    query = urllib.parse.urlencode(params)
    body = _get(f"{base}/{service}/{entity}?{query}", headers).get("d", {})
    return [_clean(row, preferred) for row in body.get("results", [])]
