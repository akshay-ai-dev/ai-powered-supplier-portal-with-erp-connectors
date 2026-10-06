"""HTTP API tests. OpenAI is replaced by FakeClient: no key, no network, no charges."""

from __future__ import annotations

import dataclasses
import io
import json

import openai
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import create_app
from app.config import MissingAPIKeyError, Settings
from app.schemas import ShipmentExtraction
from tests.helpers import (
    SAMPLE_SHIPMENT_JSON,
    SIX_KEYS,
    FakeClient,
    api_status_error,
    completed_response,
    refusal_response,
)


def png_bytes(fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format=fmt)
    return buf.getvalue()


class Harness:
    def __init__(self, tmp_path, settings: Settings, *responses, max_concurrent: int = 2):
        self.fake = FakeClient(*responses)
        self.results_dir = tmp_path / "web"

        def loader(*, require_api_key: bool) -> Settings:
            if require_api_key and not settings.api_key:
                raise MissingAPIKeyError("missing")
            return settings

        self.client = TestClient(
            create_app(
                settings_loader=loader,
                client_factory=lambda s: self.fake,
                results_dir=self.results_dir,
                max_concurrent=max_concurrent,
            )
        )

    def upload(self, name="doc.png", data: bytes | None = None, content_type="image/png"):
        data = png_bytes() if data is None else data
        return self.client.post("/api/v1/extractions", files={"file": (name, data, content_type)})

    @property
    def api_calls(self) -> int:
        return len(self.fake.responses.calls)


def assert_error(response, status: int, code: str):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]["message"]


def test_health_reports_model_without_exposing_key(tmp_path, settings):
    response = Harness(tmp_path, settings).client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "test-model", "api_key_configured": True}
    assert settings.api_key not in response.text


def test_upload_returns_envelope_with_six_key_result_and_saves_it(tmp_path, settings):
    h = Harness(tmp_path, settings)

    response = h.upload("My Scan.png")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "download_url", "source_file", "model", "processed_at", "result"}
    assert len(body["id"]) == 32
    assert body["download_url"] == f"/api/v1/extractions/{body['id']}/download"
    assert body["source_file"] == "My Scan.png"
    assert body["model"] == "test-model-2026"
    assert body["processed_at"]
    assert body["result"] == SAMPLE_SHIPMENT_JSON
    assert set(body["result"]) == SIX_KEYS

    # Saved result: exactly six keys. Metadata: a separate sidecar file.
    saved = json.loads((h.results_dir / f"{body['id']}.json").read_text(encoding="utf-8"))
    assert saved == SAMPLE_SHIPMENT_JSON
    meta = json.loads((h.results_dir / f"{body['id']}.meta.json").read_text(encoding="utf-8"))
    assert meta == {"schema_version": "2.0", "source_file": "My Scan.png", "model": "test-model-2026",
                    "processed_at": body["processed_at"]}
    assert h.fake.responses.calls[0]["store"] is False
    assert h.fake.responses.calls[0]["text_format"] is ShipmentExtraction


def test_empty_result_keeps_nulls_and_empty_arrays(tmp_path, settings):
    empty = ShipmentExtraction.model_validate(
        {"shipDate": None, "carrier": None, "trackingNumbers": [], "shippedQuantity": None,
         "lotNumbers": [], "serialNumbers": []}
    )
    h = Harness(tmp_path, settings, completed_response(parsed=empty))
    body = h.upload().json()
    assert body["result"] == {"shipDate": None, "carrier": None, "trackingNumbers": [], "shippedQuantity": None,
                              "lotNumbers": [], "serialNumbers": []}
    assert json.loads(h.client.get(body["download_url"]).content) == body["result"]


