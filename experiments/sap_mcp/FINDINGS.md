# Findings: custom SAP MCP server (POC)

**Feature:** An AI assistant (Claude Desktop, Gemini or Claude in the demo console, later the portal assistant) can read SAP
S/4HANA data through five read-only MCP tools: 3 business tools (suppliers, purchase orders) plus a generic, allow-listed
`query_sap`. The server calls SAP's standard OData APIs and returns short, clean results. Nothing is ever written to SAP.

---

## 1. High-level diagram

```
 [AI model] Gemini / Claude ──picks a tool──┐
 [AI client] Claude Desktop · console · script.py ──MCP over stdio──▶ [mcp_server.py]   5 tools, read-only
                                               │  validate input (IDs, top ≤ 20)
                                               ▼
                                         [sap_client.py]  ──HTTPS GET (OData v2, JSON)──▶ [SAP S/4HANA]
                                          mode from .env:                                  sandbox: api.sap.com (demo data)
                                          mock | sandbox | real                            real: customer's system
                                               │
                                               ◀── ~50 raw fields per record
                                               ▼
                                         keep ~8 useful fields, convert /Date()/ → ISO date
                                               ▼
 [AI client] ◀── JSON result: found / count / data / source
```

## 2. Data movement

| Stage | From → To | What data | How |
|---|---|---|---|
| In | User → console → AI model | Question; tool definitions | HTTPS (Gemini / Claude API), JSON |
| In | AI client → MCP server | Tool name + arguments | MCP (JSON-RPC over stdio) |
| Through | MCP server → SAP | OData query (`$top`, `$filter`, `$select`) | HTTPS GET, `APIKey` header (sandbox) or basic auth (real) |
| Out | SAP → MCP server | Supplier / PO records | OData v2 JSON (gzip) |
| Out | MCP server → AI client | Cleaned result | MCP tool result (JSON) |
| Out | AI model → user | Plain-English answer + list of tool calls | HTTPS, rendered in the console |

## 3. Data storage

