# API reference: SAP MCP server (POC)

The APIs and tech-stack references this experiment depends on, gathered **before** building it.

---

## 1. Requirements (input)

**Task:** Find out whether SAP provides its own MCP servers (availability, requirements, integration options).
If native MCP support for business data is not available, build a small custom MCP server on SAP's APIs
and prove that it works.

### Functional requirements

- **FR1:** An AI client can discover and call SAP tools over MCP (stdio).
- **FR2:** `search_suppliers`: list or search suppliers by name.
- **FR3:** `get_supplier`: one supplier by ID, with purchasing/payment/posting block flags.
- **FR4:** `list_purchase_orders`: recent POs, optionally for one supplier.
- **FR5:** Read-only. No tool can create or change anything in SAP.
- **FR6:** The same code works on mock data, the SAP sandbox, or a real S/4HANA system (config only).
- **FR7:** `list_sap_apis` + `query_sap`: read other allow-listed S/4HANA APIs (requisitions, PO items, goods receipts, products, invoices) without a new function per API.
- **FR8:** Demo console: call each tool from a browser, and ask an AI (Gemini or Claude) in plain English with every tool call and SAP call shown.

### Non-functional requirements

- **Availability:** Depends on the SAP system being reachable. If it is down, tools return a clear error, not a crash.
- **Latency:** One OData GET per tool call. The sandbox answers in about 1–2 seconds.
- **Throughput:** Low (a few calls per AI answer). No published sandbox quota (see `FINDINGS.md` 6.2); a real system is limited by the customer's SAP.
- **Security:** API key or credentials only in `.env` (never committed); IDs are validated so nothing can be injected into OData filters.

### Configuration (`.env`, repo root)

| Variable | Used in mode | Purpose |
|---|---|---|
| `SAP_MODE` | all | `mock` (default), `sandbox` or `real` |
| `SAP_API_HUB_URL` | sandbox | `https://sandbox.api.sap.com` (already in `.env.example`) |
| `SAP_API_HUB_KEY` | sandbox | Personal key from api.sap.com → **Show API Key** |
| `SAP_BASE_URL` | real | e.g. `https://<host>/sap/opu/odata/sap` |
| `SAP_USERNAME` / `SAP_PASSWORD` | real | Technical user with read-only API access |
| `SAP_TIMEOUT_SECONDS` | sandbox, real | Default 20 |

---

## 2. Research: does SAP provide its own MCP servers?

| Offering | What it is | Business data (suppliers, POs)? | Requirements |
|---|---|---|---|
| CAP, Fiori, UI5, UI5 Web Components, MDK MCP servers | Open-source **developer tools** for building SAP apps | No | Free (npm) |
| BTP Administration / LeanIX MCP servers | Platform administration, enterprise architecture | No | BTP / LeanIX subscription |
| Joule | SAP's own AI assistant; uses MCP internally | Not open to third-party agents | SAP licence |
| **MCP Gateway in SAP Integration Suite** | Turns existing APIs / RFCs into MCP tools (auth, rate limits) | **Yes** | **Paid**: Integration Suite Premium or Enhanced edition (Premium list price USD 29,459/month), API Management + Integration Cell, a real S/4HANA system. Shipped Q2 2026 |

**Usage limits and pricing:** see `FINDINGS.md` section 6.

**Conclusion:** no free, ready-made SAP MCP server for business data, so this POC builds a custom read-only one
on SAP's standard S/4HANA OData APIs. The same tools could later sit behind the official gateway.

---

## 3. SAP APIs used

| Tool | SAP API (OData v2) | Entity |
|---|---|---|
| `search_suppliers`, `get_supplier` | `API_BUSINESS_PARTNER` (Business Partner A2X) | `A_Supplier` |
| `list_purchase_orders` | `API_PURCHASEORDER_PROCESS_SRV` (Purchase Order) | `A_PurchaseOrder` |
| `query_sap` (generic, allow-list in `SAP_APIS`) | `API_BUSINESS_PARTNER`, `API_PURCHASEORDER_PROCESS_SRV`, `API_PURCHASEREQ_PROCESS_SRV`, `API_MATERIAL_DOCUMENT_SRV`, `API_PRODUCT_SRV`, `API_SUPPLIERINVOICE_PROCESS_SRV` | `A_Supplier`, `A_BusinessPartner`, `A_PurchaseOrder(Item)`, `A_PurchaseRequisitionItem`, `A_MaterialDocumentHeader/Item`, `A_Product`, `A_SupplierInvoice` |

- Sandbox base URL: `https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap`
- Sandbox auth: header `APIKey: <key>` (free account on api.sap.com); data is SAP demo data, read-only.
- Real system: same paths on the customer's host, with a technical user set up by their SAP admin
  (communication arrangement, read-only roles).

## 4. References

- SAP Business Accelerator Hub: https://api.sap.com
- Business Partner API: https://api.sap.com/api/API_BUSINESS_PARTNER/overview
- Purchase Order API: https://api.sap.com/api/API_PURCHASEORDER_PROCESS_SRV/overview
- SAP Integration Suite pricing: https://www.sap.com/products/technology-platform/integration-suite/pricing.html
- Third-Party MCP Access to SAP Solutions (SAP Architecture Center): https://architecture.learning.sap.com/docs/ref-arch/137800
- MCP Gateway in SAP Integration Suite (SAP Community): https://community.sap.com/t5/technology-blog-posts-by-sap/mcp-gateway-in-sap-integration-suite-your-apis-ready-for-the-age-of-agents/ba-p/14438250
- Gemini API function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Gemini API pricing / free tier: https://ai.google.dev/gemini-api/docs/pricing
- Claude tool use: https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview
- MCP Python SDK v2 (FastMCP → MCPServer): https://py.sdk.modelcontextprotocol.io/v2/migration/
- Model Context Protocol: https://modelcontextprotocol.io

**Versions:** `mcp 2.2.0` and `httpx` (same as `backend/uv.lock`) for the MCP server and script; `google-genai` and `anthropic` only for the console's AI assistant tab. Installed inside a throwaway `python:3.12-slim` container, so nothing changes in the portal's dependencies.
