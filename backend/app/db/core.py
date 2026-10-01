import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from ..config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT DEFAULT '',
    address TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'sap',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('buyer','supplier','admin','inspector')),
    supplier_id INTEGER REFERENCES suppliers(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    warehouse TEXT NOT NULL DEFAULT 'MAIN',
    source TEXT NOT NULL DEFAULT 'sap',
    created_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT NOT NULL UNIQUE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Pending','Approved','Closed')),
    delivery_status TEXT NOT NULL DEFAULT 'Not Shipped',
    total_amount REAL NOT NULL DEFAULT 0,
    erp_reference TEXT,
    erp TEXT NOT NULL DEFAULT 'sap',
    invoice_hold INTEGER NOT NULL DEFAULT 0,
    invoice_hold_reason TEXT NOT NULL DEFAULT '',
    created_via TEXT NOT NULL DEFAULT 'web',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    req_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    item_code TEXT,
    quantity INTEGER NOT NULL,
    target_price REAL,
    needed_by TEXT,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Awarded','Cancelled')),
    po_id INTEGER REFERENCES purchase_orders(id),
    created_via TEXT NOT NULL DEFAULT 'web',
    erp TEXT NOT NULL DEFAULT 'sap',
    open_to_all INTEGER NOT NULL DEFAULT 0,
    quote_deadline TEXT,
    deadline_reminded INTEGER NOT NULL DEFAULT 0,
    deadline_closed_notified INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requirement_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    declined INTEGER NOT NULL DEFAULT 0,
    decline_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (requirement_id, supplier_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    sender_id INTEGER REFERENCES users(id),
    sender_role TEXT NOT NULL CHECK (sender_role IN ('buyer','supplier')),
    body TEXT NOT NULL,
    read_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages (requirement_id, supplier_id);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL,
    stored_name TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    unit_price REAL NOT NULL,
    lead_time_days INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Submitted' CHECK (status IN ('Submitted','Accepted','Rejected','Withdrawn')),
    created_at TEXT NOT NULL,
    UNIQUE (requirement_id, supplier_id)
);
CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_no TEXT NOT NULL UNIQUE,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    carrier TEXT NOT NULL DEFAULT '',
    tracking_no TEXT NOT NULL DEFAULT '',
    expected_arrival TEXT,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Shipped' CHECK (status IN ('Shipped','Arrived','Approved','Rejected')),
    erp_inbound_ref TEXT,
    erp_movement_ref TEXT,
    arrived_at TEXT,
    arrived_by INTEGER REFERENCES users(id),
    inspected_at TEXT,
    inspected_by INTEGER REFERENCES users(id),
    inspection_notes TEXT NOT NULL DEFAULT '',
    rejection_reason TEXT NOT NULL DEFAULT '',
    quality_checks TEXT NOT NULL DEFAULT '{}',
    improvement_request TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shipment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    item_code TEXT NOT NULL,
    quantity_shipped INTEGER NOT NULL,
    quantity_received INTEGER
);
CREATE TABLE IF NOT EXISTS shipment_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('packing_list','photo')),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL,
    stored_name TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'read' CHECK (scope IN ('read','write')),
    expires_at TEXT,
    last_used_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    supplier_id INTEGER REFERENCES suppliers(id),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    detail TEXT DEFAULT '',
    channel TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = settings.database_path
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


MIGRATIONS = [  # (table, column, DDL) applied to databases created before the column existed
    ("users", "active", "INTEGER NOT NULL DEFAULT 1"),
    ("inventory", "source", "TEXT NOT NULL DEFAULT 'sap'"),
    ("suppliers", "source", "TEXT NOT NULL DEFAULT 'sap'"),
    ("inventory", "created_by", "INTEGER REFERENCES users(id)"),
    ("audit_logs", "channel", "TEXT NOT NULL DEFAULT 'web'"),
    ("purchase_orders", "created_via", "TEXT NOT NULL DEFAULT 'web'"),
    ("requirements", "created_via", "TEXT NOT NULL DEFAULT 'web'"),
    ("requirements", "erp", "TEXT NOT NULL DEFAULT 'sap'"),
    ("purchase_orders", "erp", "TEXT NOT NULL DEFAULT 'sap'"),
    ("requirements", "open_to_all", "INTEGER NOT NULL DEFAULT 0"),
    ("purchase_orders", "invoice_hold", "INTEGER NOT NULL DEFAULT 0"),
    ("purchase_orders", "invoice_hold_reason", "TEXT NOT NULL DEFAULT ''"),
    ("shipments", "quality_checks", "TEXT NOT NULL DEFAULT '{}'"),
    ("shipments", "improvement_request", "TEXT NOT NULL DEFAULT ''"),
    ("requirements", "quote_deadline", "TEXT"),
    ("requirements", "deadline_reminded", "INTEGER NOT NULL DEFAULT 0"),
    ("requirements", "deadline_closed_notified", "INTEGER NOT NULL DEFAULT 0"),
    ("requirement_invites", "declined", "INTEGER NOT NULL DEFAULT 0"),
    ("requirement_invites", "decline_reason", "TEXT NOT NULL DEFAULT ''"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_users_role(conn: sqlite3.Connection) -> None:
    """SQLite cannot alter a CHECK constraint, so databases created before the 'inspector' role get the table rebuilt."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    if not row or "'inspector'" in row["sql"]:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('buyer','supplier','admin','inspector')),
            supplier_id INTEGER REFERENCES suppliers(id),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        INSERT INTO users_new (id, name, email, password_hash, role, supplier_id, active, created_at)
            SELECT id, name, email, password_hash, role, supplier_id, active, created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        COMMIT;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _migrate_users_role(conn)
        # Requirements created before invitations existed stay visible to every supplier.
        conn.execute(
            "INSERT OR IGNORE INTO requirement_invites (requirement_id, supplier_id, created_at) "
            "SELECT r.id, s.id, r.created_at FROM requirements r CROSS JOIN suppliers s "
            "WHERE NOT EXISTS (SELECT 1 FROM requirement_invites i WHERE i.requirement_id = r.id)"
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_dep():
    """FastAPI dependency yielding a connection per request."""
    with get_conn() as conn:
        yield conn