| Stage | Stored in | What | How long |
|---|---|---|---|
| Tool call | RAM | Request and response | One call |
| Mock mode | Disk (`samples/*.json`) | Supplier sample captured from the sandbox; PO sample is mock | In repo |
| Secrets | `.env` (not committed) | `SAP_API_HUB_KEY` / SAP user, `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | Local only |
| AI provider | Google / Anthropic (external) | Question, tool results sent per AI call | Per the provider's API data policy |

Nothing from SAP is saved by our code. Every call reads live data. The AI never receives the SAP key or URLs.

## 4. Data transformation

| Step | Input | Operation | Output |
|---|---|---|---|
| 1 | Tool arguments | Validate ID (letters/digits only), cap `top` at 20, escape text | Safe OData query |
| 2 | Raw SAP record (~50 fields) | Select ~8 business fields, rename to camelCase | Short record |
| 3 | `/Date(1540771200000)/` | Convert epoch ms → ISO date | `2018-10-29` |
| 4 | PO status code (`05`) | Map to text | `Released` |

## 5. Non-functional questions

- **Availability:** Needs the SAP system. If it is down, slow or the key is wrong, the tool returns `found: false` with a clear `error`; the AI can say so.
- **Latency:** One GET per tool call (about 1–2 s on the sandbox).
- **Throughput:** Low (a few calls per AI answer). See section 6 for sandbox limits.
- **Reliability:**

| Failure | Detected by | Handled |
|---|---|---|
| Wrong or missing API key | HTTP 401 / empty `SAP_API_HUB_KEY` | Clear error message |
| SAP down / timeout | httpx exception | Clear error after 20 s |
| Rate limit hit | HTTP 429 (+ `Retry-After`) | Clear error "try again in N seconds"; rate-limit headers are logged |
| Unknown supplier ID | HTTP 404 / no rows | `found: false`, nothing invented |
| Injection attempt in an ID | Regex check (letters, digits, `_`, `-` only) | Rejected before calling SAP |
| AI asks for huge lists | `top` > 20 | Capped at 20 |

## 6. Usage limits, pricing and what is needed

### 6.1 Three ways to connect an AI to SAP data

| | **This POC: custom MCP + SAP sandbox** | **Custom MCP + customer's own S/4HANA** | **SAP official: MCP Gateway in Integration Suite** |
|---|---|---|---|
| Data | SAP demo data (read-only) | The customer's real data | The customer's real data |
| What is needed | Free account on api.sap.com + API key | Customer's SAP URL + a technical user (communication arrangement, read-only roles) created by their SAP admin | BTP account, Integration Suite (**Premium or Enhanced edition**) with API Management + Integration Cell, a real SAP system |
| Licence / cost | **Free** | Customer already pays for S/4HANA; API access is part of it. Hosting our server is our cost | Integration Suite subscription (list prices below) on top of S/4HANA |
| Who builds the tools | Us (5 tools; a new API = one line in `SAP_APIS`) | Us (same code, `.env` change only) | Configured from existing API artifacts / RFCs, no code |
| Status | Working (this experiment) | Same code, untested without a customer system | Available from SAP; check SAP Note 2903776 for plan availability |
| Allowed for production | **No** (testing only) | Yes, if it follows the SAP API Policy | Yes |

### 6.2 Usage limits

| Item | Limit | Source |
|---|---|---|
| Sandbox calls | **No published quota.** SAP does not document a number; the sandbox is for evaluation only, not productive use. No rate-limit headers were returned in our tests (all calls HTTP 200 or 404). | Observed; `sap_client.py` logs any `*RateLimit*` / `Retry-After` header and handles 429 |
| Sandbox data | Read-only demo data shared by all users; it can change at any time | Observed |
| Sandbox key | One personal key per api.sap.com account; must stay secret (`.env` only) | api.sap.com |
| Our server | Max 20 records per call (`top` capped), 20 s timeout | `mcp_server.py`, `sap_client.py` |
| Real S/4HANA | Set by the customer's system and SAP API Policy; third-party MCP servers must follow the policy and enforce auth on every call | SAP Architecture Center "Third-Party MCP Access to SAP Solutions" |

### 6.3 Pricing (SAP list prices from sap.com; contracts 3–36 months)

| Product | Price |
|---|---|
| SAP Business Accelerator Hub sandbox | **Free** (what this POC uses) |
| Integration Suite, Starter Edition | USD 1,735 / month (50,000 messages/month, 10 custom flows) |
| Integration Suite, Standard Edition | USD 5,361 / month |
| Integration Suite, Premium Edition (includes MCP Gateway) | USD 29,459 / month (10 million messages/month) |
| Additional messages | USD 7.03 / month per 10,000 |
| S/4HANA Cloud (the ERP itself) | Quote only (contact SAP); paid by the customer, not by us |
| AI model for the assistant tab | Gemini API: free tier available (rate-limited) for testing. Claude API: pay per token (prepaid credits), matches the portal spec. Switch with `AI_PROVIDER` in `.env` |

The BTP trial / free service plan can be used to evaluate the MCP Gateway, but not for production.

### 6.4 Recommendation

For the prototype: keep this custom read-only MCP server (free, works today). For a customer going live: either run
the same server against their S/4HANA with a technical user, or, if they already license Integration Suite Premium/Enhanced,
expose the same APIs through SAP's MCP Gateway for SAP-managed auth, rate limits and monitoring.

**Note (SAP API Policy, April 2026):** an AI calling SAP live is fine for sandbox testing. For a real customer, SAP only allows AI agents to call SAP APIs through SAP-approved routes such as the MCP Gateway, so the portal's AI should read the portal's own synced data instead. Details: `SAP_INTEGRATION_ARCHITECTURE.md`.

---

## 7. Validation

- [x] SAP sandbox Supplier API tested on api.sap.com (Try Out): HTTP 200, 3 suppliers (`Proof/01_sandbox_tryout_http200.png`)
- [x] Same call from code with the API key (curl): data returned
- [x] MCP client lists the tools and calls each one over stdio (`script.py`, mock and sandbox mode)
- [x] Safety checks: unknown ID → not found, injection rejected, `top` capped (3/3 pass)
- [x] `script.py` in **sandbox** mode on live SAP data: all 3 tools return live data (suppliers + purchase orders, HTTP 200), unknown ID → SAP 404 → `found: false`, 3/3 checks pass (`Proof/02_mcp_sandbox_output.txt`)
- [x] **Real AI end to end:** Claude Desktop connected to this MCP server (config below), asked "Using the SAP tools, show me 5 suppliers", called `search_suppliers`, the server called the SAP sandbox (HTTP 200 in 869 ms) and Claude answered with the 5 suppliers and their block status (`Proof/07_claude_answer.png`, `Proof/08_docker_mcp_log.png`)
- [x] **AI assistant tab, live Gemini** (`ai_agent.py`): "Show the latest 10 purchase orders and tell me which supplier has the most" → Gemini called `list_purchase_orders(top=10)` once (SAP 200, 1754 ms) and answered correctly (USSU_V8000, 4 POs) (`Proof/04_ai_assistant_answer.png`, `Proof/05_ai_tool_call.png`)
- [x] Gemini busy/retired models handled: retry on 503/429, skip 404, fall back to available models (tested with a simulated API)
- [x] `list_sap_apis` + `query_sap` (generic tool): allow-list, enum dropdown, filter/select/orderby validation and injection checks (mock mode)
- [x] `query_sap` live on extra APIs: **products** (HTTP 200, 5 records, ~0.7 s) and **purchase requisitions** (HTTP 200, 5 records, ~0.6 s) (`Proof/10_products_read.png`, `Proof/11_requisitions_read.png`)
- [x] Write on the sandbox: blocked by SAP with HTTP 405 *"only supported for GET operations"*, so the sandbox is read-only (`Proof/09_sandbox_write_blocked_405.png`)
- [ ] `query_sap` live on goods receipts and supplier invoices: not tested yet
- [x] Localhost demo console (`web_demo.py` + `web_demo.html`, http://localhost:8765): run each tool from the browser and see status, record count, SAP response time, the MCP request, the real SAP calls (endpoint, HTTP status, time) and the MCP result (`Proof/03_tool_explorer_purchase_orders.png`, `Proof/06_console_terminal.png`)

## 8. What we learned

- SAP's official MCP servers are developer tools; business data needs the paid **Integration Suite MCP Gateway**. A custom server is the practical route for a POC.
- The sandbox needs only a free api.sap.com account and the `APIKey` header. It is read-only demo data, which is exactly what a POC needs.
- Both APIs used (Business Partner and Purchase Order) answer on the sandbox with the same API key.
- Supplier IDs are not always numeric (e.g. `USSU_V8000`), so ID validation allows letters, digits, `_` and `-`.
- The sandbox gzips responses (`curl` needs `--compressed`; httpx handles it automatically).
- SAP returns about 50 fields per supplier. Selecting a few fields keeps the AI's context small and answers accurate.
- MCP stdio: logs must go to stderr, because stdout carries the protocol.
- Gemini can answer `503 UNAVAILABLE` ("high demand") or `429` (free-tier quota). `ai_agent.py` retries and then falls back to `GEMINI_FALLBACK_MODELS` (optional) and then to the flash models Google lists as available for the key. Older models (e.g. `gemini-2.5-flash`) return `404` for new API keys, so they are skipped automatically; if every model is busy the page says "Gemini is overloaded, try again in a minute"; the answer shows which model replied.
- **Not limited to 3 tools:** besides the 3 business tools, `list_sap_apis` + `query_sap` read any allow-listed S/4HANA API (suppliers, business partners, PO headers/items, purchase requisitions, goods receipts, products, supplier invoices) with OData filter/select/orderby, still GET-only, validated and capped at 20 rows. Adding an API = one line in `SAP_APIS`. The console dropdown and the AI pick up new tools automatically.
- **Model-agnostic:** the same MCP tools work with Gemini and Claude (and Claude Desktop) with no change to the server; only `.env` picks the model.
- mcp 2.x: tool results are in `structured_content` (v1 tutorials use `structuredContent`).
- **Fits the main repo:** the backend already has a FastMCP server at `/mcp` (`backend/app/mcp_server.py`) and a *mock* SAP connector (`backend/app/connectors/sap.py`). `sap_client.py` is the missing *real* SAP connector, and the 3 tools are plain functions that can be registered on that server.
- **Moving to a real customer:** change `SAP_MODE=real` and the URL/user in `.env`. No code change. The customer's SAP admin must create a technical user with read-only API access.

## 9. How to run

From the repo root, with `SAP_MODE`, `SAP_API_HUB_URL` and `SAP_API_HUB_KEY` in `.env`.
Self-contained: a throwaway Python container, so it does not touch the portal's own containers or dependencies.

```bash
docker run --rm -v "$PWD":/repo -w /repo/experiments/sap_mcp python:3.12-slim \
  sh -c "pip install -q --root-user-action=ignore 'mcp==2.2.0' httpx && python script.py"
