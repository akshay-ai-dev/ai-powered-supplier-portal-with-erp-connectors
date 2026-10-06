"""Unit-by-unit inspection of a delivery.

The supplier ships each item with its own QR code. A unit's life:

  Shipped    created with the shipment; its code is printed on a label
  Received   the inspector scanned it at arrival (unscanned units become Missing when arrival is confirmed)
  OK|Faulty  the inspector tested it: the four standard checks plus any test fields they added
  Missing    never scanned at arrival

When every received unit is tested the lot report says how accurate the delivery was and suggests approve or
reject; the inspector decides (`decide`). Approving with faulty units releases only the OK ones to stock.
"""

import csv
import io
import json
import re
import sqlite3
from collections import Counter, defaultdict
from urllib.parse import unquote

from ..config import settings
from ..connectors import get_connector
from ..db import now
from . import inspection_fields as fields_svc
from . import inventory as inventory_svc
from . import purchase_orders as po_svc
from . import shipments as ship_svc
from .errors import DomainError, Forbidden, NotFound
from .notifications import audit

DEFECT_TYPES = {
    "dimensional": "Dimensional problem",
    "cosmetic": "Cosmetic damage",
    "functional": "Functional failure",
    "wrong_item": "Wrong item",
    "missing_parts": "Missing parts",
    "packaging": "Packaging damage",
    "documentation": "Documentation problem",
    "out_of_tolerance": "Measurement out of tolerance",
    "other": "Other",
}
CHECKS = ship_svc.QUALITY_CHECKS
TESTABLE = ("Received", "OK", "Faulty")
BULK_LIMIT = 2000
CSV_MAX_BYTES = 1_000_000


def _is_inspector(user: dict) -> bool:
    return user["role"] in ("inspector", "admin")


def normalize_code(text: str) -> str:
    """A QR label holds a link (https://host/units/CODE). Scanners and phones may hand us the whole link or just the code."""
    text = (text or "").strip()
    if "://" in text or text.startswith("/"):
        path = re.split(r"[?#]", text, maxsplit=1)[0]
        text = unquote(path.rstrip("/").rsplit("/", 1)[-1])
    return text.strip()


def _load(row: sqlite3.Row) -> dict:
    u = dict(row)
    u["checks"] = json.loads(u["checks"] or "{}")
    u["readings"] = json.loads(u["readings"] or "{}")
    return u


def _shipment(
    conn: sqlite3.Connection, user: dict, shipment_id: int, need_unit_level: bool = True
) -> sqlite3.Row:
    s = ship_svc._row(conn, shipment_id)
    ship_svc._check_visible(conn, user, s)
    if need_unit_level and not s["unit_level"]:
        raise DomainError("This shipment is not inspected unit by unit")
    return s


def _units(conn: sqlite3.Connection, shipment_id: int) -> list[dict]:
    return [
        _load(r)
        for r in conn.execute(
            "SELECT * FROM shipment_units WHERE shipment_id = ? ORDER BY item_code, seq",
            (shipment_id,),
        )
    ]


def _unit_in(conn: sqlite3.Connection, shipment_id: int, code: str) -> dict:
    code = normalize_code(code)
    row = conn.execute(
        "SELECT * FROM shipment_units WHERE shipment_id = ? AND code = ? COLLATE NOCASE",
        (shipment_id, code),
    ).fetchone()
    if row is None:
        other = conn.execute(
            "SELECT s.shipment_no FROM shipment_units u JOIN shipments s ON s.id = u.shipment_id WHERE u.code = ? COLLATE NOCASE",
            (code.strip(),),
        ).fetchone()
        if other:
            raise DomainError(
                f"{code.strip()} belongs to shipment {other['shipment_no']}, not this one"
            )
        raise NotFound(f"No unit with the code {code.strip()}")
    return _load(row)


# ------------------------------------------------------------------ creating units (at shipping)
def create_units(
    conn: sqlite3.Connection, shipment_id: int, shipment_no: str, quantities: dict[str, int]
) -> int:
    rows = []
    for item, qty in quantities.items():
        for seq in range(1, qty + 1):
            rows.append((shipment_id, item, seq, f"{shipment_no}-{item}-{seq:04d}", now()))
    conn.executemany(
        "INSERT INTO shipment_units (shipment_id, item_code, seq, code, created_at) VALUES (?,?,?,?,?)",
        rows,
    )
    return len(rows)


def check_cap(quantities: dict[str, int]) -> None:
    total = sum(quantities.values())
    if total > settings.inspection_max_units:
        raise DomainError(
            f"A shipment can track at most {settings.inspection_max_units} units individually; this one has {total}. Untick the QR code option, or split the shipment."
        )


