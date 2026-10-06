"""What a buyer's own inspector may see beyond requirements, orders and shipments: the suppliers, inventory items and ERP
documents that belong to that buyer's work. Company-wide inspectors, admins and buyers are not narrowed here."""

import sqlite3


def own_buyer(user: dict | None) -> int | None:
    """The buyer an inspector was created by; None for everyone else (including company-wide inspectors)."""
    if user and user["role"] == "inspector":
        return user.get("owner_id")
    return None


# SQL fragments over the buyer's id (used with the same value bound three or two times, see the callers)
SUPPLIERS_OF_BUYER = (
    "SELECT supplier_id FROM purchase_orders WHERE created_by = :b "
    "UNION SELECT ri.supplier_id FROM requirement_invites ri JOIN requirements r ON r.id = ri.requirement_id WHERE r.created_by = :b "
    "UNION SELECT q.supplier_id FROM quotes q JOIN requirements r ON r.id = q.requirement_id WHERE r.created_by = :b"
)
ITEMS_OF_BUYER = (
    "SELECT UPPER(poi.item_code) FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id WHERE po.created_by = :b "
    "UNION SELECT UPPER(item_code) FROM requirements WHERE created_by = :b AND item_code IS NOT NULL "
    "UNION SELECT UPPER(item_code) FROM inventory WHERE created_by = :b"
)


def supplier_ids(conn: sqlite3.Connection, buyer_id: int) -> set[int]:
    return {r[0] for r in conn.execute(SUPPLIERS_OF_BUYER, {"b": buyer_id})}


def item_codes(conn: sqlite3.Connection, buyer_id: int) -> set[str]:
    return {r[0] for r in conn.execute(ITEMS_OF_BUYER, {"b": buyer_id})}


def erp_references(conn: sqlite3.Connection, buyer_id: int) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT erp_reference FROM purchase_orders WHERE created_by = ? AND erp_reference IS NOT NULL",
            (buyer_id,),
        )
    }
