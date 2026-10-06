"""ERP capabilities exposed to AI agents. Shared by the FastMCP server and the
OpenAPI-compatible REST wrappers so both surfaces behave identically."""

import sqlite3

from . import inventory as inventory_svc
from . import purchase_orders as po_svc
from . import ranking
from . import requirements as req_svc
from . import shipments as shipments_svc
from . import suppliers as suppliers_svc
from .errors import DomainError, NotFound


def get_inventory(conn: sqlite3.Connection, item_code: str) -> dict:
    item = inventory_svc.get_item(conn, item_code)
    return {
        "item_code": item["item_code"],
        "stock": item["stock_quantity"],
        "description": item["description"],
        "warehouse": item["warehouse"],
    }


def search_supplier(conn: sqlite3.Connection, supplier_name: str) -> list[dict]:
    return suppliers_svc.list_suppliers(conn, supplier_name)


def _last_unit_price(conn: sqlite3.Connection, item_code: str) -> float:
    row = conn.execute(
        "SELECT unit_price FROM purchase_order_items WHERE item_code = ? ORDER BY id DESC LIMIT 1",
        (item_code,),
    ).fetchone()
    return row["unit_price"] if row else 0.0


def create_purchase_order(
    conn: sqlite3.Connection,
    user: dict,
    supplier_id: int,
    item_code: str,
    quantity: int,
    unit_price: float | None = None,
) -> dict:
    inventory_svc.get_item(conn, item_code)  # validates the item exists
    price = unit_price if unit_price is not None else _last_unit_price(conn, item_code)
    return po_svc.create_po(
        conn,
        user,
        supplier_id,
        [{"item_code": item_code, "quantity": quantity, "unit_price": price}],
        submit=False,
    )


def get_purchase_order(conn: sqlite3.Connection, user: dict, po_number: str) -> dict:
    return po_svc.get_po_by_number(conn, user, po_number)


def list_requirements(conn: sqlite3.Connection, user: dict, stage: str | None = None) -> list[dict]:
    """Requirements visible to the acting buyer, trimmed to what an agent needs to reason about them."""
    keys = (
        "id",
        "req_number",
        "title",
        "quantity",
        "target_price",
        "needed_by",
        "quote_deadline",
        "erp",
        "stage",
        "quote_count",
        "po_number",
        "unread_messages",
    )
    return [{k: r.get(k) for k in keys} for r in req_svc.list_requirements(conn, user, stage)]


def _requirement(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    row = conn.execute(
        "SELECT id FROM requirements WHERE req_number = ?", (req_number.strip().upper(),)
    ).fetchone()
    if row is None:
        raise NotFound(f"Requirement {req_number} not found")
    return req_svc.get_requirement(conn, user, row["id"])


def get_requirement(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """One requirement with its quotes, so an agent can compare suppliers."""
    r = _requirement(conn, user, req_number)
    keep = (
        "id",
        "req_number",
        "title",
        "description",
        "item_code",
        "quantity",
        "target_price",
        "needed_by",
        "erp",
        "stage",
        "po_number",
        "quotes",
        "invites",
    )
    return {k: r.get(k) for k in keep}


# ---- SRS §6.1 buyer-assistant tools (read-only; draft_award saves nothing) ----


def list_requests(conn: sqlite3.Connection, user: dict, status: str | None = None) -> list[dict]:
    """Requests across both ERPs, optionally filtered by stage (case-insensitive)."""
    rows = list_requirements(conn, user)
    return [r for r in rows if not status or (r["stage"] or "").lower() == status.strip().lower()]


def get_request_detail(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """One request's full record: invitations, responses, threads, history, shipments and inspection results."""
    r = _requirement(conn, user, req_number)
    shipments = shipments_svc.list_shipments(conn, user, po_id=r["po_id"]) if r.get("po_id") else []
    keep = (
        "req_number",
        "title",
        "description",
        "item_code",
        "quantity",
        "target_price",
        "needed_by",
        "quote_deadline",
        "erp",
        "stage",
        "po_number",
        "delivery_status",
    )
    ship_keep = (
        "shipment_no",
        "status",
        "carrier",
        "tracking_no",
        "expected_arrival",
        "arrived_at",
        "inspected_at",
        "rejection_reason",
        "inspection_notes",
        "items",
    )
    return {
        **{k: r.get(k) for k in keep},
        "invitations": r.get("invites", []),
        "responses": [
            {
                k: q.get(k)
                for k in (
                    "supplier_name",
                    "unit_price",
                    "lead_time_days",
                    "message",
                    "status",
                    "created_at",
                )
            }
            for q in r.get("quotes", [])
        ],
        "threads": r.get("threads", []),
        "history": r.get("history", []),
        "shipments": [
            {
                **{k: s.get(k) for k in ship_keep},
                "quality": [{"label": c["label"], "passed": c["passed"]} for c in s["quality"]],
            }
            for s in shipments
        ],
    }


def compare_responses(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """Active responses ranked by ranking.rank_quotes; the assistant shows this ranking, never its own."""
    r = _requirement(conn, user, req_number)
    active = [q for q in r.get("quotes", []) if q["status"] in ("Submitted", "Accepted")]
    return {
        **{
            k: r.get(k)
            for k in ("req_number", "title", "item_code", "quantity", "needed_by", "erp", "stage")
        },
        "rule": ranking.RULE,
        "ranking": ranking.rank_quotes(r, active),
    }


def draft_award(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """Propose awarding the top-ranked response. Nothing is saved: the buyer confirms in the app,
    which calls POST /api/requirements/{id}/award."""
    r = _requirement(conn, user, req_number)
    if r["status"] != "Open":
        raise DomainError(f"{r['req_number']} cannot be awarded (stage: {r['stage']})")
    comparison = compare_responses(conn, user, req_number)
    if not comparison["ranking"]:
        raise DomainError(f"{r['req_number']} has no responses to award yet")
    top = comparison["ranking"][0]
    return {
        **comparison,
        "requirement_id": r["id"],
        "saved": False,
        "proposed": top,
        "erp_call": {
            "erp": r["erp"],
            "operation": "Create purchase order",
            "supplier_name": top["supplier_name"],
            "item_code": r.get("item_code"),
            "quantity": r["quantity"],
            "unit_price": top["unit_price"],
            "total_price": top["total_price"],
        },
        "confirm": {
            "method": "POST",
            "path": f"/api/requirements/{r['id']}/award",
            "body": {"quote_id": top["quote_id"]},
        },
    }


def list_purchase_orders(
    conn: sqlite3.Connection, user: dict, status: str | None = None
) -> list[dict]:
    keys = (
        "po_number",
        "supplier_name",
        "status",
        "delivery_status",
        "total_amount",
        "erp",
        "created_via",
        "items",
    )
    return [{k: p.get(k) for k in keys} for p in po_svc.list_pos(conn, user, status)]
