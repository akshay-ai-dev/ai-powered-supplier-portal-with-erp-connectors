# Slice 4 · Interface reference

Exact inputs and outputs of the seven MCP tools and the four HTTP endpoints the React screen uses. Types are JSON types. Dates are ISO `YYYY-MM-DD` strings. `null` is shown where a value can be absent. Integration responsibilities (authentication, roles, confirmation, ERP writes, idempotency, logging) are in [INTEGRATION.md](INTEGRATION.md).

The five read tools run immediately. The two draft tools **return proposals only**; nothing in this slice writes to the portal or an ERP.

## MCP tools

All tools return a JSON object. Unknown IDs return `{"found": false, "message": "No <kind> with ID <id> exists in the portal."}`.

### `list_requests`
| Input | Type | Required |
|---|---|---|
| `status` | string, e.g. `Open`, `Responses received`, `Locked`, `Awarded`, `Closed`, `Closed – rejected`, `Cancelled` | no |
| `erp` | `SAP` or `LN` | no |

Output: `today` (date), `count` (int), `requests[]`: `id`, `sourceErp`, `part`, `quantity` (int), `needByDate`, `responseDeadline`, `status`, `responseCount` (int), `shipmentIds` (string[]).

### `get_request_detail`
| Input | Type | Required |
|---|---|---|
| `record_id` | request ID (`REQ-0007`) or shipment ID (`SHP-0012`) | yes |

Output: `found: true`, `id`, `sourceErp`, `requisitionId`, `part`, `quantity`, `needByDate`, `responseDeadline`, `status`, `invitedSuppliers` (names), `responses[]`: `supplierId`, `supplierName`, `unitPrice` (number), `currency`, `promisedDate`, `status`, `supplierComment: {untrustedText, note}`; `award`: `null` or `{supplierId, supplierName, erpPoNumber, erpStatus}`; `shipments[]`: `id`, `requestId`, `shipDate`, `carrier`, `trackingNo`, `quantityShipped`, `status`, `erpDeliveryNumber`, `inspection: {quantityReceived, result, reasonCode|null, notes, erpReceiptNumber, erpDecisionRef, stockStatus, erpHoldRef|null}`.

Supplier comments are wrapped as `untrustedText` so the model treats them as data, never instructions.

### `compare_responses`
| Input | Type | Required |
|---|---|---|
| `request_id` | request or shipment ID | yes |

Output: `found`, `id`, `status`, `awardable` (bool), `awardBlockedReason` (string|null), `needByDate`, `quantity`, `rankingRule`, `rankingStatus` (`ranked` | `provisional_fx_ranking` | `ranked_converted` | `currency_review_required`), `rankingProvisional` (bool), `comparisonCurrency`, `exchangeRate` (`null` or `{baseCurrency, ratesToBase, approved, source, label}`), `message` (no responses, provisional or review note), `ranking[]`: `supplierId`, `supplierName`, `supplierStatus` (`active`/`blocked`), `unitPrice`, `currency`, `totalPrice` (original currency), `comparisonCurrency`, `exchangeRateToComparison`, `comparisonTotal` (total in the comparison currency; `null` when not ranked), `promisedDate`, `meetsNeedBy` (bool), `rank` (int, or `null` when `currency_review_required`).

Ranking rule (in code, `ranking.py`): lowest total price among offers meeting the need-by date, then earliest delivery; late offers after on-time ones. Offers in different currencies are compared by `comparisonTotal`, each total converted into the base currency (INR) with `PortalData.exchange_rates()`. In sample mode this is a **demo rate** (1 USD = 85 INR, `approved: false`, configurable with `DEMO_USD_INR_RATE`), so `rankingStatus` is `provisional_fx_ranking`. An approved rate from the backend gives `ranked_converted`. If a currency has no rate, `rankingStatus` is `currency_review_required`, every `rank` is `null` and no winner is chosen. Only a `Locked` request with responses is `awardable`.

### `get_erp_documents`
| Input | Type | Required |
|---|---|---|
| `request_id` | request or shipment ID | yes |

Output: `found`, `id`, `documents[]`: `type`, `number`, `erp`, optional `detail`.

### `search_suppliers`
| Input | Type | Required |
|---|---|---|
| `query` | name or ID fragment (default `""` = all) | no |
| `erp` | `SAP` / `LN` | no |
| `status` | `active` / `blocked` | no |

Output: `count`, `suppliers[]`: `id`, `sourceErp`, `name`, `status`.

### `draft_award` (draft only)
| Input | Type | Required |
|---|---|---|
| `request_id` | request ID | yes |
| `supplier_id` | supplier ID or exact name; omit to use the coded top recommendation | no |
| `justification` | buyer's reason (default `""`) | no |