# ------------------------------------------------------------------ receiving by scanning
def counts(conn: sqlite3.Connection, shipment_id: int) -> dict[str, int]:
    return {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) n FROM shipment_units WHERE shipment_id = ? GROUP BY status",
            (shipment_id,),
        )
    }


def receive(conn: sqlite3.Connection, user: dict, shipment_id: int, code: str) -> dict:
    if not _is_inspector(user):
        raise Forbidden("Only an inspector can receive units")
    s = _shipment(conn, user, shipment_id)
    u = _unit_in(conn, shipment_id, code)
    # a unit that was not scanned before arrival was confirmed counts as missing; it can still be marked present
    # (found late, or simply not scanned) until the lot is decided
    late = s["status"] == "Arrived" and u["status"] == "Missing"
    if s["status"] != "Shipped" and not late:
        raise DomainError(
            "Arrival has already been confirmed for this shipment"
            if s["status"] == "Arrived"
            else "The lot has already been decided"
        )
    if u["status"] != "Shipped" and not late:
        raise DomainError(f"{u['code']} was already received")
    conn.execute(
        "UPDATE shipment_units SET status = 'Received', received_by = ?, received_at = ? WHERE id = ?",
        (user["id"], now(), u["id"]),
    )
    if late:
        conn.execute(
            "UPDATE shipment_items SET quantity_received = COALESCE(quantity_received, 0) + 1 WHERE shipment_id = ? AND item_code = ? COLLATE NOCASE",
            (shipment_id, u["item_code"]),
        )
        po = ship_svc._po(conn, s["po_id"])
        ship_svc._tell_supplier_and_buyer(
            conn,
            po,
            f"Unit {u['code']} was found",
            f"{u['code']} (shipment {s['shipment_no']}, {po['po_number']}) was reported missing at arrival, and the inspector has now marked it received. It still needs to be tested.",
        )
    audit(
        conn,
        user["id"],
        "receive",
        "unit",
        u["code"],
        s["shipment_no"] + (" (marked present after arrival was confirmed)" if late else ""),
    )
    return {
        "unit": _brief(
            _load(conn.execute("SELECT * FROM shipment_units WHERE id = ?", (u["id"],)).fetchone()),
            [],
        ),
        "counts": counts(conn, shipment_id),
    }


def unreceive(conn: sqlite3.Connection, user: dict, shipment_id: int, code: str) -> dict:
    if not _is_inspector(user):
        raise Forbidden("Only an inspector can receive units")
    s = _shipment(conn, user, shipment_id)
    if s["status"] != "Shipped":
        raise DomainError("Arrival has already been confirmed for this shipment")
    u = _unit_in(conn, shipment_id, code)
    if u["status"] != "Received":
        raise DomainError(f"{u['code']} has not been scanned")
    conn.execute(
        "UPDATE shipment_units SET status = 'Shipped', received_by = NULL, received_at = NULL WHERE id = ?",
        (u["id"],),
    )
    audit(conn, user["id"], "unreceive", "unit", u["code"], s["shipment_no"])
    return {"counts": counts(conn, shipment_id)}


def close_arrival(conn: sqlite3.Connection, shipment_id: int) -> dict[str, int]:
    """Called when arrival is confirmed: scanned units are the received quantity, the rest are missing."""
    received: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        "SELECT item_code, status FROM shipment_units WHERE shipment_id = ?", (shipment_id,)
    ):
        if r["status"] == "Received":
            received[r["item_code"].upper()] += 1
    conn.execute(
        "UPDATE shipment_units SET status = 'Missing' WHERE shipment_id = ? AND status = 'Shipped'",
        (shipment_id,),
    )
    return received


# ------------------------------------------------------------------ one unit
def _brief(u: dict, fields: list[dict]) -> dict:
    results = {
        str(f["id"]): fields_svc.evaluate(f, u["readings"].get(str(f["id"])))
        for f in fields
        if fields_svc.applies(f, u["item_code"])
    }
    return {
        "code": u["code"],
        "item_code": u["item_code"],
        "seq": u["seq"],
        "status": u["status"],
        "defect_type": u["defect_type"],
        "defect_label": DEFECT_TYPES.get(u["defect_type"], ""),
        "notes": u["notes"],
        "tested_at": u["tested_at"],
        "readings": u["readings"],
        "field_results": results,
    }


