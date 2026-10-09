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
        "Tools for procurement: inventory lookup, supplier search, requests with supplier quotes, ERP documents, "
        "purchase orders and shipments. create_purchase_order only creates Draft orders. The draft_* tools save "
        "nothing: they return what would be saved and the REST call that saves it, which a person confirms in the app."
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
<<<<<<< HEAD
    return _run(lambda c: agent_tools.get_inventory(c, item_code, _acting_user(c)))
=======
    return _run(lambda c: agent_tools.get_inventory(c, _acting_user(c), item_code))
>>>>>>> main


@mcp.tool
def search_suppliers(supplier_name: str) -> list[dict]:
    """Search suppliers by (partial) name, email or address."""
    return _run(lambda c: agent_tools.search_suppliers(c, supplier_name))


@mcp.tool
def create_purchase_order(
    supplier_id: int, item_code: str, quantity: int, unit_price: float | None = None
) -> dict:
    """Create a purchase order (status Draft) for one item from one supplier: supplier_id is the supplier's number, e.g. 2. Unit price defaults to the item's last known price. The order still has to be approved before it goes to the ERP. MCP clients need a write-scope token."""
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
def list_purchase_orders(
    status: str | None = None, delivery_status: str | None = None
) -> list[dict]:
    """List your purchase orders. Optional status: Draft, Pending, Approved, Closed. Optional delivery_status: Not Shipped, In Transit, Delivered, Rejected."""
    return _run(
        lambda c: agent_tools.list_purchase_orders(c, _acting_user(c), status, delivery_status)
    )


@mcp.tool
def list_requests(status: str | None = None) -> list[dict]:
    """List the buyer's requests across both ERPs. Optional status: one stage or several separated by commas, from Open, Quoted, Quotes closed, Awarded, In Transit, Delivered, Rejected, Closed, Cancelled. Requests waiting for an award are "Quoted,Quotes closed"; open ones still taking quotes are "Open,Quoted"."""
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


@mcp.tool
def get_erp_documents(req_number: str) -> dict:
    """The ERP's own documents for a request's purchase order (e.g. REQ2001): the order, inbound deliveries or receipts, stock movements and invoice holds, from SAP or Infor LN."""
    return _run(lambda c: agent_tools.get_erp_documents(c, _acting_user(c), req_number))


@mcp.tool
def check_shipments(view: str = "incoming") -> list[dict]:
    """Shipments for the warehouse. view: incoming, arriving_today, overdue, awaiting_inspection or inspected."""
    return _run(lambda c: agent_tools.check_shipments(c, _acting_user(c), view))


@mcp.tool
def draft_request(
    quantity: int,
    item_code: str | None = None,
    title: str | None = None,
    needed_by: str | None = None,
    erp: str = "sap",
    target_price: float | None = None,
    description: str = "",
) -> dict:
    """Draft a new request for quotes: an item code from the buyer's inventory (or a title for something new), quantity, optional need-by date (YYYY-MM-DD), ERP (sap or infor) and target price. Saves nothing."""
    return _run(
        lambda c: agent_tools.draft_request(
            c,
            _acting_user(c),
            quantity,
            item_code,
            title,
            needed_by,
            erp,
            target_price,
            description,
        )
    )


@mcp.tool
def draft_po_approval(po_number: str) -> dict:
    """Draft approving a Pending purchase order (e.g. PO1004), which sends it to the ERP and the supplier. Saves nothing."""
    return _run(lambda c: agent_tools.draft_po_approval(c, _acting_user(c), po_number))


@mcp.tool
def draft_quote(req_number: str, unit_price: float, lead_time_days: int, message: str = "") -> dict:
    """Draft a supplier's quote on an open request (e.g. REQ2002): unit price, lead time in days and an optional message. Saves nothing."""
    return _run(
        lambda c: agent_tools.draft_quote(
            c, _acting_user(c), req_number, unit_price, lead_time_days, message
        )
    )


@mcp.tool
def draft_arrival(
    shipment_no: str, received: dict[str, int] | None = None, notes: str = ""
) -> dict:
    """Draft recording that a shipment (e.g. SHP3001) arrived. received maps item code to the quantity counted; items left out count as fully received. Saves nothing."""
    return _run(
        lambda c: agent_tools.draft_arrival(c, _acting_user(c), shipment_no, received, notes)
    )


@mcp.tool
def draft_delivery_approval(shipment_no: str, notes: str = "") -> dict:
    """Draft approving an arrived shipment (e.g. SHP3001) after all four quality checks passed; approving releases the stock. Saves nothing."""
    return _run(
        lambda c: agent_tools.draft_delivery_approval(c, _acting_user(c), shipment_no, notes)
    )


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
