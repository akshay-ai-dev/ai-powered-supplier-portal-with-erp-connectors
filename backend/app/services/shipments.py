"""Fulfilment: supplier ships against an approved PO, the warehouse inspector receives and inspects.

Shipment lifecycle:  Shipped -> Arrived -> Approved | Rejected
  Shipped   supplier submitted it (packing list attached); an inbound delivery is announced to the ERP
  Arrived   inspector recorded what physically arrived
  Approved  stock is released to available inventory (locally and in the ERP); the PO becomes Delivered once
            every ordered line has been received in approved shipments
  Rejected  needs an inspector reason and at least one photo; the received goods are booked to quarantine in the ERP,
            the PO's supplier invoice is put on hold and the PO delivery status becomes Rejected until a replacement
            shipment is approved.
"""

import json
import os
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from ..connectors import get_connector
from ..db import now
from . import attachments as attachments_svc
from . import inventory as inventory_svc
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit, notify

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
KINDS = ("packing_list", "photo")
QUALITY_CHECKS = {
    "packaging": "Packaging intact",
    "specification": "Matches specification and dimensions",
    "condition": "No visible damage or defects",
    "documentation": "Documents match the packing list and PO",
}


def _is_inspector(user: dict) -> bool:
    return user["role"] in ("inspector", "admin")


def _row(conn: sqlite3.Connection, shipment_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if row is None:
        raise NotFound("Shipment not found")
    return row


def _check_visible(conn: sqlite3.Connection, user: dict, row: sqlite3.Row) -> None:
    if _is_inspector(user):
        if user["role"] == "inspector" and user.get(
            "owner_id"
        ):  # an inspector a buyer created works on that buyer's shipments only
            po = conn.execute(
                "SELECT created_by FROM purchase_orders WHERE id = ?", (row["po_id"],)
            ).fetchone()
            if not po or po["created_by"] != user["owner_id"]:
                raise NotFound("Shipment not found")
        return
    if user["role"] == "supplier":
        if row["supplier_id"] == user.get("supplier_id"):
            return
    elif user["role"] == "buyer":
        po = conn.execute(
            "SELECT created_by FROM purchase_orders WHERE id = ?", (row["po_id"],)
        ).fetchone()
        if po and po["created_by"] == user["id"]:
            return
    raise NotFound("Shipment not found")


def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    s = dict(row)
    s["items"] = [
        dict(r)
        for r in conn.execute(
            "SELECT item_code, quantity_shipped, quantity_received, quantity_accepted FROM shipment_items WHERE shipment_id = ? ORDER BY id",
            (s["id"],),
        )
    ]
    files = [
        dict(r)
        for r in conn.execute(
            "SELECT id, kind, filename, size, created_at FROM shipment_files WHERE shipment_id = ? AND unit_id IS NULL ORDER BY id",
            (s["id"],),
        )
    ]
    try:
        checks = json.loads(s.get("quality_checks") or "{}")
    except ValueError:
        checks = {}
    s["quality_checks"] = checks
    s["quality"] = [
        {"key": k, "label": label, "passed": checks.get(k)} for k, label in QUALITY_CHECKS.items()
    ]
    s["unit_level"] = bool(s.get("unit_level"))
    if s["unit_level"]:
        s["unit_counts"] = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) n FROM shipment_units WHERE shipment_id = ? GROUP BY status",
                (s["id"],),
            )
        }
    s.pop("lot_report", None)  # the report has its own endpoint
    try:  # the supplier's reviewed packing-list draft; None for shipments created without one
        s["packing_list_review"] = (
            json.loads(s["packing_list_review"]) if s.get("packing_list_review") else None
        )
    except (ValueError, TypeError):
        s["packing_list_review"] = None
    s["packing_list"] = next((f for f in files if f["kind"] == "packing_list"), None)
    s["photos"] = [f for f in files if f["kind"] == "photo"]
    po = conn.execute(
        "SELECT po_number, erp, created_by FROM purchase_orders WHERE id = ?", (s["po_id"],)
    ).fetchone()
    s["po_number"], s["erp"] = po["po_number"], po["erp"]
    sup = conn.execute(
        "SELECT supplier_name FROM suppliers WHERE id = ?", (s["supplier_id"],)
    ).fetchone()
    s["supplier_name"] = sup["supplier_name"] if sup else None
    # replacement links (every linked shipment belongs to the same order, so it is visible to whoever sees this one)
    s["replaces_shipment_no"] = None
    if s.get("replaces_shipment_id"):
        orig = conn.execute(
            "SELECT shipment_no FROM shipments WHERE id = ?", (s["replaces_shipment_id"],)
        ).fetchone()
        s["replaces_shipment_no"] = orig["shipment_no"] if orig else None
    s["replaced_by"] = [
        dict(r)
        for r in conn.execute(
            "SELECT id, shipment_no, status FROM shipments WHERE replaces_shipment_id = ? ORDER BY id",
            (s["id"],),
        )
    ]
    s["owed"] = [
        {"item_code": d["item_code"], "quantity": d["outstanding"]}
        for d in owed_detail(conn, row)
        if d["outstanding"] > 0
    ]
    return s


