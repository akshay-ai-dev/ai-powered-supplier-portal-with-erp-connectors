"""Form flows the in-app assistant can walk a user through.

A flow is a list of steps (computed from the answers so far, so later questions can depend on earlier
ones) plus a `submit` that calls the same service function the web form calls. The generic machinery
(parsing, paging, back/cancel, summary) lives in engine.py.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.schemas import QuoteIn, RequirementCreate, ShipmentCreate
from app.services import inventory as inventory_svc
from app.services import purchase_orders as po_svc
from app.services import ranking
from app.services import requirements as req_svc
from app.services import shipments as ship_svc
from app.services import suppliers as suppliers_svc
from app.services.errors import DomainError, NotFound


@dataclass
class Option:
    value: Any  # JSON-serialisable: str, int or None
    label: str


@dataclass
class Ctx:
    conn: sqlite3.Connection
    user: dict
    values: dict = field(default_factory=dict)
    tz_offset: int = 0  # browser getTimezoneOffset(): minutes to add to local time to get UTC


@dataclass
class Step:
    key: str
    label: str  # short name used in the summary
    prompt: str
    kind: str  # text | int | number | date | datetime | choice | multichoice | file
    optional: bool = False
    default: Any = None
    hint: str = ""
    min: float | None = None
    max: float | None = None
    options: Callable[[Ctx], list[Option]] | None = None
    empty: str = "There is nothing to choose from right now."


@dataclass
class Flow:
    id: str
    title: str
    description: str
    roles: tuple[str, ...]
    steps: Callable[[Ctx], list[Step]]
    submit: Callable[[Ctx], dict]
    warning: str = ""  # shown with the summary for actions that cannot be undone
    readonly: bool = False  # a look-up: no summary to confirm, it finishes (with a link) once the last question is answered
    # extra (label, value) rows for the summary, computed from the answers (e.g. the exact ERP call)
    details: Callable[[Ctx], list[tuple[str, str]]] | None = None


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors():
        where = ".".join(str(p) for p in e["loc"])
        parts.append(f"{where}: {e['msg']}".replace("Value error, ", ""))
    return "; ".join(parts)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------ new requirement (buyer, admin)
def _item_options(ctx: Ctx) -> list[Option]:
    items = inventory_svc.list_items(ctx.conn, user=ctx.user) if ctx.user["role"] != "admin" else []
    return [Option(None, "Something else (I will describe it)")] + [
        Option(
            i["item_code"],
            f"{i['item_code']} - {i['description']} ({i['stock_quantity']} in stock)",
        )
        for i in items
    ]


def _supplier_options(ctx: Ctx) -> list[Option]:
    return [Option(s["id"], s["supplier_name"]) for s in suppliers_svc.list_suppliers(ctx.conn)]


REQ_ITEM = Step(
    "item",
    "Item",
    "Is this an item we already stock? Pick it, or choose 1 to describe something new.",
    "choice",
    options=_item_options,
)
REQ_TITLE = Step(
    "title",
    "What you need",
    "What do you need? Describe it in a few words, for example 50 laptops.",
    "text",
    max=200,
)
REQ_QTY = Step("quantity", "Quantity", "How many do you need?", "int", min=1, max=1_000_000)
REQ_PRICE = Step(
    "target_price",
    "Target price",
    "Target price per unit? (optional)",
    "number",
    optional=True,
    min=0,
    hint="Type # to skip.",
)
REQ_NEEDED = Step(
    "needed_by",
    "Needed by",
    "Needed by which date? (optional, YYYY-MM-DD)",
    "date",
    optional=True,
    hint="Type # to skip.",
)
REQ_ERP = Step(
    "erp",
    "ERP",
    "Which ERP will this order go through?",
    "choice",
    options=lambda ctx: [Option("sap", "SAP"), Option("infor", "Infor LN")],
)
REQ_AUDIENCE = Step(
    "audience",
    "Audience",
    "Who should see this requirement?",
    "choice",
    options=lambda ctx: [
        Option("open", "Open to all suppliers (also ones that join later)"),
        Option("all", "All current suppliers (invite them)"),
        Option("pick", "Only suppliers I choose"),
    ],
)
REQ_SUPPLIERS = Step(
    "suppliers",
    "Invited suppliers",
    "Which suppliers? Type their numbers separated by commas (for example 1,3) or all.",
    "multichoice",
    options=_supplier_options,
    empty="There are no suppliers to invite yet.",
)
REQ_DEADLINE = Step(
    "deadline",
    "Quote deadline",
    "Until when can suppliers send quotes?",
    "choice",
    options=lambda ctx: [
        Option("7d", "In 7 days"),
        Option("3d", "In 3 days"),
        Option("custom", "I will pick a date and time"),
        Option("none", "No deadline"),
    ],
)
REQ_DEADLINE_AT = Step(
    "deadline_at",
    "Deadline at",
    "Deadline date and time (your local time), for example 2026-11-30 17:00.",
    "datetime",
)
REQ_DESC = Step(
    "description",
    "Details",
    "Anything else suppliers should know? (optional)",
    "text",
    optional=True,
    max=2000,
    hint="Type # to skip.",
)


def _requirement_steps(ctx: Ctx) -> list[Step]:
    v = ctx.values
    steps = [REQ_ITEM]
    if "item" in v and v["item"] is None:
        steps.append(REQ_TITLE)
    steps += [REQ_QTY, REQ_PRICE, REQ_NEEDED, REQ_ERP, REQ_AUDIENCE]
    if v.get("audience") == "pick":
        steps.append(REQ_SUPPLIERS)
    steps.append(REQ_DEADLINE)
    if v.get("deadline") == "custom":
        steps.append(REQ_DEADLINE_AT)
    steps.append(REQ_DESC)
    return steps


def _submit_requirement(ctx: Ctx) -> dict:
    v = ctx.values
    title = v.get("title")
    if v.get("item"):
        title = inventory_svc.get_item(ctx.conn, v["item"], ctx.user)["description"]
    deadline = {
        "7d": _iso(datetime.now(UTC) + timedelta(days=7)),
        "3d": _iso(datetime.now(UTC) + timedelta(days=3)),
        "custom": v.get("deadline_at"),
        "none": None,
    }[v["deadline"]]
    try:
        payload = RequirementCreate(
            title=title or "",
            description=v.get("description") or "",
            item_code=v.get("item"),
            quantity=v["quantity"],
            target_price=v.get("target_price"),
            needed_by=v.get("needed_by"),
            erp=v["erp"],
            quote_deadline=deadline,
            open_to_all=v["audience"] == "open",
            supplier_ids=v.get("suppliers") or [],
        ).model_dump()
    except ValidationError as exc:
        raise DomainError(_validation_message(exc)) from None
    req = req_svc.create_requirement(ctx.conn, ctx.user, payload)
    return {"label": f"{req['req_number']} created", "href": f"/requirements/{req['id']}"}


# ------------------------------------------------------------------ submit a quote (supplier)
def _quotable(ctx: Ctx) -> list[dict]:
    return [
        r
        for r in req_svc.list_requirements(ctx.conn, ctx.user)
        if r["status"] == "Open" and not r["quotes_closed"] and not r.get("my_decline")
    ]


def _quote_options(ctx: Ctx) -> list[Option]:
    out = []
    for r in _quotable(ctx):
        label = f"{r['req_number']} - {r['title']} (qty {r['quantity']})"
        if r.get("my_quote"):
            label += f" - you quoted {r['my_quote']['unit_price']:.2f}"
        if r.get("quote_deadline"):
            label += f" - due {r['quote_deadline'][:10]}"
        out.append(Option(r["id"], label))
    return out


def _quote_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "requirement",
            "Requirement",
            "Which requirement do you want to quote on?",
            "choice",
            options=_quote_options,
            empty="There are no open requirements you can quote on right now.",
        ),
        Step("unit_price", "Unit price", "Your price per unit?", "number", min=0, max=1e9),
        Step(
            "lead_time_days",
            "Lead time (days)",
            "Lead time in days? (0 if you can deliver from stock)",
            "int",
            min=0,
            max=730,
        ),
        Step(
            "message",
            "Message",
            "A note for the buyer? (optional)",
            "text",
            optional=True,
            max=1000,
            hint="Type # to skip.",
        ),
    ]


def _submit_quote(ctx: Ctx) -> dict:
    v = ctx.values
    try:
        data = QuoteIn(
            unit_price=v["unit_price"],
            lead_time_days=v["lead_time_days"],
            message=v.get("message") or "",
        ).model_dump()
    except ValidationError as exc:
        raise DomainError(_validation_message(exc)) from None
    req = req_svc.submit_quote(ctx.conn, ctx.user, v["requirement"], data)
    return {"label": f"Quote sent on {req['req_number']}", "href": f"/requirements/{req['id']}"}


# ------------------------------------------------------------------ ship an order (supplier)
def _shippable(ctx: Ctx) -> list[tuple[dict, dict[str, int]]]:
    out = []
    for po in po_svc.list_pos(ctx.conn, ctx.user, status="Approved"):
        if po["delivery_status"] == "Delivered":
            continue
        remaining = ship_svc.remaining_quantities(ctx.conn, po)
        if any(remaining.values()):
            out.append((po, remaining))
    return out


def _po_options(ctx: Ctx) -> list[Option]:
    return [
        Option(
            po["id"],
            f"{po['po_number']} - "
            + ", ".join(f"{i['quantity']} x {i['item_code']}" for i in po["items"]),
        )
        for po, _ in _shippable(ctx)
    ]


def _ship_steps(ctx: Ctx) -> list[Step]:
    steps = [
        Step(
            "po",
            "Order",
            "Which order are you shipping?",
            "choice",
            options=_po_options,
            empty="You have no approved orders waiting to be shipped.",
        )
    ]
    po_id = ctx.values.get("po")
    if po_id is not None:
        try:
            po = po_svc.get_po(ctx.conn, ctx.user, po_id)
        except NotFound:
            raise DomainError("That order is no longer available. Please start again.") from None
        remaining = ship_svc.remaining_quantities(ctx.conn, po)
        for code, left in remaining.items():
            if left > 0:
                steps.append(
                    Step(
                        f"qty:{code}",
                        f"Qty {code}",
                        f"How many {code} are in this shipment? ({left} still to ship)",
                        "int",
                        default=left,
                        min=0,
                        max=left,
                        hint=f"Type # for {left}.",
                    )
                )
    steps += [
        Step(
            "carrier",
            "Carrier",
            "Which carrier?",
            "text",
            max=80,
            hint="Enter the carrier or courier name.",
        ),
        Step(
            "tracking_no",
            "Tracking number",
            "What is the tracking number?",
            "text",
            max=80,
            hint="Enter the shipment tracking number.",
        ),
        Step(
            "expected_arrival",
            "Expected arrival",
            "Expected arrival date? (optional, YYYY-MM-DD)",
            "date",
            optional=True,
            hint="Type # to skip.",
        ),
        Step(
            "notes",
            "Notes",
            "Any notes for the warehouse? (optional)",
            "text",
            optional=True,
            max=1000,
            hint="Type # to skip.",
        ),
        Step(
            "packing_list",
            "Packing list",
            "Attach your packing list? Choose a file, or type # to skip.",
            "file",
            optional=True,
        ),
    ]
    return steps


def _submit_shipment(ctx: Ctx) -> dict:
    v = ctx.values
    items = [
        {"item_code": k.split(":", 1)[1], "quantity": q}
        for k, q in v.items()
        if k.startswith("qty:") and q > 0
    ]
    if not items:
        raise DomainError("Enter a quantity for at least one item (go back to change it).")
    try:
        data = ShipmentCreate(
            carrier=v.get("carrier") or "",
            tracking_no=v.get("tracking_no") or "",
            expected_arrival=v.get("expected_arrival"),
            notes=v.get("notes") or "",
            items=items,
        ).model_dump()
    except ValidationError as exc:
        raise DomainError(_validation_message(exc)) from None
    shipment = ship_svc.create_shipment(ctx.conn, ctx.user, v["po"], data)
    result = {
        "label": f"{shipment['shipment_no']} submitted",
        "href": f"/shipments/{shipment['id']}",
    }
    if v.get("packing_list"):
        result["upload"] = f"/api/shipments/{shipment['id']}/files?kind=packing_list"
    return result


# ------------------------------------------------------------------ award a supplier (buyer, admin)
def _awardable(ctx: Ctx) -> list[dict]:
    return [
        r
        for r in req_svc.list_requirements(ctx.conn, ctx.user)
        if r["status"] == "Open" and r["quote_count"] > 0
    ]


def _ranked(req: dict) -> list[dict]:
    """The requirement's open quotes in SRS order (ranking.rank_quotes): on time first, then lowest
    total, then earliest delivery. The same order the AI Assistant's compare and draft-award answers use."""
    return ranking.rank_quotes(req, [q for q in req["quotes"] if q["status"] == "Submitted"])


