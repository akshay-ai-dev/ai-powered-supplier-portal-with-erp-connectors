"""Response ranking, computed in code (SRS §6.3: "Ranking in code").

Rule: offers meeting the need-by date rank before late ones; within each group the
lowest total price wins, then the earliest delivery. The AI only explains this
ranking; it never invents its own.

Offers in different currencies are compared by converting each total into one
comparison currency (INR) with the rate from PortalData.exchange_rates():
- one currency              -> "ranked" (no conversion)
- rate not approved (demo)  -> "provisional_fx_ranking": ranked, but clearly provisional
- rate approved             -> "ranked_converted"
- no rate for a currency    -> "currency_review_required": no ranking, no winner
Original prices and currencies are always kept; conversion is for comparison only.
"""

from portal_data import portal_data, supplier_by_id

RANKING_RULE = (
    "Offers that meet the need-by date rank before late offers; within each group the "
    "lowest total price wins, then the earliest promised delivery. Offers in different "
    "currencies are compared by their total converted to the comparison currency."
)

RANKED = "ranked"
PROVISIONAL_FX = "provisional_fx_ranking"
CONVERTED = "ranked_converted"
CURRENCY_REVIEW = "currency_review_required"
RANKED_STATUSES = (RANKED, PROVISIONAL_FX, CONVERTED)


def offer_currencies(request: dict) -> list[str]:
    return sorted({r.get("currency") or "unknown" for r in request["responses"]})


def ranking_context(request: dict) -> dict:
    """How this request's offers can be compared: status, message, rate used."""
    currencies = offer_currencies(request)
    if len(currencies) <= 1:
        return {"status": RANKED, "message": None, "exchangeRate": None,
                "comparisonCurrency": currencies[0] if currencies else None}

    fx = portal_data().exchange_rates()
    rates = (fx or {}).get("ratesToBase", {})
    missing = [c for c in currencies if c not in rates]
    if not fx or missing:
        return {"status": CURRENCY_REVIEW, "exchangeRate": None, "comparisonCurrency": None,
                "message": (
                    f"Currency comparison needs review: offers are in {', '.join(currencies)} "
                    f"and no exchange rate is available for {', '.join(missing or currencies)}. "
                    "Prices are not compared and no supplier is ranked or recommended.")}

    base = fx["baseCurrency"]
    used = {c: rates[c] for c in currencies}
    rate_text = ", ".join(f"1 {c} = {used[c]:g} {base}" for c in currencies if c != base)
    exchange_rate = {"baseCurrency": base, "ratesToBase": used,
                     "approved": bool(fx.get("approved")), "source": fx.get("source"),
                     "label": fx.get("label")}
    if fx.get("approved"):
        return {"status": CONVERTED, "exchangeRate": exchange_rate, "comparisonCurrency": base,
                "message": f"Offers are in {', '.join(currencies)}; totals are compared in "
                           f"{base} using the approved rate ({rate_text})."}
    return {"status": PROVISIONAL_FX, "exchangeRate": exchange_rate, "comparisonCurrency": base,
            "message": (
                f"Provisional ranking: offers are in {', '.join(currencies)}. Totals are "
                f"converted to {base} with a demo exchange rate ({rate_text}; sample data, not "
                "a live or approved rate). Treat this order as provisional until the backend "
                "supplies an approved rate. Each offer and the purchase order keep their "
                "original currency.")}


def ranking_status(request: dict) -> tuple[str, str | None]:
    """(status, message) — see ranking_context()."""
    ctx = ranking_context(request)
    return ctx["status"], ctx["message"]


def rank_responses(request: dict, context: dict | None = None) -> list[dict]:
    ctx = context or ranking_context(request)
    need_by = request["needByDate"]
    qty = request["quantity"]
    rates = (ctx["exchangeRate"] or {}).get("ratesToBase", {})
    rows = []
    for r in request["responses"]:
        supplier = supplier_by_id(r["supplierId"]) or {}
        total = round(r["unitPrice"] * qty, 2)
        if ctx["status"] == RANKED:
            rate, comparison_total = 1.0, total
        elif ctx["status"] == CURRENCY_REVIEW:
            rate, comparison_total = None, None
        else:
            rate = rates[r["currency"]]
            comparison_total = round(total * rate, 2)
        rows.append(
            {
                "supplierId": r["supplierId"],
                "supplierName": supplier.get("name", r["supplierId"]),
                "supplierStatus": supplier.get("status", "unknown"),
                "unitPrice": r["unitPrice"],
                "currency": r["currency"],
                "totalPrice": total,
                "comparisonCurrency": ctx["comparisonCurrency"],
                "exchangeRateToComparison": rate,
                "comparisonTotal": comparison_total,
                "promisedDate": r["promisedDate"],
                # ISO dates (YYYY-MM-DD) compare correctly as strings.
                "meetsNeedBy": r["promisedDate"] <= need_by,
            }
        )
    if ctx["status"] == CURRENCY_REVIEW:
        # Listed by supplier name so the order implies no price preference.
        rows.sort(key=lambda x: x["supplierName"])
        for row in rows:
            row["rank"] = None
        return rows
    rows.sort(key=lambda x: (not x["meetsNeedBy"], x["comparisonTotal"], x["promisedDate"]))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
