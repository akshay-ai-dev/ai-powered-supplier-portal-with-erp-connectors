"""Per-user inbox backed by Mailpit.

Mailpit has no notion of users, so every read goes through here: we only return messages whose
To/Cc/Bcc list contains one of the caller's own addresses, and we re-check that on every fetch.
"""

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from ..config import settings
from .errors import DomainError, NotFound


def my_addresses(conn: sqlite3.Connection, user: dict) -> set[str]:
    """The user's login email, plus their supplier company email (suppliers receive PO mail there)."""
    addrs = {user["email"].lower()}
    if user.get("supplier_id"):
        row = conn.execute(
            "SELECT email FROM suppliers WHERE id = ?", (user["supplier_id"],)
        ).fetchone()
        if row:
            addrs.add(row["email"].lower())
    return addrs


def _mailpit(path: str, params: dict | None = None) -> dict:
    url = f"{settings.mailpit_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFound("Email not found") from exc
        raise DomainError("Mail service error", 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DomainError("Mail service is unavailable", 503) from exc


def _recipients(msg: dict) -> set[str]:
    return {a["Address"].lower() for k in ("To", "Cc", "Bcc") for a in (msg.get(k) or [])}


def _summary(msg: dict) -> dict:
    return {
        "id": msg["ID"],
        "subject": msg.get("Subject", ""),
        "from": (msg.get("From") or {}).get("Address", ""),
        "to": [a["Address"] for a in (msg.get("To") or [])],
        "snippet": msg.get("Snippet", ""),
        "created": msg.get("Created"),
        "read": msg.get("Read", False),
    }


def purge_all() -> None:
    """Delete every message in Mailpit (used by the admin data reset). Best effort."""
    try:
        req = urllib.request.Request(f"{settings.mailpit_url}/api/v1/messages", method="DELETE")
        urllib.request.urlopen(req, timeout=5).close()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def list_inbox(conn: sqlite3.Connection, user: dict, limit: int = 50) -> list[dict]:
    mine = my_addresses(conn, user)
    found: dict[str, dict] = {}
    for addr in sorted(mine):  # Mailpit search has no OR, so search per address and merge
        data = _mailpit("/api/v1/search", {"query": f'to:"{addr}"', "limit": limit})
        for m in data.get("messages", []):
            if _recipients(m) & mine:  # never trust the search alone
                found[m["ID"]] = m
    newest_first = sorted(found.values(), key=lambda m: m.get("Created") or "", reverse=True)
    return [_summary(m) for m in newest_first[:limit]]


def unread_count(conn: sqlite3.Connection, user: dict) -> int:
    """How many of the user's emails are still unread. Mailpit marks an email read once it is opened."""
    return sum(1 for m in list_inbox(conn, user, limit=200) if not m["read"])


def get_email(conn: sqlite3.Connection, user: dict, message_id: str) -> dict:
    msg = _mailpit(f"/api/v1/message/{urllib.parse.quote(message_id, safe='')}")
    if not (_recipients(msg) & my_addresses(conn, user)):
        raise NotFound(
            "Email not found"
        )  # same answer as a missing message: don't reveal it exists
    return {
        "id": msg["ID"],
        "subject": msg.get("Subject", ""),
        "from": (msg.get("From") or {}).get("Address", ""),
        "to": [a["Address"] for a in (msg.get("To") or [])],
        "date": msg.get("Date"),
        "text": msg.get("Text", ""),
    }