def _day(iso: str | None) -> str:
    if not iso:
        return "no date"
    d = datetime.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _award_requirement_options(ctx: Ctx) -> list[Option]:
    out = []
    for r in _awardable(ctx):
        ranked = _ranked(req_svc.get_requirement(ctx.conn, ctx.user, r["id"]))
        top = (
            f", top {ranked[0]['supplier_name']} {ranked[0]['total_price']:,.2f}" if ranked else ""
        )
        closed = " - quotes closed" if r["quotes_closed"] else ""
        out.append(
            Option(
                r["id"],
                f"{r['req_number']} - {r['title']} (qty {r['quantity']}, {r['quote_count']} quote(s){top}){closed}",
            )
        )
    return out


def _award_quote_options(ctx: Ctx) -> list[Option]:
    req_id = ctx.values.get("requirement")
    if req_id is None:
        return []
    req = req_svc.get_requirement(ctx.conn, ctx.user, req_id)
    messages = {q["id"]: q["message"] for q in req["quotes"]}
    out = []
    for r in _ranked(req):
        timing = "on time" if r["meets_need_by"] else "late"
        label = (
            f"#{r['rank']} {r['supplier_name']}: {r['unit_price']:,.2f} each = {r['total_price']:,.2f} total, "
            f"delivery {_day(r['promised_date'])} ({timing})"
        )
        if messages.get(r["quote_id"]):
            label += f' - "{messages[r["quote_id"]][:60]}"'
        out.append(Option(r["quote_id"], label))
    return out


