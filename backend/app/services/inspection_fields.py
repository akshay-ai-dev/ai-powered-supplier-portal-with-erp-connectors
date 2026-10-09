"""Test fields the inspector defines while inspecting a delivery.

Besides the four standard checks, the inspector can add a field on the spot ("Voltage", "Weight", "Seal intact").
A field belongs to one shipment (optionally limited to one item) and can also be saved as a template, so the next
shipment of that item starts with it. Values live on each unit as JSON ({field id: value}); this module knows how
to read, validate and judge a value.

  pass_fail  "pass" or "fail"; a fail makes the unit faulty
  number     a measurement; outside the optional min/max tolerance is a fail
  text       information only; never fails
"""

import math
import sqlite3

from ..db import now
from . import shipments as ship_svc
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit

TYPES = ("pass_fail", "number", "text")
EDITABLE_STATUSES = ("Shipped", "Arrived")  # fields can change until the lot is decided


def _is_inspector(user: dict) -> bool:
    return user["role"] == "inspector"


def _dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("required", "is_template", "archived"):
        d[k] = bool(d[k])
    return d


def shipment_fields(
    conn: sqlite3.Connection, shipment_id: int, include_archived: bool = False
) -> list[dict]:
    sql = (
        "SELECT * FROM inspection_fields WHERE shipment_id = ?"
        + ("" if include_archived else " AND archived = 0")
        + " ORDER BY id"
    )
    return [_dict(r) for r in conn.execute(sql, (shipment_id,))]


def applies(field: dict, item_code: str) -> bool:
    return not field["item_code"] or field["item_code"].upper() == item_code.upper()


def get_field(conn: sqlite3.Connection, shipment_id: int, field_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM inspection_fields WHERE id = ? AND shipment_id = ?", (field_id, shipment_id)
    ).fetchone()
    if row is None:
        raise NotFound("Test field not found")
    return _dict(row)


