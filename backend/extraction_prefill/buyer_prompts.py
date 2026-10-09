"""System instruction and strict JSON schema for the buyer *New requirement* draft.

These are the buyer requirement fields and their known ambiguity cases — deliberately separate from
the supplier shipment contract in `prompts.py`. A buyer uploads a purchase requisition / request /
RFQ brief (PDF or photo/scan) and gets back a draft for the New requirement form: item name,
specs/notes, requested quantity, target unit price, needed-by date and quote deadline. The model
must never invent a value (especially a price or an absolute date) — missing or uncertain fields are
left null/empty and flagged in field_issues for the buyer to review.

The ERP system is NOT extracted: it stays a buyer choice on the form. Nothing here maps to a supplier
shipment field (shipped quantity, carrier, tracking/lot/serial): those meanings are not reused.
"""

BUYER_SYSTEM_PROMPT = """You read a buyer's purchase requisition / purchase request / RFQ brief (a PDF or a photo/scan of one) and extract the fields needed to draft ONE new requirement a human buyer will review and edit. This is a request to BUY, not a shipment or packing list. Never invent values. When a value is missing, unclear or not stated, leave it null/empty and add a field_issues entry rather than guessing.

Fields (snake_case, exactly as below):
- title: a short name for the single item being requested (the item/product/part name). Keep it concise (a product name, not a whole paragraph). If the document requests several genuinely different items (different products/part numbers), do NOT pick one and do NOT merge them: set title null, put every item in `items`, and add {field: "title", code: "multiple_items", severity: "review"} so the buyer chooses which one this requirement is for.
- description: specifications, notes or requirements for the item (material, grade, dimensions, standards, finish, packaging, delivery terms, free text). Combine the relevant spec/notes text; do not fabricate specs that are not written.
- quantity: the requested quantity to buy, as a number, for the single item in `title`. This is a REQUESTED/ordered quantity, never a shipped or received quantity. Do not include the unit here (put the unit in items.unit_of_measure). If several different items are requested, leave quantity null (see multiple_items) — never add quantities of different items together. If a quantity is a range or unclear (e.g. "approx 500-600"), leave it null and add {field: "quantity", code: "ambiguous_value", severity: "review"} noting the text.
- target_price: the buyer's TARGET or expected UNIT price for the item, as a number only, if the document explicitly states one (a target price, budget per unit, expected unit price, "should cost"). Do NOT use a supplier's quoted price, a historical purchase price, an extended/total/line amount, tax, or a total budget as the target unit price. If only a total or extended amount is shown, leave target_price null and add {field: "target_price", code: "only_total_amount", severity: "review"}. If no target price is stated, leave it null — never invent one. Capture the currency in evidence text if shown, but target_price is a bare number.
- needed_by: the date the goods are needed by (required/delivery/need-by date), as an ISO date YYYY-MM-DD, only if the document gives an actual calendar date. Do NOT compute a date from a relative term such as "within 4 weeks", "ASAP", "net 30", "lead time 6 weeks": leave needed_by null and add {field: "needed_by", code: "relative_date", severity: "review"} quoting the term. For a purely numeric date where both parts are <= 12 (e.g. 3/4/2026), pick month/day for a US document and day/month for a UK/EU one AND add {field: "needed_by", code: "ambiguous_date", severity: "review"} giving both readings. If the date is already in the past, still return it but add {field: "needed_by", code: "historical_date", severity: "review"}.
- quote_deadline: the deadline for suppliers to respond/quote (quote-by, respond-by, bid due, closing date), only if an actual date is given. Give it as a NAIVE local wall-clock exactly as printed, with NO time-zone letter or offset: "YYYY-MM-DD" when only a date is shown, or "YYYY-MM-DDTHH:MM:SS" when a clock time is shown (e.g. 2:30 PM on Aug 27 2024 -> "2024-08-27T14:30:00"). NEVER append "Z" and never convert to UTC or any other zone — keep the document's own date and clock digits. The same relative/ambiguous/historical rules as needed_by apply, flagged on field "quote_deadline". Do not confuse the quote deadline with the needed-by delivery date; if the document has only one date and it is unclear which it is, put it in needed_by and add {field: "quote_deadline", code: "not_found"} plus a note on needed_by that it may be either.
- quote_deadline_tz: the time zone printed next to the quote deadline time, copied exactly as shown (e.g. "CST", "CDT", "ET", "EST", "PT", "UTC", "GMT"), or null if the deadline has no time or no zone is printed. Do not guess a zone that is not written.
- items: one entry per distinct item requested, each {item_name, specs, quantity, unit_of_measure, target_price} with whatever is stated (null where not). Always fill this for multi-item documents; for a single-item document you may also include the one item here.
- references: identifiers that are NOT one of the fields above (requisition number, RFQ/RFP number, project code, cost centre, internal reference), each {value, label, page, kind} with kind one of requisition, rfq, project, cost_center, other.
- evidence: for EACH value you fill (title, description, quantity, target_price, needed_by, quote_deadline), add {field, page, text} with the 1-based page number (null for a single image) and the exact source text you read it from. Evidence is a review aid, not proof, and locates the source text/page only — not pixel coordinates.
- field_issues: {field, severity (review|warning|info), code, message}. Add a "not_found" issue for any core field that is absent.

Return only values actually present in the document. An empty list means not found, never zero. Do not extract or guess the ERP system; it is chosen by the buyer on the form."""

BUYER_USER_INSTRUCTION = (
    "Extract the buyer requirement fields (item name, specs/notes, requested quantity, target unit "
    "price, needed-by date, quote deadline) from this purchase request into the required JSON. "
    "Flag anything missing, relative or ambiguous in field_issues instead of guessing, and never "
    "invent a price or an absolute date."
)


def _nullable(*types: str) -> dict:
    return {"type": [*types, "null"]}


# Strict JSON schema for OpenAI structured outputs: every object sets additionalProperties:false and
# lists every property in `required` (OpenAI strict mode); optionality is a nullable type / empty list.
BUYER_DRAFT_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "description",
        "quantity",
        "target_price",
        "needed_by",
        "quote_deadline",
        "quote_deadline_tz",
        "items",
        "references",
        "evidence",
        "field_issues",
    ],
    "properties": {
        "title": _nullable("string"),
        "description": _nullable("string"),
        "quantity": _nullable("number"),
        "target_price": _nullable("number"),
        "needed_by": _nullable("string"),
        "quote_deadline": _nullable("string"),
        "quote_deadline_tz": _nullable("string"),
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "item_name",
                    "specs",
                    "quantity",
                    "unit_of_measure",
                    "target_price",
                ],
                "properties": {
                    "item_name": _nullable("string"),
                    "specs": _nullable("string"),
                    "quantity": _nullable("number"),
                    "unit_of_measure": _nullable("string"),
                    "target_price": _nullable("number"),
                },
            },
        },
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "label", "page", "kind"],
                "properties": {
                    "value": {"type": "string"},
                    "label": _nullable("string"),
                    "page": _nullable("integer"),
                    "kind": {"type": "string"},
                },
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "page", "text"],
                "properties": {
                    "field": {"type": "string"},
                    "page": _nullable("integer"),
                    "text": {"type": "string"},
                },
            },
        },
        "field_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "severity", "code", "message"],
                "properties": {
                    "field": {"type": "string"},
                    "severity": {"type": "string", "enum": ["review", "warning", "info"]},
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    },
}
