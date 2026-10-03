"""Grounding rules for the buyer assistant, enforced in code (not only in the prompt).

A portal answer may only state IDs, document numbers, tracking numbers, dates, prices,
supplier names and statuses that appear in successful MCP read/draft results (or that
the buyer typed). Anything else is treated as invented and the answer is replaced.
There is no web search: answers that claim one are rejected.
"""

import json
import re

from portal_data import find_supplier, portal_data

NOT_FOUND_TEXT = "I could not find that in the portal records."

# Words that make a question about portal records rather than general chat.
_PORTAL_WORDS = re.compile(
    r"\b(?:req(?:uest)?s?|requisitions?|rfq|quotes?|quotations?|offers?|responses?|bids?|"
    r"suppliers?|vendors?|prices?|pricing|costs?|totals?|cheapest|deliver(?:y|ies)|"
    r"promised|need-by|deadlines?|status(?:es)?|shipments?|shipped|tracking|carriers?|"
    r"inspections?|rejected|accepted|quarantined?|receipts?|goods receipt|invoices?|holds?|"
    r"po|pos|purchase orders?|erp|sap|ln|infor|documents?|award(?:s|ed)?|ranking|ranked|"
    r"blocked|lots?|serials?)\b",
    re.I,
)
PROMPT_ID_RE = re.compile(r"\b(?:REQ|SHP)-\d{3,}\b", re.I)

# Identifier-like tokens: upper-case/digit runs with at least one digit and length >= 6
# (REQ-0007, 4500000123, PUR000456, HOLD-000118, 1Z-DEMO-44821, 2026-10-22).
_ID_TOKEN_RE = re.compile(r"(?<![\w.-])(?=[A-Z0-9-]*\d)[A-Z0-9](?:[A-Z0-9-]{4,})[A-Z0-9](?![\w-])")
# Money-like numbers: currency-marked, thousands-separated (incl. Indian 2,25,600), or
# two decimals.
_MONEY_RE = re.compile(
    r"(?:(?:[$₹€£]|\b(?:USD|INR|Rs\.?|EUR|GBP)(?![\w]))\s?(\d[\d,]*(?:\.\d+)?))"
    r"|(\b\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?\b)"
    r"|(\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)"
    r"|(\b\d+\.\d{2}\b)"
)
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_WEB_CLAIM_RE = re.compile(
    r"\b(?:I|we)\s+(?:have\s+)?(?:searched|googled|browsed|looked\s+(?:it\s+)?up)\b[^.]*"
    r"\b(?:web|internet|online|google)\b"
    r"|\b(?:according to|based on|from)\s+(?:my\s+|a\s+|an\s+)?(?:web|internet|online|google)"
    r"(?:\s+(?:search|sources?|results?))?"
    r"|\b(?:web|internet|online)\s+search\s+(?:results?|shows?|found|indicates?)",
    re.I,
)
WEB_CLAIM_TEXT = (
    "I can't search the web. I can only answer from the supplier-portal records "
    "(requests, responses, suppliers, shipments, inspections and ERP documents)."
)


# Portal status values an answer may only state when a tool result contains them.
# Keep in sync with the portal's status enums at integration. Only capitalised values
# are checked; lower-case "active"/"blocked"/"posted" are too common in ordinary prose.
STATUS_VALUES = {
    # sourcing request
    "Open", "Responses received", "Locked", "Awarded", "Closed", "Closed – rejected",
    "Cancelled",
    # supplier response
    "Submitted", "Not awarded",
    # shipment / inspection / stock
    "Accepted", "Rejected", "Approved", "Unrestricted", "Quarantined",
    # ERP requisition
    "Available",
}


def supplier_names() -> set[str]:
    return {s["name"] for s in portal_data().list_suppliers()}


def is_portal_question(prompt: str) -> bool:
    return bool(PROMPT_ID_RE.search(prompt) or _PORTAL_WORDS.search(prompt))


def prompt_ids(text: str) -> list[str]:
    return sorted({m.upper() for m in PROMPT_ID_RE.findall(text)})


def has_records(tool: str, result: dict) -> bool:
    """A tool result counts as evidence only when it actually returned records."""
    if not isinstance(result, dict) or result.get("error") or result.get("found") is False:
        return False
    if tool in ("list_requests", "search_suppliers"):
        return result.get("count", 0) > 0
    if tool == "get_erp_documents":
        return bool(result.get("documents"))
    return True


def _numbers(text: str) -> set[float]:
    out = set()
    for raw in _NUMBER_RE.findall(text):
        try:
            out.add(round(float(raw.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def unsupported_values(answer: str, evidence: list[dict], user_text: str) -> list[str]:
    """Return values in the answer that no tool result (or the buyer) supplied."""
    source = json.dumps(evidence, ensure_ascii=False) + "\n" + user_text
    source_upper = source.upper()
    source_numbers = _numbers(source)
    problems: list[str] = []

    for token in set(_ID_TOKEN_RE.findall(answer)):
        if token.upper() not in source_upper:
            problems.append(token)

    for match in _MONEY_RE.finditer(answer):
        raw = next(g for g in match.groups() if g)
        value = round(float(raw.replace(",", "")), 2)
        if value not in source_numbers:
            problems.append(match.group(0).strip())

    for name in supplier_names():
        if name.lower() in answer.lower() and name.lower() not in source.lower():
            problems.append(name)

    for status in STATUS_VALUES:
        # Skip matches at the start of a sentence, where any word is capitalised.
        for m in re.finditer(rf"(?<![\w-]){re.escape(status)}(?![\w-])", answer):
            before = answer[: m.start()].rstrip()
            if before and before[-1] not in ".!?:\n*#-" and status not in source:
                problems.append(status)
                break

    return sorted(set(problems))


def claims_web_search(answer: str) -> bool:
    return bool(_WEB_CLAIM_RE.search(answer))


def not_found_text(missing_ids: list[str]) -> str:
    if missing_ids:
        return f"I could not find {', '.join(missing_ids)} in the portal records."
    return NOT_FOUND_TEXT


def draft_args_problem(tool: str, args: dict, user_text: str) -> str | None:
    """Draft tools may only act on IDs and suppliers the buyer named themselves,
    so text inside tool results (e.g. supplier comments) cannot steer a draft."""
    text = user_text.lower()

    def named(value: str) -> bool:
        value = value.strip().lower()
        if not value:
            return False
        if value in text:
            return True
        supplier = find_supplier(value)
        return bool(supplier) and (
            supplier["id"].lower() in text or supplier["name"].lower() in text
        )

    if tool == "draft_award":
        if not named(str(args.get("request_id", ""))):
            return "The buyer did not name this request. Only draft for a request ID the buyer typed."
        supplier = args.get("supplier_id")
        if supplier and not named(str(supplier)):
            return (
                "The buyer did not name this supplier. Omit supplier_id to use the coded "
                "top recommendation, or ask the buyer which supplier to use."
            )
    if tool == "draft_request":
        if not named(str(args.get("requisition_id", ""))):
            return "The buyer did not name this requisition."
        others = [s for s in args.get("supplier_ids") or [] if not named(str(s))]
        if others:
            return f"The buyer did not name these suppliers: {', '.join(map(str, others))}."
    return None
