"""Notification service and bell API (SRS §3.1, §10.1)."""

from sqlmodel import Session, select

from app.db.models import Notification
from app.db.session import get_engine
from app.notifications.events import EVENTS
from app.notifications.service import notify
from tests.conftest import as_user

CONTEXT = {
    "deadline": "2026-10-05",
    "supplier_name": "Apex Hydraulics",
    "po_number": "4500000123",
    "request_id": "REQ-0001",
    "result": "approved",
    "author_name": "Apex Hydraulics",
    "supplier_id": "SUP-SAP-01",
}


def test_all_ten_events_reach_bell_and_mailbox(client, mailbox):
    assert len(EVENTS) == 10
    with Session(get_engine()) as s:
        for event in EVENTS:
            notify(s, ["buyer-1"], event, "REQ-0001", CONTEXT)

    body = client.get("/notifications", headers=as_user("buyer-1")).json()
    assert body["unreadCount"] == 10
    assert {n["event"] for n in body["items"]} == set(EVENTS)
    assert all("{" not in n["title"] + n["body"] for n in body["items"])  # all placeholders filled

    assert len(mailbox.sent) == 10
    first = mailbox.sent[0]
    assert first["To"] == "priya.sharma@srs.demo.local"
    assert "http://localhost:5173/requests/REQ-0001" in first.get_content()
    assert "do not reply" in first.get_content()
    with Session(get_engine()) as s:
        assert all(n.email_sent_at for n in s.exec(select(Notification)).all())


def test_bell_is_per_user(client):
    with Session(get_engine()) as s:
        notify(s, ["sup-apex"], "awarded", "REQ-0001", CONTEXT)
    assert client.get("/notifications", headers=as_user("buyer-1")).json()["unreadCount"] == 0
    assert client.get("/notifications", headers=as_user("sup-apex")).json()["unreadCount"] == 1


def test_mark_read(client):
    with Session(get_engine()) as s:
        [n] = notify(s, ["buyer-1"], "response_received", "REQ-0001", CONTEXT)
        nid = n.id
    r = client.post(f"/notifications/{nid}/read", headers=as_user("buyer-1"))
    assert r.status_code == 200 and r.json()["read"] is True
    assert client.post(f"/notifications/{nid}/read", headers=as_user("buyer-1")).status_code == 200
    assert client.get("/notifications", headers=as_user("buyer-1")).json()["unreadCount"] == 0


def test_cannot_mark_someone_elses_notification(client):
    with Session(get_engine()) as s:
        [n] = notify(s, ["buyer-1"], "arrived", "SHP-0001", CONTEXT)
        nid = n.id
    assert client.post(f"/notifications/{nid}/read", headers=as_user("sup-apex")).status_code == 404


def test_duplicate_events_are_skipped(client, mailbox):
    with Session(get_engine()) as s:
        notify(s, ["sup-apex"], "awarded", "REQ-0001", CONTEXT)
        again = notify(s, ["sup-apex"], "awarded", "REQ-0001", CONTEXT)
    assert again == []
    assert len(mailbox.sent) == 1


def test_mailpit_down_keeps_the_notification(client, mailbox):
    mailbox.fail = True
    with Session(get_engine()) as s:
        notify(s, ["buyer-1"], "deadline_reached", "REQ-0001", CONTEXT)
        row = s.exec(select(Notification)).one()
        s.refresh(row)
        assert row.email_sent_at is None
        assert "Mailpit is down" in row.email_error
    assert client.get("/notifications", headers=as_user("buyer-1")).json()["unreadCount"] == 1


def test_unknown_event_is_rejected(client):
    import pytest

    with Session(get_engine()) as s, pytest.raises(ValueError):
        notify(s, ["buyer-1"], "made_up_event", "REQ-0001")


def test_missing_or_unknown_user_header(client):
    assert client.get("/notifications").status_code == 401
    assert client.get("/notifications", headers=as_user("nobody")).status_code == 401


def test_mark_all_read_only_touches_own_notifications(client):
    with Session(get_engine()) as s:
        notify(s, ["buyer-1"], "response_received", "REQ-0001", CONTEXT)
        notify(s, ["buyer-1"], "deadline_reached", "REQ-0001", CONTEXT)
        notify(s, ["sup-apex"], "awarded", "REQ-0001", CONTEXT)
    r = client.post("/notifications/read-all", headers=as_user("buyer-1"))
    assert r.status_code == 200 and r.json() == {"updated": 2}
    assert client.get("/notifications", headers=as_user("buyer-1")).json()["unreadCount"] == 0
    assert client.get("/notifications", headers=as_user("sup-apex")).json()["unreadCount"] == 1
