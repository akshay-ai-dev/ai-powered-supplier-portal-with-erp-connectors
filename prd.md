# Software Requirements Specification (SRS)

## AI-Enabled ERP Web Application

| | |
|---|---|
| **Project name** | ERP Copilot Platform |
| **Version** | 2.0 (Phase 1 MVP, extended) |
| **Date** | October 2026 |
| **Author** | Vikas Kushwaha |

**Revision note.** Version 1.0 described a Buyer and Supplier MVP. Version 2.0 documents what has actually been built since: four roles (Buyer, Supplier, Inspector, Admin), the requirement / RFQ / quote / award flow, buyer-supplier chat, shipments with warehouse inspection, per-user emails, per-user API tokens for AI agents, and audit flagging of agent actions. Every requirement is marked **Delivered** or **Planned**.

---

## 1. Introduction

### 1.1 Purpose
A modern ERP web application that simulates integration with SAP and Infor LN through mock connectors, and lets AI agents work with ERP data through MCP (Model Context Protocol). It supports the procurement cycle from a buyer's need through supplier quotes, purchase order, shipment and warehouse inspection.

The platform is ERP-agnostic: the mock connectors sit behind one interface and can later be replaced by real SAP S/4HANA or Infor LN connectors.

### 1.2 Objectives
- A responsive ERP web experience for four roles: Buyer, Supplier, Inspector, Admin.
- Mock SAP and Infor LN adapters (purchase orders, inbound deliveries, stock movements, invoice blocks/holds).
- Secure JWT authentication and role-based access control.
- Data isolation: a buyer sees only their own requirements and orders.
- REST APIs plus an MCP server (FastMCP) with OpenAPI-compatible tool endpoints.
- AI-agent access that is per-user, scoped, revocable and fully audited, with agent actions visibly flagged.
- Transactional email through Mailpit, shown to each user in their own Emails page.
- SQLite persistence and a one-command Docker Compose deployment.

---

## 2. Scope

### 2.1 Delivered

| Area | Delivered |
|---|---|
| Accounts | Registration (buyer, supplier), login, JWT, admin-created users (any role), enable/disable |
| Profile | Supplier company profile with phone validation |
| Suppliers | Directory, search, create, edit |
| Requirements / RFQ | Posting, invites or open-to-all, attachments, ERP choice, quote deadline, quotes, decline, award, cancel |
| Chat | Per-requirement buyer-supplier conversation |
| Inventory | List, search, add, edit, delete (creator only), ERP sync |
| Purchase orders | Create, approve, push to ERP, history, close |
| Shipments and inspection | Ship, arrival, quantity check, quality checklist, approve or reject, quarantine, invoice hold |
| Notifications and email | In-app notifications, Mailpit email, per-user Emails page |
| Dashboards | One per role |
| MCP and API access | 7 MCP tools, OpenAPI twins, per-user API tokens, audit flagging |
| Mock ERP | SAP and Infor LN connectors, ERP Monitor page |
| Admin | User management, all-tokens view, data reset |
| Deployment | Docker Compose with five services |

### 2.2 Planned (Phase 2, not yet built)
See section 13: supplier acceptance of the PO, invoices with three-way match and payment status, a process tracker, invoice MCP tools, and a GPT-4o assistant.

### 2.3 Out of scope
Several items per requirement, quote terms (currency, incoterms), quote scoring, PO PDF output, supplier onboarding and approval, real SAP or Infor connections, real payment processing.

---

## 3. Users, roles and permissions

### 3.1 Roles
- **Buyer**: raises requirements and purchase orders, compares quotes, awards, manages their own inventory items.
- **Supplier**: quotes on requirements they can see, fulfils orders, ships goods.
- **Inspector**: warehouse role. Sees everything read-only, receives shipments and decides on quality.
- **Admin**: everything a buyer can do across all buyers, plus user management, ERP sync and data reset.

