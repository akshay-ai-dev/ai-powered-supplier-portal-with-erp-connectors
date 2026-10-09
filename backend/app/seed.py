"""Seeds the DB from the configured ERP connector (proving the adapter path) plus demo users/POs.

Run standalone (`python -m app.seed`) by the database container to initialise the volume.
"""

import sqlite3
from datetime import date, timedelta

from .config import settings
from .connectors import get_connector
from .db import connect, init_db, now
from .security import hash_password
from .services import purchase_orders as po_svc
from .services import requirements as req_svc
from .services.notifications import audit

DEMO_PASSWORD = "Password123!"
SERVICE_USER_EMAIL = "mcp-service@erp.local"


def _ensure_user(conn: sqlite3.Connection, name, email, role, supplier_id=None) -> dict:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, supplier_id, created_at) VALUES (?,?,?,?,?,?)",
        (name, email, hash_password(DEMO_PASSWORD), role, supplier_id, now()),
    )
    return dict(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


def _supplier_id(conn: sqlite3.Connection, name_prefix: str) -> int:
    return conn.execute(
        "SELECT id FROM suppliers WHERE supplier_name LIKE ?", (f"{name_prefix}%",)
    ).fetchone()["id"]


def _seed_requests(conn: sqlite3.Connection, buyer: dict) -> None:
    """Demo requests for the AI Assistant: one with three quotes to compare and award (REQ2001 on a fresh
    database) and one still waiting for quotes. Skipped per title, so existing databases get no duplicates."""

    def exists(title: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM requirements WHERE title = ?", (title,)).fetchone())

    if not exists("Hydraulic pump assembly"):
        req = req_svc.create_requirement(
            conn,
            buyer,
            {
                "title": "Hydraulic pump assembly",
                "item_code": "ITEM003",
                "quantity": 20,
                "needed_by": (date.today() + timedelta(days=10)).isoformat(),
                "erp": "sap",
                "open_to_all": True,
            },
        )
        # Inserted directly: only ABC has a supplier login, and the quote service needs one.
        # Expected ranking: Globex (on time, cheapest), Northwind (on time), ABC (cheapest but late).
        for prefix, price, lead_days in (
            ("Globex", 12.0, 3),
            ("ABC", 11.5, 20),
            ("Northwind", 13.0, 2),
        ):
            sid = _supplier_id(conn, prefix)
            conn.execute(
                "INSERT INTO quotes (requirement_id, supplier_id, unit_price, lead_time_days, message, created_at) VALUES (?,?,?,?,?,?)",
                (req["id"], sid, price, lead_days, "", now()),
            )
            audit(conn, buyer["id"], "quote", "requirement", req["req_number"], f"supplier={sid}")

    if not exists("Gearbox housing"):
        req_svc.create_requirement(
            conn,
            buyer,
            {
                "title": "Gearbox housing",
                "item_code": "ITEM005",
                "quantity": 5,
                "erp": "infor",
                "open_to_all": True,
            },
        )


def seed(conn: sqlite3.Connection) -> None:
    erp = get_connector()
    if conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
        for it in erp.list_items():
            conn.execute(
                "INSERT INTO inventory (item_code, description, stock_quantity, warehouse, updated_at) VALUES (?,?,?,?,?)",
                (it["item_code"], it["description"], it["stock_quantity"], it["warehouse"], now()),
            )
    if conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
        for s in erp.list_suppliers():
            conn.execute(
                "INSERT INTO suppliers (supplier_name, email, phone, address, created_at) VALUES (?,?,?,?,?)",
                (s["supplier_name"], s["email"], s["phone"], s["address"], now()),
            )

    _ensure_user(conn, "MCP Service", SERVICE_USER_EMAIL, "buyer")
    if settings.admin_email and settings.admin_password:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (settings.admin_email.lower(),)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                (
                    "Administrator",
                    settings.admin_email.lower(),
                    hash_password(settings.admin_password),
                    "admin",
                    now(),
                ),
            )
    if not settings.seed_demo_data:
        return
    _ensure_user(conn, "Demo Admin", "admin@demo.com", "admin")
    _ensure_user(conn, "Warehouse Inspector", "inspector@demo.com", "inspector")

    buyer = _ensure_user(conn, "Vikas Buyer", "buyer@demo.com", "buyer")
    # Inventory is per owner: items loaded from the ERP (no creator) belong to the demo buyer.
    conn.execute(
        "UPDATE OR IGNORE inventory SET created_by = ? WHERE created_by IS NULL", (buyer["id"],)
    )
    abc = conn.execute("SELECT id FROM suppliers WHERE supplier_name LIKE 'ABC%'").fetchone()["id"]
    _ensure_user(conn, "ABC Industrial Supplies", "supplier@demo.com", "supplier", abc)
    conn.execute(
        "UPDATE users SET supplier_id = ? WHERE email = 'supplier@demo.com' AND supplier_id IS NULL",
        (abc,),
    )

    if conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0:
        globex = conn.execute(
            "SELECT id FROM suppliers WHERE supplier_name LIKE 'Globex%'"
        ).fetchone()["id"]
        # emails are disabled during seeding so a missing Mailpit never blocks startup
        prev, settings.email_enabled = settings.email_enabled, False
        try:
            po_svc.create_po(
                conn,
                buyer,
                abc,
                [
                    {"item_code": "ITEM001", "quantity": 500, "unit_price": 1},
                    {"item_code": "ITEM004", "quantity": 200, "unit_price": 1},
                ],
                submit=True,
            )
            p2 = po_svc.create_po(
                conn,
                buyer,
                globex,
                [{"item_code": "ITEM003", "quantity": 5, "unit_price": 640.0}],
                submit=True,
            )
            po_svc.update_po(conn, buyer, p2["id"], {"status": "Approved"})
            po_svc.create_po(
                conn,
                buyer,
                abc,
                [{"item_code": "ITEM002", "quantity": 40, "unit_price": 18.5}],
                submit=False,
            )
        finally:
            settings.email_enabled = prev

    prev, settings.email_enabled = settings.email_enabled, False
    try:
        _seed_requests(conn, buyer)
    finally:
        settings.email_enabled = prev


def main() -> None:
    init_db()
    conn = connect()
    try:
        seed(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"Database ready at {settings.database_path}")


if __name__ == "__main__":
    main()
