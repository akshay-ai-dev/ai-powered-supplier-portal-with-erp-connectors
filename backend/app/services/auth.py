import sqlite3

from ..db import now
from ..security import create_access_token, hash_password, verify_password
from . import suppliers as suppliers_svc
from .errors import DomainError
from .notifications import audit, send_email


def _public(user: dict) -> dict:
    return {
        k: user.get(k)
        for k in ("id", "name", "email", "role", "supplier_id", "owner_id", "owner_name")
    }


def with_owner(conn: sqlite3.Connection, user: dict) -> dict:
    """The user, plus the name of the buyer whose inspector they are (if any)."""
    owner = (
        conn.execute("SELECT name FROM users WHERE id = ?", (user.get("owner_id"),)).fetchone()
        if user.get("owner_id")
        else None
    )
    return {**user, "owner_name": owner["name"] if owner else None}


def register(conn: sqlite3.Connection, name: str, email: str, password: str, role: str) -> dict:
    email = email.lower()
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise DomainError("Email already registered", 409)
    supplier_id = None
    if role == "supplier":
        supplier_id = suppliers_svc.create_supplier(conn, name, email)["id"]
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, supplier_id, created_at) VALUES (?,?,?,?,?,?)",
        (name, email, hash_password(password), role, supplier_id, now()),
    )
    user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())
    audit(conn, user["id"], "register", "user", user["id"], role)
    send_email(email, "Welcome to ERP Copilot", f"Hi {name}, your {role} account is ready.")
    return _token_response(user)


def login(conn: sqlite3.Connection, email: str, password: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise DomainError("Invalid email or password", 401)
    if not row["active"]:
        raise DomainError("Account is disabled. Contact an administrator.", 403)
    user = dict(row)
    audit(conn, user["id"], "login", "user", user["id"])
    return _token_response(with_owner(conn, user))


def _token_response(user: dict) -> dict:
    return {
        "access_token": create_access_token(user["id"], user["role"]),
        "token_type": "bearer",
        "user": _public(user),
    }
