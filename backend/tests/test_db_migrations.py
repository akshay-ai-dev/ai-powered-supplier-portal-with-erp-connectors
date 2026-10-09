# isort: off
from tests.test_api import login  # noqa: F401  (sets the test environment before the app is imported)
import sqlite3

import pytest

from app.config import settings
from app.db import core
# isort: on

OLD_USERS = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ({roles})),
    supplier_id INTEGER REFERENCES suppliers(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""
OLD_REST = """
CREATE TABLE suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT NOT NULL, email TEXT NOT NULL,
    phone TEXT DEFAULT '', address TEXT DEFAULT '', source TEXT NOT NULL DEFAULT 'sap', created_at TEXT NOT NULL);
CREATE TABLE shipments (id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_no TEXT NOT NULL UNIQUE, po_id INTEGER NOT NULL,
    supplier_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Shipped', created_at TEXT NOT NULL);
CREATE TABLE shipment_items (id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
    item_code TEXT NOT NULL, quantity_shipped INTEGER NOT NULL, quantity_received INTEGER);
CREATE TABLE shipment_files (id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
    kind TEXT NOT NULL CHECK (kind IN ('packing_list','photo')), filename TEXT NOT NULL, size INTEGER NOT NULL,
    stored_name TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO suppliers (supplier_name, email, created_at) VALUES ('Old Supplier', 'old@x.com', '2026-01-01');
INSERT INTO users (name, email, password_hash, role, created_at) VALUES ('Old Buyer', 'old-buyer@x.com', 'x', 'buyer', '2026-01-01');
INSERT INTO shipments (shipment_no, po_id, supplier_id, created_at) VALUES ('SHP1', 1, 1, '2026-01-01');
INSERT INTO shipment_items (shipment_id, item_code, quantity_shipped, quantity_received) VALUES (1, 'ITEM001', 5, 4);
"""


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize(
    "roles", ["'buyer','supplier','admin'", "'buyer','supplier','admin','inspector'"]
)
def test_a_database_from_before_unit_inspection_is_upgraded_in_place(tmp_path, monkeypatch, roles):
    """Both the users-table rebuild (no inspector role yet) and the plain ADD COLUMN path keep the data and gain the new columns."""
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(OLD_USERS.format(roles=roles) + OLD_REST)
    old.commit()
    old.close()

    monkeypatch.setattr(settings, "database_path", path)
    core.init_db()
    core.init_db()  # running it again changes nothing

    conn = core.connect()
    try:
        assert {"owner_id"} <= columns(conn, "users")
        assert {
            "unit_level",
            "lot_report",
            "override_reason",
            "replaces_shipment_id",
            "packing_list_review",
        } <= columns(conn, "shipments")
        assert "quantity_accepted" in columns(conn, "shipment_items") and "unit_id" in columns(
            conn, "shipment_files"
        )
        assert {"shipment_units", "inspection_fields"} <= {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        old_user = conn.execute("SELECT * FROM users WHERE email = 'old-buyer@x.com'").fetchone()
        assert (
            old_user["role"] == "buyer" and old_user["owner_id"] is None and old_user["active"] == 1
        )
        item = conn.execute("SELECT * FROM shipment_items").fetchone()
        assert item["quantity_received"] == 4 and item["quantity_accepted"] is None
        assert (
            conn.execute("SELECT unit_level, lot_report FROM shipments").fetchone()["lot_report"]
            == "{}"
        )

        # a buyer-owned inspector can be stored (the role check allows it and owner_id survived the rebuild)
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, owner_id, created_at) VALUES ('Joe', 'joe@x.com', 'x', 'inspector', ?, '2026-01-02')",
            (old_user["id"],),
        )
        conn.execute(
            "INSERT INTO shipment_units (shipment_id, item_code, seq, code, created_at) VALUES (1, 'ITEM001', 1, 'SHP1-ITEM001-0001', '2026-01-02')"
        )
        conn.commit()
        assert (
            conn.execute("SELECT owner_id FROM users WHERE email = 'joe@x.com'").fetchone()[
                "owner_id"
            ]
            == old_user["id"]
        )
    finally:
        conn.close()
