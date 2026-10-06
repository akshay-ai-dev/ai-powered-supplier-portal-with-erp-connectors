"""The shipment extraction schema: the exact JSON Schema sent to OpenAI, plus a
matching Pydantic model that validates (and normalizes) every result in Python."""

from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_serializer, field_validator

# Sent verbatim as the Structured Outputs schema (strict mode). The Pydantic
# model below reports this as its JSON schema, so the SDK's responses.parse()
# uses it unchanged.
SHIPMENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shipDate": {"type": ["string", "null"], "format": "date"},
        "carrier": {"type": ["string", "null"]},
        "trackingNumbers": {"type": "array", "items": {"type": "string"}},
        "shippedQuantity": {"type": ["number", "null"], "minimum": 0},
        "lotNumbers": {"type": "array", "items": {"type": "string"}},
        "serialNumbers": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "shipDate",
        "carrier",
        "trackingNumbers",
        "shippedQuantity",
        "lotNumbers",
        "serialNumbers",
    ],
    "additionalProperties": False,
}

SHIPMENT_FIELDS = tuple(SHIPMENT_JSON_SCHEMA["required"])

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ShipmentExtraction(BaseModel):
    """Exactly six keys. Saved, displayed, copied, and downloaded as-is."""

    model_config = ConfigDict(extra="forbid")

    shipDate: date | None
    carrier: str | None
    trackingNumbers: list[StrictStr]
    shippedQuantity: float | None = Field(ge=0, strict=True, allow_inf_nan=False)
    lotNumbers: list[StrictStr]
    serialNumbers: list[StrictStr]

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler) -> dict[str, Any]:
        return copy.deepcopy(SHIPMENT_JSON_SCHEMA)

    @field_validator("shipDate", mode="before")
    @classmethod
    def _iso_calendar_date(cls, value: Any) -> Any:
        # Only null, a date object, or a real calendar date written as YYYY-MM-DD.
        # Rejects 03/04/2026, 2026-02-30, timestamps, and datetimes.
        if value is None or type(value) is date:
            return value
        if isinstance(value, str) and _ISO_DATE.fullmatch(value):
            return date.fromisoformat(value)  # ValueError for impossible dates
        raise ValueError("shipDate must be a calendar date in YYYY-MM-DD format, or null")

    @field_validator("carrier", mode="before")
    @classmethod
    def _blank_carrier_is_null(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("trackingNumbers", "lotNumbers", "serialNumbers")
    @classmethod
    def _unique_identifiers(cls, values: list[str]) -> list[str]:
        # Trim surrounding whitespace, drop blanks, and remove exact duplicates
        # while keeping first-seen order. Identifiers are otherwise unchanged
        # (leading zeros and punctuation are preserved).
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))

    @field_serializer("shippedQuantity")
    def _whole_numbers_without_decimal(self, value: float | None) -> float | int | None:
        return int(value) if value is not None and value.is_integer() else value
