# Integration guide · AI slice 4 → team backend

For Akshay and the backend/frontend team. This slice runs on its own in **sample-data mode**. Nothing here is connected to the portal database, the SAP or Infor LN connectors, authentication, or the confirmation API. Those are team integration work. Exact inputs and outputs are in [API_REFERENCE.md](API_REFERENCE.md).

## 1. What plugs in where

```
React screen ──HTTP──► web_app.py (FastAPI) ──► mcp_server.py (7 tools) ──► portal_data.PortalData
                            │                        ▲                          │
                            ├─► assistant.py ────────┘  (OpenAI tool calls)     ├─ SampleData → demo_data.py   (this demo)
                            │     └─ grounding.py                               └─ team implementation         (to build)
                            └─► prefill.py (OpenAI PDF/image extraction)
```

- **`portal_data.py`** is the only data boundary. `mcp_server.py`, `ranking.py` and `grounding.py` read portal data only through `portal_data()`. Only `SampleData` reads `demo_data.py`.
- The interface is **read-only**. It has no create, update or post methods.
- `PORTAL_DATA_SOURCE` defaults to `sample`. Any other value fails at startup with a clear error until a real implementation is registered.

### Methods the team implementation must provide

Return plain dicts in the shapes below (the sample records in `demo_data.py` are complete examples). Return copies; callers must not be able to change stored data.

| Method | Returns | Likely source (to be confirmed by the team) |
|---|---|---|
| `today()` | business date `YYYY-MM-DD` | server clock / portal setting |
| `list_requests()` | request dicts visible to the current user | portal DB |
| `get_request(request_id)` | request dict or `None` | portal DB |
| `get_shipment(shipment_id)` | shipment dict incl. `inspection`, or `None` | portal DB |
| `get_erp_documents(request_id)` | `[{type, number, erp, detail?}]` | connector core reads (SAP / LN) |
| `list_suppliers()` | `[{id, sourceErp, name, status: active|blocked}]` | portal DB / ERP business partners |
| `list_requisitions()` | `[{id, sourceErp, part, quantity, needByDate, status}]` | connector core reads |
| `exchange_rates()` | `{baseCurrency, ratesToBase: {currency: rate}, approved, source, label}` or `None` | approved treasury / ERP rate table |

**Request dict:** `id`, `sourceErp` (`SAP`/`LN`), `requisitionId`, `part`, `quantity`, `needByDate`, `responseDeadline`, `status`, `invited` (supplier IDs), `responses[]` (`supplierId`, `unitPrice`, `currency`, `promisedDate`, `comment`, `status`), `award` (`null` or `{supplierId, erpPoNumber, erpStatus}`), `shipments` (shipment IDs).

**Shipment dict:** `id`, `requestId`, `shipDate`, `carrier`, `trackingNo`, `quantityShipped`, `status`, `erpDeliveryNumber`, `inspection` (`quantityReceived`, `result`, `reasonCode`, `notes`, `erpReceiptNumber`, `erpDecisionRef`, `stockStatus`, `erpHoldRef`).

### Registering it

```python
# in the team backend's startup, before serving requests
import portal_data
portal_data.set_portal_data(TeamPortalData(db_session_factory, connector_client))  # team code
```

`test_portal_data.py` shows a minimal in-memory implementation that all seven tools accept. It is a test double, not a proposed backend API. If the status names differ from the sample ones, also update `AWARDABLE_STATUS` in `mcp_server.py` and `STATUS_VALUES` in `grounding.py`.

## 2. Who handles what

| Concern | This slice does | Team backend must do |
|---|---|---|
| **Authentication** | Nothing. All endpoints are open on `127.0.0.1`. | Put `/api/chat`, `/api/draft-award`, `/api/prefill` and the read endpoints behind portal login. |
| **Role checks** | Nothing. | Buyer-only: chat, comparisons, award draft. Supplier-only: pre-fill, and only for the supplier's own POs. `list_requests` etc. must return only records the user may see. Apply this inside the `PortalData` implementation too. |
| **Buyer confirmation** | Returns drafts with `status: awaiting_buyer_confirmation`. No confirm endpoint. | Build an explicit confirmation API. On confirm, **re-check server-side**: request still `Locked`, supplier still `active`, same currency rule, `justificationMissing` is false, response deadline and payload unchanged. Never trust the draft JSON sent back from the browser or the model. |
| **ERP writes** | None. `erpCallOnConfirm` is only a proposal. There is no posting endpoint and no write method on `PortalData`. | Only the confirmation API calls the connector core (`createPurchaseOrder` for awards; shipment posting after supplier submission). |
| **Idempotency** | Suggests `idempotencyKey: award-<requestId>` in the draft. | The posting layer owns the real key and deduplication (retries, double clicks, two buyers). |
| **ERP logging / audit** | Appends a local demo log `out/ai_tool_log.jsonl` (prompt, tool, arguments, result). It is **not** the official ERP log. | Write the official ERP log and audit trail for every confirmation and connector call, including user, role, timestamp and model ID for AI-assisted drafts. Decide whether prompts may be stored, then replace or disable the local JSONL log. |
| **Chat history** | Client sends `history` back each turn. | Keep conversation state server-side per user session, or re-validate it; the client can edit it. |
| **Secrets** | Reads `OPENAI_API_KEY` from `.env` (ignored by Git). | Use the team's secret store. Never ship `.env`. |
| **Pre-fill PO quantity** | Typed by hand as sample input. | Look up the PO quantity from the supplier's own PO via the connector, server-side. Keep mismatch as a review warning. Posting happens only after supplier submission through the team's shipment API. |

## 3. What must stay true after integration

- The AI never writes. Keep draft tools draft-only and keep ERP calls behind human confirmation.
- Tool names and response shapes stay the same, so `assistant.py`, `grounding.py` and the React screen keep working.
- Ranking stays in code (`ranking.py`). Mixed-currency offers are compared in the base currency using `exchange_rates()`. The sample source returns a demo rate with `approved: false`, so the ranking is labelled provisional. The team implementation should return the approved rate with `approved: true`; with `None` or a missing currency, offers are not ranked.
- Supplier comments and uploaded documents stay untrusted data.
- Re-run `uv run python script.py check`, `npm run build` and the live prompts (`uv run python script.py test`) against the connected backend.

## 4. Frontend

`frontend/` is React 18 + TypeScript (Vite). `src/api.ts` holds the response types used by `src/App.tsx`. To embed the screens in the main portal app, reuse those types and components and point `api()` at the team's authenticated routes. The dev server proxies `/api` to `127.0.0.1:8008`.