def _award_details(ctx: Ctx) -> list[tuple[str, str]]:
    """The exact ERP call the award makes (SRS §6.3 "Show the facts"), mirroring requirements.award()."""
    req = req_svc.get_requirement(ctx.conn, ctx.user, ctx.values["requirement"])
    chosen = next((r for r in _ranked(req) if r["quote_id"] == ctx.values["quote"]), None)
    if chosen is None:
        return []
    erp = "Infor LN" if req["erp"] == "infor" else req["erp"].upper()
    item = req["item_code"] or f"REQ{req['id']}"
    return [
        (
            "ERP call",
            f"{erp} · Create purchase order · {chosen['supplier_name']} · {item} · "
            f"{req['quantity']} × {chosen['unit_price']:,.2f} = {chosen['total_price']:,.2f}",
        )
    ]


def _award_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "requirement",
            "Requirement",
            "Which requirement do you want to award?",
            "choice",
            options=_award_requirement_options,
            empty="None of your requirements has quotes to award yet.",
        ),
        Step(
            "quote",
            "Winning quote",
            "Which quote wins? (ranked: on time first, then lowest total, then earliest delivery)",
            "choice",
            options=_award_quote_options,
            empty="This requirement has no quotes to award.",
        ),
    ]


def _submit_award(ctx: Ctx) -> dict:
    req = req_svc.award(ctx.conn, ctx.user, ctx.values["requirement"], ctx.values["quote"])
    return {
        "label": f"{req['req_number']} awarded. Purchase order {req['po_number']} created and waiting for your approval",
        "href": f"/requirements/{req['id']}",
    }