# ------------------------------------------------------------------ values
def parse_value(field: dict, raw) -> float | str | None:
    """Turn what was typed or sent into the stored value. None or "" clears the value."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    name = field["label"]
    if field["type"] == "pass_fail":
        text = str(raw).strip().lower()
        if text in ("pass", "ok", "yes", "true", "1"):
            return "pass"
        if text in ("fail", "no", "false", "0"):
            return "fail"
        raise DomainError(f"{name}: choose pass or fail")
    if field["type"] == "number":
        if isinstance(raw, bool):
            raise DomainError(f"{name}: enter a number")
        try:
            value = float(str(raw).replace(",", ".").strip())
        except ValueError:
            raise DomainError(f"{name}: enter a number") from None
        if math.isnan(value) or math.isinf(value):
            raise DomainError(f"{name}: enter a number")
        return value
    text = str(raw).strip()
    if len(text) > 200:
        raise DomainError(f"{name}: keep it under 200 characters")
    return text


def evaluate(field: dict, value) -> str | None:
    """'pass', 'fail', or None when no value is recorded."""
    if value is None:
        return None
    if field["type"] == "pass_fail":
        return "pass" if value == "pass" else "fail"
    if field["type"] == "number":
        lo, hi = field["min_value"], field["max_value"]
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            return "fail"
    return "pass"


def tolerance_text(field: dict) -> str:
    lo, hi, u = field["min_value"], field["max_value"], field["unit_label"]
    if lo is None and hi is None:
        return ""
    unit = f" {u}" if u else ""
    if lo is not None and hi is not None:
        return f"{lo:g} to {hi:g}{unit}"
    return f"at least {lo:g}{unit}" if lo is not None else f"at most {hi:g}{unit}"


def values_recorded(conn: sqlite3.Connection, shipment_id: int, field_id: int) -> int:
    import json

    n = 0
    for r in conn.execute(
        "SELECT readings FROM shipment_units WHERE shipment_id = ?", (shipment_id,)
    ):
        if str(field_id) in json.loads(r["readings"] or "{}"):
            n += 1
    return n


# ------------------------------------------------------------------ managing fields
def _check_edit(conn: sqlite3.Connection, user: dict, shipment_id: int) -> sqlite3.Row:
    if not _is_inspector(user):
        raise Forbidden("Only an inspector can add or change test fields")
    s = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if s is None:
        raise NotFound("Shipment not found")
    ship_svc._check_visible(
        conn, user, s
    )  # a buyer's own inspector cannot touch another buyer's shipment
    if not s["unit_level"]:
        raise DomainError("This shipment is not inspected unit by unit")
    if s["status"] not in EDITABLE_STATUSES:
        raise DomainError("The lot has been decided; test fields can no longer change")
    return s


def _clean(data: dict, current: dict | None = None) -> dict:
    out = dict(current or {})
    for key in ("label", "type", "unit_label", "min_value", "max_value", "required"):
        if (
            key in data
            and data[key] is not None
            or (key in ("min_value", "max_value") and key in data)
        ):
            out[key] = data[key]
    label = (out.get("label") or "").strip()
    if not label or len(label) > 80:
        raise DomainError("Give the field a name of up to 80 characters")
    if out.get("type") not in TYPES:
        raise DomainError(f"type must be one of {TYPES}")
    out["label"], out["unit_label"] = label, (out.get("unit_label") or "").strip()[:20]
    lo, hi = out.get("min_value"), out.get("max_value")
    if out["type"] != "number":
        out["min_value"] = out["max_value"] = None
        out["unit_label"] = ""
    elif lo is not None and hi is not None and lo > hi:
        raise DomainError("The minimum tolerance cannot be above the maximum")
    out["required"] = bool(out.get("required"))
    return out


def create_field(conn: sqlite3.Connection, user: dict, shipment_id: int, data: dict) -> dict:
    s = _check_edit(conn, user, shipment_id)
    f = _clean(data)
    item = (data.get("item_code") or "").strip().upper() or None
    if (
        item
        and not conn.execute(
            "SELECT 1 FROM shipment_items WHERE shipment_id = ? AND item_code = ? COLLATE NOCASE",
            (shipment_id, item),
        ).fetchone()
    ):
        raise DomainError(f"{item} is not part of this shipment")
    if data.get("save_template") and not item:
        raise DomainError(
            "Choose the item this field belongs to before saving it for future deliveries"
        )
    if any(
        x["label"].lower() == f["label"].lower() and (x["item_code"] or "") == (item or "")
        for x in shipment_fields(conn, shipment_id)
    ):
        raise DomainError(f"A test field named '{f['label']}' already exists")
    cols = (
        f["label"],
        f["type"],
        f["unit_label"],
        f["min_value"],
        f["max_value"],
        1 if f["required"] else 0,
        user["id"],
        now(),
    )
    cur = conn.execute(
        "INSERT INTO inspection_fields (shipment_id, item_code, label, type, unit_label, min_value, max_value, required, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (shipment_id, item, *cols),
    )
    if data.get("save_template"):  # kept for this buyer's future shipments of the item only
        buyer = conn.execute(
            "SELECT created_by FROM purchase_orders WHERE id = ?", (s["po_id"],)
        ).fetchone()["created_by"]
        conn.execute(
            "INSERT INTO inspection_fields (shipment_id, item_code, label, type, unit_label, min_value, max_value, required, is_template, buyer_id, created_by, created_at) VALUES (NULL,?,?,?,?,?,?,?,1,?,?,?)",
            (item, *cols[:6], buyer, *cols[6:]),
        )
    audit(
        conn,
        user["id"],
        "field",
        "shipment",
        s["shipment_no"],
        f"added '{f['label']}' ({f['type']})"
        + (f" for {item}" if item else "")
        + (", saved as template" if data.get("save_template") else ""),
    )
    return get_field(conn, shipment_id, cur.lastrowid)


def update_field(
    conn: sqlite3.Connection, user: dict, shipment_id: int, field_id: int, changes: dict
) -> dict:
    s = _check_edit(conn, user, shipment_id)
    current = get_field(conn, shipment_id, field_id)
    if (
        "type" in changes
        and changes["type"] != current["type"]
        and values_recorded(conn, shipment_id, field_id)
    ):
        raise DomainError("The type cannot change once values have been recorded")
    merged = _clean(changes, current)
    conn.execute(
        "UPDATE inspection_fields SET label = ?, type = ?, unit_label = ?, min_value = ?, max_value = ?, required = ? WHERE id = ?",
        (
            merged["label"],
            merged["type"],
            merged["unit_label"],
            merged["min_value"],
            merged["max_value"],
            1 if merged["required"] else 0,
            field_id,
        ),
    )
    audit(conn, user["id"], "field", "shipment", s["shipment_no"], f"changed '{current['label']}'")
    return get_field(conn, shipment_id, field_id)


def delete_field(conn: sqlite3.Connection, user: dict, shipment_id: int, field_id: int) -> None:
    s = _check_edit(conn, user, shipment_id)
    f = get_field(conn, shipment_id, field_id)
    if values_recorded(conn, shipment_id, field_id):
        raise DomainError(
            "Values have already been recorded for this field, so it cannot be removed"
        )
    conn.execute("DELETE FROM inspection_fields WHERE id = ?", (field_id,))
    audit(conn, user["id"], "field", "shipment", s["shipment_no"], f"removed '{f['label']}'")


# ------------------------------------------------------------------ templates (reusable per item)
def _own_buyer(user: dict) -> int | None:
    """The buyer an inspector works for; None for company-wide inspectors and admins, who work for every buyer."""
    return user.get("owner_id") if user["role"] == "inspector" else None


def templates(
    conn: sqlite3.Connection, item_code: str | None = None, buyer_id: int | None = None
) -> list[dict]:
    """Saved fields. With a buyer: that buyer's, plus the shared ones that predate per-buyer templates."""
    sql, args = "SELECT * FROM inspection_fields WHERE is_template = 1", []
    if item_code:
        sql += " AND item_code = ? COLLATE NOCASE"
        args.append(item_code)
    if buyer_id is not None:
        sql += " AND (buyer_id = ? OR buyer_id IS NULL)"
        args.append(buyer_id)
    return [_dict(r) for r in conn.execute(sql + " ORDER BY item_code, id", args)]


