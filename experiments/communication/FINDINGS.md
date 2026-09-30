# Findings: Communication (notifications, email alerts, message threads)

**Feature:** When something important happens in the workflow (invited, awarded, shipment submitted, etc.), the right user gets an in-portal notification in the bell and a one-way email alert. Buyers and suppliers can also talk privately inside each request through a message thread. Used by Buyer, Supplier and Inspector.

---

## 1. High-level diagram

```
 [Workflow code]                 [notify()]                        [SQLite]
 e.g. award, shipment  ──call──▶  build text from event   ──insert──▶  Notification row
 (teammates' code)                 transform: event → text           stored in: Disk
                                         │
                                         │ background task (user does not wait)
                                         ▼
                                  [email.py]  ──SMTP :1025──▶  [Mailpit]  ──▶  inbox at localhost:8025
                                  transform: text → email              stored in: Mailpit (RAM/disk)
                                  on success: set emailSentAt

 [Browser / bell]  ──GET /notifications──▶  [FastAPI]  ──select──▶  [SQLite]   (newest first, unread count)
 [Browser / bell]  ──POST /notifications/{id}/read──▶  [FastAPI]  ──update read=true──▶  [SQLite]

 [Buyer or Supplier] ──POST /requests/{id}/threads/{supplierId}/messages──▶ [FastAPI]
        access check: supplier = own thread only; buyer = all threads
        ──insert──▶ Message row (Disk)  ──then──▶ notify(other party, "new message")
```

---

## 2. Data movement

| Stage | From → To | What data | How (protocol / format) |
|-------|-----------|-----------|-------------------------|
| In | Teammates' workflow code → `notify()` | user_id, event name, record_id | In-process Python function call |
| In | Browser → FastAPI | Bell requests, new messages (text + attachment IDs) | REST over HTTP, JSON |
| Through | `notify()` → email sender | Recipient, subject, body with portal link | Background task (in-process) |
| Out | FastAPI → SQLite | Notification, MessageThread, Message rows | SQL insert/update via SQLModel |
| Out | Email sender → Mailpit | Email alert | SMTP on localhost:1025, no login, no TLS |
| Out | FastAPI → Browser | Notification list, unread count, thread messages | HTTP response, JSON |

---

## 3. Data storage

| Stage | Stored in | What is stored | How long it lives | Rough size |
|-------|-----------|----------------|-------------------|------------|
| Building the notification/email | RAM (process memory) | Event, text, email object | Milliseconds (one request) | < 10 KB |
| Saved notifications | Disk (SQLite `data/portal.db`) | Notification rows | Until data reset | ~200 bytes per row; a few hundred per demo |
| Saved messages | Disk (SQLite) | MessageThread and Message rows | Until data reset | < 1 KB per message |
| Message attachments | Disk (`data/files/`) | Uploaded PDFs/images | Until data reset | Up to 20 MB each (`MAX_UPLOAD_SIZE_MB`) |
| Delivered emails | Mailpit (inside Docker) | Copy of each email alert | Until Mailpit is cleared/restarted | ~2 KB per email |

---

## 4. Data transformation

| Step | Input | Operation | Output |
|------|-------|-----------|--------|
| 1 | Event name + record ID | Map: look up the event's text template (10 events) | Notification title and message |
| 2 | Event name | Map: look up who receives it (buyer, supplier, inspector) | List of recipient user IDs |
| 3 | Notification text + `PORTAL_BASE_URL` + record ID | Build: add a link back into the portal | Email subject and body |
| 4 | All notifications | Filter by current user, sort newest first, count unread | Bell list + unread count |
| 5 | Thread request + current user | Filter: supplier sees only own thread; buyer sees all | Allowed messages, or 403 |

---

## 5. Non-functional questions

### 5.1 Availability

- **Needs to be up:** FastAPI backend and the SQLite file for the bell and threads.
- **Mailpit (SMTP) is optional:** if it is down, notifications are still saved and the bell still works. Only the email is missed, and that failure is logged.
- **Does not depend on** the ERP adapters or the AI features.

### 5.2 Latency

- Saving a notification: a few milliseconds (one SQLite insert).
- Email: runs in a background task, so the user's action returns without waiting for SMTP. Sending to local Mailpit takes well under a second.
- Bell list: one query; well within the spec's 2-second screen load target.

### 5.3 Throughput

- Low. A full demo raises a few dozen notifications and messages. SQLite in WAL mode handles this easily while other reads and writes happen.

### 5.4 Reliability

| Failure | How it is detected | How it is handled |
|---------|--------------------|-------------------|
| Mailpit / SMTP down or timeout | Exception when sending | Log the error, leave `emailSentAt` empty; notification row is kept |
| Same event raised twice | Check for an existing notification with the same user + event + record | Skip the duplicate, so no double bell entry or double email |
| Unknown event name | Validation against the 10-event list | Reject with a clear error during development |
| Supplier opens another supplier's thread | Access check in the API | Return 403; nothing is shown |
| Bad message input (empty text, file too large or wrong type) | Validation on the request | Return 400 with a clear message |

- **Data loss:** notifications are written to the database before the email is attempted, so a failed email never loses the notification.
- **Duplication:** prevented by the duplicate check above.

---

## 6. Validation

Tested in Docker (api + web + mailpit) on 30 Sep 2026. Screenshots in `proof/`.

- [x] Test email from `script.py` visible in Mailpit (http://localhost:8025)
- [x] 20 backend tests pass: `docker compose exec api pytest -q`
- [x] All 10 events raise a bell notification and an email:
      `send_all_events.py` → 13 notifications, 13 emails sent
- [x] Emails contain a link back into the portal; one-way (no reply-by-email)
- [x] Bell and message thread work against the real backend (http://localhost:5173/dev/live)
- [x] Supplier can only open their own thread (403); buyer sees all; declined thread is read-only
- [x] Mailpit down: notification is still saved and the error recorded (covered by tests)

Proof: `proof/01_tests_and_events.png`, `proof/02_mailpit_inbox.png`, `proof/03_bell_and_thread.png`

### What we learned

- Real SMTP credentials in a developer's `.env` broke the tests and could send real emails.
  Docker now always uses Mailpit (no login, no TLS), whatever `.env` says.
- The bell's "Mark all read" needed `POST /notifications/read-all`, which the spec didn't list.
- Other slices must call `notify()` at each workflow step, or the bell stays empty.

## 7. Implementation notes

- Code: `backend/app/notifications/` (events, service, email, directory), `backend/app/api/`
  (notifications, messages, deps), `backend/app/db/` (models, session).
- Identity: the role picker sends the demo user id in the `X-Portal-User` header.
- `notifications/directory.py` is a stand-in for users and invitations until the role picker (Slice 1)
  and Request/Invitation tables (Slice 2) exist; only that file changes when they do.
- `db/models.py` and `db/session.py` are shared: other slices add their tables there.
  Tables are created at startup for now; switch to Alembic migrations when the schema settles.