# ------------------------------------------------------------------ approve a purchase order (buyer, admin)
def _approvable(ctx: Ctx) -> list[dict]:
    return po_svc.list_pos(ctx.conn, ctx.user, status="Pending")


def _approve_options(ctx: Ctx) -> list[Option]:
    return [
        Option(
            po["id"],
            f"{po['po_number']} - {po['supplier_name']} - {po['total_amount']:,.2f} total ("
            + ", ".join(
                f"{i['quantity']} x {i['item_code']} @ {i['unit_price']:,.2f}" for i in po["items"]
            )
            + f") via {po['erp'].upper()}",
        )
        for po in _approvable(ctx)
    ]


def _approve_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "po",
            "Purchase order",
            "Which purchase order do you want to approve?",
            "choice",
            options=_approve_options,
            empty="You have no purchase orders waiting for approval.",
        )
    ]


def _submit_approval(ctx: Ctx) -> dict:
    po = po_svc.update_po(ctx.conn, ctx.user, ctx.values["po"], {"status": "Approved"})
    return {
        "label": f"{po['po_number']} approved and sent to {po['erp'].upper()} (reference {po['erp_reference']}). The supplier has been told",
        "href": f"/purchase-orders/{po['id']}",
    }


# ------------------------------------------------------------------ inspector: deliveries and look-ups
# Deliveries that carry QR unit codes are received and tested unit by unit by scanning, so the chat only
# handles lot-level deliveries. Rejecting needs a photo, so that stays on the shipment page.
def _lot_shipments(ctx: Ctx, status: str) -> list[dict]:
    return [
        s
        for s in ship_svc.list_shipments(ctx.conn, ctx.user, status=status)
        if not s.get("unit_level")
    ]


