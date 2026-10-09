"""ERP capabilities exposed to AI agents. Shared by the FastMCP server and the
OpenAPI-compatible REST wrappers so both surfaces behave identically."""

import sqlite3

from pydantic import ValidationError

from ..connectors import get_connector
from ..schemas import RequirementCreate
from . import inventory as inventory_svc
from . import purchase_orders as po_svc
from . import ranking
from . import requirements as req_svc
from . import shipments as shipments_svc
from . import suppliers as suppliers_svc
from .errors import DomainError, NotFound


def get_inventory(conn: sqlite3.Connection, item_code: str, user: dict | None = None) -> dict:
    item = inventory_svc.get_item(conn, item_code, user)
    return {
        "item_code": item["item_code"],
        "stock": item["stock_quantity"],
        "description": item["description"],
        "warehouse": item["warehouse"],
    }


def search_suppliers(conn: sqlite3.Connection, supplier_name: str) -> list[dict]:
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
    inventory_svc.get_item(conn, item_code, user)  # validates the item is in the buyer's inventory
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


def _list_requirements(
    conn: sqlite3.Connection, user: dict, stage: str | None = None
) -> list[dict]:
    """Requirements visible to the acting user, trimmed to what an agent needs to reason about them."""
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


# ---- SRS §6.1 buyer-assistant tools (read-only; draft_award saves nothing) ----


def list_requests(conn: sqlite3.Connection, user: dict, status: str | None = None) -> list[dict]:
    """Requests across both ERPs, optionally filtered by stage: one, or several separated by commas (case-insensitive)."""
    rows = _list_requirements(conn, user)
    wanted = {s.strip().lower() for s in (status or "").split(",") if s.strip()}
    return [r for r in rows if not wanted or (r["stage"] or "").lower() in wanted]


def get_request_detail(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """One request's full record: invitations, responses, threads, history, shipments and inspection results."""
    r = _requirement(conn, user, req_number)
    shipments = (
        shipments_svc.list_shipments(conn, user, po_id=r["po_id"])
        if r.get("po_id") and user["role"] != "admin"
        else []
    )
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
    conn: sqlite3.Connection,
    user: dict,
    status: str | None = None,
    delivery_status: str | None = None,
) -> list[dict]:
    """POs the user may see, optionally filtered by status and by delivery status (case-insensitive)."""
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
    pos = po_svc.list_pos(conn, user, status)
    if delivery_status:
        wanted = delivery_status.strip().lower()
        pos = [p for p in pos if (p.get("delivery_status") or "").lower() == wanted]
    return [{k: p.get(k) for k in keys} for p in pos]


# ---- ERP documents (SRS §6.1) ----

# per ERP: the mock's PO record (key holding the ERP reference, key holding the portal PO number) and the
# documents that carry the same ERP reference
_ERP_DOCS = {
    "sap": {
        "order": ("raw_purchase_orders", "EBELN", "REF"),
        "documents": {
            "inbound_deliveries": ("raw_inbound_deliveries", "EBELN"),
            "stock_movements": ("raw_stock_movements", "EBELN"),
            "invoice_blocks": ("raw_invoice_blocks", "EBELN"),
        },
    },
    "infor": {
        "order": ("raw_orders", "orno", "ref"),
        "documents": {
            "receipts": ("raw_receipts", "orno"),
            "stock_movements": ("raw_stock_movements", "orno"),
            "invoice_holds": ("raw_invoice_holds", "orno"),
        },
    },
}


def get_erp_documents(conn: sqlite3.Connection, user: dict, req_number: str) -> dict:
    """The ERP's own records for a request's purchase order: the order, deliveries or receipts, stock
    movements and invoice holds. Read from the mock SAP / Infor LN connectors."""
    r = _requirement(conn, user, req_number)
    out = {"req_number": r["req_number"], "erp": r["erp"], "po_number": None, "erp_reference": None}
    if not r.get("po_id"):
        return {
            **out,
            "found": False,
            "note": "No purchase order yet, so the ERP has no documents.",
        }
    po = po_svc.get_po(conn, user, r["po_id"])
    out.update(po_number=po["po_number"], erp=po["erp"], erp_reference=po.get("erp_reference"))
    spec, connector = _ERP_DOCS[po["erp"]], get_connector(po["erp"])
    accessor, ref_key, po_key = spec["order"]
    # the mock ERPs keep their data in memory and restart their numbering, so an ERP reference alone can
    # point at another PO: only trust the ERP order whose own record names this portal PO
    order = next(
        (
            o
            for o in getattr(connector, accessor)()
            if o.get(ref_key) == po.get("erp_reference") and o.get(po_key) == po["po_number"]
        ),
        None,
    )
    if order is None:
        return {
            **out,
            "found": False,
            "note": f"The {po['erp'].upper()} mock has no record of {po['po_number']} (it was restarted since).",
        }
    docs = {
        name: [d for d in getattr(connector, acc)() if d.get(key) == po["erp_reference"]]
        for name, (acc, key) in spec["documents"].items()
    }
    return {**out, "found": True, "order": order, **docs}


