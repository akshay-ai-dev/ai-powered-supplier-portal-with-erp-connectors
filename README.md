# ERP Copilot Platform (Phase 1 MVP)

Next.js 15 frontend, FastAPI backend, SQLite, Mailpit, FastMCP, and mock SAP / Infor LN connectors. See `prd.md`.

## Run

```
docker compose up --build
```

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

The FastMCP server is at `/mcp/` (Streamable HTTP). Tools: `get_inventory`, `search_supplier`, `create_purchase_order` (Draft only),
`get_purchase_order`, `list_requirements`, `get_requirement`, `list_purchase_orders`, and the buyer-assistant tools (SRS §6.1)
`list_requests`, `get_request_detail`, `compare_responses` (ranking computed in code) and `draft_award` (saves nothing).
Approving, awarding and closing stay human-only.
The same tools exist as OpenAPI endpoints under `POST /api/mcp/<tool>` (schema at `/openapi.json`, discovery at `GET /api/mcp/tools`).

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

## AI Assistant (buyers)

**AI Assistant** in the buyer menu answers four kinds of questions: list requests, show one request, compare responses,
and draft an award. Everything runs in the browser:
- A semantic router (all-MiniLM-L6-v2 in a Web Worker) picks the tool. Its example phrasings are in
  `frontend/src/lib/router/routes.json`; after editing them, run `npm run build:centroids`.
- The page calls that tool's `POST /api/mcp/<tool>` and shows the result in a fixed template. No LLM writes the answers.
- **Confirm award** calls the normal award endpoint. Nothing is saved before that click.
- The mic button transcribes speech with Moonshine (English). The ~385 MB model loads on the first press.

**Models (once, before `docker compose up --build`).** They are served from `frontend/public/models/`, which is
gitignored, and never fetched from Hugging Face or a CDN at runtime:

```
cd frontend && npm run fetch:models
```

Moonshine is copied from `experiments/moonshine_browser_stt/models/` when present; otherwise it is downloaded and
re-saved, which needs `uv`. To serve the models from file storage later, set `NEXT_PUBLIC_MODELS_URL`.

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
