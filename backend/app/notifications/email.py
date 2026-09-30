"""One-way email alerts over SMTP (Mailpit in the prototype; SRS §3.1, §8).

send_email() never raises: a mail failure must not break the user's action or the
bell. It returns an error string instead, which the caller records.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.config import get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> str | None:
    """Send one plain-text email. Returns None on success, or an error message."""
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.smtp_from_name, s.smtp_from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as server:
            if s.smtp_use_tls:
                server.starttls()
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
        return None
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Email to %s failed: %s", to, exc)
        return f"{type(exc).__name__}: {exc}"