def _full(conn: sqlite3.Connection, user: dict, u: dict, s: sqlite3.Row) -> dict:
    fields = fields_svc.shipment_fields(conn, s["id"], include_archived=True)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}
    ship = ship_svc._hydrate(conn, s)
    readings = []
    for f in fields:
        if not fields_svc.applies(f, u["item_code"]):
            continue
        value = u["readings"].get(str(f["id"]))
        readings.append(
            {
                "field_id": f["id"],
                "label": f["label"],
                "type": f["type"],
                "unit_label": f["unit_label"],
                "tolerance": fields_svc.tolerance_text(f),
                "required": f["required"],
                "archived": f["archived"],
                "value": value,
                "result": fields_svc.evaluate(f, value),
            }
        )
    photos = [
        dict(r)
        for r in conn.execute(
            "SELECT id, kind, filename, size, created_at FROM shipment_files WHERE unit_id = ? ORDER BY id",
            (u["id"],),
        )
    ]
    out = _brief(u, fields)
    out.update(
        checks=[
            {"key": k, "label": label, "passed": u["checks"].get(k)} for k, label in CHECKS.items()
        ],
        field_values=readings,
        photos=photos,
        history=po_svc.history(conn, "unit", u["code"]),
        received_by=names.get(u.get("received_by")),
        received_at=u.get("received_at"),
        tested_by=names.get(u.get("tested_by")),
        shipment={
            "id": s["id"],
            "shipment_no": s["shipment_no"],
            "status": s["status"],
            "po_number": ship["po_number"],
            "supplier_name": ship["supplier_name"],
            "erp": ship["erp"],
        },
        can_test=_is_inspector(user) and s["status"] == "Arrived" and u["status"] in TESTABLE,
        can_receive=_is_inspector(user)
        and (
            (s["status"] == "Shipped" and u["status"] == "Shipped")
            or (s["status"] == "Arrived" and u["status"] == "Missing")
        ),
    )
    return out


def get_unit(conn: sqlite3.Connection, user: dict, code: str) -> dict:
    code = normalize_code(code)
    row = conn.execute(
        "SELECT * FROM shipment_units WHERE code = ? COLLATE NOCASE", (code,)
    ).fetchone()
    if row is None:
        raise NotFound(f"No unit with the code {code}")
    s = ship_svc._row(conn, row["shipment_id"])
    ship_svc._check_visible(conn, user, s)  # others get the same "not found" as for a missing code
    return _full(conn, user, _load(row), s)


# ------------------------------------------------------------------ testing
def _std_checks(raw: dict | None) -> dict[str, bool]:
    raw = raw or {}
    unknown = set(raw) - set(CHECKS)
    if unknown:
        raise DomainError(
            f"Unknown check(s): {', '.join(sorted(unknown))}. Use: {', '.join(CHECKS)}"
        )
    return {k: bool(v) for k, v in raw.items()}


def _plan(u: dict, fields: list[dict], data: dict) -> dict:
    """The unit's new values after applying `data` (result, checks, readings, defect_type, notes), or DomainError.
    Pure: nothing is written, so imports can validate every row before saving any."""
    result = data.get("result")
    if result not in (None, "OK", "Faulty"):
        raise DomainError("result must be OK or Faulty")
    if u["status"] not in TESTABLE:
        raise DomainError(
            f"{u['code']} is {u['status']}: only units that were received can be tested"
        )
    mine = {str(f["id"]): f for f in fields if fields_svc.applies(f, u["item_code"])}
    readings = dict(u["readings"])
    for fid, raw in (data.get("readings") or {}).items():
        f = mine.get(str(fid))
        if f is None:
            raise DomainError(f"{u['code']}: test field {fid} does not apply to this unit")
        value = fields_svc.parse_value(f, raw)
        if value is None:
            readings.pop(str(fid), None)
        else:
            readings[str(fid)] = value
    provided = _std_checks(data.get("checks"))
    checks = {**u["checks"], **provided}
    notes = (data["notes"] if data.get("notes") is not None else u["notes"]).strip()[:1000]
    defect = data["defect_type"] if data.get("defect_type") else u["defect_type"]
    results = {fid: fields_svc.evaluate(f, readings.get(fid)) for fid, f in mine.items()}
    failed = [mine[fid]["label"] for fid, r in results.items() if r == "fail"]
    missing = [
        mine[fid]["label"] for fid, r in results.items() if r is None and mine[fid]["required"]
    ]
    status = u["status"]

    if result == "OK":
        if any(
            v is False for v in provided.values()
        ):  # checks stored by an earlier Faulty result are replaced, not kept
            raise DomainError(
                f"{u['code']}: OK needs all four standard checks to pass. Tag it Faulty instead"
            )
        if missing:
            raise DomainError(f"{u['code']}: record {', '.join(missing)} first (required for OK)")
        if failed:
            raise DomainError(
                f"{u['code']}: {', '.join(failed)} failed, so the unit cannot be OK. Tag it Faulty (defect: measurement out of tolerance)"
            )
        checks, status, defect = {k: True for k in CHECKS}, "OK", ""
    elif result == "Faulty":
        if defect not in DEFECT_TYPES:
            raise DomainError(f"{u['code']}: choose a defect type: {', '.join(DEFECT_TYPES)}")
        status = "Faulty"
    else:
        if status == "OK" and (failed or any(v is False for v in checks.values())):
            raise DomainError(f"{u['code']} is OK but that value fails. Set the result to Faulty")
        if status == "OK" and missing:
            raise DomainError(f"{u['code']} is OK, so {', '.join(missing)} cannot be cleared")
    return {
        "status": status,
        "checks": checks,
        "readings": readings,
        "defect_type": defect,
        "notes": notes,
        "tested": result is not None,
    }


