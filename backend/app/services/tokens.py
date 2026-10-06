"""Per-user API tokens for AI agents (MCP and the /api/mcp/* endpoints only).

A token acts as its owner: the agent sees exactly what that user sees and every action is audited with the token's name.
Tokens are random 256-bit strings, so a plain SHA-256 is enough for storage; the raw value is shown once at creation.
They are refused by the normal REST API, so a leaked token can never approve, award, close or change users.
"""

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from ..db import now
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit

PREFIX = "erp_"
SCOPES = ("read", "write")  # read = look things up; write = read + create Drafts
MAX_ACTIVE_PER_USER = 10
AGENT_ROLES = ("buyer", "admin")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _status(row: sqlite3.Row) -> str:
    if row["revoked_at"]:
        return "revoked"
    if row["expires_at"] and _parse(row["expires_at"]) <= datetime.now(UTC):
        return "expired"
    return "active"


def _public(row: sqlite3.Row) -> dict:
    d = {
        k: row[k]
        for k in (
            "id",
            "name",
            "prefix",
            "scope",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
        )
    }
    d["status"] = _status(row)
    if "owner_name" in row.keys():  # noqa: SIM118 - sqlite3.Row: `in` would test the values, not the columns
        d["owner_name"], d["owner_email"] = row["owner_name"], row["owner_email"]
    return d


def create_token(
    conn: sqlite3.Connection, user: dict, name: str, scope: str, expires_in_days: int | None
) -> dict:
    if user["role"] not in AGENT_ROLES:
        raise Forbidden("Only buyers and admins can create API tokens")
    name = (name or "").strip()
    if not name:
        raise DomainError("Give the token a name, for example the device or agent that will use it")
    if scope not in SCOPES:
        raise DomainError(f"scope must be one of {SCOPES}")
    active = sum(
        1
        for r in conn.execute("SELECT * FROM api_tokens WHERE user_id = ?", (user["id"],))
        if _status(r) == "active"
    )
    if active >= MAX_ACTIVE_PER_USER:
        raise DomainError(
            f"You already have {MAX_ACTIVE_PER_USER} active tokens. Revoke one first."
        )
    raw = PREFIX + secrets.token_urlsafe(32)
    expires_at = (
        (datetime.now(UTC) + timedelta(days=expires_in_days)).isoformat(timespec="seconds")
        if expires_in_days
        else None
    )
    cur = conn.execute(
        "INSERT INTO api_tokens (user_id, name, token_hash, prefix, scope, expires_at, created_at) VALUES (?,?,?,?,?,?,?)",
        (user["id"], name[:80], hash_token(raw), raw[: len(PREFIX) + 6], scope, expires_at, now()),
    )
    audit(conn, user["id"], "create", "api_token", cur.lastrowid, f"{name[:80]} ({scope})")
    row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {**_public(row), "token": raw}  # the only time the raw token is ever returned


def list_tokens(conn: sqlite3.Connection, user: dict, everyone: bool = False) -> list[dict]:
    if everyone:
        rows = conn.execute(
            "SELECT t.*, u.name AS owner_name, u.email AS owner_email FROM api_tokens t JOIN users u ON u.id = t.user_id ORDER BY t.id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM api_tokens WHERE user_id = ? ORDER BY id DESC", (user["id"],)
        ).fetchall()
    return [_public(r) for r in rows]


def revoke(conn: sqlite3.Connection, user: dict, token_id: int) -> dict:
    row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
    if row is None or (row["user_id"] != user["id"] and user["role"] != "admin"):
        raise NotFound("Token not found")
    if not row["revoked_at"]:
        conn.execute("UPDATE api_tokens SET revoked_at = ? WHERE id = ?", (now(), token_id))
        audit(conn, user["id"], "revoke", "api_token", token_id, row["name"])
    return _public(conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone())


def authenticate(conn: sqlite3.Connection, raw: str) -> tuple[dict, dict] | None:
    """Returns (user, token) for a valid token, else None. Also refuses inactive users and non-agent roles."""
    if not raw.startswith(PREFIX):
        return None
    row = conn.execute(
        "SELECT * FROM api_tokens WHERE token_hash = ?", (hash_token(raw),)
    ).fetchone()
    if row is None or _status(row) != "active":
        return None
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if user is None or not user["active"] or user["role"] not in AGENT_ROLES:
        return None
    # record usage at most once a minute so busy agents don't write on every call
    if (
        not row["last_used_at"]
        or (datetime.now(UTC) - _parse(row["last_used_at"])).total_seconds() > 60
    ):
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now(), row["id"]))
    return dict(user), dict(row)
