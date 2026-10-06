"""The ERP Monitor page's data: what the mock ERPs hold, for people who are signed in.

The mock ERPs themselves (/mock/*) stand in for external systems and have no login. This feed reads the same records and, for a
buyer's own inspector, keeps only the documents that belong to that buyer's purchase orders (every ERP document carries the
PO's ERP reference) and only the items that buyer's work uses.
"""

import sqlite3

from fastapi import APIRouter, Depends

from ..connectors import get_connector
from ..db import db_dep
from ..deps import require_reader
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
    summary="Records the mock ERP holds (a buyer's own inspector sees only that buyer's)",
)
def monitor(
    erp: str,
    view: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_reader),
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