def _apply(conn: sqlite3.Connection, user: dict, u: dict, plan: dict) -> None:
    if plan["tested"]:
        conn.execute(
            "UPDATE shipment_units SET status = ?, checks = ?, readings = ?, defect_type = ?, notes = ?, tested_by = ?, tested_at = ? WHERE id = ?",
            (
                plan["status"],
                json.dumps(plan["checks"]),
                json.dumps(plan["readings"]),
                plan["defect_type"],
                plan["notes"],
                user["id"],
                now(),
                u["id"],
            ),
        )
    else:
        conn.execute(
            "UPDATE shipment_units SET checks = ?, readings = ?, defect_type = ?, notes = ? WHERE id = ?",
            (
                json.dumps(plan["checks"]),
                json.dumps(plan["readings"]),
                plan["defect_type"],
                plan["notes"],
                u["id"],
            ),
        )


def _testing_shipment(conn: sqlite3.Connection, user: dict, shipment_id: int) -> sqlite3.Row:
    if not _is_inspector(user):
        raise Forbidden("Only an inspector can test units")
    s = _shipment(conn, user, shipment_id)
    if s["status"] != "Arrived":
        raise DomainError(
            "Units can be tested after arrival is confirmed and before the lot is decided"
        )
    return s


def record_result(
    conn: sqlite3.Connection, user: dict, shipment_id: int, code: str, data: dict
) -> dict:
    _testing_shipment(conn, user, shipment_id)
    u = _unit_in(conn, shipment_id, code)
    plan = _plan(u, fields_svc.shipment_fields(conn, shipment_id), data)
    _apply(conn, user, u, plan)
    if plan["tested"]:
        audit(
            conn,
            user["id"],
            "test",
            "unit",
            u["code"],
            f"{plan['status']}"
            + (
                f": {DEFECT_TYPES.get(plan['defect_type'], plan['defect_type'])}"
                if plan["status"] == "Faulty"
                else ""
            ),
        )
    else:
        audit(conn, user["id"], "readings", "unit", u["code"], "updated")
    return get_unit(conn, user, u["code"])


def add_photo(
    conn: sqlite3.Connection,
    user: dict,
    shipment_id: int,
    code: str,
    filename: str,
    data: bytes,
    content_type: str | None,
) -> dict:
    u = _unit_in(conn, shipment_id, code)
    return ship_svc.add_file(
        conn, user, shipment_id, "photo", filename, data, content_type, unit_id=u["id"]
    )


def _targets(conn: sqlite3.Connection, shipment_id: int, data: dict) -> list[dict]:
    units = _units(conn, shipment_id)
    if data.get("codes"):
        wanted = {c.strip().upper() for c in data["codes"]}
        units = [u for u in units if u["code"].upper() in wanted]
    elif data.get("item_code"):
        units = [u for u in units if u["item_code"].upper() == data["item_code"].strip().upper()]
    if len(units) > BULK_LIMIT:
        raise DomainError(f"Too many units at once (max {BULK_LIMIT})")
    return units


def bulk(conn: sqlite3.Connection, user: dict, shipment_id: int, data: dict) -> dict:
    """action 'ok': tag the received, untested units OK. action 'set_field': record one value on many units."""
    s = _testing_shipment(conn, user, shipment_id)
    fields = fields_svc.shipment_fields(conn, shipment_id)
    action = data.get("action")
    if action not in ("ok", "set_field"):
        raise DomainError("action must be 'ok' or 'set_field'")
    if not data.get("codes") and not data.get("all_pending") and not data.get("item_code"):
        raise DomainError("Choose the units: send codes, an item_code, or all_pending")
    if action == "set_field":
        if data.get("field_id") is None:
            raise DomainError("field_id is required")
        fields_svc.get_field(conn, shipment_id, data["field_id"])
    updated, skipped = 0, []
    for u in _targets(conn, shipment_id, data):
        if action == "ok":
            if u["status"] != "Received":
                if data.get("codes"):
                    skipped.append(
                        {
                            "code": u["code"],
                            "reason": f"already {u['status']}"
                            if u["status"] in ("OK", "Faulty")
                            else u["status"],
                        }
                    )
                continue
            payload = {"result": "OK"}
        else:
            if u["status"] not in TESTABLE or not fields_svc.applies(
                fields_svc.get_field(conn, shipment_id, data["field_id"]), u["item_code"]
            ):
                continue
            payload = {"readings": {str(data["field_id"]): data.get("value")}}
        try:
            plan = _plan(u, fields, payload)
        except DomainError as exc:
            skipped.append({"code": u["code"], "reason": exc.message})
            continue
        _apply(conn, user, u, plan)
        updated += 1
    audit(
        conn,
        user["id"],
        "bulk",
        "shipment",
        s["shipment_no"],
        f"{action}: {updated} unit(s) updated, {len(skipped)} skipped",
    )
    return {
        "updated": updated,
        "skipped_count": len(skipped),
        "skipped": skipped[:50],
        "counts": counts(conn, shipment_id),
    }