def _po(conn: sqlite3.Connection, po_id: int) -> dict:
    row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if row is None:
        raise NotFound("Purchase order not found")
    po = dict(row)
    po["items"] = [
        dict(r)
        for r in conn.execute(
            "SELECT item_code, quantity, unit_price FROM purchase_order_items WHERE po_id = ?",
            (po_id,),
        )
    ]
    return po


def _buyer(conn: sqlite3.Connection, po: dict):
    return conn.execute("SELECT id, email FROM users WHERE id = ?", (po["created_by"],)).fetchone()


def _tell_inspectors(
    conn: sqlite3.Connection, title: str, message: str, buyer_id: int | None = None
) -> None:
    """Company-wide inspectors, plus the inspectors the order's buyer created."""
    for u in conn.execute(
        "SELECT id, email FROM users WHERE role = 'inspector' AND active = 1 AND (owner_id IS NULL OR owner_id = ?)",
        (buyer_id,),
    ):
        notify(conn, title=title, message=message, email_to=u["email"], user_id=u["id"])


def _tell_supplier_and_buyer(conn: sqlite3.Connection, po: dict, title: str, message: str) -> None:
    sup = conn.execute(
        "SELECT id, email FROM suppliers WHERE id = ?", (po["supplier_id"],)
    ).fetchone()
    notify(conn, title=title, message=message, email_to=sup["email"], supplier_id=sup["id"])
    buyer = _buyer(conn, po)
    if buyer:
        notify(conn, title=title, message=message, email_to=buyer["email"], user_id=buyer["id"])


# ---------------------------------------------------------------- queries
VIEWS = ("arriving_today", "overdue", "inspected_today")


def view_condition(view: str, tz_minutes: int = 0) -> tuple[str, list]:
    """The SQL behind the inspector dashboard's counts, so a count and the list it links to always agree.
    "Today" is the user's own day: `tz_minutes` is their offset from UTC (minutes east), sent by the browser.
    Expected arrival is a plain date they typed; the inspection time is a UTC timestamp, so it is compared against the user's day in UTC."""
    offset = timedelta(minutes=max(-840, min(840, tz_minutes)))
    today = (datetime.now(UTC) + offset).date()
    start = datetime.combine(today, time.min, tzinfo=UTC) - offset
    if view == "arriving_today":
        return "s.status = 'Shipped' AND substr(s.expected_arrival, 1, 10) = ?", [today.isoformat()]
    if view == "overdue":
        return (
            "s.status = 'Shipped' AND s.expected_arrival IS NOT NULL AND s.expected_arrival != '' AND substr(s.expected_arrival, 1, 10) < ?",
            [today.isoformat()],
        )
    if view == "inspected_today":
        return (
            "s.status IN ('Approved','Rejected') AND s.inspected_at >= ? AND s.inspected_at < ?",
            [
                start.isoformat(timespec="seconds"),
                (start + timedelta(days=1)).isoformat(timespec="seconds"),
            ],
        )
    raise DomainError(f"Unknown view: {view}")


def list_shipments(
    conn: sqlite3.Connection,
    user: dict,
    status: str | None = None,
    po_id: int | None = None,
    view: str | None = None,
    tz_minutes: int = 0,
) -> list[dict]:
    sql, args = (
        "SELECT s.* FROM shipments s JOIN purchase_orders po ON po.id = s.po_id WHERE 1=1",
        [],
    )
    if view:
        cond, cond_args = view_condition(view, tz_minutes)
        sql += f" AND {cond}"
        args += cond_args
    if user["role"] == "supplier":
        sql += " AND s.supplier_id = ?"
        args.append(user.get("supplier_id") or -1)
    elif user["role"] == "buyer":
        sql += " AND po.created_by = ?"
        args.append(user["id"])
    elif user["role"] == "inspector" and user.get("owner_id"):
        sql += " AND po.created_by = ?"
        args.append(user["owner_id"])
    if status:
        sql += " AND s.status = ?"
        args.append(status)
    if po_id:
        sql += " AND s.po_id = ?"
        args.append(po_id)
    return [_hydrate(conn, r) for r in conn.execute(sql + " ORDER BY s.id DESC", args).fetchall()]


