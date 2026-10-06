"""A buyer's own inspectors.

A buyer can create inspector logins for their warehouse. Such an inspector belongs to that buyer (`users.owner_id`) and sees
and inspects only that buyer's requirements, orders and shipments; inspectors created by an admin stay company-wide.
Buyers manage only their own inspectors: create, rename, reset the password, disable or enable. Nothing is ever deleted,
so the history of what an inspector did stays intact.
"""

import sqlite3

from ..db import now
from ..security import hash_password
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, send_email

MAX_INSPECTORS = 25
COLS = "id, name, email, role, active, created_at"


def _require_buyer(user: dict) -> None:
    if user["role"] != "buyer":
        raise Forbidden("Only buyers manage their own inspectors")


def list_inspectors(conn: sqlite3.Connection, buyer: dict) -> list[dict]:
    _require_buyer(buyer)
    rows = conn.execute(
        f"SELECT {COLS} FROM users WHERE role = 'inspector' AND owner_id = ? ORDER BY id",
        (buyer["id"],),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = bool(d["active"])
        d["last_login"] = (
            conn.execute(
                "SELECT created_at FROM audit_logs WHERE entity = 'user' AND entity_id = ? AND action = 'login' ORDER BY id DESC LIMIT 1",
                (str(r["id"]),),
            ).fetchone()
            or {"created_at": None}
        )["created_at"]
        d["inspected"] = conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE inspected_by = ?", (r["id"],)
        ).fetchone()[0]
        out.append(d)
    return out


def _mine(conn: sqlite3.Connection, buyer: dict, user_id: int) -> sqlite3.Row:
    _require_buyer(buyer)
    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'inspector' AND owner_id = ?",
        (user_id, buyer["id"]),
    ).fetchone()
    if row is None:
        raise NotFound("Inspector not found")
    return row


def _public(conn: sqlite3.Connection, user_id: int) -> dict:
    d = dict(conn.execute(f"SELECT {COLS} FROM users WHERE id = ?", (user_id,)).fetchone())
    d["active"] = bool(d["active"])
    return d


def create_inspector(conn: sqlite3.Connection, buyer: dict, data: dict) -> dict:
    _require_buyer(buyer)
    email = data["email"].lower()
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise DomainError("That email address already has an account", 409)
    if (
        conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'inspector' AND owner_id = ? AND active = 1",
            (buyer["id"],),
        ).fetchone()[0]
        >= MAX_INSPECTORS
    ):
        raise DomainError(f"You can have at most {MAX_INSPECTORS} active inspectors")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, owner_id, created_at) VALUES (?,?,?,?,?,?)",
        (
            data["name"].strip(),
            email,
            hash_password(data["password"]),
            "inspector",
            buyer["id"],
            now(),
        ),
    )
    audit(conn, buyer["id"], "create", "user", cur.lastrowid, f"inspector for {buyer['name']}")
    send_email(
        email,
        f"You were added as an inspector for {buyer['name']} on SRS ERP",
        f"Hi {data['name'].strip()}, {buyer['name']} added you as an inspector. Sign in with this email address and the password they gave you. "
        "You will see the shipments for their purchase orders, scan and test the units, and record the result.",
    )
    return _public(conn, cur.lastrowid)


def update_inspector(conn: sqlite3.Connection, buyer: dict, user_id: int, changes: dict) -> dict:
    row = _mine(conn, buyer, user_id)
    if changes.get("name") and changes["name"].strip():
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (changes["name"].strip(), user_id))
    if changes.get("active") is not None:
        if (
            changes["active"]
            and not row["active"]
            and conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'inspector' AND owner_id = ? AND active = 1",
                (buyer["id"],),
            ).fetchone()[0]
            >= MAX_INSPECTORS
        ):
            raise DomainError(f"You can have at most {MAX_INSPECTORS} active inspectors")
        conn.execute(
            "UPDATE users SET active = ? WHERE id = ?", (1 if changes["active"] else 0, user_id)
        )
    if changes.get("password"):
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(changes["password"]), user_id),
        )
    fields = [k for k in changes if k != "password"] + (
        ["password"] if changes.get("password") else []
    )
    audit(conn, buyer["id"], "update", "user", user_id, ",".join(fields))
    return _public(conn, user_id)
