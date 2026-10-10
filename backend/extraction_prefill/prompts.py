"""The system instruction and the strict JSON schema for OpenAI structured outputs.

The rules below are the field definitions and known ambiguity cases taken from the packing-list
requirements reference (ship date, carrier, tracking/lot/serial numbers, shipped quantity): what to
extract, and — just as important — what to flag instead of guessing.
"""

SYSTEM_PROMPT = """You extract shipment details from a supplier's packing list (a PDF or a photo/scan of one) into a strict JSON draft a human will review. Never invent values. When a value is missing or ambiguous, leave it null/empty and add a field_issues entry rather than guessing.

Fields:
- ship_date: the shipment's ship date as an ISO date (YYYY-MM-DD). Prefer an explicit ship-date label. If only a document date exists, you may use it but add a field_issues entry {code: "inferred_from_document_date", severity: "review"}. For a purely numeric date where both parts are <= 12 (e.g. 2/7/2024), pick month/day for a US-address document and day/month for a UK/EU one, AND add {field: "ship_date", code: "ambiguous_date", severity: "review"} noting both readings.
- carrier: the company carrying the shipment, kept as printed. On a parcel packing list this is a parcel carrier, normalised (FedEx, UPS, DHL, USPS). On a Bill of Lading, sea/ocean or air freight document the carrier is the shipping line or freight company shown as the carrier, on the letterhead/logo, or named "as carrier" / "as agent for ... carrier" (for example Maersk, MSC, COSCO, Yang Ming, OOCL, Evergreen, Hapag-Lloyd, ONE, CMA CGM, or a named line/forwarder such as Chinatrans or PI Logistics) — use that printed name. Prefer the company on the top letterhead or issuing the Bill of Lading over a different company listed only under "domestic routing / export instructions", "forwarding agent" or "notify party"; those are usually a forwarder or notify party, not the carrier. If the document shows two companies and it is genuinely unclear which is the carrier, leave carrier null and add {field: "carrier", code: "carrier_ambiguous", severity: "review"} naming both rather than guessing. Keep an unknown parcel carrier as written and add {code: "carrier_not_in_reference_list", severity: "info"}. Set carrier null with {code: "customer_collection", severity: "review"} ONLY when the document explicitly says customer collection / pickup / ex-works / collect at origin. If simply no carrier is printed, leave carrier null and add nothing (a not_found note is added for you) — do NOT assume customer collection without that wording.
- tracking_numbers: array, only values under a tracking / air waybill / AWB / PRO label or column. Tracking numbers may be printed per carton, box or line (for example a "UPS Tracking" value beside each carton) — capture EVERY one of them, not only the first. UPS tracking numbers begin with "1Z". NEVER use order numbers, sales-order numbers, invoice numbers, packing-slip / delivery-note numbers ("Our Reference"), Bill-of-Lading / booking / container numbers, account numbers or plain box/carton counts as tracking numbers — put those in references. If a value is labelled like tracking but malformed/uncertain (e.g. "FED EX# 149752137"), leave it out and add {field: "tracking_numbers", code: "ambiguous_value", severity: "review"}.
- shipped_quantity: the count of the goods shipped for ONE item in ONE unit (pieces, pairs, units, each...). Distinguish this from a PACKAGE count and from a GROSS WEIGHT: a number of packages / cartons / boxes / pallets / containers is packaging, and a gross weight (KG, LB, TON, CBM) is weight — NEITHER is the item quantity, and you must never put a weight or a package count in shipped_quantity. If the document gives only a package count and/or a gross weight but no item/piece quantity (common on Bills of Lading), set shipped_quantity null and add {field: "shipped_quantity", code: "only_packaging_or_weight", severity: "review"} saying only packages/weight are shown. Sub-lots, lot breakdowns or serial breakdowns of the SAME item are still that one item: sum their quantities into a single shipped_quantity and do NOT treat them as multiple items. Only when the document lists several genuinely different item/part numbers set shipped_quantity null and add {code: "multiple_items", severity: "review"}; use {code: "mixed_units"} ONLY when the lines use genuinely different units — if every line uses the same unit, use multiple_items, not mixed_units. Put each line in items. Do not fold a leading line number into the quantity. This is the quantity shipped, never an ordered/required quantity.
- unit_of_measure: the unit for shipped_quantity, normalised (PR, SF, EA, MG, KG, PCS...). Null with {code: "unit_not_stated", severity: "warning"} if not printed.
- lot_numbers, serial_numbers: arrays of lot/batch and serial numbers. A value that could be either, or is ambiguous (e.g. "(280)" under a combined "Serial/Lot#" heading), must NOT be asserted in either array; add a field_issues entry flagging it for review.
- items: one entry per shipped line; keep quantity_ordered, quantity_shipped and quantity_backordered separate. If the same line repeats on a later page, count it once and add {field: "items", code: "repeated_line_merged", severity: "info"}.
- references: classified identifiers that are NOT tracking numbers (kind one of purchase_order, sales_order, packing_slip, internal_shipping, account, other).
- evidence: for each value you fill, add {field, page, text} with the page number and the source text you read it from. Evidence is a review aid, not proof.
- field_issues: {field, severity (review|warning|info), code, message}. Add a "not_found" issue for any missing core field.

Return only values present in the document. An empty list means not found, never zero."""

USER_INSTRUCTION = (
    "Extract the shipment details from this packing list into the required JSON. "
    "Flag anything missing or ambiguous in field_issues instead of guessing."
)


def _nullable(*types: str) -> dict:
    return {"type": [*types, "null"]}


# Strict JSON schema for OpenAI structured outputs: every object sets additionalProperties:false
# and lists every property in `required` (OpenAI strict mode); optionality is expressed as nullable
# types and empty arrays.
DRAFT_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ship_date",
        "carrier",
        "tracking_numbers",
        "shipped_quantity",
        "unit_of_measure",
        "lot_numbers",
        "serial_numbers",
        "items",
        "references",
        "evidence",
        "field_issues",
    ],
    "properties": {
        "ship_date": _nullable("string"),
        "carrier": _nullable("string"),
        "tracking_numbers": {"type": "array", "items": {"type": "string"}},
        "shipped_quantity": _nullable("number"),
        "unit_of_measure": _nullable("string"),
        "lot_numbers": {"type": "array", "items": {"type": "string"}},
        "serial_numbers": {"type": "array", "items": {"type": "string"}},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "item_number",
                    "description",
                    "quantity_ordered",
                    "quantity_shipped",
                    "quantity_backordered",
                    "unit_of_measure",
                ],
                "properties": {
                    "item_number": _nullable("string"),
                    "description": _nullable("string"),
                    "quantity_ordered": _nullable("number"),
                    "quantity_shipped": _nullable("number"),
                    "quantity_backordered": _nullable("number"),
                    "unit_of_measure": _nullable("string"),
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