def get_shipment(conn: sqlite3.Connection, user: dict, shipment_id: int) -> dict:
    row = _row(conn, shipment_id)
    _check_visible(conn, user, row)
    return _hydrate(conn, row)


# ---------------------------------------------------------------- supplier: ship
def _ordered_and_committed(
    conn: sqlite3.Connection, po: dict
) -> tuple[dict[str, int], dict[str, int]]:
    ordered: dict[str, int] = defaultdict(int)
    for i in po["items"]:
        ordered[i["item_code"].upper()] += i["quantity"]
    committed: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        # in flight: what was declared; already approved: what actually arrived, so a short delivery can be topped up
        "SELECT si.item_code, SUM(CASE WHEN s.status = 'Approved' THEN COALESCE(si.quantity_accepted, si.quantity_received, 0) ELSE si.quantity_shipped END) AS q "
        "FROM shipment_items si JOIN shipments s ON s.id = si.shipment_id "
        "WHERE s.po_id = ? AND s.status != 'Rejected' GROUP BY si.item_code",
        (po["id"],),
    ):
        committed[r["item_code"].upper()] += r["q"]
    return ordered, committed


def remaining_quantities(conn: sqlite3.Connection, po: dict) -> dict[str, int]:
    """Per item code (upper case): how much of the order can still be shipped."""
    ordered, committed = _ordered_and_committed(conn, po)
    return {code: max(qty - committed[code], 0) for code, qty in ordered.items()}


def _received_ok(r: sqlite3.Row | dict, status: str) -> int:
    """What an inspected shipment line delivered: the accepted units; zero when the lot was rejected."""
    if status != "Approved":
        return 0
    return (
        r["quantity_accepted"]
        if r["quantity_accepted"] is not None
        else (r["quantity_received"] or 0)
    )


