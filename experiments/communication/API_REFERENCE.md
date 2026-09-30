# API reference: Communication (notifications, email alerts, message threads)

The APIs and tech-stack references this feature depends on, gathered **before** building it.

**Slice:** 3 (Communication), SRS spec sections 2.1 (row 8), 3.1, 4, 5.1, 7, 8, 10.1 and 11 (D5).
**Out of scope for now:** role dashboards.

---

## 1. Requirements (input)

### Functional requirements

- **FR1 – Notifications for 10 events.** Raise an in-portal notification for each event in SRS §3.1:

  | # | Event | Who receives it |
  |---|-------|-----------------|
  | 1 | Invited | Invited suppliers |
  | 2 | Response received | Buyer |
  | 3 | Deadline reached | Buyer |
  | 4 | Awarded | Winning supplier |
  | 5 | Not awarded | Other suppliers |
  | 6 | Shipment submitted | Buyer, Inspector |
  | 7 | Arrived | Buyer |
  | 8 | Inspection result | Buyer, Supplier |
  | 9 | ERP change flagged | Buyer |
  | 10 | New message | The other party in the thread |

- **FR2 – Notification bell.** Each user sees an unread count and a list of their notifications. Clicking one marks it read and opens the linked record (request, shipment, etc.).
- **FR3 – One-way email alerts.** Every notification also sends an email with a link back into the portal. No reply-by-email; replies happen in the portal.
- **FR4 – Request message threads.** Per request, one private thread between the buyer and each invited supplier. Text plus attachments.
- **FR5 – Thread privacy.** A supplier can read and write only their own thread. The buyer can open all threads on their request. Enforced in the API.
- **FR6 – Single entry point.** One function, `notify(user_id, event, record_id)`, that other teammates call from their workflow code.

### API endpoints (SRS §5.1)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/notifications` | Current user's notifications, newest first, with unread count |
| POST | `/notifications/{id}/read` | Mark one notification as read |
| GET | `/requests/{id}/threads/{supplierId}/messages` | Read a thread |
| POST | `/requests/{id}/threads/{supplierId}/messages` | Send a message (text + attachment IDs) |

### Data (SRS §7)

- `Notification`: id, userId, event, recordId, read, emailSentAt
- `MessageThread`: requestId, supplierId
- `Message`: author, text, attachmentIds, sentAt
- Attachments reuse the shared `Attachment` table with `ownerType = "message"`

### Non-functional requirements

- **Availability:** The bell must keep working if Mailpit/SMTP is down. Email failure must never block the user's action.
- **Latency:** Email is sent in the background, so the user's action returns immediately. Screens load in under 2 s on seed data (SRS §8).
- **Throughput:** Low. A demo raises a few dozen notifications; no special scaling needed.
- **Reliability:** No duplicate notifications or emails for one event. A failed email is logged (and `emailSentAt` stays empty) rather than lost silently.
- **Security / data rules (SRS §8):** Demo data only. No real emails leave the environment (Mailpit in dev). No SMTP credentials committed; secrets live only in local `.env`.

### Configuration (from repo `.env.example`)

| Variable | Value in dev | Purpose |
|----------|--------------|---------|
| `SMTP_HOST` | `localhost` | Where emails are sent (Mailpit) |
| `SMTP_PORT` | `1025` | Mailpit SMTP port |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | empty | Not needed for Mailpit |
| `SMTP_USE_TLS` | `false` | Mailpit does not use TLS |
| `SMTP_FROM_ADDRESS` | `no-reply@supplier-portal.local` | Sender address |
| `EMAIL_ALERTS_ENABLED` | `true` | On/off switch (email is 2nd on the cut list) |
| `PORTAL_BASE_URL` | `http://localhost:5173` | Used for links in email alerts |
| `MAILPIT_UI_PORT` | `8025` | Inbox at http://localhost:8025 |

---

## 2. References

**Mailpit (local email catcher)**
- Docs: https://mailpit.axllent.org/docs/
- Docker image: https://hub.docker.com/r/axllent/mailpit
- Run command used (from repo `package.json`):
  `docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit`

**Sending email from Python**
- `smtplib` (standard library): https://docs.python.org/3/library/smtplib.html
- `email.message.EmailMessage`: https://docs.python.org/3/library/email.message.html

**Running work in the background**
- FastAPI background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/

**Database models**
- SQLModel tutorial: https://sqlmodel.tiangolo.com/tutorial/

**Project sources**
- SRS Supplier Portal Final Build Specification (sections listed at the top)
- Repo `.env.example` and `backend/app/config.py`
