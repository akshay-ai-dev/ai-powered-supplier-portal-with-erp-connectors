"""FastMCP server. Mounted by main.py at /mcp (Streamable HTTP).

Auth: callers send `Authorization: Bearer <token>`: a per-user API token (erp_..., created under API access),
a buyer login JWT, or the optional shared MCP_API_KEY. See agent_auth.py.
"""

import contextvars

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.responses import JSONResponse

from .agent_auth import RATE_LIMIT, SERVICE_USER_EMAIL, rate_limited, resolve
from .db import get_conn
from .services import agent_tools
from .services.context import channel as channel_var
from .services.context import require_write
from .services.context import scope as scope_var
from .services.context import token_label as label_var
from .services.errors import DomainError

_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mcp_user_id", default=None
)

mcp = FastMCP(
    "ERP Copilot",
    instructions=(
        "Tools for procurement: inventory lookup, supplier search, requirements with supplier quotes, and purchase orders. "
        "Write tools only create Drafts; approving, awarding and closing stay with a human buyer. "
        "draft_award only proposes an award and saves nothing; the buyer confirms it in the app."
    ),
)


def _acting_user(conn) -> dict:
    uid = _current_user_id.get()
    row = (
        conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if uid
        else conn.execute("SELECT * FROM users WHERE email = ?", (SERVICE_USER_EMAIL,)).fetchone()
    )
    if row is None:
        raise ToolError("MCP service user is not provisioned")
    return dict(row)


def _run(fn, write: bool = False):
    try:
        if write:
            require_write()  # read-only tokens may look but not create
        with get_conn() as conn:
            return fn(conn)
    except DomainError as exc:
        raise ToolError(exc.message) from exc


@mcp.tool
def get_inventory(item_code: str) -> dict:
    """Get current stock for an item code, e.g. ITEM001."""
    return _run(lambda c: agent_tools.get_inventory(c, item_code, _acting_user(c)))


@mcp.tool
def search_supplier(supplier_name: str) -> list[dict]:
    """Search suppliers by (partial) name, email or address."""
    return _run(lambda c: agent_tools.search_supplier(c, supplier_name))


@mcp.tool
def create_purchase_order(
    supplier_id: int, item_code: str, quantity: int, unit_price: float | None = None
) -> dict:
    """Create a Draft purchase order for one item. Unit price defaults to the item's last known price. Needs a write-scope token."""
    return _run(
        lambda c: agent_tools.create_purchase_order(
            c, _acting_user(c), supplier_id, item_code, quantity, unit_price
        ),
        write=True,
    )


@mcp.tool
def get_purchase_order(po_number: str) -> dict:
    """Get a purchase order (with items and status) by PO number, e.g. PO1001."""
    return _run(lambda c: agent_tools.get_purchase_order(c, _acting_user(c), po_number))


@mcp.tool
def list_requirements(stage: str | None = None) -> list[dict]:
    """List the buyer's requirements (RFQs). Optional stage: Open, Quoted, Awarded, In Transit, Delivered, Closed, Cancelled."""
    return _run(lambda c: agent_tools.list_requirements(c, _acting_user(c), stage))


@mcp.tool
def get_requirement(req_number: str) -> dict:
    """Get one requirement (e.g. REQ2001) with all supplier quotes, for comparing offers."""
    return _run(lambda c: agent_tools.get_requirement(c, _acting_user(c), req_number))


@mcp.tool
def list_purchase_orders(status: str | None = None) -> list[dict]:
    """List the buyer's purchase orders. Optional status: Draft, Pending, Approved, Closed."""
    return _run(lambda c: agent_tools.list_purchase_orders(c, _acting_user(c), status))


@mcp.tool
def list_requests(status: str | None = None) -> list[dict]:
    """List the buyer's requests across both ERPs. Optional status (stage): Open, Quoted, Quotes closed, Awarded, In Transit, Delivered, Rejected, Closed, Cancelled."""
    return _run(lambda c: agent_tools.list_requests(c, _acting_user(c), status))


@mcp.tool
def get_request_detail(req_number: str) -> dict:
    """Get one request's full record (e.g. REQ2001): invitations, responses, message threads, history, shipments and inspection."""
    return _run(lambda c: agent_tools.get_request_detail(c, _acting_user(c), req_number))


@mcp.tool
def compare_responses(req_number: str) -> dict:
    """Rank a request's supplier responses (computed in code: lowest total price among suppliers meeting the need-by date, then earliest delivery)."""
    return _run(lambda c: agent_tools.compare_responses(c, _acting_user(c), req_number))


@mcp.tool
def draft_award(req_number: str) -> dict:
    """Propose awarding a request to its top-ranked supplier: returns the comparison table and the exact ERP call. Saves nothing."""
    return _run(lambda c: agent_tools.draft_award(c, _acting_user(c), req_number))


class MCPAuthMiddleware:
    """Pure ASGI middleware: authenticates the agent, applies the rate limit and records who is acting."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()
        raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        principal = resolve(raw)
        if principal is None:
            resp = JSONResponse(
                {"detail": "MCP requires a buyer API token (erp_...) or a buyer login token"},
                status_code=401,
            )
            return await resp(scope, receive, send)
        if rate_limited(principal.key):
            resp = JSONResponse(
                {"detail": f"Too many requests. Limit is {RATE_LIMIT} per minute."}, status_code=429
            )
            return await resp(scope, receive, send)
        resets = (
            (_current_user_id, _current_user_id.set(principal.user_id)),
            (channel_var, channel_var.set("mcp")),
            (scope_var, scope_var.set(principal.scope)),
            (label_var, label_var.set(principal.label)),
        )
        try:
            await self.app(scope, receive, send)
        finally:
            for var, tok in reversed(resets):
                var.reset(tok)


def build_mcp_app():
    """Returns (inner_http_app, auth_wrapped_app). The inner app's lifespan must be run by the parent app."""
    inner = mcp.http_app(path="/")
    return inner, MCPAuthMiddleware(inner)