# ------------------------------------------------------------------ listing, labels, CSV
def list_units(
    conn: sqlite3.Connection,
    user: dict,
    shipment_id: int,
    status: str | None = None,
    item_code: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    s = _shipment(conn, user, shipment_id)
    fields = fields_svc.shipment_fields(conn, shipment_id)
    units = _units(conn, shipment_id)
    all_counts = Counter(u["status"] for u in units)
    if status:
        units = [u for u in units if u["status"] == status]
    if item_code:
        units = [u for u in units if u["item_code"].upper() == item_code.upper()]
    if q:
        units = [u for u in units if q.strip().lower() in u["code"].lower()]
    limit = max(1, min(limit, 200))
    return {
        "total": len(units),
        "counts": dict(all_counts),
        "offset": offset,
        "limit": limit,
        "units": [_brief(u, fields) for u in units[offset : offset + limit]],
        "fields": [
            {
                k: f[k]
                for k in (
                    "id",
                    "label",
                    "type",
                    "unit_label",
                    "min_value",
                    "max_value",
                    "required",
                    "item_code",
                )
            }
            | {"tolerance": fields_svc.tolerance_text(f)}
            for f in fields
        ],
        "items": sorted({u["item_code"] for u in _units(conn, shipment_id)}),
        "shipment_status": s["status"],
    }


def labels(conn: sqlite3.Connection, user: dict, shipment_id: int) -> dict:
    s = _shipment(conn, user, shipment_id)
    if user["role"] not in ("supplier", "inspector", "admin"):
        raise NotFound("Shipment not found")
    ship = ship_svc._hydrate(conn, s)
    return {
        "shipment_no": s["shipment_no"],
        "po_number": ship["po_number"],
        "supplier_name": ship["supplier_name"],
        "base_url": settings.public_app_url,
        "units": [
            {"code": u["code"], "item_code": u["item_code"], "seq": u["seq"]}
            for u in _units(conn, shipment_id)
        ],
    }


_YES = {"yes", "y", "true", "1", "pass", "ok"}
_NO = {"no", "n", "false", "0", "fail"}


def export_csv(conn: sqlite3.Connection, user: dict, shipment_id: int) -> str:
    _shipment(conn, user, shipment_id)
    fields = fields_svc.shipment_fields(conn, shipment_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "code",
            "item_code",
            "status",
            "result",
            "defect_type",
            "notes",
            *CHECKS,
            *[f"f_{f['id']}_{f['label']}" for f in fields],
        ]
    )
    for u in _units(conn, shipment_id):
        w.writerow(
            [
                u["code"],
                u["item_code"],
                u["status"],
                u["status"] if u["status"] in ("OK", "Faulty") else "",
                u["defect_type"],
                u["notes"],
                *[
                    ("yes" if u["checks"].get(k) else "no") if k in u["checks"] else ""
                    for k in CHECKS
                ],
                *[
                    u["readings"].get(str(f["id"]), "")
                    if fields_svc.applies(f, u["item_code"])
                    else ""
                    for f in fields
                ],
            ]
        )
    return out.getvalue()