# ---- inspector look-up ----

SHIPMENT_VIEWS = ("incoming", "arriving_today", "overdue", "awaiting_inspection", "inspected")


def check_shipments(
    conn: sqlite3.Connection, user: dict, view: str = "incoming", tz_minutes: int = 0
) -> list[dict]:
    """Shipments by view: incoming (on their way), arriving_today, overdue, awaiting_inspection, inspected."""
    if view == "incoming":
        found = shipments_svc.list_shipments(conn, user, status="Shipped")
    elif view in ("arriving_today", "overdue"):
        found = shipments_svc.list_shipments(conn, user, view=view, tz_minutes=tz_minutes)
    elif view == "awaiting_inspection":
        found = shipments_svc.list_shipments(conn, user, status="Arrived")
    elif view == "inspected":
        found = shipments_svc.list_shipments(
            conn, user, status="Approved"
        ) + shipments_svc.list_shipments(conn, user, status="Rejected")
    else:
        raise DomainError(f"view must be one of {', '.join(SHIPMENT_VIEWS)}")
    keys = (
        "shipment_no",
        "po_number",
        "supplier_name",
        "status",
        "carrier",
        "tracking_no",
        "expected_arrival",
        "items",
    )
    return [
        {k: s.get(k) for k in keys} for s in sorted(found, key=lambda s: s["id"], reverse=True)[:10]
    ]


# ---- drafts: each returns what would be saved and the REST call that saves it; nothing is saved here ----


def _draft(summary: dict, method: str, path: str, body: dict, label: str) -> dict:
    return {
        "saved": False,
        "summary": summary,
        "confirm": {"method": method, "path": path, "body": body, "label": label},
    }