def owed_detail(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> list[dict]:
    """What an inspected shipment still owes, per item: units that were faulty, missing or rejected, less what replacements
    already delivered (``replaced``) or have on the way (``on_the_way``). Replacements the inspector rejected do not count."""
    if row["status"] not in ("Approved", "Rejected"):
        return []
    short = {}
    for r in conn.execute(
        "SELECT item_code, quantity_shipped, quantity_received, quantity_accepted FROM shipment_items WHERE shipment_id = ?",
        (row["id"],),
    ):
        n = r["quantity_shipped"] - _received_ok(r, row["status"])
        if n > 0:
            short[r["item_code"].upper()] = n
    if not short:
        return []
    replaced, on_the_way = defaultdict(int), defaultdict(int)
    for r in conn.execute(
        "SELECT si.item_code, si.quantity_shipped, si.quantity_received, si.quantity_accepted, s.status FROM shipment_items si "
        "JOIN shipments s ON s.id = si.shipment_id WHERE s.replaces_shipment_id = ? AND s.status != 'Rejected'",
        (row["id"],),
    ):
        code = r["item_code"].upper()
        if r["status"] == "Approved":
            replaced[code] += _received_ok(r, "Approved")
        else:
            on_the_way[code] += r["quantity_shipped"]
    return [
        {
            "item_code": c,
            "short": n,
            "replaced": replaced[c],
            "on_the_way": on_the_way[c],
            "outstanding": max(n - replaced[c] - on_the_way[c], 0),
        }
        for c, n in short.items()
    ]


def _units_to_replace(conn: sqlite3.Connection, shipment_id: int) -> list[dict]:
    """The faulty and missing units of a unit-level shipment, with the reason, so the supplier knows what to send."""
    from .units import DEFECT_TYPES

    return [
        {
            "code": u["code"],
            "item_code": u["item_code"],
            "status": u["status"],
            "defect_label": DEFECT_TYPES.get(u["defect_type"], u["defect_type"])
            if u["defect_type"]
            else "",
            "notes": u["notes"] or "",
        }
        for u in conn.execute(
            "SELECT code, item_code, status, defect_type, notes FROM shipment_units WHERE shipment_id = ? AND status IN ('Faulty','Missing') ORDER BY item_code, seq",
            (shipment_id,),
        )
    ]


def replacement_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """Both ends of the replacement link for a shipment's report: the shipment it replaces, and the ones that replace it."""
    replaces = None
    if row["replaces_shipment_id"]:
        orig = conn.execute(
            "SELECT * FROM shipments WHERE id = ?", (row["replaces_shipment_id"],)
        ).fetchone()
        if orig:
            replaces = {
                "id": orig["id"],
                "shipment_no": orig["shipment_no"],
                "status": orig["status"],
                "items": owed_detail(conn, orig),
                "units": _units_to_replace(conn, orig["id"])
                if orig["status"] == "Approved"
                else [],
            }
    replaced_by = []
    for r in conn.execute(
        "SELECT * FROM shipments WHERE replaces_shipment_id = ? ORDER BY id", (row["id"],)
    ):
        items = [
            dict(i)
            for i in conn.execute(
                "SELECT item_code, quantity_shipped, quantity_received, quantity_accepted FROM shipment_items WHERE shipment_id = ?",
                (r["id"],),
            )
        ]
        quality = None
        if r["status"] in ("Approved", "Rejected") and r["lot_report"] and r["lot_report"] != "{}":
            quality = json.loads(r["lot_report"]).get("quality_accuracy")
        replaced_by.append(
            {
                "id": r["id"],
                "shipment_no": r["shipment_no"],
                "status": r["status"],
                "shipped": sum(i["quantity_shipped"] for i in items),
                "accepted": sum(_received_ok(i, r["status"]) for i in items)
                if r["status"] in ("Approved", "Rejected")
                else None,
                "quality_accuracy": quality,
            }
        )
    return {"replaces": replaces, "replaced_by": replaced_by, "owed": owed_detail(conn, row)}


def to_ship(conn: sqlite3.Connection, po: dict) -> dict:
    """What the supplier can still ship on an order: the quantity left per item, the inspected shipments
    with units to replace, and the delivery progress per item."""
    ordered, committed = _ordered_and_committed(conn, po)
    accepted, in_flight = defaultdict(int), defaultdict(int)
    for r in conn.execute(
        "SELECT si.item_code, si.quantity_shipped, si.quantity_received, si.quantity_accepted, s.status FROM shipment_items si "
        "JOIN shipments s ON s.id = si.shipment_id WHERE s.po_id = ? AND s.status != 'Rejected'",
        (po["id"],),
    ):
        if r["status"] == "Approved":
            accepted[r["item_code"].upper()] += _received_ok(r, "Approved")
        else:
            in_flight[r["item_code"].upper()] += r["quantity_shipped"]
    progress, seen = [], set()
    for i in po["items"]:
        code = i["item_code"].upper()
        if code in seen:
            continue
        seen.add(code)
        progress.append(
            {
                "item_code": i["item_code"],
                "ordered": ordered[code],
                "accepted": accepted[code],
                "on_the_way": in_flight[code],
                "left": max(ordered[code] - committed[code], 0),
            }
        )
    rows = conn.execute(
        "SELECT * FROM shipments WHERE po_id = ? AND status IN ('Approved','Rejected') ORDER BY id",
        (po["id"],),
    ).fetchall()
    rejected_replacements = {
        r["replaces_shipment_id"]
        for r in rows
        if r["status"] == "Rejected" and r["replaces_shipment_id"]
    }
    replace = []
    for r in rows:
        items = [d for d in owed_detail(conn, r) if d["outstanding"] > 0]
        if (
            not items or r["id"] in rejected_replacements
        ):  # a rejected replacement now carries what the original owed
            continue
        replace.append(
            {
                "shipment_id": r["id"],
                "shipment_no": r["shipment_no"],
                "status": r["status"],
                "decided_at": r["inspected_at"],
                "items": items,
                "units": _units_to_replace(conn, r["id"]) if r["status"] == "Approved" else [],
            }
        )
    return {"progress": progress, "replace": replace}


def create_shipment(conn: sqlite3.Connection, user: dict, po_id: int, data: dict) -> dict:
    if user["role"] != "supplier" or not user.get("supplier_id"):
        raise Forbidden("Only the assigned supplier can ship an order")
    po = _po(conn, po_id)
    if po["supplier_id"] != user["supplier_id"] or po["status"] == "Draft":
        raise NotFound("Purchase order not found")
    if po["status"] != "Approved":
        raise DomainError("Shipments can only be created for Approved orders")
    if po["delivery_status"] == "Delivered":
        raise DomainError("This order has already been delivered")

    ordered, committed = _ordered_and_committed(conn, po)

    lines: dict[str, int] = defaultdict(int)
    for it in data["items"]:
        lines[it["item_code"].strip().upper()] += it["quantity"]
    if data.get("unit_inspection"):
        from . import units as units_svc

        units_svc.check_cap(lines)
    replaces = None
    if data.get(
        "replaces_shipment_id"
    ):  # checked first, so a bad link says so rather than "exceeds the order"
        replaces = conn.execute(
            "SELECT * FROM shipments WHERE id = ? AND po_id = ?",
            (data["replaces_shipment_id"], po_id),
        ).fetchone()
        if replaces is None:
            raise DomainError("The shipment to replace must be a shipment on this order")
        if replaces["status"] not in ("Approved", "Rejected"):
            raise DomainError(
                f"{replaces['shipment_no']} has not been inspected yet, so there is nothing to replace"
            )
        owed = {d["item_code"]: d["outstanding"] for d in owed_detail(conn, replaces)}
        if not any(owed.values()):
            raise DomainError(
                f"{replaces['shipment_no']} has no faulty, missing or rejected units left to replace"
            )
        for code, qty in lines.items():
            if owed.get(code, 0) == 0:
                raise DomainError(
                    f"{code} is not owed for {replaces['shipment_no']}. Ship items that are not replacements as a separate shipment"
                )
            if qty > owed[code]:
                raise DomainError(
                    f"{code}: {replaces['shipment_no']} still needs {owed[code]} replaced, not {qty}"
                )
    for code, qty in lines.items():
        if code not in ordered:
            raise DomainError(f"{code} is not on this purchase order")
        if qty <= 0:
            raise DomainError("Quantities must be positive")
        if committed[code] + qty > ordered[code]:
            raise DomainError(
                f"{code}: shipping {qty} would exceed the ordered {ordered[code]} (already shipped {committed[code]})"
            )

    review = data.get("packing_list_review")
    cur = conn.execute(
        "INSERT INTO shipments (shipment_no, po_id, supplier_id, carrier, tracking_no, expected_arrival, notes, packing_list_review, replaces_shipment_id, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"TMP-{now()}-{user['id']}",
            po_id,
            user["supplier_id"],
            data.get("carrier", ""),
            data.get("tracking_no", ""),
            data.get("expected_arrival"),
            data.get("notes", ""),
            json.dumps(review) if review else None,
            replaces["id"] if replaces else None,
            user["id"],
            now(),
        ),
    )
    sid = cur.lastrowid
    number = f"SHP{3000 + sid}"
    conn.execute("UPDATE shipments SET shipment_no = ? WHERE id = ?", (number, sid))
    conn.executemany(
        "INSERT INTO shipment_items (shipment_id, item_code, quantity_shipped) VALUES (?,?,?)",
        [(sid, c, q) for c, q in lines.items()],
    )
    if data.get("unit_inspection"):
        from . import inspection_fields as fields_svc
        from . import units as units_svc

        units_svc.create_units(conn, sid, number, lines)
        conn.execute("UPDATE shipments SET unit_level = 1 WHERE id = ?", (sid,))
        fields_svc.copy_templates(conn, sid, list(lines), po["created_by"])
        audit(
            conn,
            user["id"],
            "units",
            "shipment",
            number,
            f"{sum(lines.values())} unit(s) with QR codes",
        )
    shipment = _hydrate(conn, _row(conn, sid))
    ref = get_connector(po["erp"]).create_inbound_delivery(po, shipment)
    conn.execute(
        "UPDATE shipments SET erp_inbound_ref = ? WHERE id = ?", (ref["erp_inbound_ref"], sid)
    )
    conn.execute("UPDATE purchase_orders SET delivery_status = 'In Transit' WHERE id = ?", (po_id,))
    audit(
        conn,
        user["id"],
        "ship",
        "purchase_order",
        po["po_number"],
        f"{number} inbound={ref['erp_inbound_ref']}"
        + (f"; replaces {replaces['shipment_no']}" if replaces else ""),
    )

    msg = f"{shipment['supplier_name']} shipped {po['po_number']} ({number}). Tracking: {data.get('tracking_no') or 'n/a'}."
    if replaces:
        msg += f" This replaces the {'rejected' if replaces['status'] == 'Rejected' else 'faulty or missing'} units of {replaces['shipment_no']}."
    buyer = _buyer(conn, po)
    if buyer:
        notify(
            conn,
            title=f"Shipment {number} on its way",
            message=msg,
            email_to=buyer["email"],
            user_id=buyer["id"],
        )
    _tell_inspectors(
        conn,
        f"Incoming shipment {number}",
        msg + " Please receive and inspect it on arrival.",
        po["created_by"],
    )
    return _hydrate(conn, _row(conn, sid))


