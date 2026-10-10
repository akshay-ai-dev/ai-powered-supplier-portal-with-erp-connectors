import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Draft extraction package (OpenAI PDF/image -> reviewable draft). Lives beside `app/` as
# backend/extraction_prefill/ and is wired in here; it creates no requirement, shipment, attachment
# or ERP record. One router for supplier shipment pre-fill, one for buyer New-requirement pre-fill.
from extraction_prefill.buyer_router import router as buyer_extraction_prefill_router
from extraction_prefill.router import router as extraction_prefill_router

from .config import settings
from .db import get_conn, init_db
from .mcp_server import build_mcp_app
from .routers import (
    admin,
    ai_tools,
    api,
    assistant,
    emails,
    erp_monitor,
    mock_erp,
    shipments,
    team,
    tokens,
    units,
)
from .seed import seed
from .services import requirements as req_svc
from .services.errors import DomainError

mcp_inner, mcp_asgi = build_mcp_app()


# App logs ("erp.*" loggers) go to the console, where Docker collects them (`docker compose logs -f backend`).
# DEBUG=true adds the debug lines, such as each chat question and GPT-4o's raw output (logger "erp.llm").
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger("erp").addHandler(_console)
logging.getLogger("erp").setLevel(logging.DEBUG if settings.debug else logging.INFO)

log = logging.getLogger("erp.deadlines")


def _run_deadlines() -> dict:
    with get_conn() as conn:
        return req_svc.process_deadlines(conn)


async def _deadline_loop(interval: int) -> None:
    """Checks quote deadlines every `interval` seconds. Runs in a worker thread so email sending never blocks requests."""
    while True:
        try:
            await asyncio.to_thread(_run_deadlines)
        except Exception:  # noqa: BLE001  a failed pass must never stop the loop
            log.exception("deadline check failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with get_conn() as conn:
        seed(conn)
    task = (
        asyncio.create_task(_deadline_loop(settings.deadline_check_seconds))
        if settings.deadline_check_seconds > 0
        else None
    )
    try:
        async with mcp_inner.lifespan(mcp_inner):
            yield
    finally:
        if task:
            task.cancel()


app = FastAPI(
    title="ERP Copilot Platform API",
    version="1.0.0",
    description="Procurement REST API, mock SAP / Infor LN connectors and OpenAPI-compatible MCP tools. "
    "The FastMCP server itself is mounted at /mcp.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.get("/health", tags=["System"])
def health():
    with get_conn() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


for r in (
    api.auth,
    api.suppliers,
    api.requirements,
    api.files,
    api.purchase_orders,
    api.inventory,
    api.misc,
    admin.router,
    admin.erp,
    emails.router,
    erp_monitor.router,
    shipments.router,
    units.router,
    team.router,
    tokens.router,
    assistant.router,
    ai_tools.router,
    extraction_prefill_router,
    buyer_extraction_prefill_router,
    mock_erp.sap,
    mock_erp.infor,
):
    app.include_router(r)

app.mount("/mcp", mcp_asgi)
