"""notify(): the single entry point for raising notifications (SRS §3.1).

Other slices call it at each workflow step, e.g. after an award:

    from app.notifications.service import notify
    notify(session, ["sup-apex"], "awarded", "REQ-0007",
           context={"po_number": "4500000123"}, background=background_tasks)

It (1) saves one Notification row per recipient (the bell), then (2) sends an email
alert per row in the background and records emailSentAt. The row is saved first, so
a mail failure never loses the notification.
"""

import logging
from datetime import UTC, datetime

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import Notification
from app.db.session import get_engine
from app.notifications import directory
from app.notifications.email import send_email
from app.notifications.events import render

log = logging.getLogger(__name__)

# Events that can legitimately repeat for the same record (every message is new).
REPEATABLE_EVENTS = {"new_message"}


def notify(
    session: Session,
    user_ids: list[str],
    event: str,
    record_id: str,
    context: dict | None = None,
    background: BackgroundTasks | None = None,
) -> list[Notification]:
    """Create bell notifications for each user and queue their email alerts.

    Returns the created rows. Duplicate (user, event, record) notifications are skipped
    for non-repeatable events, so a retried workflow step doesn't notify twice.
    With `background=None` the emails are sent immediately (scripts and tests).
    """
    title, body, link = render(event, record_id, context)
    created: list[Notification] = []
    for user_id in dict.fromkeys(user_ids):  # de-duplicate, keep order
        if event not in REPEATABLE_EVENTS:
            exists = session.exec(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.event == event,
                    Notification.record_id == record_id,
                )
            ).first()
            if exists:
                continue
        row = Notification(
            user_id=user_id, event=event, record_id=record_id, title=title, body=body, link=link
        )
        session.add(row)
        created.append(row)
    session.commit()

    if get_settings().email_alerts_enabled:
        for row in created:
            if background is not None:
                background.add_task(send_notification_email, row.id)
            else:
                send_notification_email(row.id)
    return created


def send_notification_email(notification_id: int) -> None:
    """Send the email alert for one notification and record the outcome."""
    with Session(get_engine()) as session:
        row = session.get(Notification, notification_id)
        if row is None or row.email_sent_at is not None:
            return
        user = directory.get_user(row.user_id)
        if user is None:
            row.email_error = "No email address for user"
        else:
            url = get_settings().portal_base_url.rstrip("/") + row.link
            body = (
                f"{row.body}\n\nOpen in the portal: {url}\n\n"
                "This is an automated alert. Please do not reply to this email; "
                "reply in the portal instead."
            )
            error = send_email(user.email, f"[SRS Supplier Portal] {row.title}", body)
            if error:
                row.email_error = error
            else:
                row.email_sent_at = datetime.now(UTC)
                row.email_error = None
        session.add(row)
        session.commit()
