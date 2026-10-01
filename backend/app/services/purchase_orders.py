import sqlite3
import uuid

from ..config import settings
from ..connectors import get_connector
from ..db import now
from .context import current_channel
from . import suppliers as suppliers_svc
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, notify

STATUS_FLOW = {"Draft": {"Pending"}, "Pending": {"Approved"}, "Approved": {"Closed"}, "Closed": set()}


def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    po = dict(row)
    items = conn.execute(
        "SELECT item_code, quantity, unit_price FROM purchase_order_items WHERE po_id = ? ORDER BY id", (po["id"],)
    ).fetchall()
    po["items"] = [dict(i) for i in items]
    supplier = conn.execute("SELECT supplier_name FROM suppliers WHERE id = ?", (po["supplier_id"],)).fetchone()
    po["supplier_name"] = supplier["supplier_name"] if supplier else None
    src = conn.execute("SELECT id FROM requirements WHERE po_id = ?", (po["id"],)).fetchone()
    po["requirement_id"] = src["id"] if src else None
    return po


def _fetch(conn: sqlite3.Connection, where: str, arg) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM purchase_orders WHERE {where} = ?", (arg,)).fetchone()
    if row is None:
        raise NotFound("Purchase order not found")
    return row


def _check_visible(user: dict, po: dict) -> None:
    # Buyers only see POs they created (admins see everything).
    if user["role"] == "buyer" and po["created_by"] != user["id"]:
        raise NotFound("Purchase order not found")
    if user["role"] == "supplier" and (po["supplier_id"] != user.get("supplier_id") or po["status"] == "Draft"):
        raise NotFound("Purchase order not found")


def list_pos(conn: sqlite3.Connection, user: dict, status: str | None = None, q: str | None = None) -> list[dict]:
    sql = "SELECT po.* FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id WHERE 1=1"
    args: list = []
    if user["role"] == "buyer":
        sql += " AND po.created_by = ?"
        args.append(user["id"])
    if user["role"] == "supplier":
        sql += " AND po.supplier_id = ? AND po.status != 'Draft'"
        args.append(user.get("supplier_id") or -1)
    if status:
        sql += " AND po.status = ?"
        args.append(status)
    if q:
        sql += " AND (po.po_number LIKE ? OR s.supplier_name LIKE ?)"
        args += [f"%{q}%"] * 2
    rows = conn.execute(sql + " ORDER BY po.id DESC", args).fetchall()
    return [_hydrate(conn, r) for r in rows]


def history(conn: sqlite3.Connection, entity: str, entity_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT a.action, a.detail, a.channel, a.created_at, u.name AS user_name FROM audit_logs a "
        "LEFT JOIN users u ON u.id = a.user_id WHERE a.entity = ? AND a.entity_id = ? ORDER BY a.id DESC",
        (entity, entity_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_po(conn: sqlite3.Connection, user: dict, po_id: int) -> dict:
    po = _hydrate(conn, _fetch(conn, "id", po_id))
    _check_visible(user, po)
    if user["role"] != "supplier":
        po["history"] = history(conn, "purchase_order", po["po_number"])
    return po


def get_po_by_number(conn: sqlite3.Connection, user: dict, po_number: str) -> dict:
    po = _hydrate(conn, _fetch(conn, "po_number", po_number.upper()))
    _check_visible(user, po)
    return po


def _notify_new_po(conn: sqlite3.Connection, po: dict) -> None:
    supplier = suppliers_svc.get_supplier(conn, po["supplier_id"])
    notify(
        conn,
        title=f"New Purchase Order {po['po_number']}",
        message=f"A new purchase order {po['po_number']} totalling {po['total_amount']:.2f} has been raised for {supplier['supplier_name']}.",
        email_to=supplier["email"],
        supplier_id=supplier["id"],
    )


def create_po(conn: sqlite3.Connection, user: dict, supplier_id: int, items: list[dict], submit: bool = False, erp: str | None = None) -> dict:
    if user["role"] not in ("buyer", "admin"):
        raise Forbidden("Only buyers can create purchase orders")
    suppliers_svc.get_supplier(conn, supplier_id)
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    status = "Pending" if submit else "Draft"
    cur = conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, total_amount, created_by, created_via, erp, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (f"TMP-{uuid.uuid4().hex}", supplier_id, status, round(total, 2), user["id"], current_channel(), erp or settings.erp_backend, now()),
    )
    po_id = cur.lastrowid
    conn.execute("UPDATE purchase_orders SET po_number = ? WHERE id = ?", (f"PO{1000 + po_id}", po_id))
    conn.executemany(
        "INSERT INTO purchase_order_items (po_id, item_code, quantity, unit_price) VALUES (?,?,?,?)",
        [(po_id, i["item_code"], i["quantity"], i["unit_price"]) for i in items],
    )
    po = get_po(conn, user, po_id)
    audit(conn, user["id"], "create", "purchase_order", po["po_number"], f"status={status}")
    if submit:
        _notify_new_po(conn, po)
    return po


def update_po(conn: sqlite3.Connection, user: dict, po_id: int, changes: dict) -> dict:
    po = get_po(conn, user, po_id)
    is_buyer = user["role"] in ("buyer", "admin")

    if changes.get("items") is not None:
        if not is_buyer:
            raise Forbidden("Only buyers can edit items")
        if po["status"] not in ("Draft", "Pending"):
            raise DomainError("Items can only be edited while the order is Draft or Pending")
        conn.execute("DELETE FROM purchase_order_items WHERE po_id = ?", (po_id,))
        conn.executemany(
            "INSERT INTO purchase_order_items (po_id, item_code, quantity, unit_price) VALUES (?,?,?,?)",
            [(po_id, i["item_code"], i["quantity"], i["unit_price"]) for i in changes["items"]],
        )
        total = sum(i["quantity"] * i["unit_price"] for i in changes["items"])
        conn.execute("UPDATE purchase_orders SET total_amount = ? WHERE id = ?", (round(total, 2), po_id))

    new_status = changes.get("status")
    if new_status and new_status != po["status"]:
        if not is_buyer:
            raise Forbidden("Only buyers can change the order status")
        if new_status not in STATUS_FLOW[po["status"]]:
            raise DomainError(f"Cannot move order from {po['status']} to {new_status}")
        if new_status == "Closed" and po["delivery_status"] != "Delivered":
            raise DomainError("Order can only be closed once it has been delivered")
        conn.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new_status, po_id))
        audit(conn, user["id"], "status", "purchase_order", po["po_number"], f"{po['status']} -> {new_status}")
        refreshed = get_po(conn, user, po_id)
        if new_status == "Pending":
            _notify_new_po(conn, refreshed)
        elif new_status == "Approved":
            ref = get_connector(refreshed["erp"]).push_purchase_order(refreshed)
            conn.execute("UPDATE purchase_orders SET erp_reference = ? WHERE id = ?", (ref["erp_reference"], po_id))
            supplier = suppliers_svc.get_supplier(conn, po["supplier_id"])
            notify(
                conn,
                title=f"Purchase Order {po['po_number']} approved",
                message=f"Purchase order {po['po_number']} has been approved. Please arrange delivery. ERP ref: {ref['erp_reference']}.",
                email_to=supplier["email"],
                supplier_id=supplier["id"],
            )

    new_delivery = changes.get("delivery_status")
    if new_delivery and new_delivery != po["delivery_status"]:
        raise DomainError("Delivery status follows shipments and warehouse inspection. Suppliers create a shipment; the inspector receives it.")

    return get_po(conn, user, po_id)