# ---------------------------------------------------------------- files
def add_file(
    conn: sqlite3.Connection,
    user: dict,
    shipment_id: int,
    kind: str,
    filename: str,
    data: bytes,
    content_type: str | None,
    unit_id: int | None = None,
) -> dict:
    if kind not in KINDS:
        raise DomainError(f"kind must be one of {KINDS}")
    s = _row(conn, shipment_id)
    _check_visible(conn, user, s)
    if kind == "packing_list":
        if user["role"] != "supplier" or s["supplier_id"] != user.get("supplier_id"):
            raise Forbidden("Only the shipping supplier can attach the packing list")
        if s["status"] != "Shipped":
            raise DomainError("The packing list can only be changed before the shipment arrives")
        conn.execute(
            "DELETE FROM shipment_files WHERE shipment_id = ? AND kind = 'packing_list'",
            (shipment_id,),
        )  # one per shipment
    else:
        if not _is_inspector(user):
            raise Forbidden("Only the warehouse inspector can attach inspection photos")
        if s["status"] != "Arrived":
            raise DomainError(
                "Photos can be added after arrival is recorded and before the decision"
            )
        if os.path.splitext(filename or "")[1].lower() not in IMAGE_EXT:
            raise DomainError("Inspection photos must be images (png, jpg, gif, webp)", 415)
    stored = attachments_svc.store(filename, data)
    cur = conn.execute(
        "INSERT INTO shipment_files (shipment_id, kind, filename, content_type, size, stored_name, uploaded_by, unit_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            shipment_id,
            kind,
            stored["filename"],
            content_type or "application/octet-stream",
            stored["size"],
            stored["stored_name"],
            user["id"],
            unit_id,
            now(),
        ),
    )
    audit(conn, user["id"], "file", "shipment", s["shipment_no"], f"{kind}: {stored['filename']}")
    return dict(
        conn.execute(
            "SELECT id, kind, filename, size, created_at FROM shipment_files WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    )


def open_file(conn: sqlite3.Connection, user: dict, file_id: int):
    f = conn.execute("SELECT * FROM shipment_files WHERE id = ?", (file_id,)).fetchone()
    if f is None:
        raise NotFound("File not found")
    _check_visible(conn, user, _row(conn, f["shipment_id"]))
    path = attachments_svc.upload_dir() / f["stored_name"]
    if not path.exists():
        raise NotFound("File not found")
    return f, path


# ---------------------------------------------------------------- inspector
def _remaining(conn: sqlite3.Connection, po_id: int) -> dict[str, int]:
    """Units still to be delivered: ordered minus received in approved shipments."""
    ordered: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        "SELECT item_code, quantity FROM purchase_order_items WHERE po_id = ?", (po_id,)
    ):
        ordered[r["item_code"].upper()] += r["quantity"]
    got: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        "SELECT si.item_code, COALESCE(si.quantity_accepted, si.quantity_received, 0) AS q FROM shipment_items si JOIN shipments s ON s.id = si.shipment_id "
        "WHERE s.po_id = ? AND s.status = 'Approved'",
        (po_id,),
    ):
        got[r["item_code"].upper()] += r["q"] or 0
    return {c: q - got[c] for c, q in ordered.items() if q - got[c] > 0}


