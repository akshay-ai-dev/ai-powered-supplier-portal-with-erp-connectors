"""ERP capabilities exposed to AI agents. Shared by the FastMCP server and the
OpenAPI-compatible REST wrappers so both surfaces behave identically."""
import sqlite3

from . import inventory as inventory_svc
from .errors import NotFound
from . import purchase_orders as po_svc
from . import requirements as req_svc
from . import suppliers as suppliers_svc


def get_inventory(conn: sqlite3.Connection, item_code: str) -> dict:
    item = inventory_svc.get_item(conn, item_code)
    return {
        "item_code": item["item_code"],
        "stock": item["stock_quantity"],
        "description": item["description"],
        "warehouse": item["warehouse"],
    }


def search_supplier(conn: sqlite3.Connection, supplier_name: str) -> list[dict]:
    return suppliers_svc.list_suppliers(conn, supplier_name)


def _last_unit_price(conn: sqlite3.Connection, item_code: str) -> float:
    row = conn.execute(
        "SELECT unit_price FROM purchase_order_items WHERE item_code = ? ORDER BY id DESC LIMIT 1", (item_code,)
    ).fetchone()
    return row["unit_price"] if row else 0.0


def create_purchase_order(
    conn: sqlite3.Connection, user: dict, supplier_id: int, item_code: str, quantity: int, unit_price: float | None = None
) -> dict:
    inventory_svc.get_item(conn, item_code)  # validates the item exists
    price = unit_price if unit_price is not None else _last_unit_price(conn, item_code)
    return po_svc.create_po(
        conn, user, supplier_id, [{"item_code": item_code, "quantity": quantity, "unit_price": price}], submit=False
    )


def get_purchase_order(conn: sqlite3.Connection, user: dict, po_number: str) -> dict:
    return po_svc.get_po_by_number(conn, user, po_number)


def list_requirements(conn: sqlite3.Connection, user: dict, stage: str | None = None) -> list[dict]:
    """Requirements visible to the acting buyer, trimmed to what an agent needs to reason about them."""
    keys = ("id", "req_number", "title", "quantity", "target_price", "needed_by", "quote_deadline", "erp", "stage", "quote_count", "po_number", "unread_messages")
    return [{k: r.get(k) for k in keys} for r in req_svc.list_requirements(conn, user, stage)]


def get_requirement(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """One requirement with its quotes, so an agent can compare suppliers."""
    row = conn.execute("SELECT id FROM requirements WHERE req_number = ?", (req_number.upper(),)).fetchone()
    if row is None:
        raise NotFound(f"Requirement {req_number} not found")
    r = req_svc.get_requirement(conn, user, row["id"])
    keep = ("id", "req_number", "title", "description", "item_code", "quantity", "target_price", "needed_by", "erp", "stage", "po_number", "quotes", "invites")
    return {k: r.get(k) for k in keep}


def list_purchase_orders(conn: sqlite3.Connection, user: dict, status: str | None = None) -> list[dict]:
    keys = ("po_number", "supplier_name", "status", "delivery_status", "total_amount", "erp", "created_via", "items")
    return [{k: p.get(k) for k in keys} for p in po_svc.list_pos(conn, user, status)]
