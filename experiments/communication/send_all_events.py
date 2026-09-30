"""Proof for SRS §10.1: every event raises a bell notification AND an email in Mailpit.

Run from the repo root with Mailpit running (http://localhost:8025):

    uv run --directory backend python ../experiments/communication/send_all_events.py

Then open Mailpit: you should see 10 emails, one per event.
It uses a separate throwaway database (data/proof_events.db), so it never touches portal.db.
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./data/proof_events.db"
Path("data/proof_events.db").unlink(missing_ok=True)

from sqlmodel import Session, select  # noqa: E402

from app.db.models import Notification  # noqa: E402
from app.db.session import create_tables, get_engine  # noqa: E402
from app.notifications.events import EVENTS  # noqa: E402
from app.notifications.service import notify  # noqa: E402

# (event, recipients, record, context) following SRS §4 "Notification" column
CASES = [
    ("invited", ["sup-apex", "sup-delta"], "REQ-0001", {"deadline": "2026-10-05"}),
    ("response_received", ["buyer-1"], "REQ-0001", {"supplier_name": "Apex Hydraulics"}),
    ("deadline_reached", ["buyer-1"], "REQ-0001", {}),
    ("awarded", ["sup-apex"], "REQ-0001", {"po_number": "4500000123"}),
    ("not_awarded", ["sup-delta"], "REQ-0001", {}),
    ("shipment_submitted", ["buyer-1", "inspector-1"], "SHP-0001",
     {"supplier_name": "Apex Hydraulics", "request_id": "REQ-0001"}),
    ("arrived", ["buyer-1"], "SHP-0001", {}),
    ("inspection_result", ["buyer-1", "sup-apex"], "SHP-0001", {"result": "approved"}),
    ("erp_change_flagged", ["buyer-1"], "REQ-0002", {}),
    ("new_message", ["buyer-1"], "REQ-0001",
     {"author_name": "Apex Hydraulics", "supplier_id": "SUP-SAP-01"}),
]


def main() -> None:
    assert {c[0] for c in CASES} == set(EVENTS), "every one of the 10 events is covered"
    create_tables()
    with Session(get_engine()) as s:
        for event, users, record, ctx in CASES:
            notify(s, users, event, record, ctx)  # no background: sends right away
        rows = s.exec(select(Notification).order_by(Notification.id)).all()

    print(f"{'event':<20} {'user':<12} {'email':<8} title")
    for r in rows:
        status = "sent" if r.email_sent_at else "FAILED"
        print(f"{r.event:<20} {r.user_id:<12} {status:<8} {r.title}")
    failed = [r for r in rows if not r.email_sent_at]
    print(f"\n{len(rows)} notifications, {len(rows) - len(failed)} emails sent.")
    if failed:
        print(f"Email error: {failed[0].email_error}  (is Mailpit running on port 1025?)")
    else:
        print("Open http://localhost:8025 to see them.")


if __name__ == "__main__":
    main()
