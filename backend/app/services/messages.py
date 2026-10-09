"""Buyer <-> supplier conversation, one private thread per (requirement, supplier).

The thread starts while the requirement is open (clarifying questions), and carries on after award so the buyer
and the winning supplier can keep talking through PO approval and delivery. Other suppliers never see it.
A message can carry one file (drawing, photo, certificate); only the two sides of the thread can download it.
"""

import sqlite3
from pathlib import Path

from ..db import now
from . import attachments as attachments_svc
from . import requirements as req_svc
from . import suppliers as suppliers_svc
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, notify

MAX_LEN = 2000


def _role(user: dict) -> str:
    return "supplier" if user["role"] == "supplier" else "buyer"


def _resolve(
    conn: sqlite3.Connection, user: dict, req_id: int, supplier_id: int | None
) -> tuple[sqlite3.Row, int]:
    """Returns (requirement row, supplier id of the thread) after checking the user may see this thread."""
    if user["role"] not in ("buyer", "supplier"):
        raise Forbidden("Only buyers and suppliers can access private conversations")
    if _role(user) == "supplier":
        if not user.get("supplier_id"):
            raise Forbidden("No supplier profile")
        req = req_svc._get_visible(conn, user, req_id)  # 404 unless invited / quoted
        return req, user["supplier_id"]
    req = req_svc._get_owned(conn, user, req_id)
    if not supplier_id:
        raise DomainError("supplier_id is required")
    suppliers_svc.get_supplier(conn, supplier_id)
    return req, supplier_id


def _can_post(conn: sqlite3.Connection, req: sqlite3.Row, supplier_id: int) -> bool:
    if req["status"] == "Cancelled":
        return False
    if (
        req["status"] == "Awarded"
    ):  # after award, only the winning supplier keeps talking to the buyer
        return bool(
            conn.execute(
                "SELECT 1 FROM quotes WHERE requirement_id = ? AND supplier_id = ? AND status = 'Accepted'",
                (req["id"], supplier_id),
            ).fetchone()
        )
    return True


def list_messages(
    conn: sqlite3.Connection, user: dict, req_id: int, supplier_id: int | None = None
) -> dict:
    req, sid = _resolve(conn, user, req_id, supplier_id)
    me = _role(user)
    # opening the thread marks the other side's messages as read
    conn.execute(
        "UPDATE messages SET read_at = ? WHERE requirement_id = ? AND supplier_id = ? AND sender_role != ? AND read_at IS NULL",
        (now(), req_id, sid, me),
    )
    rows = conn.execute(
        "SELECT m.id, m.body, m.sender_role, m.created_at, u.name AS sender_name FROM messages m "
        "LEFT JOIN users u ON u.id = m.sender_id WHERE m.requirement_id = ? AND m.supplier_id = ? ORDER BY m.id",
        (req_id, sid),
    ).fetchall()
    files: dict[int, list[dict]] = {}
    for a in conn.execute(
        "SELECT a.id, a.message_id, a.filename, a.size FROM message_attachments a "
        "JOIN messages m ON m.id = a.message_id WHERE m.requirement_id = ? AND m.supplier_id = ? ORDER BY a.id",
        (req_id, sid),
    ):
        files.setdefault(a["message_id"], []).append(
            {"id": a["id"], "filename": a["filename"], "size": a["size"]}
        )
    return {
        "supplier_id": sid,
        "supplier_name": suppliers_svc.get_supplier(conn, sid)["supplier_name"],
        "can_post": _can_post(conn, req, sid),
        "messages": [
            {**dict(r), "mine": r["sender_role"] == me, "attachments": files.get(r["id"], [])}
            for r in rows
        ],
    }


