import logging
import smtplib
import sqlite3
from email.message import EmailMessage

from ..config import settings
from ..db import now
from .context import current_channel, token_label

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
) -> None:
    """Store an in-app notification and send the matching email."""
    conn.execute(
        "INSERT INTO notifications (user_id, supplier_id, title, message, created_at) VALUES (?,?,?,?,?)",
        (user_id, supplier_id, title, message, now()),
    )
    if email_to:
        send_email(email_to, title, message)


def list_for_user(conn: sqlite3.Connection, user: dict, limit: int = 50) -> list[dict]:
    if user["role"] == "supplier" and user.get("supplier_id"):
        rows = conn.execute(
            "SELECT * FROM notifications WHERE supplier_id = ? OR user_id = ? ORDER BY id DESC LIMIT ?",
            (user["supplier_id"], user["id"], limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
    return [dict(r) for r in rows]