def _po_fully_received(conn: sqlite3.Connection, po_id: int) -> bool:
    return not _remaining(conn, po_id)


def _clean_checks(checks: dict | None) -> dict[str, bool]:
    checks = checks or {}
    unknown = set(checks) - set(QUALITY_CHECKS)
    if unknown:
        raise DomainError(
            f"Unknown quality check(s): {', '.join(sorted(unknown))}. Use: {', '.join(QUALITY_CHECKS)}"
        )
    return {k: bool(v) for k, v in checks.items()}


def record_arrival(
    conn: sqlite3.Connection, user: dict, shipment_id: int, lines: list[dict], notes: str = ""
) -> dict:
    """Quantity check: the inspector counts what physically arrived against what the supplier declared."""
    if not _is_inspector(user):
        raise Forbidden("Only the warehouse inspector can record arrivals")
    s = _row(conn, shipment_id)
    _check_visible(conn, user, s)
    if s["status"] != "Shipped":
        raise DomainError(f"Shipment is already {s['status']}")
    shipped = {
        r["item_code"].upper(): r["quantity_shipped"]
        for r in conn.execute(
            "SELECT item_code, quantity_shipped FROM shipment_items WHERE shipment_id = ?",
            (shipment_id,),
        )
    }
    if s["unit_level"]:  # every scanned unit counts as received; the rest are missing
        from . import units as units_svc

        got = units_svc.close_arrival(conn, shipment_id)
        received = {code: got.get(code, 0) for code in shipped}
    else:
        received = {ln["item_code"].strip().upper(): ln["quantity_received"] for ln in lines}
    if set(received) != set(shipped):
        raise DomainError(
            f"Enter the received quantity for every shipped item: {', '.join(sorted(shipped))}"
        )
    for code, qty in received.items():
        if qty < 0 or qty > shipped[code]:
            raise DomainError(
                f"{code}: received quantity must be between 0 and the shipped {shipped[code]}"
            )
    for code, qty in received.items():
        conn.execute(
            "UPDATE shipment_items SET quantity_received = ? WHERE shipment_id = ? AND item_code = ? COLLATE NOCASE",
            (qty, shipment_id, code),
        )
    conn.execute(
        "UPDATE shipments SET status = 'Arrived', arrived_at = ?, arrived_by = ?, inspection_notes = ? WHERE id = ?",
        (now(), user["id"], notes.strip(), shipment_id),
    )
    audit(
        conn,
        user["id"],
        "arrival",
        "shipment",
        s["shipment_no"],
        ", ".join(f"{c}={q}" for c, q in received.items()),
    )
    po = _po(conn, s["po_id"])
    short = [
        f"{c}: received {received[c]} of {shipped[c]} (short by {shipped[c] - received[c]})"
        for c in shipped
        if received[c] < shipped[c]
    ]
    body = (
        f"Shipment {s['shipment_no']} for {po['po_number']} has arrived and is awaiting inspection."
    )
    if short:
        body += (
            "\n\nQuantity check found a shortfall:\n- "
            + "\n- ".join(short)
            + "\nPlease explain the difference and send the missing units."
        )
        audit(
            conn,
            user["id"],
            "shortfall",
            "purchase_order",
            po["po_number"],
            f"{s['shipment_no']}: " + "; ".join(short),
        )
    _tell_supplier_and_buyer(
        conn,
        po,
        f"Shipment {s['shipment_no']} arrived" + (" with a quantity shortfall" if short else ""),
        body,
    )
    return get_shipment(conn, user, shipment_id)


