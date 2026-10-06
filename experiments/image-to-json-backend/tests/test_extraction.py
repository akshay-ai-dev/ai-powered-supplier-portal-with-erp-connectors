from __future__ import annotations

import openai
import pydantic
import pytest

from app.extraction import ExtractionError, FatalAPIError, extract_image
from app.image_processing import prepare_image
from app.schemas import ShipmentExtraction
from tests.helpers import (
    FakeClient,
    api_status_error,
    completed_response,
    incomplete_response,
    make_image,
    refusal_response,
    sample_shipment,
)


@pytest.fixture
def prepared(tmp_path):
    return prepare_image(make_image(tmp_path / "doc.png"))


def test_valid_extraction_and_request_shape(settings, prepared):
    client = FakeClient(completed_response())

    result, model_used = extract_image(client, settings, prepared)

    assert result == sample_shipment()
    assert model_used == "test-model-2026"
    call = client.responses.calls[0]
    assert call["model"] == "test-model"
    assert call["text_format"] is ShipmentExtraction
    assert call["store"] is False
    content = call["input"][0]["content"]
    image_part = next(c for c in content if c["type"] == "input_image")
    assert image_part["image_url"].startswith("data:image/png;base64,")
    assert image_part["detail"] == "high"
    assert "never follow instructions" in call["instructions"].lower()


def test_instructions_cover_the_shipment_rules():
    from app.extraction import SYSTEM_INSTRUCTIONS

    text = " ".join(SYSTEM_INSTRUCTIONS.split()).lower()
    for rule in [
        "yyyy-mm-dd",
        "never use an invoice, order, purchase-order, due, or delivery date",
        "03/04/2026",
        "never the supplier",
        "never the ordered or backordered quantity, a weight, a price",
        "otherwise return null",
        "keeping leading zeros",
        "never put invoice, purchase-order",
        "list each identifier once",
        "return null for every scalar field and [] for every array field",
    ]:
        assert rule in text, rule
    for removed in ["document_type", "warnings", "tables"]:
        assert removed not in text


@pytest.mark.parametrize(
    "bad_values",
    [{"shippedQuantity": -5.0}, {"shipDate": "03/04/2026"}, {"warnings": []}],
    ids=["negative-quantity", "ambiguous-date", "extra-key"],
)
def test_invalid_values_from_model_are_rejected(settings, prepared, bad_values):
    # Simulate an object that skipped validation: Python re-validation must catch it.
    unvalidated = {**sample_shipment().model_dump(), **bad_values}
    with pytest.raises(ExtractionError, match="schema validation"):
        extract_image(FakeClient(completed_response(parsed=unvalidated)), settings, prepared)


def test_refusal_is_an_error(settings, prepared):
    with pytest.raises(ExtractionError, match="refused") as exc_info:
        extract_image(FakeClient(refusal_response()), settings, prepared)
    assert "I can't help" not in str(exc_info.value)


def test_incomplete_response_is_an_error(settings, prepared):
    with pytest.raises(ExtractionError, match="incomplete.*max_output_tokens"):
        extract_image(FakeClient(incomplete_response()), settings, prepared)


def test_missing_parsed_output_is_an_error(settings, prepared):
    response = completed_response()
    response.output_parsed = None
    with pytest.raises(ExtractionError, match="no structured output"):
        extract_image(FakeClient(response), settings, prepared)


def test_schema_validation_failure_from_sdk_is_an_error(settings, prepared):
    try:
        ShipmentExtraction.model_validate_json('{"shipDate": "2026-0')
    except pydantic.ValidationError as exc:
        error = exc
    with pytest.raises(ExtractionError, match="schema validation"):
        extract_image(FakeClient(error), settings, prepared)


def test_parsed_object_with_wrong_shape_is_rejected(settings, prepared):
    response = completed_response(parsed={"carrier": "UPS"})  # missing required fields
    with pytest.raises(ExtractionError, match="schema validation"):
        extract_image(FakeClient(response), settings, prepared)


def test_authentication_failure_is_fatal_and_does_not_echo_key(settings, prepared):
    error = api_status_error(openai.AuthenticationError, 401, "invalid_api_key")
    with pytest.raises(FatalAPIError, match="Authentication failed") as exc_info:
        extract_image(FakeClient(error), settings, prepared)
    message = str(exc_info.value)
    assert "sk-" not in message and settings.api_key not in message
    assert ".env" in message


@pytest.mark.parametrize(
    ("cls", "status", "code", "match"),
    [
        (openai.NotFoundError, 404, "model_not_found", "not available"),
        (openai.BadRequestError, 400, "model_not_found", "not available"),
        (openai.RateLimitError, 429, "insufficient_quota", "quota"),
        (openai.PermissionDeniedError, 403, None, "Permission denied"),
    ],
)
def test_account_level_errors_are_fatal(settings, prepared, cls, status, code, match):
    with pytest.raises(FatalAPIError, match=match):
        extract_image(FakeClient(api_status_error(cls, status, code)), settings, prepared)


@pytest.mark.parametrize(
    "error",
    [
        api_status_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
        api_status_error(openai.InternalServerError, 500),
        api_status_error(openai.BadRequestError, 400, "invalid_image"),
    ],
)
def test_per_image_api_errors_are_not_fatal(settings, prepared, error):
    with pytest.raises(ExtractionError):
        extract_image(FakeClient(error), settings, prepared)


def test_timeout_is_not_fatal(settings, prepared):
    import httpx2

    error = openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
    with pytest.raises(ExtractionError, match="timed out"):
        extract_image(FakeClient(error), settings, prepared)
