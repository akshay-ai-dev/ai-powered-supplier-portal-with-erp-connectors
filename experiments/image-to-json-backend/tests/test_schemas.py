"""The six-key shipment schema: exact JSON Schema sent to OpenAI, plus Python validation."""

from __future__ import annotations

import json
from datetime import date

import pydantic
import pytest
from openai.lib._parsing._responses import type_to_text_format_param

from app.schemas import SHIPMENT_FIELDS, SHIPMENT_JSON_SCHEMA, ShipmentExtraction
from tests.helpers import SAMPLE_SHIPMENT_JSON, SIX_KEYS, sample_shipment

REQUIRED_SCHEMA = {
    "type": "object",
    "properties": {
        "shipDate": {"type": ["string", "null"], "format": "date"},
        "carrier": {"type": ["string", "null"]},
        "trackingNumbers": {"type": "array", "items": {"type": "string"}},
        "shippedQuantity": {"type": ["number", "null"], "minimum": 0},
        "lotNumbers": {"type": "array", "items": {"type": "string"}},
        "serialNumbers": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["shipDate", "carrier", "trackingNumbers", "shippedQuantity", "lotNumbers", "serialNumbers"],
    "additionalProperties": False,
}

EMPTY = {
    "shipDate": None,
    "carrier": None,
    "trackingNumbers": [],
    "shippedQuantity": None,
    "lotNumbers": [],
    "serialNumbers": [],
}


def dumped(model: ShipmentExtraction) -> dict:
    return json.loads(model.model_dump_json())


def test_schema_sent_to_openai_is_exactly_the_required_schema():
    assert SHIPMENT_JSON_SCHEMA == REQUIRED_SCHEMA
    assert ShipmentExtraction.model_json_schema() == REQUIRED_SCHEMA
    # What the installed SDK's responses.parse(text_format=...) actually sends:
    text_format = type_to_text_format_param(ShipmentExtraction)
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"] == REQUIRED_SCHEMA


def test_exactly_six_keys_in_output():
    data = dumped(sample_shipment())
    assert set(data) == SIX_KEYS
    assert list(data) == list(SHIPMENT_FIELDS)
    assert data == SAMPLE_SHIPMENT_JSON


def test_extra_keys_rejected():
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate({**EMPTY, "warnings": []})


@pytest.mark.parametrize("missing", sorted(SIX_KEYS))
def test_every_key_is_required(missing):
    data = dict(EMPTY)
    del data[missing]
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate(data)


def test_null_and_empty_array_result_round_trips():
    model = ShipmentExtraction.model_validate(EMPTY)
    assert dumped(model) == EMPTY


def test_blank_carrier_becomes_null():
    assert ShipmentExtraction.model_validate({**EMPTY, "carrier": "   "}).carrier is None


@pytest.mark.parametrize("value", [[], None])
def test_arrays_cannot_be_null(value):
    if value is None:
        with pytest.raises(pydantic.ValidationError):
            ShipmentExtraction.model_validate({**EMPTY, "lotNumbers": None})
    else:
        assert ShipmentExtraction.model_validate({**EMPTY, "lotNumbers": value}).lotNumbers == []


def test_valid_date_serializes_as_iso():
    model = ShipmentExtraction.model_validate({**EMPTY, "shipDate": "2026-12-31"})
    assert model.shipDate == date(2026, 12, 31)
    assert dumped(model)["shipDate"] == "2026-12-31"


@pytest.mark.parametrize(
    "bad",
    ["03/04/2026", "2026-02-30", "2026-13-01", "2026-3-4", "4 March 2026", "2026-03-04T10:00:00", "", 20260304],
)
def test_invalid_dates_rejected(bad):
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate({**EMPTY, "shipDate": bad})


def test_negative_quantity_rejected():
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate({**EMPTY, "shippedQuantity": -1})


@pytest.mark.parametrize("bad", ["12", True, float("nan"), float("inf")])
def test_non_numeric_quantity_rejected(bad):
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate({**EMPTY, "shippedQuantity": bad})


@pytest.mark.parametrize(("value", "expected"), [(0, 0), (12, 12), (12.0, 12), (2.5, 2.5)])
def test_quantity_serialization(value, expected):
    out = dumped(ShipmentExtraction.model_validate({**EMPTY, "shippedQuantity": value}))
    assert out["shippedQuantity"] == expected
    assert type(out["shippedQuantity"]) is type(expected)


def test_identifiers_stay_strings_with_leading_zeros_and_punctuation():
    ids = ["000123", "0012-3456", "LOT-77/B", "A.B_C#9"]
    out = dumped(ShipmentExtraction.model_validate({**EMPTY, "lotNumbers": ids, "serialNumbers": ids}))
    assert out["lotNumbers"] == ids
    assert out["serialNumbers"] == ids
    assert '"000123"' in sample_shipment().model_dump_json()


def test_numeric_identifiers_rejected_rather_than_coerced():
    # A number would already have lost leading zeros, so it is not accepted.
    with pytest.raises(pydantic.ValidationError):
        ShipmentExtraction.model_validate({**EMPTY, "trackingNumbers": [123]})


def test_duplicate_identifiers_removed_in_first_seen_order():
    model = ShipmentExtraction.model_validate(
        {**EMPTY, "trackingNumbers": ["B2", "A1", "B2", " A1 ", "C3", "", "  "]}
    )
    assert model.trackingNumbers == ["B2", "A1", "C3"]


def test_case_differences_are_not_duplicates():
    model = ShipmentExtraction.model_validate({**EMPTY, "serialNumbers": ["ab1", "AB1"]})
    assert model.serialNumbers == ["ab1", "AB1"]