def test_download_returns_only_the_six_key_result(tmp_path, settings):
    h = Harness(tmp_path, settings)
    body = h.upload("photo.jpg", png_bytes("JPEG"), "image/jpeg").json()

    response = h.client.get(body["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert 'attachment; filename="photo.jpg.json"' in response.headers["content-disposition"]
    downloaded = json.loads(response.content)
    assert downloaded == body["result"] == SAMPLE_SHIPMENT_JSON
    assert set(downloaded) == SIX_KEYS


def test_download_without_metadata_uses_fallback_name(tmp_path, settings):
    h = Harness(tmp_path, settings)
    body = h.upload().json()
    (h.results_dir / f"{body['id']}.meta.json").unlink()
    response = h.client.get(body["download_url"])
    assert response.status_code == 200
    assert f'filename="shipment-{body["id"]}.json"' in response.headers["content-disposition"]


def test_download_refuses_a_file_that_is_not_a_valid_shipment_result(tmp_path, settings):
    h = Harness(tmp_path, settings)
    body = h.upload().json()
    (h.results_dir / f"{body['id']}.json").write_text('{"extraction": {}}', encoding="utf-8")
    assert_error(h.client.get(body["download_url"]), 500, "corrupt_result")


@pytest.mark.parametrize("bad_id", ["0" * 32, "not-an-id", "..%2F..%2Fetc%2Fpasswd"])
def test_download_unknown_or_malformed_id_is_404(tmp_path, settings, bad_id):
    response = Harness(tmp_path, settings).client.get(f"/api/v1/extractions/{bad_id}/download")
    assert_error(response, 404, "not_found")


def test_missing_file_field(tmp_path, settings):
    h = Harness(tmp_path, settings)
    response = h.client.post("/api/v1/extractions", files={"other": ("a.png", png_bytes(), "image/png")})
    assert response.status_code == 400
    assert h.api_calls == 0


def test_unsupported_extension_rejected_without_api_call(tmp_path, settings):
    h = Harness(tmp_path, settings)
    assert_error(h.upload("notes.txt", b"hello", "text/plain"), 415, "unsupported_file_type")
    assert h.api_calls == 0


@pytest.mark.parametrize(
    "data",
    [b"\x89PNG\r\n\x1a\n not really a png", png_bytes("GIF"), b""],
    ids=["corrupt", "gif-renamed-png", "empty"],
)
def test_invalid_image_rejected_without_api_call(tmp_path, settings, data):
    h = Harness(tmp_path, settings)
    assert_error(h.upload("doc.png", data), 422, "invalid_image")
    assert h.api_calls == 0


def test_oversized_upload_rejected(tmp_path, settings):
    small = dataclasses.replace(settings, max_image_bytes=100)
    h = Harness(tmp_path, small)
    assert_error(h.upload("doc.png", b"\x00" * 200_000), 413, "file_too_large")  # Content-Length check
    assert_error(h.upload("doc.png", png_bytes()), 413, "file_too_large")  # streamed read limit
    assert h.api_calls == 0


def test_missing_api_key_is_503_with_instructions(tmp_path):
    h = Harness(tmp_path, Settings(api_key=None, model="test-model"))
    message = assert_error(h.upload(), 503, "api_key_missing")
    assert ".env" in message
    assert h.api_calls == 0


def test_refusal_returns_502_and_saves_nothing(tmp_path, settings):
    h = Harness(tmp_path, settings, refusal_response())
    message = assert_error(h.upload(), 502, "extraction_failed")
    assert "refused" in message
    assert not h.results_dir.exists() or not list(h.results_dir.iterdir())


def test_authentication_failure_is_reported_without_key(tmp_path, settings):
    h = Harness(tmp_path, settings, api_status_error(openai.AuthenticationError, 401, "invalid_api_key"))
    response = h.upload()
    message = assert_error(response, 502, "openai_account_error")
    assert "Authentication failed" in message
    assert settings.api_key not in response.text and "sk-abc" not in response.text


def test_concurrent_extractions_are_bounded(tmp_path, settings):
    h = Harness(tmp_path, settings, completed_response(), max_concurrent=0)  # no free slots
    assert_error(h.upload(), 429, "busy")
    assert h.api_calls == 0