def inspect(
    conn: sqlite3.Connection,
    user: dict,
    shipment_id: int,
    decision: str,
    notes: str = "",
    reason: str = "",
    checks: dict | None = None,
    improvement: str = "",
    override_reason: str = "",
) -> dict:
    """Quality check and decision. Approve needs every quality check to pass; reject needs a reason and a photo.
    A rejection tells the supplier exactly what to improve and to fulfil the order with a replacement."""
    if not _is_inspector(user):
        raise Forbidden("Only the warehouse inspector can approve or reject a shipment")
    s = _row(conn, shipment_id)
    _check_visible(conn, user, s)
    if s["status"] != "Arrived":
        raise DomainError(
            "Record the arrival before inspecting"
            if s["status"] == "Shipped"
            else f"Shipment is already {s['status']}"
        )
    if s["unit_level"]:
        from . import units as units_svc

        return units_svc.decide(
            conn, user, s, decision, notes, reason, improvement, override_reason
        )
    checks = _clean_checks(checks)
    po = _po(conn, s["po_id"])
    erp = get_connector(po["erp"])
    ship = _hydrate(conn, s)
    lines = [
        {"item_code": i["item_code"], "quantity": i["quantity_received"] or 0}
        for i in ship["items"]
        if (i["quantity_received"] or 0) > 0
    ]
    checks_json = json.dumps(checks)
    notes = (notes or s["inspection_notes"] or "").strip()

    if decision == "approve":
        not_passed = [label for k, label in QUALITY_CHECKS.items() if checks.get(k) is not True]
        if not_passed:
            raise DomainError(
                "All quality checks must pass to approve. Not passed: "
                + ", ".join(not_passed)
                + ". Reject the shipment if the goods are not acceptable."
            )
        movement = erp.release_stock(po, ship, lines)["movement_ref"] if lines else None
        for ln in lines:
            inventory_svc.receive_stock(conn, ln["item_code"], ln["quantity"])
        conn.execute(
            "UPDATE shipments SET status = 'Approved', inspected_at = ?, inspected_by = ?, inspection_notes = ?, quality_checks = ?, erp_movement_ref = ? WHERE id = ?",
            (now(), user["id"], notes, checks_json, movement, shipment_id),
        )
        remaining = _remaining(conn, po["id"])
        delivered = not remaining
        conn.execute(
            "UPDATE purchase_orders SET delivery_status = ? WHERE id = ?",
            ("Delivered" if delivered else "In Transit", po["id"]),
        )
        if delivered and po["invoice_hold"]:
            erp.set_invoice_hold(po, False)
            conn.execute(
                "UPDATE purchase_orders SET invoice_hold = 0, invoice_hold_reason = '' WHERE id = ?",
                (po["id"],),
            )
        audit(conn, user["id"], "approve", "shipment", s["shipment_no"], f"movement={movement}")
        text = f"Shipment {s['shipment_no']} for {po['po_number']} passed the quantity and quality checks and the stock was released."
        if delivered:
            text += " The order is now fully delivered and can proceed to closing."
        else:
            text += (
                "\n\nThe order is only partly delivered. Still to fulfil:\n- "
                + "\n- ".join(f"{q} x {c}" for c, q in remaining.items())
                + "\nPlease ship the remaining quantity."
            )
        _tell_supplier_and_buyer(conn, po, f"Shipment {s['shipment_no']} approved", text)

    elif decision == "reject":
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise DomainError("A rejection reason is required")
        if not conn.execute(
            "SELECT 1 FROM shipment_files WHERE shipment_id = ? AND kind = 'photo'", (shipment_id,)
        ).fetchone():
            raise DomainError("Attach at least one photo of the problem before rejecting")
        improvement = (improvement or "").strip()
        failed = [label for k, label in QUALITY_CHECKS.items() if checks.get(k) is False]
        movement = erp.quarantine_stock(po, ship, lines, reason)["movement_ref"] if lines else None
        erp.set_invoice_hold(po, True, reason)
        conn.execute(
            "UPDATE shipments SET status = 'Rejected', inspected_at = ?, inspected_by = ?, inspection_notes = ?, rejection_reason = ?, "
            "quality_checks = ?, improvement_request = ?, erp_movement_ref = ? WHERE id = ?",
            (now(), user["id"], notes, reason, checks_json, improvement, movement, shipment_id),
        )
        active = conn.execute(
            "SELECT 1 FROM shipments WHERE po_id = ? AND status IN ('Shipped','Arrived')",
            (po["id"],),
        ).fetchone()
        conn.execute(
            "UPDATE purchase_orders SET delivery_status = ?, invoice_hold = 1, invoice_hold_reason = ? WHERE id = ?",
            ("In Transit" if active else "Rejected", reason, po["id"]),
        )
        audit(
            conn,
            user["id"],
            "reject",
            "shipment",
            s["shipment_no"],
            f"{reason}; quarantine={movement}",
        )
        text = f"Shipment {s['shipment_no']} for {po['po_number']} failed inspection.\n\nReason: {reason}"
        if failed:
            text += "\n\nQuality checks not passed:\n- " + "\n- ".join(failed)
        if improvement:
            text += f"\n\nWhat needs to improve:\n{improvement}"
        text += "\n\nThe goods are in quarantine and the invoice is on hold. Please correct the issue and ship a replacement to fulfil the order."
        _tell_supplier_and_buyer(
            conn, po, f"Shipment {s['shipment_no']} rejected: improvement required", text
        )
    else:
        raise DomainError("decision must be 'approve' or 'reject'")
    return get_shipment(conn, user, shipment_id)
