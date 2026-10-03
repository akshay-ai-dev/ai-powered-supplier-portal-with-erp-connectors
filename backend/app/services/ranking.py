"""Supplier ranking for one requirement, computed in code (SRS §6.3 "Ranking in code").

Rule: suppliers whose promised date meets the need-by date come first, ordered by lowest total price,
then earliest promised date. Suppliers who miss the date follow, ordered the same way.
Tools and the AI Assistant only show this ranking; they never compute their own.
"""
from datetime import date, timedelta

RULE = "Lowest total price among suppliers meeting the need-by date, then earliest delivery."


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def promised_date(quote: dict) -> date | None:
    """A quote promises delivery `lead_time_days` after it was submitted."""
    sent = _day(quote.get("created_at"))
    return sent + timedelta(days=quote.get("lead_time_days") or 0) if sent else None


def rank_quotes(requirement: dict, quotes: list[dict]) -> list[dict]:
    need_by = _day(requirement.get("needed_by"))
    qty = requirement.get("quantity") or 0
    rows = []
    for q in quotes:
        promised = promised_date(q)
        rows.append(
            {
                "quote_id": q["id"],
                "supplier_id": q["supplier_id"],
                "supplier_name": q.get("supplier_name"),
                "unit_price": q["unit_price"],
                "total_price": round(q["unit_price"] * qty, 2),
                "lead_time_days": q.get("lead_time_days") or 0,
                "promised_date": promised.isoformat() if promised else None,
                "meets_need_by": need_by is None or (promised is not None and promised <= need_by),
                "status": q.get("status"),
            }
        )
    rows.sort(key=lambda r: (not r["meets_need_by"], r["total_price"], r["promised_date"] or "9999", r["supplier_name"] or ""))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows
