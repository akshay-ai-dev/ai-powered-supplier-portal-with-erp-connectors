"""Database tables (SRS §7).

Communication slice (Slice 3) tables only: Notification, MessageThread, Message,
Attachment. Other slices add their tables here.
"""

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Notification(SQLModel, table=True):
    """One bell entry for one user. Email alert state is tracked on the same row."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    event: str = Field(index=True)  # one of app.notifications.events.EVENTS
    record_id: str = Field(index=True)  # e.g. REQ-0007 or SHP-0012
    title: str
    body: str
    link: str  # portal path, e.g. /requests/REQ-0007
    read: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    email_sent_at: datetime | None = None
    email_error: str | None = None


class MessageThread(SQLModel, table=True):
    """Private thread per request per invited supplier (SRS §3.1)."""

    __table_args__ = (UniqueConstraint("request_id", "supplier_id"),)

    id: int | None = Field(default=None, primary_key=True)
    request_id: str = Field(index=True)
    supplier_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    thread_id: int = Field(foreign_key="messagethread.id", index=True)
    author: str  # user id
    author_role: str  # buyer | supplier | admin
    text: str
    sent_at: datetime = Field(default_factory=utcnow, index=True)


class Attachment(SQLModel, table=True):
    """Shared attachment table (SRS §7). ownerType: request | message | shipment."""

    id: int | None = Field(default=None, primary_key=True)
    owner_type: str = Field(index=True)
    owner_id: int = Field(index=True)
    file_name: str
    file_type: str  # MIME type
    size_bytes: int
    storage_path: str  # relative to FILE_STORAGE_PATH
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=utcnow)
