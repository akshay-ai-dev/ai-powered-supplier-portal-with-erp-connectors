import sqlite3

from ..connectors import all_connectors
from ..db import now
from ..security import hash_password
from . import attachments as attachments_svc
from . import mailbox
from .errors import DomainError, NotFound
from .notifications import audit

PUBLIC_COLS = "id, name, email, role, supplier_id, active, created_at"
SERVICE_EMAIL = "mcp-service@erp.local"


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {PUBLIC_COLS} FROM users WHERE email != ? ORDER BY id", (SERVICE_EMAIL,)).fetchall()
    return [dict(r) for r in rows]


def create_user(conn: sqlite3.Connection, admin: dict, data: dict) -> dict:
    email = data["email"].lower()
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise DomainError("Email already registered", 409)
    supplier_id = None
    if data["role"] == "supplier":
        cur = conn.execute(
            "INSERT INTO suppliers (supplier_name, email, created_at) VALUES (?,?,?)", (data["name"], email, now())
        )
        supplier_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, supplier_id, created_at) VALUES (?,?,?,?,?,?)",
        (data["name"], email, hash_password(data["password"]), data["role"], supplier_id, now()),
    )
    audit(conn, admin["id"], "create", "user", cur.lastrowid, data["role"])
    return dict(conn.execute(f"SELECT {PUBLIC_COLS} FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_user(conn: sqlite3.Connection, admin: dict, user_id: int, changes: dict) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFound("User not found")
    if user_id == admin["id"] and changes.get("active") is False:
        raise DomainError("You cannot disable your own account")
    if changes.get("name"):
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (changes["name"], user_id))
    if changes.get("active") is not None:
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (1 if changes["active"] else 0, user_id))
    if changes.get("password"):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(changes["password"]), user_id))
    fields = [k for k in changes if k != "password"] + (["password"] if changes.get("password") else [])
    audit(conn, admin["id"], "update", "user", user_id, ",".join(fields))
    return dict(conn.execute(f"SELECT {PUBLIC_COLS} FROM users WHERE id = ?", (user_id,)).fetchone())


def stats(conn: sqlite3.Connection) -> dict:
    def one(sql):
        return conn.execute(sql).fetchone()[0]

    return {
        "users_by_role": {
            r["role"]: r["n"]
            for r in conn.execute("SELECT role, COUNT(*) n FROM users WHERE email != ? GROUP BY role", (SERVICE_EMAIL,))
        },
        "suppliers": one("SELECT COUNT(*) FROM suppliers"),
        "inventory_items": one("SELECT COUNT(*) FROM inventory"),
        "requirements_by_status": {
            r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM requirements GROUP BY status")
        },
        "orders_by_status": {
            r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM purchase_orders GROUP BY status")
        },
        "recent_audit": [
            dict(r)
            for r in conn.execute(
                "SELECT a.action, a.entity, a.entity_id, a.detail, a.created_at, a.channel, u.name AS user_name FROM audit_logs a "
                "LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 10"
            )
        ],
    }


def sync_erp(conn: sqlite3.Connection, user: dict, erp: str) -> dict:
    """Pull items and suppliers from an ERP connector. The ERP is the source of truth for
    item descriptions/stock/warehouse; existing supplier profiles are left as edited."""
    connector = all_connectors().get(erp)
    if connector is None:
        raise NotFound(f"Unknown ERP '{erp}'")
    added = updated = suppliers_added = 0
    for it in connector.list_items():
        cur = conn.execute(
            "UPDATE inventory SET description=?, stock_quantity=?, warehouse=?, source=?, updated_at=? WHERE item_code=?",
            (it["description"], it["stock_quantity"], it["warehouse"], erp, now(), it["item_code"]),
        )
        if cur.rowcount:
            updated += 1
        else:
            conn.execute(
                "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, source, updated_at) VALUES (?,?,?,?,?,?)",
                (it["item_code"], it["description"], it["stock_quantity"], it["warehouse"], erp, now()),
            )
            added += 1
    for s in connector.list_suppliers():
        exists = conn.execute("SELECT 1 FROM suppliers WHERE supplier_name = ? COLLATE NOCASE", (s["supplier_name"],)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO suppliers (supplier_name, email, phone, address, source, created_at) VALUES (?,?,?,?,?,?)",
                (s["supplier_name"], s["email"], s["phone"], s["address"], erp, now()),
            )
            suppliers_added += 1
    audit(conn, user["id"], "sync", "erp", erp, f"items +{added}/~{updated}, suppliers +{suppliers_added}")
    return {"erp": erp, "items_added": added, "items_updated": updated, "suppliers_added": suppliers_added}


def reset_data(conn: sqlite3.Connection, admin: dict) -> None:
    """Wipe all business data and reseed. The acting admin is kept so their session stays valid."""
    from ..seed import seed  # local import: seed imports services

    for table in ("api_tokens", "shipment_files", "shipment_items", "shipments", "messages", "quotes", "attachments", "requirement_invites", "requirements", "purchase_order_items", "purchase_orders", "notifications", "audit_logs"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("UPDATE users SET supplier_id = NULL WHERE id = ?", (admin["id"],))
    conn.execute("DELETE FROM users WHERE id != ?", (admin["id"],))
    conn.execute("DELETE FROM inventory")
    conn.execute("DELETE FROM suppliers")
    conn.execute("DELETE FROM sqlite_sequence WHERE name NOT IN ('users')")
    for c in all_connectors().values():
        c.reset()
    mailbox.purge_all()
    attachments_svc.purge_all()
    seed(conn)
    audit(conn, admin["id"], "reset", "system", "all", "data reset and reseeded")