def _shipment_or_gone(ctx: Ctx, shipment_id: Any) -> dict:
    try:
        return ship_svc.get_shipment(ctx.conn, ctx.user, shipment_id)
    except NotFound:
        raise DomainError("That delivery is no longer available. Please start again.") from None


def _due(s: dict) -> str:
    return f" - due {s['expected_arrival'][:10]}" if s.get("expected_arrival") else ""


def _arrival_options(ctx: Ctx) -> list[Option]:
    return [
        Option(
            s["id"],
            f"{s['shipment_no']} - {s['po_number']} - {s['supplier_name']} - "
            + ", ".join(f"{i['quantity_shipped']} x {i['item_code']}" for i in s["items"])
            + _due(s),
        )
        for s in _lot_shipments(ctx, "Shipped")
    ]


def _arrival_steps(ctx: Ctx) -> list[Step]:
    steps = [
        Step(
            "shipment",
            "Delivery",
            "Which delivery has arrived?",
            "choice",
            options=_arrival_options,
            empty="No deliveries are waiting to arrive. (Deliveries with QR unit codes are received by scanning them on the Shipments page.)",
        )
    ]
    if ctx.values.get("shipment") is not None:
        for i in _shipment_or_gone(ctx, ctx.values["shipment"])["items"]:
            n = i["quantity_shipped"]
            steps.append(
                Step(
                    f"recv:{i['item_code']}",
                    f"Received {i['item_code']}",
                    f"How many {i['item_code']} actually arrived? ({n} were shipped)",
                    "int",
                    default=n,
                    min=0,
                    max=n,
                    hint=f"Type # for {n}.",
                )
            )
    steps.append(
        Step(
            "notes",
            "Notes",
            "Any notes about the delivery? (optional)",
            "text",
            optional=True,
            max=1000,
            hint="Type # to skip.",
        )
    )
    return steps


def _submit_arrival(ctx: Ctx) -> dict:
    v = ctx.values
    lines = [
        {"item_code": k.split(":", 1)[1], "quantity_received": q}
        for k, q in v.items()
        if k.startswith("recv:")
    ]
    s = ship_svc.record_arrival(ctx.conn, ctx.user, v["shipment"], lines, v.get("notes") or "")
    short = any((i["quantity_received"] or 0) < i["quantity_shipped"] for i in s["items"])
    note = (
        " with a quantity shortfall. The supplier and buyer have been told"
        if short
        else ". It is ready to be inspected"
    )
    return {
        "label": f"{s['shipment_no']} recorded as arrived{note}",
        "href": f"/shipments/{s['id']}",
    }


def _verify_options(ctx: Ctx) -> list[Option]:
    return [
        Option(
            s["id"],
            f"{s['shipment_no']} - {s['po_number']} - {s['supplier_name']} - arrived: "
            + ", ".join(
                f"{i['quantity_received']} of {i['quantity_shipped']} {i['item_code']}"
                for i in s["items"]
            ),
        )
        for s in _lot_shipments(ctx, "Arrived")
    ]


