# AI-powered Supplier Portal with ERP Connectors

Prototype supplier portal that reads suppliers, parts and demand from SAP and Infor LN (mocked), runs a buyer-led sourcing, shipment and inspection workflow, and records every outcome back in the ERP.


## Slice 3 – Communication: Demo video

▶️ **Demo (≈3 min):** [Watch the demo] (https://srsconsultinc-my.sharepoint.com/:v:/g/personal/nagamani_ch_srsconsultinginc_com/IQBSLtcMjol7QpAb8M055JIYAT7t3TawPVy66s_ho6BOWGw?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJPbmVEcml2ZUZvckJ1c2luZXNzIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXciLCJyZWZlcnJhbFZpZXciOiJNeUZpbGVzTGlua0NvcHkifX0&e=z2c11m)

The demo shows starting the app with Docker Compose, the 20 passing tests, all 10 notification events
sent as email alerts to Mailpit, the notification bell, private buyer–supplier message threads with
attachments, the privacy and read-only rules, and the key design decisions.

Details: [`experiments/communication/FINDINGS.md`](experiments/communication/FINDINGS.md)

---

## Layout

```
backend/                 Python 3.12 · FastAPI · uv · ruff · pytest
  app/
    api/                 FastAPI routers (SRS §5.1)
    core/                connector core, canonical models, idempotency, ERP Log
    adapters/
      base.py            adapter interface (SRS §5.2)
      mock_sap/
      mock_ln/
    mcp/                 MCP server and tools (SRS §6.1)
    ai/                  assistant and packing-list pre-fill
    notifications/       in-portal notifications and email alerts
    db/                  SQLModel models, Alembic migrations
  seed/                  seed data, sample drawings, sample packing lists
  tests/
frontend/                React 18 · TypeScript · Vite · Tailwind CSS v4 · shadcn/ui
  src/
    api/                 generated TypeScript types and API client
    pages/               buyer, supplier, inspector, admin
    components/          shared components; ui/ holds shadcn/ui components
    lib/                 helpers (cn() for class names)
docs/decisions.md        decisions log
.env.example             copy to .env
package.json             root scripts: setup, dev, lint, test (cross-platform)
```

## Getting started

Works the same on Windows (PowerShell), macOS and Linux.

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 22+, and Docker Desktop (for Mailpit).

```bash
cp .env.example .env     # PowerShell: Copy-Item .env.example .env   — then set ANTHROPIC_API_KEY
npm run setup            # npm install (root + frontend) and uv sync (backend)
npm run dev              # backend :8000, frontend :5173, Mailpit UI :8025
```

| Command | What it does |
|---------|--------------|
| `npm test` | Backend tests (pytest) |
| `npm run lint` | ruff + ESLint |
| `npm run format` | Auto-format and auto-fix backend code with ruff |
| `npm run gen:api` | Regenerate TypeScript types from the running API's OpenAPI spec |
| `npx shadcn@latest add button` | Add a shadcn/ui component (run in `frontend/`) |
