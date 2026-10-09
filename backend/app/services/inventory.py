import sqlite3

from ..db import now
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit


def owner_of(user: dict | None) -> int | None:
    """Whose inventory this user works with: buyers and suppliers their own, a buyer's own inspector that buyer's.
    None means every owner (admins, company-wide inspectors, and internal callers without a user)."""
    if user is None or user["role"] == "admin":
        return None
    if user["role"] == "inspector":
        return user.get("owner_id")
    return user["id"]


def usage_count(conn: sqlite3.Connection, item: dict) -> int:
    """How many of the owner's purchase-order lines and requirements reference this item."""
    pos = conn.execute(
        "SELECT COUNT(*) FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id "
        "WHERE poi.item_code = ? COLLATE NOCASE AND po.created_by IS ?",
        (item["item_code"], item["created_by"]),
    ).fetchone()[0]
    reqs = conn.execute(
        "SELECT COUNT(*) FROM requirements WHERE item_code = ? COLLATE NOCASE AND created_by IS ?",
        (item["item_code"], item["created_by"]),
    ).fetchone()[0]
    return pos + reqs


def can_manage(user: dict | None, item: dict) -> bool:
<<<<<<< HEAD
    """Creators may edit/delete their own items. ERP-synced items have no creator."""
    if user is None or user["role"] == "admin":
=======
    """Owners may edit/delete their own items; admins may manage any."""
    if user is None:
>>>>>>> main
        return False
    return item.get("created_by") is not None and item["created_by"] == user["id"]


def list_items(
    conn: sqlite3.Connection,
    q: str | None = None,
    warehouse: str | None = None,
    user: dict | None = None,
) -> list[dict]:
    if user is not None and user["role"] == "admin":
        raise Forbidden("Administrators cannot access inventory")
    sql, args = "SELECT * FROM inventory WHERE 1=1", []
    owner = owner_of(user)
    if owner is not None:
        sql += " AND created_by = ?"
        args.append(owner)
    if q:
        sql += " AND (item_code LIKE ? OR description LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if warehouse:
        sql += " AND warehouse = ?"
        args.append(warehouse)
    items = [dict(r) for r in conn.execute(sql + " ORDER BY item_code", args).fetchall()]
    if user is not None:
        for it in items:
            it["can_edit"] = it["can_delete"] = can_manage(user, it)
            it["in_use"] = usage_count(conn, it)
    return items


def get_item(conn: sqlite3.Connection, item_code: str, user: dict | None = None) -> dict:
<<<<<<< HEAD
    if user is not None and user["role"] == "admin":
        raise Forbidden("Administrators cannot access inventory")
    row = conn.execute(
        "SELECT * FROM inventory WHERE item_code = ? COLLATE NOCASE", (item_code,)
    ).fetchone()
=======
    sql, args = "SELECT * FROM inventory WHERE item_code = ? COLLATE NOCASE", [item_code]
    owner = owner_of(user)
    if owner is not None:
        sql += " AND created_by = ?"
        args.append(owner)
    row = conn.execute(sql + " ORDER BY id", args).fetchone()
>>>>>>> main
    if row is None:
        raise NotFound(f"Item {item_code} not found")
    return dict(row)


def receive_stock(conn: sqlite3.Connection, owner_id: int, item_code: str, quantity: int) -> None:
    """Add received goods to the owner's stock (creates the item if it is new)."""
    cur = conn.execute(
        "UPDATE inventory SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE item_code = ? AND created_by = ?",
        (quantity, now(), item_code, owner_id),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, created_by, updated_at) VALUES (?,?,?,?,?,?)",
            (item_code, item_code, quantity, "MAIN", owner_id, now()),
        )


def create_item(conn: sqlite3.Connection, user: dict, data: dict) -> dict:
    if user["role"] == "admin":
        raise Forbidden("Administrators cannot access inventory")
    code = data["item_code"].strip().upper()
    if conn.execute(
        "SELECT 1 FROM inventory WHERE item_code = ? AND created_by = ?", (code, user["id"])
    ).fetchone():
        raise DomainError(f"Item {code} already exists", 409)
    cur = conn.execute(
        "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, source, created_by, updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            code,
            data["description"].strip(),
            data["stock_quantity"],
            data.get("warehouse") or "MAIN",
            "manual",
            user["id"],
            now(),
        ),
    )
    audit(conn, user["id"], "create", "inventory", code, f"stock={data['stock_quantity']}")
    return _by_id(conn, cur.lastrowid)


def _by_id(conn: sqlite3.Connection, item_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone())


def update_item(conn: sqlite3.Connection, user: dict, item_code: str, changes: dict) -> dict:
    current = get_item(conn, item_code, user)
    if not can_manage(user, current):
        raise Forbidden("You can only edit items you created")
    merged = {
        k: (changes[k] if changes.get(k) is not None else current[k])
        for k in ("description", "stock_quantity", "warehouse")
    }
    conn.execute(
        "UPDATE inventory SET description=?, stock_quantity=?, warehouse=?, updated_at=? WHERE id=?",
        (
            merged["description"],
            merged["stock_quantity"],
            merged["warehouse"],
            now(),
            current["id"],
        ),
    )
    detail = (
        f"stock {current['stock_quantity']} -> {merged['stock_quantity']}"
        if merged["stock_quantity"] != current["stock_quantity"]
        else "details"
    )
    audit(conn, user["id"], "update", "inventory", current["item_code"], detail)
    return _by_id(conn, current["id"])


def delete_item(conn: sqlite3.Connection, user: dict, item_code: str) -> None:
    item = get_item(conn, item_code, user)
    if not can_manage(user, item):
        raise Forbidden("You can only delete items you created")
    used = usage_count(conn, item)
    if used:
        raise DomainError(
            f"{item['item_code']} is used by {used} purchase order line(s) or requirement(s) and cannot be deleted",
            409,
        )
    conn.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
    audit(conn, user["id"], "delete", "inventory", item["item_code"], item["description"])