```

Without Docker (Python 3.12 + `pip install "mcp==2.2.0" httpx`): `python experiments/sap_mcp/script.py`

Run the server alone for an MCP client (e.g. Claude Desktop, MCP Inspector):
`python experiments/sap_mcp/mcp_server.py`

**Localhost demo page** (http://localhost:8765, Ctrl+C to stop):

```bash
docker run --rm -p 8765:8765 -v "$PWD":/repo -w /repo/experiments/sap_mcp python:3.12-slim \
  sh -c "pip install -q --root-user-action=ignore 'mcp==2.2.0' httpx google-genai anthropic && python web_demo.py"
```

Backup without internet: add `-e SAP_MODE=mock` to either command.

**Connect a real AI (Claude Desktop):** Settings → Developer → Edit Config, add (adjust the paths), restart Claude, then ask
"Using the SAP tools, show me 5 suppliers":

```json
"mcpServers": {
  "sap-s4hana": {
    "command": "/Users/<you>/.docker/bin/docker",
    "args": ["run", "-i", "--rm",
      "-v", "/Users/<you>/Projects/<repo>:/repo",
      "-w", "/repo/experiments/sap_mcp", "python:3.12-slim",
      "sh", "-c", "pip install -q --root-user-action=ignore 'mcp==2.2.0' httpx >&2 && python mcp_server.py"]
  }
}
```

Use the full path to `docker` (desktop apps do not see the shell PATH). pip output goes to stderr (`>&2`) so stdout stays clean for MCP.

**AI assistant tab:** add to `.env` (never commit keys):

```
AI_PROVIDER=gemini            # or claude
GEMINI_API_KEY=...            # aistudio.google.com -> Get API key
GEMINI_MODEL=gemini-3.8-flash # optional (default)
# ANTHROPIC_API_KEY=...       # when AI_PROVIDER=claude (CLAUDE_MODEL from .env)
```

The console command then installs the AI SDKs too:
`pip install -q 'mcp==2.2.0' httpx google-genai anthropic && python web_demo.py`

## 10. Fit with the build specification (§5.4 adapter map, §6.1 assistant tools)

**§5.4 says vendor MCP servers (SAP Integration Suite, Infor ION) are optional later adapters.** This experiment confirms
the SAP one needs a paid Integration Suite edition, and shows a free custom server works on the same S/4HANA APIs.

How our read tools cover the spec's S/4HANA adapter calls:

| Spec adapter call | S/4HANA API (spec) | Covered here | Notes |
|---|---|---|---|
| listSuppliers | API_BUSINESS_PARTNER | ✅ `search_suppliers`, `get_supplier` | Tested live |
| listOpenRequisitions | Purchase requisition API | ✅ `query_sap(api="purchase_requisitions")` | Read only |
| createPurchaseOrder | Purchase order API | ❌ write, out of scope | Reading POs: ✅ `list_purchase_orders`, `query_sap(api="purchase_order_items")` |
| createInboundDelivery | Inbound delivery API | ❌ write, out of scope | |
| postGoodsReceipt | Material document API | ❌ write, out of scope | Reading goods receipts: ✅ `query_sap(api="goods_receipts")` |
| postQualityDecision | Inspection lot usage decision | ❌ write, out of scope | |

**§6.1 buyer-assistant tools** (`list_requests`, `get_request_detail`, `compare_responses`, `get_erp_documents`,
`search_suppliers`, `draft_award`, `draft_request`) work on **portal** data (requests, responses, awards) and belong to the
AI slice. They are not duplicated here. Where they need SAP data, they can call this server's tools:
`search_suppliers` (same name) and `get_erp_documents` (PO and goods receipt look-ups via `list_purchase_orders` / `query_sap`).
Writes stay out of MCP, as the spec requires: the AI returns a draft, a person confirms, and the REST API posts to the ERP.
