"""Buyer requirements (RFQs) and supplier quotes.

Lifecycle: Open (not finalised, visible only to invited suppliers) -> Awarded (a quote was accepted and a PO
was raised) | Cancelled. After award, the stage follows the PO: Awarded -> In Transit -> Delivered -> Closed.

Each requirement targets one ERP (sap | infor); the PO raised on award is pushed to that ERP when approved.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import now
from . import attachments as attachments_svc
from . import purchase_orders as po_svc
from . import suppliers as suppliers_svc
from .context import current_channel
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, notify

ERPS = ("sap", "infor")
REMINDER_WINDOW = timedelta(hours=24)


def parse_deadline(value: str | None) -> str | None:
    """Accepts ISO 8601 (no offset = UTC) and returns a normalised UTC string, or None for "no deadline"."""
    if value is None or str(value).strip() == "":
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise DomainError("quote_deadline must be an ISO date-time such as 2026-10-15T17:00:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _deadline(req) -> datetime | None:
    d = req["quote_deadline"]
    return datetime.fromisoformat(d) if d else None


def quotes_closed(req) -> bool:
    """An Open requirement whose quote deadline has passed: no new, changed, withdrawn or declined quotes."""
    d = _deadline(req)
    return req["status"] == "Open" and d is not None and d <= datetime.now(timezone.utc)


def ensure_quoting_open(req) -> None:
    if quotes_closed(req):
        raise DomainError("Quotes are closed: the deadline for this requirement has passed.")


def _deadline_text(req) -> str:
    d = _deadline(req)
    return d.strftime("%Y-%m-%d %H:%M UTC") if d else ""


def _stage(req: dict, po: sqlite3.Row | None, quote_count: int) -> str:
    if req["status"] == "Cancelled":
        return "Cancelled"
    if req["status"] == "Open":
        if quotes_closed(req):
            return "Quotes closed"
        return "Quoted" if quote_count else "Open"
    if po is None:
        return "Awarded"
    if po["status"] == "Closed":
        return "Closed"
    if po["delivery_status"] == "Delivered":
        return "Delivered"
    if po["delivery_status"] == "Rejected":
        return "Rejected"
    if po["delivery_status"] == "In Transit":
        return "In Transit"
    return "Awarded"


def _is_invited(conn: sqlite3.Connection, req_id: int, supplier_id: int | None) -> bool:
    """True if the supplier was invited, or the requirement is open to all suppliers."""
    return bool(
        supplier_id
        and conn.execute(
            "SELECT 1 FROM requirements r WHERE r.id = ? AND (r.open_to_all = 1 OR EXISTS "
            "(SELECT 1 FROM requirement_invites i WHERE i.requirement_id = r.id AND i.supplier_id = ?))",
            (req_id, supplier_id),
        ).fetchone()
    )


def _has_quote(conn: sqlite3.Connection, req_id: int, supplier_id: int | None) -> bool:
    return bool(
        supplier_id
        and conn.execute("SELECT 1 FROM quotes WHERE requirement_id = ? AND supplier_id = ?", (req_id, supplier_id)).fetchone()
    )


def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row, user: dict, with_quotes: bool = False) -> dict:
    req = dict(row)
    po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (req["po_id"],)).fetchone() if req["po_id"] else None
    quotes = [
        dict(q)
        for q in conn.execute(
            "SELECT q.*, s.supplier_name FROM quotes q JOIN suppliers s ON s.id = q.supplier_id "
            "WHERE q.requirement_id = ? AND q.status != 'Withdrawn' ORDER BY q.unit_price",
            (req["id"],),
        )
    ]
    req["quote_count"] = len(quotes)
    req["quotes_closed"] = quotes_closed(req)
    if user["role"] == "supplier":
        req["unread_messages"] = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE requirement_id = ? AND supplier_id = ? AND sender_role = 'buyer' AND read_at IS NULL",
            (req["id"], user.get("supplier_id") or -1),
        ).fetchone()[0]
    elif user["role"] == "inspector":
        req["unread_messages"] = 0  # the buyer-supplier conversation is private
    else:
        req["unread_messages"] = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE requirement_id = ? AND sender_role = 'supplier' AND read_at IS NULL", (req["id"],)
        ).fetchone()[0]
    req["stage"] = _stage(req, po, len(quotes))
    req["po_number"] = po["po_number"] if po else None
    req["delivery_status"] = po["delivery_status"] if po else None
    if user["role"] == "supplier":
        req["my_quote"] = next((q for q in quotes if q["supplier_id"] == user.get("supplier_id")), None)
        req["awarded_to_me"] = bool(req["my_quote"] and req["my_quote"]["status"] == "Accepted")
        dec = conn.execute(
            "SELECT declined, decline_reason FROM requirement_invites WHERE requirement_id = ? AND supplier_id = ?",
            (req["id"], user.get("supplier_id") or -1),
        ).fetchone()
        req["my_decline"] = {"reason": dec["decline_reason"]} if dec and dec["declined"] else None
        # suppliers never see competitors' quotes, other invitees, or someone else's PO
        if po and not req["awarded_to_me"]:
            req["po_id"], req["po_number"], req["delivery_status"] = None, None, None
        if with_quotes:
            req["attachments"] = attachments_svc.list_for(conn, req["id"])
    elif with_quotes:
        req["quotes"] = quotes
        quoted = {q["supplier_id"] for q in quotes}
        req["invites"] = [
            {
                "supplier_id": r["supplier_id"],
                "supplier_name": r["supplier_name"],
                "quoted": r["supplier_id"] in quoted,
                "declined": bool(r["declined"]),
                "decline_reason": r["decline_reason"],
            }
            for r in conn.execute(
                "SELECT i.supplier_id, i.declined, i.decline_reason, s.supplier_name FROM requirement_invites i JOIN suppliers s ON s.id = i.supplier_id "
                "WHERE i.requirement_id = ? ORDER BY s.supplier_name",
                (req["id"],),
            )
        ]
        req["attachments"] = attachments_svc.list_for(conn, req["id"])
        req["threads"] = [] if user["role"] == "inspector" else _threads(conn, req["id"])
        req["history"] = po_svc.history(conn, "requirement", req["req_number"])
    return req


def _threads(conn: sqlite3.Connection, req_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT m.supplier_id, s.supplier_name, COUNT(*) AS total, "
        "SUM(CASE WHEN m.sender_role = 'supplier' AND m.read_at IS NULL THEN 1 ELSE 0 END) AS unread, MAX(m.created_at) AS last_at "
        "FROM messages m JOIN suppliers s ON s.id = m.supplier_id WHERE m.requirement_id = ? GROUP BY m.supplier_id ORDER BY last_at DESC",
        (req_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_row(conn: sqlite3.Connection, req_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM requirements WHERE id = ?", (req_id,)).fetchone()
    if row is None:
        raise NotFound("Requirement not found")
    return row


def _require_buyer(user: dict) -> None:
    if user["role"] not in ("buyer", "admin"):
        raise Forbidden("Only buyers can do this")


def _get_owned(conn: sqlite3.Connection, user: dict, req_id: int) -> sqlite3.Row:
    """Buyer-side access: a buyer can only act on their own requirements (admins on all)."""
    _require_buyer(user)
    row = _get_row(conn, req_id)
    if user["role"] == "buyer" and row["created_by"] != user["id"]:
        raise NotFound("Requirement not found")
    return row


def _get_visible(conn: sqlite3.Connection, user: dict, req_id: int) -> sqlite3.Row:
    """Read access for anyone: owner buyer/admin, or a supplier who was invited (while open) or has quoted."""
    if user["role"] == "inspector":  # read-only view of everything except the private chat
        return _get_row(conn, req_id)
    if user["role"] != "supplier":
        return _get_owned(conn, user, req_id)
    row = _get_row(conn, req_id)
    sid = user.get("supplier_id")
    if _has_quote(conn, req_id, sid) or (row["status"] == "Open" and _is_invited(conn, req_id, sid)):
        return row
    raise NotFound("Requirement not found")


def _valid_supplier_ids(conn: sqlite3.Connection, ids: list[int]) -> list[int]:
    ids = list(dict.fromkeys(ids))
    known = {r["id"] for r in conn.execute("SELECT id FROM suppliers")}
    bad = [i for i in ids if i not in known]
    if bad:
        raise DomainError(f"Unknown supplier id(s): {bad}")
    return ids


def _notify_invited(conn: sqlite3.Connection, req: dict, supplier_id: int) -> None:
    s = suppliers_svc.get_supplier(conn, supplier_id)
    notify(
        conn,
        title=f"You are invited to quote: {req['req_number']} {req['title']}",
        message=f"A buyer is looking for {req['quantity']} x {req['title']}. Log in to review the details and submit a quote."
        + (f" Quotes are due by {_deadline_text(req)}." if req["quote_deadline"] else ""),
        email_to=s["email"],
        supplier_id=supplier_id,
    )


def _invite(conn: sqlite3.Connection, req: dict, supplier_ids: list[int]) -> list[int]:
    """Add invitations (idempotent) and tell newly invited suppliers. Returns the newly invited ids."""
    new = []
    for sid in supplier_ids:
        cur = conn.execute(
            "INSERT OR IGNORE INTO requirement_invites (requirement_id, supplier_id, created_at) VALUES (?,?,?)",
            (req["id"], sid, now()),
        )
        if cur.rowcount:
            new.append(sid)
            _notify_invited(conn, req, sid)
    return new


def create_requirement(conn: sqlite3.Connection, user: dict, data: dict) -> dict:
    """`supplier_ids` picks the invited suppliers; an empty list invites every supplier."""
    _require_buyer(user)
    erp = data.get("erp") or "sap"
    if erp not in ERPS:
        raise DomainError(f"erp must be one of {ERPS}")
    open_to_all = bool(data.get("open_to_all"))
    invited = [] if open_to_all else _valid_supplier_ids(conn, data.get("supplier_ids") or [r["id"] for r in conn.execute("SELECT id FROM suppliers")])
    if not open_to_all and not invited:
        raise DomainError("There are no suppliers to invite")
    deadline = parse_deadline(data.get("quote_deadline"))
    if deadline and datetime.fromisoformat(deadline) <= datetime.now(timezone.utc):
        raise DomainError("The quote deadline must be in the future")
    # a deadline less than a day away needs no "closing soon" reminder right after the invitation
    soon = bool(deadline) and datetime.fromisoformat(deadline) - datetime.now(timezone.utc) <= REMINDER_WINDOW
    cur = conn.execute(
        "INSERT INTO requirements (req_number, title, description, item_code, quantity, target_price, needed_by, erp, open_to_all, "
        "quote_deadline, deadline_reminded, created_by, created_via, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"TMP-{now()}-{user['id']}", data["title"], data.get("description", ""), data.get("item_code") or None,
         data["quantity"], data.get("target_price"), data.get("needed_by"), erp, 1 if open_to_all else 0,
         deadline, 1 if soon else 0, user["id"], current_channel(), now()),
    )
    rid = cur.lastrowid
    conn.execute("UPDATE requirements SET req_number = ? WHERE id = ?", (f"REQ{2000 + rid}", rid))
    audit(conn, user["id"], "create", "requirement", f"REQ{2000 + rid}", f"erp={erp}, " + ("open to all" if open_to_all else f"invited={len(invited)}") + (f", deadline={deadline}" if deadline else ""))
    req = dict(_get_row(conn, rid))
    if open_to_all:
        for s in suppliers_svc.list_suppliers(conn):
            _notify_invited(conn, req, s["id"])
    else:
        _invite(conn, req, invited)
    return _hydrate(conn, _get_row(conn, rid), user, with_quotes=True)


def open_to_everyone(conn: sqlite3.Connection, user: dict, req_id: int) -> dict:
    """Widen an open requirement so every supplier (now and later) can see and quote it."""
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("Only open requirements can be opened to all suppliers")
    if not req["open_to_all"]:
        already = {r["supplier_id"] for r in conn.execute("SELECT supplier_id FROM requirement_invites WHERE requirement_id = ?", (req_id,))}
        conn.execute("UPDATE requirements SET open_to_all = 1 WHERE id = ?", (req_id,))
        for s in suppliers_svc.list_suppliers(conn):
            if s["id"] not in already:
                _notify_invited(conn, dict(req), s["id"])
        audit(conn, user["id"], "open", "requirement", req["req_number"], "opened to all suppliers")
    return get_requirement(conn, user, req_id)


def invite_more(conn: sqlite3.Connection, user: dict, req_id: int, supplier_ids: list[int]) -> dict:
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("Suppliers can only be invited while the requirement is open")
    if req["open_to_all"]:
        raise DomainError("This requirement is already open to all suppliers")
    new = _invite(conn, dict(req), _valid_supplier_ids(conn, supplier_ids))
    if new:
        audit(conn, user["id"], "invite", "requirement", req["req_number"], f"suppliers={new}")
    return get_requirement(conn, user, req_id)


def list_requirements(conn: sqlite3.Connection, user: dict, stage: str | None = None, mine_only: bool = False) -> list[dict]:
    if user["role"] == "supplier":
        sid = user.get("supplier_id") or -1
        rows = conn.execute(
            "SELECT DISTINCT r.* FROM requirements r "
            "LEFT JOIN quotes q ON q.requirement_id = r.id AND q.supplier_id = ? "
            "LEFT JOIN requirement_invites i ON i.requirement_id = r.id AND i.supplier_id = ? "
            "WHERE (r.status = 'Open' AND (i.id IS NOT NULL OR r.open_to_all = 1) AND ? = 0) OR q.id IS NOT NULL ORDER BY r.id DESC",
            (sid, sid, 1 if mine_only else 0),
        ).fetchall()
    elif user["role"] == "buyer":
        rows = conn.execute("SELECT * FROM requirements WHERE created_by = ? ORDER BY id DESC", (user["id"],)).fetchall()
    elif user["role"] in ("admin", "inspector"):
        rows = conn.execute("SELECT * FROM requirements ORDER BY id DESC").fetchall()
    else:
        raise Forbidden("Not available for your role")
    result = [_hydrate(conn, r, user) for r in rows]
    return [r for r in result if not stage or r["stage"] == stage]


def get_requirement(conn: sqlite3.Connection, user: dict, req_id: int) -> dict:
    return _hydrate(conn, _get_visible(conn, user, req_id), user, with_quotes=True)


def submit_quote(conn: sqlite3.Connection, user: dict, req_id: int, data: dict) -> dict:
    if user["role"] != "supplier" or not user.get("supplier_id"):
        raise Forbidden("Only suppliers can submit quotes")
    sid = user["supplier_id"]
    req = _get_row(conn, req_id)
    if not _is_invited(conn, req_id, sid):
        raise NotFound("Requirement not found")  # not invited: same answer as a missing requirement
    if req["status"] != "Open":
        raise DomainError("This requirement is no longer open")
    ensure_quoting_open(req)
    conn.execute("UPDATE requirement_invites SET declined = 0, decline_reason = '' WHERE requirement_id = ? AND supplier_id = ?", (req_id, sid))
    existing = conn.execute("SELECT id FROM quotes WHERE requirement_id = ? AND supplier_id = ?", (req_id, sid)).fetchone()
    if existing:  # re-applying updates the quote (also reactivates a withdrawn one)
        conn.execute(
            "UPDATE quotes SET unit_price=?, lead_time_days=?, message=?, status='Submitted' WHERE id=?",
            (data["unit_price"], data["lead_time_days"], data.get("message", ""), existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO quotes (requirement_id, supplier_id, unit_price, lead_time_days, message, created_at) VALUES (?,?,?,?,?,?)",
            (req_id, sid, data["unit_price"], data["lead_time_days"], data.get("message", ""), now()),
        )
    supplier = suppliers_svc.get_supplier(conn, sid)
    buyer = conn.execute("SELECT id, email FROM users WHERE id = ?", (req["created_by"],)).fetchone()
    notify(
        conn,
        title=f"New quote on {req['req_number']}",
        message=f"{supplier['supplier_name']} quoted {data['unit_price']:.2f} per unit ({data['lead_time_days']} days lead time).",
        email_to=buyer["email"] if buyer else None,
        user_id=buyer["id"] if buyer else None,
    )
    audit(conn, user["id"], "quote", "requirement", req["req_number"], f"supplier={sid}")
    return get_requirement(conn, user, req_id)


def withdraw_quote(conn: sqlite3.Connection, user: dict, req_id: int) -> dict:
    if user["role"] != "supplier":
        raise Forbidden("Only suppliers can withdraw quotes")
    req = _get_row(conn, req_id)
    if req["status"] != "Open":
        raise DomainError("This requirement is no longer open")
    ensure_quoting_open(req)
    cur = conn.execute(
        "UPDATE quotes SET status='Withdrawn' WHERE requirement_id = ? AND supplier_id = ? AND status = 'Submitted'",
        (req_id, user.get("supplier_id")),
    )
    if cur.rowcount == 0:
        raise NotFound("No active quote to withdraw")
    return get_requirement(conn, user, req_id)


def _audience(conn: sqlite3.Connection, req) -> list[int]:
    """Suppliers who can still respond: everyone if open to all, else the invited ones, minus those who declined."""
    if req["open_to_all"]:
        ids = [r["id"] for r in conn.execute("SELECT id FROM suppliers")]
    else:
        ids = [r["supplier_id"] for r in conn.execute("SELECT supplier_id FROM requirement_invites WHERE requirement_id = ?", (req["id"],))]
    declined = {r["supplier_id"] for r in conn.execute("SELECT supplier_id FROM requirement_invites WHERE requirement_id = ? AND declined = 1", (req["id"],))}
    return [i for i in ids if i not in declined]


def _has_active_quote(conn: sqlite3.Connection, req_id: int, supplier_id: int) -> bool:
    return bool(conn.execute("SELECT 1 FROM quotes WHERE requirement_id = ? AND supplier_id = ? AND status = 'Submitted'", (req_id, supplier_id)).fetchone())


def set_deadline(conn: sqlite3.Connection, user: dict, req_id: int, value: str | None) -> dict:
    """Owner sets, extends or clears the quote deadline while the requirement is Open. Extending reopens a closed RFQ."""
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("The deadline can only be changed while the requirement is open")
    new = parse_deadline(value)
    if new and datetime.fromisoformat(new) <= datetime.now(timezone.utc):
        raise DomainError("The new deadline must be in the future")
    soon = bool(new) and datetime.fromisoformat(new) - datetime.now(timezone.utc) <= REMINDER_WINDOW
    conn.execute(
        "UPDATE requirements SET quote_deadline = ?, deadline_reminded = ?, deadline_closed_notified = 0 WHERE id = ?",
        (new, 1 if soon else 0, req_id),
    )
    audit(conn, user["id"], "deadline", "requirement", req["req_number"], new or "cleared")
    fresh = _get_row(conn, req_id)
    when = f"The new deadline is {_deadline_text(fresh)}." if new else "There is no longer a deadline."
    for sid in _audience(conn, fresh):
        s = suppliers_svc.get_supplier(conn, sid)
        notify(conn, title=f"Quote deadline updated: {req['req_number']}", message=f"The deadline for '{req['title']}' changed. {when}", email_to=s["email"], supplier_id=sid)
    return get_requirement(conn, user, req_id)


def process_deadlines(conn: sqlite3.Connection, now_dt: datetime | None = None) -> dict:
    """Background job: remind suppliers who have not quoted ~24 h before the deadline, and tell the buyer once it has passed.
    Idempotent: each notification is sent once per deadline (flags are reset when the deadline changes)."""
    now_dt = now_dt or datetime.now(timezone.utc)
    reminded = closed = 0
    for r in conn.execute("SELECT * FROM requirements WHERE status = 'Open' AND quote_deadline IS NOT NULL").fetchall():
        deadline = datetime.fromisoformat(r["quote_deadline"])
        if deadline <= now_dt:
            if not r["deadline_closed_notified"]:
                n = conn.execute("SELECT COUNT(*) FROM quotes WHERE requirement_id = ? AND status = 'Submitted'", (r["id"],)).fetchone()[0]
                buyer = conn.execute("SELECT id, email FROM users WHERE id = ?", (r["created_by"],)).fetchone()
                notify(
                    conn,
                    title=f"Quotes closed for {r['req_number']}",
                    message=f"The deadline for '{r['title']}' has passed. {n} quote(s) received. Award a supplier, or extend the deadline to collect more quotes.",
                    email_to=buyer["email"] if buyer else None,
                    user_id=buyer["id"] if buyer else None,
                )
                conn.execute("UPDATE requirements SET deadline_closed_notified = 1 WHERE id = ?", (r["id"],))
                closed += 1
        elif deadline - now_dt <= REMINDER_WINDOW and not r["deadline_reminded"]:
            for sid in _audience(conn, r):
                if _has_active_quote(conn, r["id"], sid):
                    continue
                s = suppliers_svc.get_supplier(conn, sid)
                notify(
                    conn,
                    title=f"Quotes close soon: {r['req_number']}",
                    message=f"The deadline to quote on '{r['title']}' is {_deadline_text(r)}. Log in to submit a quote or decline.",
                    email_to=s["email"],
                    supplier_id=sid,
                )
            conn.execute("UPDATE requirements SET deadline_reminded = 1 WHERE id = ?", (r["id"],))
            reminded += 1
    return {"reminded": reminded, "closed": closed}


def award(conn: sqlite3.Connection, user: dict, req_id: int, quote_id: int) -> dict:
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("Requirement is not open")
    quote = conn.execute(
        "SELECT * FROM quotes WHERE id = ? AND requirement_id = ? AND status = 'Submitted'", (quote_id, req_id)
    ).fetchone()
    if quote is None:
        raise NotFound("Quote not found or no longer active")
    po = po_svc.create_po(
        conn, user, quote["supplier_id"],
        [{"item_code": req["item_code"] or f"REQ{req_id}", "quantity": req["quantity"], "unit_price": quote["unit_price"]}],
        submit=True,
        erp=req["erp"],
    )
    conn.execute("UPDATE quotes SET status='Accepted' WHERE id = ?", (quote_id,))
    losers = conn.execute(
        "SELECT q.id, q.supplier_id FROM quotes q WHERE requirement_id = ? AND status = 'Submitted' AND id != ?", (req_id, quote_id)
    ).fetchall()
    for q in losers:
        conn.execute("UPDATE quotes SET status='Rejected' WHERE id = ?", (q["id"],))
        s = suppliers_svc.get_supplier(conn, q["supplier_id"])
        notify(
            conn,
            title=f"Requirement {req['req_number']} awarded",
            message=f"Thank you for quoting. The requirement '{req['title']}' was awarded to another supplier.",
            email_to=s["email"],
            supplier_id=s["id"],
        )
    conn.execute("UPDATE requirements SET status='Awarded', po_id = ? WHERE id = ?", (po["id"], req_id))
    audit(conn, user["id"], "award", "requirement", req["req_number"], f"po={po['po_number']}")
    return get_requirement(conn, user, req_id)


def cancel(conn: sqlite3.Connection, user: dict, req_id: int) -> dict:
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("Only open requirements can be cancelled")
    conn.execute("UPDATE requirements SET status='Cancelled' WHERE id = ?", (req_id,))
    conn.execute("UPDATE quotes SET status='Rejected' WHERE requirement_id = ? AND status = 'Submitted'", (req_id,))
    audit(conn, user["id"], "cancel", "requirement", req["req_number"])
    return get_requirement(conn, user, req_id)


# ---- attachments (access-checked wrappers around attachments_svc) ----
def add_attachment(conn: sqlite3.Connection, user: dict, req_id: int, filename: str, data: bytes, content_type: str | None) -> dict:
    req = _get_owned(conn, user, req_id)
    if req["status"] != "Open":
        raise DomainError("Files can only be added while the requirement is open")
    att = attachments_svc.save(conn, req_id, user["id"], filename, data, content_type)
    audit(conn, user["id"], "attach", "requirement", req["req_number"], att["filename"])
    return att


def open_attachment(conn: sqlite3.Connection, user: dict, att_id: int) -> tuple[sqlite3.Row, "object"]:
    """Returns (row, path) if the user may see the requirement the file belongs to."""
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if row is None:
        raise NotFound("File not found")
    _get_visible(conn, user, row["requirement_id"])  # raises NotFound for anyone without access
    path = attachments_svc.path_of(row)
    if not path.exists():
        raise NotFound("File not found")
    return row, path


def remove_attachment(conn: sqlite3.Connection, user: dict, att_id: int) -> None:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if row is None:
        raise NotFound("File not found")
    req = _get_owned(conn, user, row["requirement_id"])
    if req["status"] != "Open":
        raise DomainError("Files can only be removed while the requirement is open")
    attachments_svc.remove(conn, row)
    audit(conn, user["id"], "detach", "requirement", req["req_number"], row["filename"])
