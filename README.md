# ERP Copilot Platform (Phase 1 MVP)

Next.js 15 frontend, FastAPI backend, SQLite, Mailpit, FastMCP, and mock SAP / Infor LN connectors. See `prd.md`.

## First-time setup

**Prerequisites:** Git, Docker Desktop (running; on Windows use the WSL 2 backend), Node.js 22+. About 2 GB free disk.

1. **Clone**
   ```bash
   git clone https://github.com/akshay-ai-dev/ai-powered-supplier-portal-with-erp-connectors.git
   cd ai-powered-supplier-portal-with-erp-connectors
   ```
2. **OpenAI key** (for the chat widget's ask box): copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
   Without it the ask box says the assistant is unavailable; the numbered menus still work.
3. **Free ports** 3000, 8000, 8025 and 8080 (stop any other Docker project using them).
4. **Build and start** (first build takes about 5 minutes)
   ```bash
   docker compose up --build -d
   docker compose ps    # all 5 services should be Up
   ```
5. **Open** http://localhost:3000 and log in (logins below). The database comes with two demo requests:
   REQ2001 (3 supplier quotes, ready to compare and award) and REQ2002 (no quotes yet).

**Later:** `git pull origin main && docker compose up --build -d` to update, `docker compose down` to stop.

| Service    | URL                                              |
|------------|--------------------------------------------------|
| Frontend   | http://localhost:3000                            |
| API docs   | http://localhost:8000/docs                       |
| MCP        | http://localhost:8000/mcp/                       |
| Mailpit    | http://localhost:8025 (shows every user's mail)  |
| DB viewer  | http://localhost:8080 (localhost only)           |

Demo logins (password `Password123!`): `buyer@demo.com`, `supplier@demo.com`, `admin@demo.com`, `inspector@demo.com`.
Copy `.env.example` to `.env` (in the project root, next to docker-compose.yml) to set the JWT secret, the optional `MCP_API_KEY`, `ADMIN_EMAIL`/`ADMIN_PASSWORD`, or the default ERP.

## Roles

| Role | Can do |
|---|---|
| Buyer | Post requirements (open to all or selected suppliers, with files), compare quotes, award, manage own POs, add/edit/delete own inventory items. Sees only their own requirements and POs. |
| Supplier | See invited or open requirements, quote or decline, message the buyer, ship approved orders with a packing list, see inspection results. |
| Inspector | Read-only view of every requirement, quote, PO, supplier and inventory item (not the private buyer-supplier chat). Receives shipments, checks quantity and a 4-point quality checklist, then approves or rejects. |
| Admin | Everything a buyer can, across all buyers, plus users, ERP sync and data reset. |

## The flow

1. **Requirement**: buyer posts it (choose SAP or Infor LN, attach drawings, open to all or invite suppliers).
2. **Conversation**: a private buyer-and-supplier thread per requirement, alive until delivery. Suppliers may decline with a reason.
3. **Award**: accepting a quote creates a PO for that supplier; the buyer approves it and it is pushed to the chosen ERP.
4. **Ship**: the supplier submits a shipment with a packing list. The ERP gets an inbound delivery and the inspector is notified.
5. **Receive**: the inspector records arrival, then decides.
   - **Quantity check**: received units are counted against what was shipped; a shortfall notifies the supplier to send the rest.
   - **Approve** (all four quality checks must pass): stock is released (in the app and in the mock ERP). The PO becomes Delivered once every ordered line is received; until then the supplier is told what is still owed.
   - **Reject** (reason and a photo required): goods go to quarantine in the ERP, the supplier invoice is put on hold, and the supplier gets a notice listing the failed checks and what to improve, then ships a replacement. Approving the replacement lifts the hold.
6. Watch the ERP side under **ERP Monitor** (POs, inbound deliveries, stock movements, invoice holds).

Everything is audited, and actions that arrived through an AI agent carry an **AI agent** badge.

## MCP / AI agents

The FastMCP server is at `/mcp/` (Streamable HTTP). 16 tools:
- **Read:** `list_requests`, `get_request_detail`, `compare_responses` (ranking computed in code), `get_erp_documents`
  (the mock SAP / Infor LN documents for a request's PO), `search_suppliers`, `get_inventory`, `get_purchase_order`,
  `list_purchase_orders`, `check_shipments`.
- **Drafts, which save nothing** and return the REST call that saves it, for a person to confirm in the app: `draft_award`,
  `draft_request`, `draft_po_approval`, `draft_quote`, `draft_arrival`, `draft_delivery_approval`.
- **Write:** `create_purchase_order` (Draft orders only). Approving, awarding and closing stay human-only.

The tools that existed before the chat widget used them also exist as OpenAPI endpoints under `POST /api/mcp/<tool>`
(schema at `/openapi.json`); `GET /api/mcp/tools` lists all 16.

**Authentication**: `Authorization: Bearer <token>`. Each buyer (or admin) creates their own token under **API access** in the app:
- the token acts as that user: the agent sees only that user's data, and the audit log names the token used;
- scope **read** (look things up) or **write** (also create Draft POs); optional expiry; revoke any time (admins can revoke anyone's);
- the secret is shown once and stored only as a hash; at most 10 active tokens per user; 120 requests/minute per credential;
- tokens work only for MCP and `/api/mcp/*`. The normal REST API rejects them, so a leaked token can never approve, award, close or change users.

A buyer login JWT (60 minutes) also works, and the optional shared `MCP_API_KEY` (acts as the "MCP Service" buyer) is still accepted, but per-user tokens are preferred.

**Check it works**

```
cd backend
.venv/Scripts/python scripts/mcp_check.py --email buyer@demo.com --password Password123!
.venv/Scripts/python scripts/mcp_check.py --token erp_xxxxx --write     # also creates a Draft PO (needs a write-scope token)
```

**Connect an agent**

- Claude Code: `claude mcp add --transport http erp http://localhost:8000/mcp/ --header "Authorization: Bearer <token>"`
- MCP Inspector (interactive): `npx @modelcontextprotocol/inspector`, choose Streamable HTTP, URL `http://localhost:8000/mcp/`, add the Authorization header.
- Clients that only speak stdio (for example Claude Desktop) can bridge with `npx mcp-remote http://localhost:8000/mcp/ --header "Authorization: Bearer <token>"`.
- Custom agents: any MCP SDK client works, for example `fastmcp.Client("http://localhost:8000/mcp/", auth="<token>")`.

## Chat assistant (every role)

The floating chat widget has numbered menus for each role and, on the menu screen, an ask box:
- `POST /api/assistant/chat` sends the question and the chat history (earlier questions and tool calls, never tool
  results) to GPT-4o (`OPENAI_MODEL`) with only the user's role's MCP tools. GPT-4o picks at most one tool and its
  parameters; the backend runs it as the user (`backend/app/ai/chat.py`).
  - Buyers: requests, comparisons, ERP documents, suppliers, stock; drafts a request, an award, a PO approval or a PO.
  - Suppliers: their orders and stock; drafts a quote.
  - Inspectors: latest requests, shipments, stock; drafts an arrival or a delivery approval.
- The widget shows the tool's result as it is; no LLM writes the answers. A question no tool fits gets a fixed help list.
- A draft is shown as a card with what would be saved and the exact REST call. Nothing is saved before the user clicks
  confirm, which calls the normal endpoint.

## Local dev (without Docker)

```
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest          # backend tests
.venv/Scripts/uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

## Architecture

`backend/app`: `routers/` (HTTP) -> `services/` (business rules, shared by REST and MCP) -> SQLite. `connectors/` holds the `ERPConnector`
interface (PO push, inbound delivery, stock release, quarantine, invoice hold) with mock SAP and Infor implementations; raw views are under
`/mock/sap/*` and `/mock/infor/*`. A real connector only needs to implement that interface.
The `database` container owns the SQLite volume (schema and seed data); uploads live in the same volume. Databases from earlier versions are
upgraded in place at start-up.