Refusal: `{draft: false, requestId, requestStatus, message}` when the request is not `Locked`, has no responses, the supplier is blocked or did not respond, no active supplier meets the need-by date, or a currency has no exchange rate and no supplier was chosen.

Draft: `draft: true`, `status: "awaiting_buyer_confirmation"`, `requestId`, `awardTo: {supplierId, supplierName}`, `rank` (int|null), `isTopRanked`, `rankingStatus`, `rankingProvisional`, `exchangeRate`, `justificationRequired`, `justificationProvided` (string|null), `justificationMissing` (confirmation must be refused while `true`; filler such as "hi" or "test" does not count: at least 15 characters and 3 meaningful words), `justificationProblem` (why the reason was rejected, or null), `warnings[]` (includes the provisional-rate note), `comparison[]` (same rows as `ranking`), `erpCallOnConfirm: {erp, operation: "createPurchaseOrder", payload: {requisition, supplier, quantity, unitPrice, currency (the chosen offer's original currency; never converted), deliveryDate}, idempotencyKey: "award-<requestId>"}`, `note`.

`erpCallOnConfirm` is a **proposal** for the team's confirmation API; it is never executed here.

### `draft_request` (draft only)
| Input | Type | Required |
|---|---|---|
| `requisition_id` | ERP requisition number | yes |
| `supplier_ids` | string[] of supplier IDs or names | yes |
| `response_deadline` | date | yes |
| `notes` | string | no |

Output: `draft`, `status: "awaiting_buyer_confirmation"`, `fromRequisition: {id, sourceErp, part, quantity, needByDate, status}`, `invite[]: {supplierId, supplierName}`, `problems[]` (unknown, wrong-ERP or blocked suppliers), `responseDeadline`, `notes`, `note`. Refuses (`draft: false`) if the requisition is not `Available` or the date is malformed.

## HTTP endpoints (`web_app.py`)

| Method & path | Input | Output |
|---|---|---|
| `GET /api/status` | none | `{mode, dataSource, liveAIReady, model, erpWriteEnabled: false}` |
| `GET /api/requests` | none | `list_requests` output |
| `GET /api/requests/{id}` | path `id` | `get_request_detail` output |
| `GET /api/requests/{id}/comparison` | path `id` | `compare_responses` output |
| `POST /api/draft-award` | JSON `{request_id, supplier_id?, justification?}` | `draft_award` output |
| `POST /api/chat` | JSON `{prompt: string (1–1000 chars), history: object[]}` | see buyer chat |
| `POST /api/prefill` | multipart `file` (PDF/PNG/JPG/WEBP, ≤ 8 MB), optional `po_quantity` (int ≥ 0) | see packing-list pre-fill |
| `GET /` | none | built React app (`frontend/dist`) or 503 if not built |

There is **no** confirmation, PO-creation, shipment-creation or ERP-posting endpoint.

### Buyer chat (`POST /api/chat`)
Input: `prompt`, and `history` = the `messages` array returned by the previous reply (text turns only; max 12 kept).

Output: `answer` (string), `trace[]: {tool, arguments, ok}`, `drafts[]: {tool, result}` (only real drafts with `draft: true`), `messages[]` (send back as `history`), `grounding: {portalQuestion, outcome, unsupported[]}` where `outcome` is one of `answered`, `partial`, `no_portal_record`, `unsupported_values_withheld`, `web_claim_withheld`, `empty_answer`, `tool_limit`.

Errors: 503 when `OPENAI_API_KEY` is not set; 502 when the OpenAI call fails.

Grounding (in code, `grounding.py`): portal questions must call a tool first; only successful tool results with records count as evidence; IDs, document and tracking numbers, ISO dates, amounts, supplier names and statuses not found in the evidence or the buyer's text trigger one rewrite, then the answer is withheld. Draft tools are offered only for an explicit buyer request and may only use the request and suppliers the buyer named.

### Packing-list pre-fill (`POST /api/prefill`)
Output: `draft: true`, `file`, `fields: {shipDate, carrier, trackingNumber, quantity (int), lotNumbers (string[])}` (unreadable values are `null`), `unreadableFields[]`, `manualEntryRequired[]: {field, label, message}`, `poQuantity` (int|null), `poQuantitySource` (`manual_sample_input`|null), `poQuantityNote`, `quantityCheck: {status: match|mismatch|not_checked, message}`, `quantityMismatch` (bool), `aiPrefilled: true`, `modelId`, `note`.

The PO quantity is **typed in by hand** in this demo; it is not fetched from SAP, LN or a database. A mismatch is a review warning, not a rejection. The document is treated as untrusted data (the sample delivery note contains an injected instruction that extraction ignores). Nothing is created or posted.

Errors: 400 for wrong type, oversize file or negative quantity; 503 without an API key; 502 when extraction fails.
