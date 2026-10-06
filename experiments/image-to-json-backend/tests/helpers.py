"""Shared test helpers. All OpenAI calls are mocked: no API key, no network, no charges."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
from PIL import Image

from app.schemas import ShipmentExtraction

SIX_KEYS = {"shipDate", "carrier", "trackingNumbers", "shippedQuantity", "lotNumbers", "serialNumbers"}

# What the saved/downloaded JSON for sample_shipment() must look like.
SAMPLE_SHIPMENT_JSON = {
    "shipDate": "2026-03-04",
    "carrier": "UPS Ground",
    "trackingNumbers": ["1Z999AA10123456784", "0012-3456"],
    "shippedQuantity": 120,
    "lotNumbers": ["000123", "LOT-77/B"],
    "serialNumbers": ["SN-0001"],
}


def make_image(path: Path, fmt: str = "PNG", size=(40, 30), color="white", **save_kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format=fmt, **save_kwargs)
    return path


def sample_shipment(**overrides: Any) -> ShipmentExtraction:
    return ShipmentExtraction.model_validate({**SAMPLE_SHIPMENT_JSON, **overrides})


def completed_response(parsed: Any = None, model: str = "test-model-2026") -> SimpleNamespace:
    parsed = sample_shipment() if parsed is None else parsed
    return SimpleNamespace(
        status="completed",
        incomplete_details=None,
        model=model,
        output=[
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="{...}", parsed=parsed)],
            ),
        ],
        output_parsed=parsed,
    )


def refusal_response() -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        incomplete_details=None,
        model="test-model",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="refusal", refusal="I can't help with that.")],
            )
        ],
        output_parsed=None,
    )


def incomplete_response(reason: str = "max_output_tokens") -> SimpleNamespace:
    return SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason=reason),
        model="test-model",
        output=[],
        output_parsed=None,
    )


def api_status_error(cls: type[openai.APIStatusError], status: int, code: str | None = None):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(status, request=request)
    body = {"message": "Incorrect API key provided: sk-abc***xyz", "type": "error", "code": code}
    return cls("error", response=response, body=body)


class FakeResponses:
    def __init__(self, results: list[Any]):
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        if isinstance(result, BaseException):
            raise result
        return result


class FakeClient:
    """Stands in for openai.OpenAI. Each parse() call returns/raises the next result
    (the last one repeats)."""

    def __init__(self, *results: Any):
        self.responses = FakeResponses(list(results) or [completed_response()])
