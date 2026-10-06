import sqlite3

from ..db import now
from . import scope
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit


def usage_count(conn: sqlite3.Connection, item_code: str) -> int:
    """How many purchase-order lines and requirements reference this item."""
    pos = conn.execute("SELECT COUNT(*) FROM purchase_order_items WHERE item_code = ? COLLATE NOCASE", (item_code,)).fetchone()[0]
    reqs = conn.execute("SELECT COUNT(*) FROM requirements WHERE item_code = ? COLLATE NOCASE", (item_code,)).fetchone()[0]
    return pos + reqs


def can_manage(user: dict | None, item: dict) -> bool:
    """Creators may edit/delete their own items; admins may manage any. ERP-synced items have no creator."""
    if user is None:
        return False
    return user["role"] == "admin" or (item.get("created_by") is not None and item["created_by"] == user["id"])


def list_items(conn: sqlite3.Connection, q: str | None = None, warehouse: str | None = None, user: dict | None = None) -> list[dict]:
    sql, args = "SELECT * FROM inventory WHERE 1=1", []
    if q:
        sql += " AND (item_code LIKE ? OR description LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if warehouse:
        sql += " AND warehouse = ?"
        args.append(warehouse)
    items = [dict(r) for r in conn.execute(sql + " ORDER BY item_code", args).fetchall()]
    buyer = scope.own_buyer(user)
    if buyer is not None:  # a buyer's own inspector sees only the items that buyer's orders, requirements and stock use
        mine = scope.item_codes(conn, buyer)
        items = [it for it in items if it["item_code"].upper() in mine]
    if user is not None:
        for it in items:
            it["can_edit"] = it["can_delete"] = can_manage(user, it)
            it["in_use"] = usage_count(conn, it["item_code"])
    return items


def get_item(conn: sqlite3.Connection, item_code: str, user: dict | None = None) -> dict:
    row = conn.execute("SELECT * FROM inventory WHERE item_code = ? COLLATE NOCASE", (item_code,)).fetchone()
    if row is None:
        raise NotFound(f"Item {item_code} not found")
    buyer = scope.own_buyer(user)
    if buyer is not None and row["item_code"].upper() not in scope.item_codes(conn, buyer):
        raise NotFound(f"Item {item_code} not found")
    return dict(row)


def receive_stock(conn: sqlite3.Connection, item_code: str, quantity: int) -> None:
    """Add received goods to stock (creates the item if it is new)."""
    cur = conn.execute(
        "UPDATE inventory SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE item_code = ?",
        (quantity, now(), item_code),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, updated_at) VALUES (?,?,?,?,?)",
            (item_code, item_code, quantity, "MAIN", now()),
        )


def create_item(conn: sqlite3.Connection, user: dict, data: dict) -> dict:
    code = data["item_code"].strip().upper()
    if conn.execute("SELECT 1 FROM inventory WHERE item_code = ?", (code,)).fetchone():
        raise DomainError(f"Item {code} already exists", 409)
    conn.execute(
        "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, source, created_by, updated_at) VALUES (?,?,?,?,?,?,?)",
        (code, data["description"].strip(), data["stock_quantity"], data.get("warehouse") or "MAIN", "manual", user["id"], now()),
    )
    audit(conn, user["id"], "create", "inventory", code, f"stock={data['stock_quantity']}")
    return get_item(conn, code)


def update_item(conn: sqlite3.Connection, user: dict, item_code: str, changes: dict) -> dict:
    current = get_item(conn, item_code)
    if not can_manage(user, current):
        raise Forbidden("You can only edit items you created")
    merged = {k: (changes[k] if changes.get(k) is not None else current[k]) for k in ("description", "stock_quantity", "warehouse")}
    conn.execute(
        "UPDATE inventory SET description=?, stock_quantity=?, warehouse=?, updated_at=? WHERE id=?",
        (merged["description"], merged["stock_quantity"], merged["warehouse"], now(), current["id"]),
    )
    detail = f"stock {current['stock_quantity']} -> {merged['stock_quantity']}" if merged["stock_quantity"] != current["stock_quantity"] else "details"
    audit(conn, user["id"], "update", "inventory", current["item_code"], detail)
    return get_item(conn, current["item_code"])


def delete_item(conn: sqlite3.Connection, user: dict, item_code: str) -> None:
    item = get_item(conn, item_code)
    if not can_manage(user, item):
        raise Forbidden("You can only delete items you created")
    used = usage_count(conn, item["item_code"])
    if used:
        raise DomainError(f"{item['item_code']} is used by {used} purchase order line(s) or requirement(s) and cannot be deleted", 409)
    conn.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
    audit(conn, user["id"], "delete", "inventory", item["item_code"], item["description"])