def draft_request(
    conn: sqlite3.Connection,
    user: dict,
    quantity: int,
    item_code: str | None = None,
    title: str | None = None,
    needed_by: str | None = None,
    erp: str = "sap",
    target_price: float | None = None,
    description: str = "",
) -> dict:
    """Draft a new request for quotes (all current suppliers are invited). Saves nothing."""
    if user["role"] not in ("buyer", "admin"):
        raise DomainError("Only buyers can create requests")
    if item_code:
        item = inventory_svc.get_item(conn, item_code, user)
        item_code, title = item["item_code"], title or item["description"]
    if not title:
        raise DomainError("Say which item (an item code from your inventory) or what you need")
    body = {
        "title": title,
        "description": description or "",
        "item_code": item_code,
        "quantity": quantity,
        "target_price": target_price,
        "needed_by": needed_by,
        "erp": (erp or "sap").lower(),
    }
    try:
        body = RequirementCreate(**body).model_dump()
    except ValidationError as exc:
        raise DomainError("; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())) from exc
    summary = {
        "Item": f"{item_code} - {title}" if item_code else title,
        "Quantity": quantity,
        "Needed by": needed_by or "(not set)",
        "Target price": target_price if target_price is not None else "(not set)",
        "ERP": "Infor LN" if body["erp"] == "infor" else "SAP",
        "Suppliers": "All current suppliers are invited",
    }
    return _draft(summary, "POST", "/api/requirements", body, "Create request")


def draft_po_approval(conn: sqlite3.Connection, user: dict, po_number: str) -> dict:
    """Draft approving a Pending purchase order (sends it to the ERP and the supplier). Saves nothing."""
    if user["role"] not in ("buyer", "admin"):
        raise DomainError("Only buyers can approve purchase orders")
    po = po_svc.get_po_by_number(conn, user, po_number)
    if po["status"] != "Pending":
        raise DomainError(
            f"{po['po_number']} is {po['status']}; only Pending orders can be approved"
        )
    summary = {
        "Purchase order": po["po_number"],
        "Supplier": po.get("supplier_name"),
        "Items": ", ".join(
            f"{i['quantity']} x {i['item_code']} @ {i['unit_price']:.2f}" for i in po["items"]
        ),
        "Total": f"{po['total_amount']:.2f}",
        "ERP call": f"{po['erp'].upper() if po['erp'] == 'sap' else 'Infor LN'} · Create purchase order",
    }
    return _draft(
        summary,
        "PUT",
        f"/api/purchase-orders/{po['id']}",
        {"status": "Approved"},
        "Approve and send",
    )


def draft_quote(
    conn: sqlite3.Connection,
    user: dict,
    req_number: str,
    unit_price: float,
    lead_time_days: int,
    message: str = "",
) -> dict:
    """Draft a supplier's quote on an open request. Saves nothing."""
    if user["role"] != "supplier" or not user.get("supplier_id"):
        raise DomainError("Only suppliers can submit quotes")
    r = _requirement(conn, user, req_number)
    if r["status"] != "Open":
        raise DomainError(f"{r['req_number']} is no longer open for quotes")
    req_svc.ensure_quoting_open(r)
    if unit_price < 0 or not 0 <= lead_time_days <= 730:
        raise DomainError("Price must be 0 or more and lead time 0 to 730 days")
    summary = {
        "Request": f"{r['req_number']} - {r['title']} (qty {r['quantity']})",
        "Unit price": f"{unit_price:.2f}",
        "Total": f"{unit_price * r['quantity']:.2f}",
        "Lead time (days)": lead_time_days,
        "Message": message or "(none)",
    }
    body = {"unit_price": unit_price, "lead_time_days": lead_time_days, "message": message or ""}
    return _draft(summary, "PUT", f"/api/requirements/{r['id']}/quote", body, "Send quote")


def _shipment(conn: sqlite3.Connection, user: dict, shipment_no: str) -> dict:
    row = conn.execute(
        "SELECT id FROM shipments WHERE shipment_no = ?", (shipment_no.strip().upper(),)
    ).fetchone()
    if row is None:
        raise NotFound(f"Shipment {shipment_no} not found")
    return shipments_svc.get_shipment(conn, user, row["id"])


def _inspector_shipment(
    conn: sqlite3.Connection, user: dict, shipment_no: str, status: str
) -> dict:
    if user["role"] != "inspector":
        raise DomainError("Only the warehouse inspector can do this")
    s = _shipment(conn, user, shipment_no)
    if s["status"] != status:
        raise DomainError(f"{s['shipment_no']} is {s['status']}, not {status}")
    if s.get("unit_level"):
        raise DomainError(
            f"{s['shipment_no']} has QR-coded units: use the shipment page to scan them"
        )
    return s


def draft_arrival(
    conn: sqlite3.Connection,
    user: dict,
    shipment_no: str,
    received: dict[str, int] | None = None,
    notes: str = "",
) -> dict:
    """Draft recording that a shipment arrived. received maps item code to the quantity counted; items
    not given are recorded as fully received. Saves nothing."""
    s = _inspector_shipment(conn, user, shipment_no, "Shipped")
    counted = {k.upper(): v for k, v in (received or {}).items()}
    lines = [
        {
            "item_code": i["item_code"],
            "quantity_received": counted.get(i["item_code"].upper(), i["quantity_shipped"]),
        }
        for i in s["items"]
    ]
    summary = {
        "Shipment": f"{s['shipment_no']} ({s.get('po_number')}, {s.get('supplier_name')})",
        **{
            f"Received {ln['item_code']}": f"{ln['quantity_received']} of {i['quantity_shipped']}"
            for ln, i in zip(lines, s["items"], strict=True)
        },
        "Notes": notes or "(none)",
    }
    return _draft(
        summary,
        "POST",
        f"/api/shipments/{s['id']}/arrival",
        {"lines": lines, "notes": notes or ""},
        "Record arrival",
    )


def draft_delivery_approval(
    conn: sqlite3.Connection, user: dict, shipment_no: str, notes: str = ""
) -> dict:
    """Draft approving an arrived shipment, which releases the stock to inventory and the ERP. Confirming
    means the inspector says all four quality checks passed. Saves nothing."""
    s = _inspector_shipment(conn, user, shipment_no, "Arrived")
    summary = {
        "Shipment": f"{s['shipment_no']} ({s.get('po_number')}, {s.get('supplier_name')})",
        "Arrived": ", ".join(
            f"{i['quantity_received']} of {i['quantity_shipped']} {i['item_code']}"
            for i in s["items"]
        ),
        "Quality checks": "All four passed: " + "; ".join(shipments_svc.QUALITY_CHECKS.values()),
        "Notes": notes or "(none)",
    }
    body = {
        "decision": "approve",
        "notes": notes or "",
        "checks": {k: True for k in shipments_svc.QUALITY_CHECKS},
    }
    return _draft(
        summary, "POST", f"/api/shipments/{s['id']}/inspection", body, "All checks passed: approve"
    )


def draft_purchase_order(
    conn: sqlite3.Connection,
    user: dict,
    supplier_id: int,
    item_code: str,
    quantity: int,
    unit_price: float | None = None,
) -> dict:
    """create_purchase_order as a draft, for the in-app assistant: the buyer confirms before it is saved."""
    if user["role"] not in ("buyer", "admin"):
        raise DomainError("Only buyers can create purchase orders")
    item = inventory_svc.get_item(conn, item_code, user)
    supplier = suppliers_svc.get_supplier(conn, supplier_id)
    price = unit_price if unit_price is not None else _last_unit_price(conn, item["item_code"])
    summary = {
        "Supplier": supplier["supplier_name"],
        "Item": f"{item['item_code']} - {item['description']}",
        "Quantity": quantity,
        "Unit price": f"{price:.2f}",
        "Total": f"{price * quantity:.2f}",
        "Status": "Draft (approve it later to send it to the ERP)",
    }
    body = {
        "supplier_id": supplier_id,
        "items": [{"item_code": item["item_code"], "quantity": quantity, "unit_price": price}],
        "submit": False,
    }
    return _draft(summary, "POST", "/api/purchase-orders", body, "Create draft PO")