Registration offers Buyer and Supplier only. Inspectors and admins are created by an admin (a first admin is seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD`).

### 3.2 Permission matrix

| Capability | Buyer | Supplier | Inspector | Admin |
|---|:---:|:---:|:---:|:---:|
| Register themselves | Yes | Yes | No | No |
| View suppliers | Yes | Own profile only | Yes (read) | Yes |
| Create suppliers | Yes | No | No | Yes |
| Edit supplier profile | Yes | Own only | No | Yes |
| View inventory | Yes | No | Yes (read) | Yes |
| Add / edit / delete inventory | Own items only | No | No | Any item |
| Post requirements | Yes | No | No | Yes |
| See requirements | Own only | Invited or open ones | All (no chat) | All |
| Submit, revise, withdraw quote | No | Yes | No | No |
| Decline a requirement | No | Yes | No | No |
| Award a quote, cancel, extend deadline | Own | No | No | Yes |
| Chat on a requirement | Yes | Yes | No (hidden) | Yes |
| Create and approve purchase orders | Own | No | No | Yes |
| See purchase orders | Own | Non-draft, own | All (read) | All |
| Ship an approved order | No | Yes | No | No |
| Record arrival, approve or reject shipment | No | No | Yes | Yes |
| Upload packing list | No | Yes | No | No |
| Upload inspection photos | No | No | Yes | Yes |
| See shipments | Own POs | Own | All | All |
| Use the ERP Monitor | Yes | No | Yes | Yes |
| Create API tokens for MCP | Yes | No | No | Yes |
| Manage users, reset data, sync ERP | No | No | No | Yes (sync also buyer) |
| See own emails | Yes | Yes | Yes | Yes |

---

## 4. Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router), React, TypeScript, Tailwind CSS v4, shadcn UI, Recharts, light and dark mode |
| Backend | FastAPI, Python 3.12+, Pydantic v2 |
| Database | SQLite3 (raw SQL, additive migrations applied at start-up) |
| Authentication | JWT (PyJWT), scrypt password hashing |
| AI / MCP | FastMCP 4.x, Streamable HTTP at `/mcp/` |
| Email | Mailpit (local SMTP and inbox) |
| Deployment | Docker Compose |

---

## 5. System architecture

Layered: **routers** (HTTP) call **services** (all business rules, shared by REST and MCP), which read and write SQLite and call the **ERP connector**. The MCP server and the REST API use the same services, so rules are enforced once.

| Layer | Component | Purpose |
|---|---|---|
| Frontend | Next.js UI | One portal with role-specific navigation |
| Authentication | JWT and API tokens | JWT for the web app; hashed API tokens for MCP only |
| Backend | FastAPI | REST endpoints and the MCP mount |
| Services | `backend/app/services/` | Business rules, audit and notification |
| Connectors | `ERPConnector` interface, mock SAP and Infor | PO push, inbound delivery, stock release, quarantine, invoice hold, reset |
| Data | SQLite | Users, suppliers, inventory, requirements, quotes, orders, shipments, tokens, notifications, audit |
| Email | Mailpit | Captures all outgoing email |
| Background | Deadline loop | Runs every 60 seconds (`DEADLINE_CHECK_SECONDS`, 0 disables) |

Uploads (requirement attachments, packing lists, inspection photos) are stored in the shared data volume.

---

## 6. Functional requirements by feature area

### 6.1 Authentication and accounts (Delivered)
- **FR-AUTH-1** Users register as Buyer or Supplier with name, email and password (8 to 128 characters). A supplier registration also creates the supplier company record.
- **FR-AUTH-2** Login by email and password returns a JWT (default 60 minutes) and the user profile. Disabled accounts cannot log in.
- **FR-AUTH-3** Role-based access control is enforced on every endpoint; other users' records return "not found".
- **FR-AUTH-4** Cross-origin requests from the configured origins are accepted so the app works over the LAN (`CORS_ORIGINS` and an origin regex).
- **FR-AUTH-5** API tokens are refused by the normal REST API (see 6.11).

### 6.2 Profile (Delivered)
- **FR-PROF-1** Suppliers maintain company name, order email, phone and address on the **Profile** page. The order email receives purchase order mail.
- **FR-PROF-2** Phone numbers are validated: digits with an optional leading `+`, separators `space ( ) . - /`, 7 to 15 digits. Letters and other characters are rejected.
- **FR-PROF-3** The signed-in user's name, email and role are shown in the sidebar for every role.

### 6.3 Suppliers (Delivered)
- **FR-SUP-1** Buyers, inspectors and admins list and search suppliers (`/suppliers`).
- **FR-SUP-2** Buyers and admins create suppliers. Each supplier record shows its source ERP (SAP or Infor).
- **FR-SUP-3** A supplier edits only their own profile; buyers and admins may edit any.
- **FR-SUP-4** Suppliers can read only their own supplier record.

### 6.4 Requirements and RFQ (Delivered)
A requirement is a buyer's need for one item, listed to suppliers for quotes.

- **FR-REQ-1 Posting.** The buyer enters a title, optional description, quantity, optional target price and needed-by date, and the ERP (SAP or Infor LN). The item can be linked to an inventory item or described in free text.
- **FR-REQ-2 Audience.** The buyer either invites selected suppliers, or posts it **open to all** (visible to every supplier, including those who join later). Invites can be added while it is open; an open requirement can later be opened to all. Suppliers not invited cannot see it.
- **FR-REQ-3 Attachments.** Files up to 10 MB with whitelisted types can be added or removed while the requirement is open; invited suppliers can download them.
- **FR-REQ-4 Quote deadline.** Optional, pre-filled 7 days out. After it passes, suppliers can no longer submit, revise, withdraw or decline, and the stage becomes **Quotes closed**. The buyer can still award, and can extend, change or clear the deadline (which reopens quoting and notifies suppliers). Suppliers who have not quoted or declined get a reminder about 24 hours before; the buyer is told when quotes close and how many were received. Each notice is sent once per deadline.
- **FR-REQ-5 Quotes.** A supplier submits a unit price, lead time (0 to 730 days) and message; revises or withdraws it while open. The buyer compares quotes side by side.
- **FR-REQ-6 Decline.** A supplier can decline with a reason; the buyer is notified.
- **FR-REQ-7 Award.** Awarding a quote creates a Pending PO for that supplier, marks the quote Accepted, rejects the others and notifies the suppliers.
- **FR-REQ-8 Cancel.** The buyer can cancel an open requirement.
- **FR-REQ-9 Stages.** Open, Quoted, Quotes closed, Awarded, In Transit, Delivered, Rejected, Closed, Cancelled (derived from the requirement, its PO and shipments).
- **FR-REQ-10 Isolation.** A buyer sees only their own requirements; an admin sees all; an inspector sees all read-only but not the private chat.
- **FR-REQ-11 History.** Every change is listed in the requirement's history with who did it and through which channel.

### 6.5 Buyer-supplier chat (Delivered)
- **FR-CHAT-1** Each requirement has one private thread per supplier, available until delivery.
- **FR-CHAT-2** Suppliers see only their own thread; buyers choose a supplier's thread.
- **FR-CHAT-3** Sending a message notifies and emails the other party. Unread counts show on the requirement list.
- **FR-CHAT-4** Inspectors cannot read the chat. Declining shares the reason in the thread.

### 6.6 Inventory (Delivered)
- **FR-INV-1** Buyers, inspectors and admins list, search and filter items (code, description, stock, warehouse, last updated, source).
- **FR-INV-2** Buyers and admins add items (code: letters, digits, `.`, `_`, `-`; unique; stock 0 or more).
- **FR-INV-3** An item can be edited or deleted only by the user who created it (admins may do either). Delete is refused when a PO line or a requirement uses the item.
- **FR-INV-4** ERP sync (Admin **Data & ERP** page, buyers via API) pulls items and suppliers from SAP or Infor. The ERP is the source of truth for description, stock and warehouse.
- **FR-INV-5** Stock increases only when an inspector approves a shipment, in the app and in the mock ERP.
- **FR-INV-6** Items under 20 units count as low stock on the buyer dashboard.

### 6.7 Purchase orders (Delivered)
- **FR-PO-1 Create.** Buyers create POs for a supplier with one or more lines (item, quantity, unit price), as Draft or submitted as Pending. Number format `PO1001`. POs can also come from an awarded requirement or from an AI agent (Draft only).
- **FR-PO-2 Status flow.** Draft, then Pending, then Approved, then Closed. Items can be edited only while Draft or Pending.
- **FR-PO-3 Approval.** Approving pushes the PO to the chosen ERP (SAP or Infor), stores the ERP reference, and notifies and emails the supplier.
- **FR-PO-4 Delivery status.** Not Shipped, In Transit, Delivered, Rejected. It is driven only by shipments and inspection, never edited by hand.
- **FR-PO-5 Close.** A PO can be closed only after it is Delivered.
- **FR-PO-6 Visibility.** Buyers see their own POs; suppliers see their own non-draft POs; inspectors and admins see all.
- **FR-PO-7 History and flags.** PO history shows every action; actions done through an AI agent carry an **AI agent** badge. A PO shows an **invoice hold** flag with its reason when a shipment is rejected.
- **FR-PO-8 Search.** Filter by status and search by number or supplier.

### 6.8 Shipments and fulfilment (Delivered)
- **FR-SHIP-1 Ship.** The assigned supplier ships an Approved order: carrier, tracking number, expected arrival, notes, quantities per item, and a packing list file. The quantity cannot exceed what is still outstanding. The ERP receives an inbound delivery; the buyer and inspectors are notified.
- **FR-SHIP-2 Lifecycle.** Shipped, then Arrived, then Approved or Rejected.
- **FR-SHIP-3 Arrival.** The inspector records the quantity actually received per item. A shortfall notifies the supplier to send the rest.
- **FR-SHIP-4 Quality checklist.** Four checks: packaging, specification, condition, documentation.
- **FR-SHIP-5 Approve.** Allowed only when all four checks pass. Stock is released in the app and the ERP. The PO becomes Delivered once every ordered line is fully received; until then the supplier is told what is still owed. Approving a replacement lifts the invoice hold.
- **FR-SHIP-6 Reject.** Requires a reason and at least one inspection photo. Goods go to **quarantine** in the ERP, the PO invoice is put **on hold**, and the supplier receives a notice listing the failed checks and the improvement required. The supplier then ships a replacement.
- **FR-SHIP-7 Quantity rule.** A shipment counts toward the committed quantity as shipped while open, and as received once Approved, so short deliveries can be topped up.
- **FR-SHIP-8 Files.** Packing lists (supplier) and photos (inspector) are stored and downloadable by authorised users.
- **FR-SHIP-9 Visibility.** Suppliers see their own shipments; buyers see shipments on their POs; inspectors and admins see all. The inspector's menu item is named **Receiving**.

### 6.9 Notifications and email (Delivered)
- **FR-NOT-1** Every notification is stored in-app (shown on dashboards) and emailed through Mailpit.
- **FR-NOT-2 Events.** New PO, PO approved, invited to quote, new quote received, quote deadline changed, quotes closing soon, quotes closed, requirement awarded or lost, chat message, supplier declined, shipment on its way, shipment arrival and shortfall, inspection approved, inspection rejected with improvement request.
- **FR-NOT-3 Emails page.** Each user sees only mail addressed to their login address (or, for suppliers, their company order address). The server re-checks the recipient on every message fetch. Mailpit itself (port 8025) shows everyone's mail and is for administrators and developers.

### 6.10 Dashboards (Delivered)
- **Buyer:** open orders, inventory count, low-stock count, supplier count, orders by status, spend by supplier, recent activity.
- **Supplier:** active orders, pending deliveries, notifications.
- **Inspector:** incoming, awaiting inspection, approved, rejected, notifications.
- **Admin:** users by role, supplier and item counts, requirements and orders by status, recent audit entries.

### 6.11 MCP and API access (Delivered)
See section 7.

### 6.12 Audit and history (Delivered)
- **FR-AUD-1** Every create, update, status change, award, ship, inspect, token and admin action is written to the audit log with user, entity, time and channel.
- **FR-AUD-2** The channel is `web` or `agent`. For agent actions the token name is recorded. History cards show an **AI agent** badge.

### 6.13 Mock ERP connectors (Delivered)
- **FR-ERP-1** One `ERPConnector` interface: push PO, inbound delivery, release stock, quarantine, invoice hold, list items and suppliers, reset.
- **FR-ERP-2** Mock SAP and Mock Infor LN implementations.
- **FR-ERP-3** Raw views are served under `/mock/sap/*` and `/mock/infor/*` (section 9.12).
- **FR-ERP-4** The **ERP Monitor** page shows what each ERP received: purchase orders, inbound deliveries, stock movements, invoice blocks and holds.
- **FR-ERP-5** Each requirement and PO records which ERP it belongs to.

### 6.14 Admin (Delivered)
- **FR-ADM-1** List all users, create users of any role (including Inspector), rename, reset a password, disable or enable. An admin cannot disable their own account.
- **FR-ADM-2** View every user's API tokens and revoke any of them.
- **FR-ADM-3** **Data & ERP** page: sync from SAP or Infor, and reset all business data (typed confirmation `RESET`), which reseeds demo data, clears Mailpit and uploads, and resets the ERP mocks.
- **FR-ADM-4** Admins can do everything a buyer can across all buyers.

---

## 7. MCP and AI-agent access

### 7.1 Goal
Let AI agents (for example Claude Desktop or Claude Code) read ERP data and draft work on a user's behalf, with no ability to approve, award or close anything.

### 7.2 Tools (Delivered)

| Tool | Purpose | Needs write scope |
|---|---|:---:|
| `get_inventory` | Stock for an item code | No |
| `search_supplier` | Find suppliers by name | No |
| `create_purchase_order` | Create a **Draft** PO (supplier, item, quantity, optional price) | Yes |
| `get_purchase_order` | One PO by number | No |
| `list_purchase_orders` | POs, optionally by status | No |
| `list_requirements` | Requirements, optionally by stage | No |
| `get_requirement` | One requirement with quotes by number | No |

Every tool is also an OpenAPI endpoint at `POST /api/mcp/<tool>`, with discovery at `GET /api/mcp/tools` and the schema at `/openapi.json`.

### 7.3 API tokens (Delivered)
- **FR-MCP-1** Buyers and admins create their own tokens on the **API access** page. The token acts as that user: the agent sees only that user's data.
- **FR-MCP-2** Scope **read** (look things up) or **write** (also create Draft POs). A read-only token is refused any write.
- **FR-MCP-3** Optional expiry (30, 90, 180, 365 days or never). Revoke at any time; admins can revoke anyone's.
- **FR-MCP-4** The secret (`erp_...`) is shown once and stored only as a SHA-256 hash. At most 10 active tokens per user. 120 requests per minute per credential.
- **FR-MCP-5** Tokens work only for `/mcp/` and `/api/mcp/*`. The normal REST API rejects them, so a leaked token can never approve, award, close or change users.
- **FR-MCP-6** A buyer login JWT also works on MCP; an optional shared `MCP_API_KEY` is still accepted but per-user tokens are preferred.
- **FR-MCP-7** Everything an agent does is audited with the token name and flagged as an **AI agent** action in history.
- **FR-MCP-8** The API access page shows ready-made setup snippets for Claude Desktop (via the `mcp-remote` bridge), Claude Code, and other MCP clients.
- **FR-MCP-9** `backend/scripts/mcp_check.py` verifies the server with a token or a login.

---

## 8. Business flow and statuses

### 8.1 End-to-end flow (Delivered up to step 7)
1. **Requirement**: buyer posts it (open to all or invited, files, SAP or Infor, quote deadline).
2. **RFQ**: suppliers quote, revise, withdraw or decline; buyer and supplier chat.
3. **Quotes closed**: the deadline passes; buyer is told how many quotes arrived.
4. **Award**: buyer accepts one quote; a Pending PO is created; other quotes are rejected.
5. **PO approval**: buyer approves; the PO is pushed to the ERP; the supplier is notified.
6. **Shipment**: supplier ships with a packing list; ERP receives an inbound delivery.
7. **Receiving**: inspector records arrival, checks quantity and quality, then approves (stock released) or rejects (quarantine, invoice hold, improvement request).
8. *Planned:* supplier accepts the PO before shipping; invoice, three-way match, payment (section 13).

### 8.2 Status lists

| Object | Values |
|---|---|
| Requirement (stored) | Open, Awarded, Cancelled |
| Requirement (shown stage) | Open, Quoted, Quotes closed, Awarded, In Transit, Delivered, Rejected, Closed, Cancelled |
| Quote | Submitted, Accepted, Rejected, Withdrawn |
| Purchase order | Draft, Pending, Approved, Closed |
| PO delivery | Not Shipped, In Transit, Delivered, Rejected |
| Shipment | Shipped, Arrived, Approved, Rejected |
| API token | active, expired, revoked |

---

## 9. REST API summary

Interactive documentation is at `/docs`. All `/api/*` routes need a JWT unless stated.

### 9.1 Authentication
`POST /api/auth/register` · `POST /api/auth/login` · `GET /api/auth/me`

### 9.2 Suppliers
`GET /api/suppliers` · `GET /api/suppliers/{id}` · `POST /api/suppliers` · `PUT /api/suppliers/{id}`

### 9.3 Requirements and quotes
`GET /api/requirements` · `POST /api/requirements` · `GET /api/requirements/{id}` · `PUT /api/requirements/{id}/quote` · `DELETE /api/requirements/{id}/quote` · `POST /api/requirements/{id}/award` · `POST /api/requirements/{id}/cancel` · `PUT /api/requirements/{id}/deadline` · `POST /api/requirements/{id}/open-to-all` · `POST /api/requirements/{id}/invite` · `POST /api/requirements/{id}/decline`

### 9.4 Chat
`GET /api/requirements/{id}/messages` · `POST /api/requirements/{id}/messages`

### 9.5 Files
`POST /api/requirements/{id}/attachments` · `GET /api/attachments/{id}/download` · `DELETE /api/attachments/{id}`

### 9.6 Purchase orders
`GET /api/purchase-orders` · `POST /api/purchase-orders` · `GET /api/purchase-orders/{id}` · `PUT /api/purchase-orders/{id}`

### 9.7 Inventory
`GET /api/inventory` · `POST /api/inventory` · `GET /api/inventory/{itemCode}` · `PUT /api/inventory/{itemCode}` · `DELETE /api/inventory/{itemCode}`

### 9.8 Shipments
`GET /api/shipments` · `GET /api/shipments/{id}` · `GET /api/purchase-orders/{id}/shipments` · `POST /api/purchase-orders/{id}/shipments` · `POST /api/shipments/{id}/files` · `GET /api/shipment-files/{id}/download` · `POST /api/shipments/{id}/arrival` · `POST /api/shipments/{id}/inspection`

### 9.9 Dashboard, notifications and emails
`GET /api/dashboard` · `GET /api/notifications` · `GET /api/emails` · `GET /api/emails/{id}`

### 9.10 API tokens
`GET /api/tokens` · `POST /api/tokens` · `DELETE /api/tokens/{id}` · `GET /api/admin/tokens` (admin)

### 9.11 Admin and ERP sync
`GET /api/admin/stats` · `GET /api/admin/users` · `POST /api/admin/users` · `PATCH /api/admin/users/{id}` · `POST /api/admin/reset` · `POST /api/erp/sync/{sap|infor}`

### 9.12 Mock ERP
- SAP: `GET /mock/sap/materials`, `/vendors`, `/purchase-orders`, `/inbound-deliveries`, `/stock-movements`, `/invoice-blocks`; `POST /mock/sap/purchase-orders`
- Infor LN: `GET /mock/infor/items`, `/suppliers`, `/orders`, `/receipts`, `/stock-movements`, `/invoice-holds`; `POST /mock/infor/orders`

### 9.13 MCP twins
`GET /api/mcp/tools` · `POST /api/mcp/{get_inventory | search_supplier | create_purchase_order | get_purchase_order | list_requirements | get_requirement | list_purchase_orders}`

---

## 10. Database design (SQLite)

| Table | Purpose and key columns |
|---|---|
| `users` | id, name, email (unique), password_hash, role (buyer, supplier, admin, inspector), supplier_id, active, created_at |
| `suppliers` | id, supplier_name, email, phone, address, source (sap or infor), created_at |
| `inventory` | id, item_code (unique), description, stock_quantity, warehouse, source, created_by, updated_at |
| `purchase_orders` | id, po_number, supplier_id, status, delivery_status, total_amount, erp, erp_reference, invoice_hold, invoice_hold_reason, created_via, created_by, created_at |
| `purchase_order_items` | id, po_id, item_code, quantity, unit_price |
| `requirements` | id, req_number, title, description, item_code, quantity, target_price, needed_by, status, po_id, erp, open_to_all, quote_deadline, deadline_reminded, deadline_closed_notified, created_via, created_by, created_at |
| `requirement_invites` | requirement_id, supplier_id, declined, decline_reason |
| `quotes` | requirement_id, supplier_id (unique pair), unit_price, lead_time_days, message, status |
| `messages` | requirement_id, supplier_id, sender_id, sender_role, body, read_at |
| `attachments` | requirement_id, filename, content_type, size, stored_name, uploaded_by |
| `shipments` | shipment_no, po_id, supplier_id, carrier, tracking_no, expected_arrival, status, erp_inbound_ref, erp_movement_ref, arrived_at/by, inspected_at/by, inspection_notes, rejection_reason, quality_checks, improvement_request |
| `shipment_items` | shipment_id, item_code, quantity_shipped, quantity_received |
| `shipment_files` | shipment_id, kind (packing_list or photo), filename, size, stored_name |
| `api_tokens` | user_id, name, token_hash, prefix, scope (read or write), expires_at, last_used_at, revoked_at |
| `notifications` | user_id or supplier_id, title, message, is_read, created_at |
| `audit_logs` | user_id, action, entity, entity_id, detail, channel, created_at |

Older databases are upgraded in place at start-up (added columns, and a table rebuild when the `users.role` constraint gained `inspector`).

---

## 11. Non-functional requirements

### 11.1 Security
- scrypt password hashing; JWT with expiry; role checks on every endpoint.
- Buyer data isolation; inspector cannot read private chat; suppliers cannot see requirements they were not invited to.
- API tokens stored as hashes, scoped, expiring, revocable, rate limited, and refused by the normal REST API.
- Uploads limited to 10 MB and a whitelist of file types.
- Input validation on every request body (Pydantic), including phone, email and item-code formats.
- Per-user email isolation enforced on the server.

### 11.2 Performance
API responses under 2 seconds and dashboard load under 3 seconds on the demo data set.

### 11.3 Scalability
Mock connectors can be replaced by real SAP S/4HANA or Infor LN connectors by implementing the `ERPConnector` interface, with no change to routers or services.

### 11.4 Quality
Automated backend test suite (pytest, 34 tests) covering flows, roles, isolation, deadlines, inspection, tokens and MCP.

---

## 12. Deployment

The environment starts with one command: `docker compose up --build`.

### 12.1 Services

| Service | Image or build | Purpose | Port |
|---|---|---|---|
| frontend | Next.js | Web portal | 3000 |
| backend | FastAPI | REST, mock ERP, MCP at `/mcp/` | 8000 |
| database | SQLite volume | Schema, seed data, persistent volume `erp_data` | internal |
| mailpit | axllent/mailpit | Email capture and inbox | 8025 |
| dbviewer | coleifer/sqlite-web | Browse the database | 8080 (localhost only) |

### 12.2 Configuration (environment variables)
`JWT_SECRET`, `JWT_EXPIRE_MINUTES`, `CORS_ORIGINS`, `MCP_API_KEY` (optional), `ERP_BACKEND` (sap or infor), `SEED_DEMO_DATA`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PUBLIC_API_URL`, `DEADLINE_CHECK_SECONDS`, `DBVIEWER_PASSWORD`. Defaults are in `.env.example`.

### 12.3 Acceptance criteria
- All containers start and report healthy.
- The frontend is reachable on port 3000 and talks to the backend.
- Data survives a container restart (named volume).
- Service logs are available through Docker Compose.
- A clean machine with Docker can reproduce the setup.

Demo logins use password `Password123!`: `buyer@demo.com`, `supplier@demo.com`, `inspector@demo.com`, `admin@demo.com`. See `README.md` for the walkthrough.

---

## 13. Planned (Phase 2, not yet built)

### 13.1 Supplier accepts the purchase order
After approval, the supplier accepts or declines. Shipping requires acceptance. If the supplier declines, the buyer chooses case by case: discuss in chat, cancel the PO (new status **Cancelled**), or reopen the RFQ with the declining supplier's quote withdrawn. New requirement stage **PO confirmed**.

### 13.2 Invoices, three-way match and payment
- Supplier submits an invoice against a PO with approved receipts (optional file).
- Match against PO and goods received: invoiced quantity not above received, unit price within 2 percent of the PO price. Differences are listed.
- An invoice on a PO with an invoice hold is **On hold**.
- Buyer or admin approves, overrides a mismatch with a reason, disputes or rejects, then records payment. Due date defaults to 30 days; Overdue is derived. Inspector is read-only.
- ERP: new connector methods to post the invoice and record payment, shown in the ERP Monitor.
- New requirement stages **Invoiced** and **Paid**.

### 13.3 Process tracker and dashboard tiles
A stepper on the requirement page (Listed, Quotes, Awarded, PO confirmed, Shipped, Delivered, Invoiced, Paid, Closed) and dashboard tiles for RFQs closing soon, POs awaiting supplier response, invoices to approve and overdue payments.

### 13.4 More MCP tools
Read-only `list_invoices` and `get_invoice`.

### 13.5 AI assistant
An in-app assistant using OpenAI GPT-4o that answers questions and drafts actions through the same services, asking for confirmation before any write. GPT-4o can also pre-fill shipment data from an uploaded packing list.

---

## 14. Success criteria

- Buyer, Supplier, Inspector and Admin can each log in and use only what their role allows.
- A requirement can be followed from posting to quotes, award, PO, shipment and inspection, with notifications and emails at each step.
- Buyers cannot see each other's requirements or orders.
- Rejected deliveries are quarantined, invoices are held and the supplier receives clear improvement instructions.
- SAP and Infor LN integrations are simulated and visible in the ERP Monitor.
- MCP tools work with a per-user token, and agent actions are flagged in the audit trail.
- Each user sees only their own email.
- The whole environment starts with `docker compose up --build` and data persists.
- Future-ready architecture for real SAP and Infor LN connectors and an AI Copilot.

*End of Software Requirements Specification*