def _verify_steps(ctx: Ctx) -> list[Step]:
    yes_no = lambda _ctx: [Option("yes", "Yes"), Option("no", "No")]  # noqa: E731
    steps = [
        Step(
            "shipment",
            "Delivery",
            "Which delivery do you want to approve?",
            "choice",
            options=_verify_options,
            empty="No deliveries are waiting for inspection. (Deliveries with QR unit codes are inspected unit by unit on the Shipments page.)",
        )
    ]
    if ctx.values.get("shipment") is not None:
        _shipment_or_gone(ctx, ctx.values["shipment"])
        steps += [
            Step(f"check:{key}", label, f"{label}?", "choice", options=yes_no)
            for key, label in ship_svc.QUALITY_CHECKS.items()
        ]
        steps.append(
            Step(
                "notes",
                "Notes",
                "Any inspection notes? (optional)",
                "text",
                optional=True,
                max=1000,
                hint="Type # to skip.",
            )
        )
    return steps


def _submit_verification(ctx: Ctx) -> dict:
    v = ctx.values
    checks = {key: v.get(f"check:{key}") == "yes" for key in ship_svc.QUALITY_CHECKS}
    if not all(checks.values()):
        raise DomainError(
            "A delivery can only be approved when every check passes. If something is wrong, reject it from the shipment page: a rejection needs a reason and a photo."
        )
    s = ship_svc.inspect(
        ctx.conn, ctx.user, v["shipment"], "approve", notes=v.get("notes") or "", checks=checks
    )
    return {
        "label": f"{s['shipment_no']} approved and the stock was released. The supplier and buyer have been told",
        "href": f"/shipments/{s['id']}",
    }


def _latest_requirements(ctx: Ctx) -> list[dict]:
    reqs = req_svc.list_requirements(ctx.conn, ctx.user)
    return sorted(reqs, key=lambda r: r["id"], reverse=True)[:5]


def _latest_requirement_options(ctx: Ctx) -> list[Option]:
    return [
        Option(r["id"], f"{r['req_number']} - {r['title']} (qty {r['quantity']}) - {r['stage']}")
        for r in _latest_requirements(ctx)
    ]


def _latest_requirement_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "requirement",
            "Requirement",
            "These are the 5 latest requirements. Pick one to open it, or type * to close.",
            "choice",
            options=_latest_requirement_options,
            empty="There are no requirements yet.",
        )
    ]


def _submit_latest_requirement(ctx: Ctx) -> dict:
    r = next(r for r in _latest_requirements(ctx) if r["id"] == ctx.values["requirement"])
    return {
        "label": f"{r['req_number']}: {r['title']}, qty {r['quantity']}, {r['stage']}",
        "href": f"/requirements/{r['id']}",
    }


SHIPMENT_FILTERS = {
    "incoming": "Incoming - on their way",
    "today": "Arriving today",
    "overdue": "Overdue",
    "inspect": "Arrived - waiting for inspection",
    "done": "Recently inspected",
}


def _filtered_shipments(ctx: Ctx) -> list[dict]:
    f = ctx.values.get("filter")
    # browser getTimezoneOffset() has the opposite sign to "minutes east of UTC"
    tz = -ctx.tz_offset
    if f == "incoming":
        found = ship_svc.list_shipments(ctx.conn, ctx.user, status="Shipped")
    elif f == "today":
        found = ship_svc.list_shipments(ctx.conn, ctx.user, view="arriving_today", tz_minutes=tz)
    elif f == "overdue":
        found = ship_svc.list_shipments(ctx.conn, ctx.user, view="overdue", tz_minutes=tz)
    elif f == "inspect":
        found = ship_svc.list_shipments(ctx.conn, ctx.user, status="Arrived")
    elif f == "done":
        found = ship_svc.list_shipments(
            ctx.conn, ctx.user, status="Approved"
        ) + ship_svc.list_shipments(ctx.conn, ctx.user, status="Rejected")
    else:
        return []
    return sorted(found, key=lambda s: s["id"], reverse=True)[:10]


def _shipment_check_options(ctx: Ctx) -> list[Option]:
    return [
        Option(
            s["id"],
            f"{s['shipment_no']} - {s['po_number']} - {s['supplier_name']} - {s['status']}"
            + (" - QR units" if s.get("unit_level") else "")
            + _due(s),
        )
        for s in _filtered_shipments(ctx)
    ]


def _shipment_check_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "filter",
            "Which shipments",
            "Which shipments do you want to see?",
            "choice",
            options=lambda _ctx: [Option(k, label) for k, label in SHIPMENT_FILTERS.items()],
        ),
        Step(
            "shipment",
            "Shipment",
            "Pick one to open it, or type * to close.",
            "choice",
            options=_shipment_check_options,
            empty="There are no shipments in that group right now.",
        ),
    ]