def visible_templates(
    conn: sqlite3.Connection, user: dict, item_code: str | None = None
) -> list[dict]:
    return templates(conn, item_code, _own_buyer(user)) if _is_inspector(user) else []


def delete_template(conn: sqlite3.Connection, user: dict, template_id: int) -> None:
    if not _is_inspector(user):
        raise Forbidden("Only an inspector can remove saved test fields")
    own = _own_buyer(user)
    cur = conn.execute(
        "DELETE FROM inspection_fields WHERE id = ? AND is_template = 1"
        + ("" if own is None else " AND buyer_id = ?"),
        (template_id,) if own is None else (template_id, own),
    )
    if cur.rowcount == 0:
        raise NotFound("Saved test field not found")
    audit(conn, user["id"], "template", "inspection", str(template_id), "removed")


def copy_templates(
    conn: sqlite3.Connection, shipment_id: int, item_codes: list[str], buyer_id: int
) -> int:
    """Start a new unit-level shipment with the fields saved for its items by the same buyer."""
    n = 0
    for code in dict.fromkeys(c.upper() for c in item_codes):
        for t in templates(conn, code, buyer_id):
            conn.execute(
                "INSERT INTO inspection_fields (shipment_id, item_code, label, type, unit_label, min_value, max_value, required, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    shipment_id,
                    t["item_code"],
                    t["label"],
                    t["type"],
                    t["unit_label"],
                    t["min_value"],
                    t["max_value"],
                    1 if t["required"] else 0,
                    t["created_by"],
                    now(),
                ),
            )
            n += 1
    return n


# ------------------------------------------------------------------ report statistics
def stats(fields: list[dict], units: list[dict]) -> list[dict]:
    """Per field: how many units passed, failed or have no value, plus min / max / average for numbers."""
    out = []
    for f in fields:
        relevant = [
            u
            for u in units
            if applies(f, u["item_code"]) and u["status"] in ("Received", "OK", "Faulty")
        ]
        values = [u["readings"].get(str(f["id"])) for u in relevant]
        recorded = [v for v in values if v is not None]
        results = [evaluate(f, v) for v in recorded]
        row = {
            "id": f["id"],
            "label": f["label"],
            "type": f["type"],
            "unit_label": f["unit_label"],
            "required": f["required"],
            "item_code": f["item_code"],
            "tolerance": tolerance_text(f),
            "units": len(relevant),
            "recorded": len(recorded),
            "not_recorded": len(relevant) - len(recorded),
            "passed": results.count("pass"),
            "failed": results.count("fail"),
        }
        if f["type"] == "number" and recorded:
            row.update(
                min=min(recorded),
                max=max(recorded),
                average=round(sum(recorded) / len(recorded), 3),
            )
        out.append(row)
    return out
