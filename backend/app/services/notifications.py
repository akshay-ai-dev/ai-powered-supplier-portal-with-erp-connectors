import logging
import smtplib
import sqlite3
from email.message import EmailMessage

from ..config import settings
from ..db import now
from .context import current_channel, token_label
from .errors import NotFound

log = logging.getLogger("erp.notifications")


def audit(
    conn: sqlite3.Connection,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id,
    detail: str = "",
) -> None:
    label = token_label.get()
    if label:
        detail = f"{detail} [token: {label}]".strip()
    conn.execute(
        "INSERT INTO audit_logs (user_id, action, entity, entity_id, detail, channel, created_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, action, entity, str(entity_id), detail, current_channel(), now()),
    )


def send_email(to: str, subject: str, body: str) -> bool:
    """Send via SMTP (Mailpit locally). Never raises: email must not break a business flow."""
    if not settings.email_enabled or not to:
        return False
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=3) as smtp:
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Email to %s failed: %s", to, exc)
        return False


def notify(
    conn: sqlite3.Connection,
    *,
    title: str,
    message: str,
    email_to: str | None,
    user_id: int | None = None,
    supplier_id: int | None = None,
    link: str | None = None,
) -> None:
    """Store an in-app notification (shown in the bell) and send the matching email.

    `link` is the portal path the bell opens when the notification is clicked,
    e.g. "/requirements/7" or "/shipments/3".
    """
    conn.execute(
        "INSERT INTO notifications (user_id, supplier_id, title, message, link, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, supplier_id, title, message, link, now()),
    )
    if email_to:
        if link:
            message = f"{message}\n\nOpen in the portal: {settings.portal_url.rstrip('/')}{link}"
        send_email(email_to, title, message)


def _scope(user: dict) -> tuple[str, tuple]:
    """WHERE clause for the notifications a user may see.

    Suppliers see everything addressed to their supplier company plus anything sent to them
    personally; every other role sees only notifications addressed to their user id.
    """
    if user["role"] == "supplier" and user.get("supplier_id"):
        return "(supplier_id = ? OR user_id = ?)", (user["supplier_id"], user["id"])
    return "user_id = ?", (user["id"],)


def list_for_user(
    conn: sqlite3.Connection, user: dict, limit: int = 50, unread_only: bool = False
) -> list[dict]:
    where, args = _scope(user)
    if unread_only:
        where += " AND is_read = 0"
    rows = conn.execute(
        f"SELECT * FROM notifications WHERE {where} ORDER BY id DESC LIMIT ?", (*args, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def unread_count(conn: sqlite3.Connection, user: dict) -> int:
    where, args = _scope(user)
    return conn.execute(
        f"SELECT COUNT(*) FROM notifications WHERE {where} AND is_read = 0", args
    ).fetchone()[0]


def mark_read(conn: sqlite3.Connection, user: dict, notification_id: int) -> dict:
    """Mark one notification read. Raises NotFound if it does not exist or is not the user's."""
    where, args = _scope(user)
    row = conn.execute(
        f"SELECT * FROM notifications WHERE id = ? AND {where}", (notification_id, *args)
    ).fetchone()
    if row is None:
        raise NotFound("Notification not found")
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
    return {**dict(row), "is_read": 1}


def mark_all_read(conn: sqlite3.Connection, user: dict) -> int:
    """Mark every unread notification of the user read. Returns how many changed."""
    where, args = _scope(user)
    cur = conn.execute(f"UPDATE notifications SET is_read = 1 WHERE {where} AND is_read = 0", args)
    return cur.rowcount