def import_csv(conn: sqlite3.Connection, user: dict, shipment_id: int, raw: bytes) -> dict:
    """All-or-nothing: every row is checked first; one bad row means nothing is saved and the problems are listed."""
    s = _testing_shipment(conn, user, shipment_id)
    if len(raw) > CSV_MAX_BYTES:
        raise DomainError("The file is too large (max 1 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DomainError("The file must be UTF-8 text (CSV)", 415) from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    if "code" not in headers:
        raise DomainError("The CSV needs a 'code' column. Download the units CSV and fill it in")
    fields = fields_svc.shipment_fields(conn, shipment_id)
    field_cols = {}
    for h in headers:
        if h.startswith("f_"):
            try:
                field_cols[h] = str(int(h.split("_")[1]))
            except (IndexError, ValueError):
                raise DomainError(f"Column '{h}' is not a test field column") from None
    errors, plans = [], []
    for n, row in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not row.get("code"):
            continue
        try:
            u = _unit_in(conn, shipment_id, row["code"])
            result = row.get("result", "")
            data: dict = {}
            if result:
                if result.lower() not in ("ok", "faulty"):
                    raise DomainError(f"result '{result}' must be OK or Faulty")
                data["result"] = "OK" if result.lower() == "ok" else "Faulty"
            if row.get("defect_type"):
                data["defect_type"] = row["defect_type"]
            if row.get("notes"):
                data["notes"] = row["notes"]
            checks = {}
            for k in CHECKS:
                v = row.get(k, "").lower()
                if v in _YES:
                    checks[k] = True
                elif v in _NO:
                    checks[k] = False
            if checks:
                data["checks"] = checks
            readings = {fid: row[h] for h, fid in field_cols.items() if row.get(h)}
            if readings:
                data["readings"] = readings
            if not data:
                continue
            if "result" not in data and u["status"] == "Received":
                data = {k: v for k, v in data.items() if k != "defect_type"}
            plans.append((u, _plan(u, fields, data)))
        except DomainError as exc:
            errors.append(f"row {n}: {exc.message}")
    if errors:
        more = f" (and {len(errors) - 20} more)" if len(errors) > 20 else ""
        raise DomainError(
            f"Nothing was imported. {len(errors)} row(s) have problems:\n"
            + "\n".join(errors[:20])
            + more
        )
    for u, plan in plans:
        _apply(conn, user, u, plan)
    audit(
        conn, user["id"], "import", "shipment", s["shipment_no"], f"{len(plans)} unit(s) from CSV"
    )
    return {"updated": len(plans), "counts": counts(conn, shipment_id)}


# ------------------------------------------------------------------ lot report
def compute_report(conn: sqlite3.Connection, s: sqlite3.Row) -> dict:
    fields = fields_svc.shipment_fields(conn, s["id"])
    units = _units(conn, s["id"])
    by_status = Counter(u["status"] for u in units)
    shipped, ok, faulty = len(units), by_status["OK"], by_status["Faulty"]
    received = by_status["Received"] + ok + faulty
    untested = by_status["Received"]
    per_item: dict[str, dict] = {}
    for u in units:
        row = per_item.setdefault(
            u["item_code"],
            {
                "item_code": u["item_code"],
                "shipped": 0,
                "received": 0,
                "ok": 0,
                "faulty": 0,
                "missing": 0,
            },
        )
        row["shipped"] += 1
        if u["status"] in TESTABLE:
            row["received"] += 1
        if u["status"] == "OK":
            row["ok"] += 1
        elif u["status"] == "Faulty":
            row["faulty"] += 1
        elif u["status"] == "Missing":
            row["missing"] += 1
    defects = Counter(u["defect_type"] for u in units if u["status"] == "Faulty")
    failed_checks = Counter(
        k for u in units if u["status"] == "Faulty" for k, v in u["checks"].items() if v is False
    )
    by_field = {f["id"]: f for f in fields}
    faulty_units = []
    for u in units:
        if u["status"] != "Faulty":
            continue
        bad_fields = []
        for fid, value in u["readings"].items():
            f = by_field.get(int(fid))
            if f and fields_svc.evaluate(f, value) == "fail":
                bad_fields.append(
                    {
                        "label": f["label"],
                        "value": value,
                        "unit_label": f["unit_label"],
                        "tolerance": fields_svc.tolerance_text(f),
                    }
                )
        faulty_units.append(
            {
                "code": u["code"],
                "item_code": u["item_code"],
                "defect_type": u["defect_type"],
                "defect_label": DEFECT_TYPES.get(u["defect_type"], u["defect_type"]),
                "notes": u["notes"],
                "failed_checks": [
                    CHECKS[k] for k, v in u["checks"].items() if v is False and k in CHECKS
                ],
                "failed_fields": bad_fields,
            }
        )
    field_stats = fields_svc.stats(fields, units)
    blockers = []
    if s["status"] == "Shipped":
        blockers.append("Confirm arrival first")
    if untested:
        blockers.append(f"{untested} received unit(s) still need a result")
    for st in field_stats:
        if st["required"] and st["not_recorded"] and not untested:
            blockers.append(
                f"'{st['label']}' (required) is missing on {st['not_recorded']} unit(s)"
            )
    quality = round(ok * 100 / received, 1) if received else None
    fulfilment = round(ok * 100 / shipped, 1) if shipped else None
    threshold = settings.inspection_accept_threshold
    suggestion = (
        None if quality is None or untested else ("approve" if quality >= threshold else "reject")
    )
    return {
        "shipment_no": s["shipment_no"],
        "status": s["status"],
        "frozen": False,
        "totals": {
            "shipped": shipped,
            "received": received,
            "missing": by_status["Missing"],
            "tested": ok + faulty,
            "untested": untested,
            "ok": ok,
            "faulty": faulty,
        },
        "quality_accuracy": quality,
        "fulfilment_accuracy": fulfilment,
        "threshold": threshold,
        "suggestion": suggestion,
        "per_item": sorted(per_item.values(), key=lambda r: r["item_code"]),
        "defects": [
            {"defect_type": k, "label": DEFECT_TYPES.get(k, k), "count": n}
            for k, n in defects.most_common()
        ],
        "failed_checks": [
            {"key": k, "label": CHECKS[k], "count": n}
            for k, n in failed_checks.most_common()
            if k in CHECKS
        ],
        "fields": field_stats,
        "faulty_units": faulty_units,
        "blockers": blockers,
        "ready": not blockers,
        "decision": None,
        "decided_at": None,
        "decided_by": None,
        "override_reason": "",
    }


def lot_report(conn: sqlite3.Connection, user: dict, shipment_id: int) -> dict:
    s = _shipment(conn, user, shipment_id)
    frozen = json.loads(s["lot_report"] or "{}")
    # the replacement links keep changing after the decision, so they are read live and never frozen
    return {
        **(frozen or compute_report(conn, s)),
        "replacement": ship_svc.replacement_summary(conn, s),
    }


# ------------------------------------------------------------------ the lot decision
def _headline(rep: dict) -> str:
    t = rep["totals"]
    text = f"Quality accuracy {rep['quality_accuracy']}% ({t['ok']} OK and {t['faulty']} faulty of {t['received']} received); fulfilment accuracy {rep['fulfilment_accuracy']}% of {t['shipped']} shipped."
    if t["missing"]:
        text += f" {t['missing']} unit(s) never arrived."
    return text


def decide(
    conn: sqlite3.Connection,
    user: dict,
    s: sqlite3.Row,
    decision: str,
    notes: str,
    reason: str,
    improvement: str,
    override_reason: str,
) -> dict:
    """Approve or reject a lot that was inspected unit by unit (called by shipments.inspect)."""
    if decision not in ("approve", "reject"):
        raise DomainError("decision must be 'approve' or 'reject'")
    rep = compute_report(conn, s)
    if rep["blockers"]:
        raise DomainError("The lot cannot be decided yet: " + "; ".join(rep["blockers"]) + ".")
    override_reason = (override_reason or "").strip()
    if decision != rep["suggestion"] and len(override_reason) < 3:
        raise DomainError(
            f"Quality accuracy is {rep['quality_accuracy']}% against a {rep['threshold']:g}% threshold, which suggests {rep['suggestion']}. "
            f"To {decision} anyway, give an override reason."
        )
    po = ship_svc._po(conn, s["po_id"])
    erp = get_connector(po["erp"])
    ship = ship_svc._hydrate(conn, s)
    notes = (notes or s["inspection_notes"] or "").strip()
    per_item = {r["item_code"].upper(): r for r in rep["per_item"]}
    lines_ok = [{"item_code": c, "quantity": r["ok"]} for c, r in per_item.items() if r["ok"] > 0]
    lines_bad = [
        {"item_code": c, "quantity": r["faulty"]} for c, r in per_item.items() if r["faulty"] > 0
    ]
    lines_all = [
        {"item_code": c, "quantity": r["received"]}
        for c, r in per_item.items()
        if r["received"] > 0
    ]
    derived = {
        k: not any(
            u["checks"].get(k) is False
            for u in _units(conn, s["id"])
            if u["status"] in ("OK", "Faulty")
        )
        for k in CHECKS
    }
    n_faulty = rep["totals"]["faulty"]
    headline = _headline(rep)
    defects = "\n- ".join(f"{d['label']}: {d['count']}" for d in rep["defects"])

    if decision == "approve":
        refs = []
        if lines_ok:
            refs.append(erp.release_stock(po, ship, lines_ok)["movement_ref"])
        if lines_bad:
            refs.append(
                erp.quarantine_stock(
                    po, ship, lines_bad, f"{n_faulty} faulty unit(s) in {s['shipment_no']}"
                )["movement_ref"]
            )
        for ln in lines_ok:
            inventory_svc.receive_stock(conn, ln["item_code"], ln["quantity"])
        for it in ship["items"]:
            conn.execute(
                "UPDATE shipment_items SET quantity_accepted = ? WHERE shipment_id = ? AND item_code = ? COLLATE NOCASE",
                (per_item.get(it["item_code"].upper(), {}).get("ok", 0), s["id"], it["item_code"]),
            )
        final_status = "Approved"
    else:
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise DomainError("A rejection reason is required")
        if not conn.execute(
            "SELECT 1 FROM shipment_files WHERE shipment_id = ? AND kind = 'photo'", (s["id"],)
        ).fetchone():
            raise DomainError("Attach at least one photo of the problem before rejecting")
        refs = (
            [erp.quarantine_stock(po, ship, lines_all, reason)["movement_ref"]] if lines_all else []
        )
        conn.execute(
            "UPDATE shipment_items SET quantity_accepted = 0 WHERE shipment_id = ?", (s["id"],)
        )
        final_status = "Rejected"

    rep.update(
        frozen=True,
        decision=decision,
        decided_at=now(),
        decided_by=user["name"],
        override_reason=override_reason,
        status=final_status,
    )
    conn.execute(
        "UPDATE shipments SET status = ?, inspected_at = ?, inspected_by = ?, inspection_notes = ?, rejection_reason = ?, quality_checks = ?, "
        "improvement_request = ?, erp_movement_ref = ?, override_reason = ?, lot_report = ? WHERE id = ?",
        (
            final_status,
            now(),
            user["id"],
            notes,
            reason if decision == "reject" else "",
            json.dumps(derived),
            (improvement or "").strip(),
            " / ".join(r for r in refs if r) or None,
            override_reason,
            json.dumps(rep),
            s["id"],
        ),
    )

    if decision == "approve":
        remaining = ship_svc._remaining(conn, po["id"])
        delivered = not remaining
        conn.execute(
            "UPDATE purchase_orders SET delivery_status = ? WHERE id = ?",
            ("Delivered" if delivered else "In Transit", po["id"]),
        )
        if n_faulty and not delivered:
            hold = f"{n_faulty} faulty unit(s) from {s['shipment_no']} awaiting replacement"
            erp.set_invoice_hold(po, True, hold)
            conn.execute(
                "UPDATE purchase_orders SET invoice_hold = 1, invoice_hold_reason = ? WHERE id = ?",
                (hold, po["id"]),
            )
        elif delivered and po["invoice_hold"]:
            erp.set_invoice_hold(po, False)
            conn.execute(
                "UPDATE purchase_orders SET invoice_hold = 0, invoice_hold_reason = '' WHERE id = ?",
                (po["id"],),
            )
        audit(
            conn,
            user["id"],
            "approve",
            "shipment",
            s["shipment_no"],
            f"{rep['totals']['ok']} OK, {n_faulty} faulty, accuracy {rep['quality_accuracy']}%"
            + (f"; override: {override_reason}" if override_reason else ""),
        )
        text = f"Shipment {s['shipment_no']} for {po['po_number']} was inspected unit by unit.\n\n{headline}"
        if n_faulty:
            text += f"\n\nFaulty units by defect:\n- {defects}\n\nThe {n_faulty} faulty unit(s) are in quarantine and the invoice is on hold. Please replace them. The OK units were released to stock."
        elif delivered:
            text += "\n\nAll units passed. The order is fully delivered and can proceed to closing."
        else:
            text += "\n\nAll units passed. Still to deliver:\n- " + "\n- ".join(
                f"{q} x {c}" for c, q in remaining.items()
            )
        if improvement:
            text += f"\n\nWhat needs to improve:\n{improvement.strip()}"
        title = f"Shipment {s['shipment_no']} approved ({rep['quality_accuracy']}% accuracy)" + (
            f", {n_faulty} faulty unit(s) to replace" if n_faulty else ""
        )
    else:
        active = conn.execute(
            "SELECT 1 FROM shipments WHERE po_id = ? AND status IN ('Shipped','Arrived')",
            (po["id"],),
        ).fetchone()
        erp.set_invoice_hold(po, True, reason)
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
            f"{reason}; accuracy {rep['quality_accuracy']}%",
        )
        text = f"Shipment {s['shipment_no']} for {po['po_number']} failed inspection.\n\nReason: {reason}\n\n{headline}"
        if defects:
            text += f"\n\nFaulty units by defect:\n- {defects}"
        if improvement:
            text += f"\n\nWhat needs to improve:\n{improvement.strip()}"
        text += "\n\nThe goods are in quarantine and the invoice is on hold. Please correct the issue and ship a replacement to fulfil the order."
        title = f"Shipment {s['shipment_no']} rejected: improvement required ({rep['quality_accuracy']}% accuracy)"
    if override_reason:
        text += f"\n\nInspector's note on the decision: {override_reason}"
    text += "\n\nOpen the shipment in the portal for the full per-unit report."
    ship_svc._tell_supplier_and_buyer(conn, po, title, text)
    return ship_svc.get_shipment(conn, user, s["id"])