def _submit_shipment_check(ctx: Ctx) -> dict:
    s = next(s for s in _filtered_shipments(ctx) if s["id"] == ctx.values["shipment"])
    tracking = f", tracking {s['tracking_no']}" if s.get("tracking_no") else ""
    return {
        "label": f"{s['shipment_no']}: {s['status']}, {s['po_number']} from {s['supplier_name']}{tracking}",
        "href": f"/shipments/{s['id']}",
    }


def _stock_options(ctx: Ctx) -> list[Option]:
    out = []
    for i in inventory_svc.list_items(ctx.conn, user=ctx.user):
        q = i["stock_quantity"]
        flag = " - OUT OF STOCK" if q <= 0 else " - low stock" if q < 20 else ""
        out.append(
            Option(
                i["item_code"],
                f"{i['item_code']} - {i['description']}: {q} in stock ({i['warehouse']}){flag}",
            )
        )
    return out


def _stock_steps(ctx: Ctx) -> list[Step]:
    return [
        Step(
            "item",
            "Item",
            "Which item? Pick a number, or type part of its name to search.",
            "choice",
            options=_stock_options,
            empty="There are no inventory items yet.",
        )
    ]


def _submit_stock(ctx: Ctx) -> dict:
    label = next(o.label for o in _stock_options(ctx) if o.value == ctx.values["item"])
    return {"label": label, "href": "/inventory"}


FLOWS: dict[str, Flow] = {
    f.id: f
    for f in (
        Flow(
            "new_requirement",
            "New requirement",
            "Post what you need and ask suppliers for quotes.",
            ("buyer", "admin"),
            _requirement_steps,
            _submit_requirement,
        ),
        Flow(
            "award_supplier",
            "Award a supplier",
            "Pick the winning quote on a requirement and create the purchase order.",
            ("buyer", "admin"),
            _award_steps,
            _submit_award,
            warning="Awarding creates the purchase order for this supplier and tells the other suppliers they were not selected. It cannot be undone.",
            details=_award_details,
        ),
        Flow(
            "approve_po",
            "Approve a purchase order",
            "Approve a pending order so it goes to the ERP and the supplier.",
            ("buyer", "admin"),
            _approve_steps,
            _submit_approval,
            warning="Approving sends the order to the ERP and notifies the supplier, who can then ship. It cannot be undone.",
        ),
        Flow(
            "submit_quote",
            "Submit a quote",
            "Answer an open requirement with your price and lead time.",
            ("supplier",),
            _quote_steps,
            _submit_quote,
        ),
        Flow(
            "ship_order",
            "Ship an order",
            "Create a shipment for an approved purchase order.",
            ("supplier",),
            _ship_steps,
            _submit_shipment,
        ),
        Flow(
            "confirm_arrival",
            "Confirm a delivery arrived",
            "Record that a shipment has arrived and how many units you counted.",
            ("inspector",),
            _arrival_steps,
            _submit_arrival,
        ),
        Flow(
            "approve_delivery",
            "Verify and approve a delivery",
            "Check an arrived delivery and approve it so the stock is released.",
            ("inspector",),
            _verify_steps,
            _submit_verification,
            warning="Approving releases the stock to inventory and the ERP and tells the supplier and buyer. It cannot be undone.",
        ),
        Flow(
            "latest_requirements",
            "Latest requirements",
            "See the 5 newest requirements.",
            ("inspector",),
            _latest_requirement_steps,
            _submit_latest_requirement,
            readonly=True,
        ),
        Flow(
            "check_shipments",
            "Check shipments",
            "Incoming, arriving today, overdue, waiting for inspection, or recently inspected.",
            ("inspector",),
            _shipment_check_steps,
            _submit_shipment_check,
            readonly=True,
        ),
        Flow(
            "check_stock",
            "Check stock",
            "Look up how much of an item is in stock.",
            ("inspector",),
            _stock_steps,
            _submit_stock,
            readonly=True,
        ),
    )
}


def flows_for(user: dict) -> list[Flow]:
    return [f for f in FLOWS.values() if user["role"] in f.roles]
