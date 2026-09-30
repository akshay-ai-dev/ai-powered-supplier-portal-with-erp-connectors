"""Notification bell endpoints (SRS §5.1): list and mark as read."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import Notification

router = APIRouter(tags=["notifications"])


class NotificationItem(BaseModel):
    id: int
    event: str
    title: str
    body: str
    link: str
    read: bool
    createdAt: datetime


class NotificationList(BaseModel):
    unreadCount: int
    items: list[NotificationItem]


def _item(n: Notification) -> NotificationItem:
    return NotificationItem(
        id=n.id,
        event=n.event,
        title=n.title,
        body=n.body,
        link=n.link,
        read=n.read,
        createdAt=n.created_at,
    )


@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    user: CurrentUser, session: SessionDep, limit: int = Query(20, ge=1, le=100)
) -> NotificationList:
    """The current user's notifications, newest first, with the unread count."""
    rows = session.exec(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    unread = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read == False)  # noqa: E712
    ).one()
    return NotificationList(unreadCount=unread, items=[_item(n) for n in rows])


@router.post("/notifications/{notification_id}/read", response_model=NotificationItem)
def mark_read(notification_id: int, user: CurrentUser, session: SessionDep) -> NotificationItem:
    """Mark one of the current user's notifications as read. Safe to repeat."""
    n = session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # never reveal other users' notifications
        raise HTTPException(404, "Notification not found.")
    if not n.read:
        n.read = True
        session.add(n)
        session.commit()
        session.refresh(n)
    return _item(n)


class ReadAllResult(BaseModel):
    updated: int


@router.post("/notifications/read-all", response_model=ReadAllResult)
def mark_all_read(user: CurrentUser, session: SessionDep) -> ReadAllResult:
    """Mark all of the current user's notifications as read (bell 'Mark all read')."""
    rows = session.exec(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.read == False,  # noqa: E712
        )
    ).all()
    for n in rows:
        n.read = True
        session.add(n)
    session.commit()
    return ReadAllResult(updated=len(rows))
