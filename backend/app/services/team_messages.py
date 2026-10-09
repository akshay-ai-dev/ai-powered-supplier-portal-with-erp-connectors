"""Private conversations between a buyer and their own inspectors."""

import sqlite3

from ..db import now
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, notify


def _require_role(user: dict) -> None:
    if user["role"] not in ("buyer", "inspector"):
        raise Forbidden("Only buyers and inspectors can access these conversations")


def _participants(conn: sqlite3.Connection, user: dict, inspector_id: int):
    _require_role(user)
    inspector = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'inspector' AND owner_id IS NOT NULL",
        (inspector_id,),
    ).fetchone()
    if (
        inspector is None
        or (user["role"] == "buyer" and inspector["owner_id"] != user["id"])
        or (user["role"] == "inspector" and inspector["id"] != user["id"])
    ):
        raise NotFound("Conversation not found")
    buyer = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'buyer'", (inspector["owner_id"],)
    ).fetchone()
    if buyer is None:
        raise NotFound("Conversation not found")
    return buyer, inspector


def list_contacts(conn: sqlite3.Connection, user: dict) -> list[dict]:
    _require_role(user)
    if user["role"] == "buyer":
        ids = conn.execute(
            "SELECT id FROM users WHERE role = 'inspector' AND owner_id = ? ORDER BY name, id",
            (user["id"],),
        ).fetchall()
    elif user.get("owner_id"):
        ids = [{"id": user["id"]}]
    else:
        return []
    contacts = []
    for row in ids:
        buyer, inspector = _participants(conn, user, row["id"])
        partner = inspector if user["role"] == "buyer" else buyer
        unread = conn.execute(
            "SELECT COUNT(*) FROM team_messages WHERE buyer_id = ? AND inspector_id = ? "
            "AND sender_id != ? AND read_at IS NULL",
            (buyer["id"], inspector["id"], user["id"]),
        ).fetchone()[0]
        contacts.append(
            {
                "inspector_id": inspector["id"],
                "name": partner["name"],
                "active": bool(partner["active"]),
                "unread": unread,
            }
        )
    return contacts


def list_messages(conn: sqlite3.Connection, user: dict, inspector_id: int) -> dict:
    buyer, inspector = _participants(conn, user, inspector_id)
    conn.execute(
        "UPDATE team_messages SET read_at = ? WHERE buyer_id = ? AND inspector_id = ? "
        "AND sender_id != ? AND read_at IS NULL",
        (now(), buyer["id"], inspector_id, user["id"]),
    )
    rows = conn.execute(
        "SELECT m.id, m.body, m.created_at, m.sender_id, u.name AS sender_name "
        "FROM team_messages m JOIN users u ON u.id = m.sender_id "
        "WHERE m.buyer_id = ? AND m.inspector_id = ? ORDER BY m.id",
        (buyer["id"], inspector_id),
    ).fetchall()
    return {
        "can_post": bool(buyer["active"] and inspector["active"]),
        "messages": [{**dict(r), "mine": r["sender_id"] == user["id"]} for r in rows],
    }


def post_message(conn: sqlite3.Connection, user: dict, inspector_id: int, body: str) -> dict:
    buyer, inspector = _participants(conn, user, inspector_id)
    if not buyer["active"] or not inspector["active"]:
        raise Forbidden("Messages cannot be sent while either account is disabled")
    body = body.strip()
    if not body or len(body) > 2000:
        raise DomainError("Enter a message between 1 and 2,000 characters")
    conn.execute(
        "INSERT INTO team_messages (buyer_id, inspector_id, sender_id, body, created_at) "
        "VALUES (?,?,?,?,?)",
        (buyer["id"], inspector_id, user["id"], body, now()),
    )
    partner = inspector if user["role"] == "buyer" else buyer
    notify(
        conn,
        title=f"New message from {user['name']}",
        message=body[:300],
        email_to=None,
        user_id=partner["id"],
        link=f"/team-chat?inspector={inspector_id}",
    )
    audit(conn, user["id"], "message", "team_chat", inspector_id)
    return list_messages(conn, user, inspector_id)
