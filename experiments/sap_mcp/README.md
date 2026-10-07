# SAP MCP server (POC)

A custom, **read-only MCP server** that lets an AI read SAP S/4HANA data (suppliers, purchase orders, requisitions,
goods receipts, …) through SAP's standard OData APIs. Tested live against the **SAP Business Accelerator Hub sandbox**,
with Claude Desktop and with Gemini in a local demo console.

**Why custom:** SAP's own MCP servers are developer tools; the official route to business data (MCP Gateway in
SAP Integration Suite) needs a paid Premium/Enhanced edition. Details, limits and pricing: [FINDINGS.md](FINDINGS.md) §6.

```
AI (Claude / Gemini) ──MCP──▶ mcp_server.py (5 read-only tools) ──HTTPS GET, OData v2──▶ SAP S/4HANA
```

## Results

| Check | Result | Proof |
|---|---|---|
| SAP sandbox reachable with API key | HTTP 200, live suppliers | `Proof/01_sandbox_tryout_http200.png` |
| MCP client → server → SAP (`script.py`) | 3 tools, live data, 3/3 safety checks | `Proof/02_mcp_sandbox_output.txt` |
| Demo console, Tool explorer | Live POs, SAP 200 ≈ 1.7 s | `Proof/03_tool_explorer_purchase_orders.png` |
| Gemini answers from SAP via MCP | 1 tool call, correct answer | `Proof/04_ai_assistant_answer.png`, `Proof/05_ai_tool_call.png` |
| Claude Desktop answers from SAP via MCP | `search_suppliers`, SAP 200 | `Proof/07_claude_answer.png`, `Proof/08_docker_mcp_log.png` |
| Generic tool on more APIs (products, requisitions) | Live data, SAP 200 | `Proof/10_products_read.png`, `Proof/11_requisitions_read.png` |
| Write on the sandbox | Blocked, HTTP 405 (read-only) | `Proof/09_sandbox_write_blocked_405.png` |

## Files

| File | Purpose |
|---|---|
| `mcp_server.py` | MCP server: `search_suppliers`, `get_supplier`, `list_purchase_orders`, `list_sap_apis`, `query_sap` |
| `sap_client.py` | SAP OData client (GET only): modes `mock` / `sandbox` / `real`, validation, errors, timing |
| `script.py` | Proof script: acts as an MCP client, calls every tool, runs safety checks |
| `web_demo.py`, `web_demo.html` | Demo console at http://localhost:8765 (Tool explorer + AI assistant) |
| `ai_agent.py` | AI assistant loop: Gemini or Claude + the MCP tools (switch in `.env`) |
| `samples/` | Sandbox response captured for mock mode (`A_PurchaseOrder.json` is mock data) |
| `Proof/` | Screenshots and outputs |
| `FINDINGS.md` | Design, data flow, failure handling, limits, pricing, what we learned, spec fit |
| `API_REFERENCE.md` | Requirements, SAP MCP research, SAP APIs used, references |
| `SAP_INTEGRATION_ARCHITECTURE.md` | How the portal connects to SAP: integration points, test results, pricing, constraints |

## Quick start

1. Get a free API key on [api.sap.com](https://api.sap.com) (log on → any API → **Show API Key**).
2. Add to the repo-root `.env` (never commit it):
   ```
   SAP_MODE=sandbox
   SAP_API_HUB_URL=https://sandbox.api.sap.com
   SAP_API_HUB_KEY=<your key>
   # optional, for the AI assistant tab:
   AI_PROVIDER=gemini
   GEMINI_API_KEY=<your key>
   ```
3. From the repo root (Docker running):
   ```bash
   # proof script
   docker run --rm -v "$PWD":/repo -w /repo/experiments/sap_mcp python:3.12-slim \
     sh -c "pip install -q 'mcp==2.2.0' httpx && python script.py"

   # demo console → http://localhost:8765
   docker run --rm -p 8765:8765 -v "$PWD":/repo -w /repo/experiments/sap_mcp python:3.12-slim \
     sh -c "pip install -q 'mcp==2.2.0' httpx google-genai anthropic && python web_demo.py"
   ```
   No internet / no key: add `-e SAP_MODE=mock`. Claude Desktop setup: [FINDINGS.md](FINDINGS.md) §9.

## Safety and limits

- **Read-only:** only HTTP GET; no tool can create or change SAP data. Writes stay with the portal's REST API after a person confirms (spec §6).
- **Validated input:** IDs and OData filter/select/orderby are checked before calling SAP; max 20 rows per call.
- **Secrets:** SAP and AI keys only in `.env`; the AI never sees the SAP key or URLs.
- **Sandbox:** demo data, testing only, no published quota. A real customer needs one technical user from their SAP admin
  with the required APIs enabled; then set `SAP_MODE=real`, `SAP_BASE_URL`, `SAP_USERNAME`, `SAP_PASSWORD` (no code change).
- **Verified live:** suppliers, purchase orders, products and purchase requisitions. Not yet tested: goods receipts and supplier invoices.
- **Writes:** the sandbox is read-only (SAP returns HTTP 405); testing writes needs a real SAP system.

## Next steps

1. Confirm each extra API on the sandbox and keep the ones that answer.
2. Register these tools on the backend's FastMCP server (`/mcp`) and use `sap_client.py` as the real SAP connector.
3. Switch the console AI to Claude (`AI_PROVIDER=claude`) when the team API key is available.
