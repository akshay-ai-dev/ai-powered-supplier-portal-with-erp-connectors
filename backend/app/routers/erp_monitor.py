"""The ERP Monitor page's data: what the mock ERPs hold, for buyers and admins only.

The mock ERPs themselves (/mock/*) stand in for external systems and have no login. This feed reads the same records for
the ERP Monitor page, which only buyers and admins can open. The narrowing below (a buyer's own inspector sees only that
buyer's documents) stays in place in case inspectors are given access again.
"""

import sqlite3

from fastapi import APIRouter, Depends

from ..connectors import get_connector, sap_live
from ..db import db_dep
from ..deps import require_buyer
from ..services import scope
from ..services.errors import NotFound

router = APIRouter(prefix="/api/erp-monitor", tags=["ERP monitor"])

# view -> (raw accessor on the connector, key of the PO reference or item code, what that key holds)
VIEWS = {
    "sap": {
        "purchase-orders": ("raw_purchase_orders", "EBELN", "po"),
        "inbound-deliveries": ("raw_inbound_deliveries", "EBELN", "po"),
        "stock-movements": ("raw_stock_movements", "EBELN", "po"),
        "invoice-blocks": ("raw_invoice_blocks", "EBELN", "po"),
        "materials": ("raw_materials", "MATNR", "item"),
    },
    "infor": {
        "orders": ("raw_orders", "orno", "po"),
        "receipts": ("raw_receipts", "orno", "po"),
        "stock-movements": ("raw_stock_movements", "orno", "po"),
        "invoice-holds": ("raw_invoice_holds", "orno", "po"),
        "items": ("raw_items", "item", "item"),
    },
}


@router.get(
    "/{erp}/{view}",
    summary="Records the mock ERP holds (buyers and admins only)",
)
def monitor(
    erp: str,
    view: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_buyer),
):
    spec = VIEWS.get(erp, {}).get(view)
    if spec is None:
        raise NotFound("Unknown ERP view")
    accessor, key, kind = spec
    rows = list(getattr(get_connector(erp), accessor)())
    buyer = scope.own_buyer(user)
    if buyer is None:
        return rows
    mine = scope.erp_references(conn, buyer) if kind == "po" else scope.item_codes(conn, buyer)
    return [
        r
        for r in rows
        if (str(r.get(key) or "") if kind == "po" else str(r.get(key) or "").upper()) in mine
    ]


@router.get(
    "/live/sap/{view}",
    summary="Live records from SAP S/4HANA, read-only (buyers and admins only)",
)
def live_sap(view: str, q: str | None = None, user: dict = Depends(require_buyer)):
    """Reads SAP directly (sandbox or a company's system, see SAP_MODE). Not narrowed per buyer: this is SAP's own data.
    `q` looks up one record by its number (PO number, supplier ID, ...)."""
    return sap_live.read(view, q)
