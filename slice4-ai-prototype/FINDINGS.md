# How this AI demo works

1. The browser calls `web_app.py`. Every read goes through `mcp_server.py` to the `portal_data.PortalData` interface; in this demo that is `SampleData`, which reads `demo_data.py`.
2. `ranking.py` computes the offer order: lowest total price among on-time offers, then earliest delivery. The AI explains the result but never ranks. Offers in different currencies (INR and USD in the sample data) are ranked by their total converted to INR with a configurable demo exchange rate (1 USD = 85 INR). The ranking is marked provisional, the rate is shown beside the comparison, and each offer and the proposed PO keep their original currency. A currency with no rate is not ranked.
3. For a chat question, `assistant.py` sends the prompt and tool definitions to the OpenAI Responses API and runs the tools the model asks for. `grounding.py` then checks the answer in code:
   - A portal question must call a tool first. Only successful results that contain records count as evidence.
   - With no evidence, the reply is "I could not find … in the portal records".
   - IDs, document and tracking numbers, ISO dates, amounts, supplier names and statuses that are not in the evidence or the buyer's text trigger one rewrite, then the answer is withheld.
   - Claims of web search are replaced. There is no web-search tool.
   - Draft tools are offered only for an explicit buyer request, and may only use the request and suppliers the buyer named.
4. `draft_award` and `draft_request` return proposals only:
   - Awards require a `Locked` request and an active supplier.
   - A choice outside the top recommendation is flagged `justificationMissing` until a meaningful reason is given; filler such as "hi" or "test" is rejected.
   - There is no confirmation or ERP-posting endpoint.
5. A supplier document goes from the upload form to `prefill.py`, then to OpenAI for structured extraction. The document is untrusted data.
   - Unreadable fields are listed for manual entry.
   - The quantity is compared with a PO quantity typed in by hand as sample input; it is not fetched from SAP, LN or a database.
   - A difference is a review warning, not a rejection. Nothing is created or posted.
6. Tool calls are appended to `out/ai_tool_log.jsonl`. This is a local demo log, not the official ERP log.

**Current state:** runs independently on sample data. Test status for the latest run is in the handoff summary. Not connected: portal database, SAP / Infor LN connector core, authentication and roles, confirmation API, official ERP log. See [INTEGRATION.md](INTEGRATION.md).
