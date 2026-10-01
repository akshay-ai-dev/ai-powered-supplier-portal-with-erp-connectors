import sqlite3

from ..db import now
from .errors import Forbidden, NotFound


def list_suppliers(conn: sqlite3.Connection, q: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM suppliers WHERE 1=1", []
    if q:
        sql += " AND (supplier_name LIKE ? OR email LIKE ? OR address LIKE ?)"
        args += [f"%{q}%"] * 3
    return [dict(r) for r in conn.execute(sql + " ORDER BY supplier_name", args).fetchall()]


def get_supplier(conn: sqlite3.Connection, supplier_id: int) -> dict:
    row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if row is None:
        raise NotFound("Supplier not found")
    return dict(row)


def create_supplier(conn: sqlite3.Connection, supplier_name: str, email: str, phone: str = "", address: str = "") -> dict:
    cur = conn.execute(
        "INSERT INTO suppliers (supplier_name, email, phone, address, created_at) VALUES (?,?,?,?,?)",
        (supplier_name, email, phone, address, now()),
    )
    return get_supplier(conn, cur.lastrowid)


def update_supplier(conn: sqlite3.Connection, user: dict, supplier_id: int, changes: dict) -> dict:
    """Suppliers may only edit their own profile; buyers may edit any."""
    if user["role"] == "supplier" and user.get("supplier_id") != supplier_id:
        raise Forbidden("You can only edit your own supplier profile")
    current = get_supplier(conn, supplier_id)
    merged = {k: (changes[k] if changes.get(k) is not None else current[k]) for k in ("supplier_name", "email", "phone", "address")}
    conn.execute(
        "UPDATE suppliers SET supplier_name=?, email=?, phone=?, address=? WHERE id=?",
        (merged["supplier_name"], merged["email"], merged["phone"], merged["address"], supplier_id),
    )
    return get_supplier(conn, supplier_id)