def post_message(
    conn: sqlite3.Connection,
    user: dict,
    req_id: int,
    body: str,
    supplier_id: int | None = None,
    file: tuple[str, bytes, str | None] | None = None,
) -> dict:
    """Send a message. `file` is (filename, data, content type) for a message with an attachment; the text is then optional."""
    body = (body or "").strip()
    if not body and file is None:
        raise DomainError("Message is empty")
    if len(body) > MAX_LEN:
        raise DomainError(f"Message is longer than {MAX_LEN} characters")
    req, sid = _resolve(conn, user, req_id, supplier_id)
    if not _can_post(conn, req, sid):
        raise DomainError("This conversation is closed")
    stored = attachments_svc.store(file[0], file[1]) if file else None  # checks type and size first
    me = _role(user)
    cur = conn.execute(
        "INSERT INTO messages (requirement_id, supplier_id, sender_id, sender_role, body, created_at) VALUES (?,?,?,?,?,?)",
        (req_id, sid, user["id"], me, body, now()),
    )
    if stored:
        conn.execute(
            "INSERT INTO message_attachments (message_id, filename, content_type, size, stored_name, created_at) VALUES (?,?,?,?,?,?)",
            (
                cur.lastrowid,
                stored["filename"],
                file[2] or "application/octet-stream",
                stored["size"],
                stored["stored_name"],
                now(),
            ),
        )
    supplier = suppliers_svc.get_supplier(conn, sid)
    preview = body if len(body) <= 300 else body[:300] + "…"
    if stored:
        preview = (preview + "\n\n" if preview else "") + f"Attached file: {stored['filename']}"
    if me == "supplier":
        buyer = conn.execute(
            "SELECT id, email FROM users WHERE id = ?", (req["created_by"],)
        ).fetchone()
        notify(
            conn,
            title=f"{supplier['supplier_name']} sent a message on {req['req_number']}",
            message=f"{preview}\n\nReply in the app under Requirements > {req['req_number']}.",
            email_to=buyer["email"] if buyer else None,
            user_id=buyer["id"] if buyer else None,
            link=f"/requirements/{req_id}",
        )
    else:
        notify(
            conn,
            title=f"New message from the buyer on {req['req_number']}",
            message=f"{preview}\n\nReply in the app under Requirements > {req['req_number']}.",
            email_to=supplier["email"],
            supplier_id=sid,
            link=f"/requirements/{req_id}",
        )
    audit(
        conn,
        user["id"],
        "message",
        "requirement",
        req["req_number"],
        f"{me} -> supplier {sid}" + (f" with file {stored['filename']}" if stored else ""),
    )
    return list_messages(conn, user, req_id, sid)


def open_attachment(conn: sqlite3.Connection, user: dict, att_id: int) -> tuple[sqlite3.Row, Path]:
    """A message file and its path on disk, for the buyer or the supplier of that thread only (404 for anyone else)."""
    row = conn.execute(
        "SELECT a.*, m.requirement_id, m.supplier_id FROM message_attachments a "
        "JOIN messages m ON m.id = a.message_id WHERE a.id = ?",
        (att_id,),
    ).fetchone()
    if row is None:
        raise NotFound("Attachment not found")
    _, sid = _resolve(conn, user, row["requirement_id"], row["supplier_id"])
    if sid != row["supplier_id"]:  # a supplier asking for another supplier's file
        raise NotFound("Attachment not found")
    path = attachments_svc.path_of(row)
    if not path.is_file():
        raise NotFound("File is missing")
    return row, path


def decline(conn: sqlite3.Connection, user: dict, req_id: int, reason: str) -> dict:
    """A supplier says they will not quote. Withdraws any active quote; the buyer is told and sees the reason."""
    if user["role"] != "supplier" or not user.get("supplier_id"):
        raise Forbidden("Only suppliers can decline")
    reason = (reason or "").strip()[:500]
    sid = user["supplier_id"]
    req = req_svc._get_visible(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("This requirement is no longer open")
    req_svc.ensure_quoting_open(req)
    conn.execute(
        "UPDATE quotes SET status = 'Withdrawn' WHERE requirement_id = ? AND supplier_id = ? AND status = 'Submitted'",
        (req_id, sid),
    )
    cur = conn.execute(
        "UPDATE requirement_invites SET declined = 1, decline_reason = ? WHERE requirement_id = ? AND supplier_id = ?",
        (reason, req_id, sid),
    )
    if cur.rowcount == 0:  # open-to-all requirements have no invite row until someone declines
        conn.execute(
            "INSERT INTO requirement_invites (requirement_id, supplier_id, declined, decline_reason, created_at) VALUES (?,?,1,?,?)",
            (req_id, sid, reason, now()),
        )
    supplier = suppliers_svc.get_supplier(conn, sid)
    buyer = conn.execute(
        "SELECT id, email FROM users WHERE id = ?", (req["created_by"],)
    ).fetchone()
    notify(
        conn,
        title=f"{supplier['supplier_name']} declined {req['req_number']}",
        message=f"{supplier['supplier_name']} will not quote on '{req['title']}'."
        + (f" Reason: {reason}" if reason else ""),
        email_to=buyer["email"] if buyer else None,
        user_id=buyer["id"] if buyer else None,
        link=f"/requirements/{req_id}",
    )
    conn.execute(
        "INSERT INTO messages (requirement_id, supplier_id, sender_id, sender_role, body, created_at) VALUES (?,?,?,?,?,?)",
        (
            req_id,
            sid,
            user["id"],
            "supplier",
            "Declined to quote." + (f" Reason: {reason}" if reason else ""),
            now(),
        ),
    )
    audit(conn, user["id"], "decline", "requirement", req["req_number"], f"supplier={sid}")
    return req_svc.get_requirement(conn, user, req_id)
