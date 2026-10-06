from __future__ import annotations

import json

import openai
import pytest

from app import batch, config
from app.batch import EXIT_FATAL, EXIT_OK, EXIT_SOME_FAILED, run_batch
from app.schemas import SHIPMENT_FIELDS as SIX_KEYS_ORDER
from app.schemas import ShipmentExtraction
from tests.helpers import (
    SAMPLE_SHIPMENT_JSON,
    SIX_KEYS,
    FakeClient,
    api_status_error,
    completed_response,
    incomplete_response,
    make_image,
    refusal_response,
)


class Output:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    make_image(root / "5 images" / "scan one.png")
    make_image(root / "5 images" / "scan one.jpg", fmt="JPEG")  # same stem, other extension
    make_image(root / "top.webp", fmt="WEBP")
    return root


def summary(output_dir):
    return json.loads((output_dir / "batch_summary.json").read_text(encoding="utf-8"))


def test_full_run_writes_valid_json_preserving_structure(tmp_path, data, settings):
    out_dir = tmp_path / "outputs"
    client = FakeClient(completed_response())

    code = run_batch(data, out_dir, settings=settings, client=client, out=Output())

    assert code == EXIT_OK
    assert len(client.responses.calls) == 3
    png_json = out_dir / "5 images" / "scan one.png.json"
    jpg_json = out_dir / "5 images" / "scan one.jpg.json"
    assert png_json.is_file() and jpg_json.is_file() and (out_dir / "top.webp.json").is_file()

    # Each result file contains exactly the six shipment keys and nothing else.
    for path in (png_json, jpg_json, out_dir / "top.webp.json"):
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved == SAMPLE_SHIPMENT_JSON
        assert set(saved) == SIX_KEYS
    assert '"000123"' in png_json.read_text(encoding="utf-8")  # leading zeros kept as strings

    # Operational metadata is in the summary, not in the result files.
    s = summary(out_dir)
    assert s["schema_version"] == "2.0"
    assert s["result_fields"] == list(SIX_KEYS_ORDER)
    assert s["counts"] == {"success": 3, "failed": 0, "skipped": 0, "not_attempted": 0}
    files = {f["output_file"]: f for f in s["files"]}
    assert set(files) == {"5 images/scan one.jpg.json", "5 images/scan one.png.json", "top.webp.json"}
    png_record = files["5 images/scan one.png.json"]
    assert png_record["source_file"] == "5 images/scan one.png"
    assert png_record["model"] == "test-model-2026"
    assert png_record["processed_at"]
    assert not list(out_dir.rglob("*.tmp"))


def test_default_cli_output_folder_is_outputs_shipments():
    import main

    assert main.parse_args([]).output_dir.as_posix() == "outputs_shipments"


def test_old_format_results_are_protected(tmp_path, data, settings):
    out_dir = tmp_path / "outputs"
    old = out_dir / "5 images" / "scan one.png.json"
    old.parent.mkdir(parents=True)
    old_content = json.dumps(
        {"schema_version": "1.0", "source_file": "scan one.png", "processed_at": "x", "model": "m",
         "extraction": {"document_type": None, "language": None, "text": "", "fields": [], "tables": [], "warnings": []}}
    )
    old.write_text(old_content, encoding="utf-8")
    old_summary = out_dir / "batch_summary.json"
    old_summary.write_text('{"old": true}', encoding="utf-8")

    for overwrite in (False, True):
        client = FakeClient()
        out = Output()
        assert run_batch(data, out_dir, overwrite=overwrite, settings=settings, client=client, out=out) == EXIT_FATAL
        assert client.responses.calls == []
        assert "previous" in out.text and "outputs_shipments" in out.text
    assert run_batch(data, out_dir, dry_run=True, settings=settings, out=Output()) == EXIT_FATAL

    assert old.read_text(encoding="utf-8") == old_content
    assert old_summary.read_text(encoding="utf-8") == '{"old": true}'
    assert sorted(p.name for p in out_dir.rglob("*")) == ["5 images", "batch_summary.json", "scan one.png.json"]


def test_existing_results_are_skipped_then_overwrite_reprocesses(tmp_path, data, settings):
    out_dir = tmp_path / "outputs"
    run_batch(data, out_dir, settings=settings, client=FakeClient(), out=Output())

    client = FakeClient()
    out = Output()
    assert run_batch(data, out_dir, settings=settings, client=client, out=out) == EXIT_OK
    assert client.responses.calls == []
    assert summary(out_dir)["counts"]["skipped"] == 3
    assert "skipped" in out.text

    client = FakeClient()
    run_batch(data, out_dir, overwrite=True, settings=settings, client=client, out=Output())
    assert len(client.responses.calls) == 3
    assert summary(out_dir)["counts"]["success"] == 3


def test_invalid_existing_output_is_reprocessed(tmp_path, data, settings):
    out_dir = tmp_path / "outputs"
    bad = out_dir / "top.webp.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not valid json", encoding="utf-8")

    client = FakeClient()
    run_batch(data, out_dir, settings=settings, client=client, out=Output())

    assert len(client.responses.calls) == 3
    ShipmentExtraction.model_validate_json(bad.read_bytes())


def test_corrupt_image_fails_and_batch_continues(tmp_path, data, settings):
    (data / "5 images" / "corrupt.png").write_bytes(b"garbage bytes")
    out_dir = tmp_path / "outputs"
    client = FakeClient()

    code = run_batch(data, out_dir, settings=settings, client=client, out=Output())

    assert code == EXIT_SOME_FAILED
    assert len(client.responses.calls) == 3  # no API call for the corrupt file
    assert not (out_dir / "5 images" / "corrupt.png.json").exists()
    record = next(f for f in summary(out_dir)["files"] if f["source_file"].endswith("corrupt.png"))
    assert record["status"] == "failed" and "invalid image" in record["error"]


@pytest.mark.parametrize("bad_response", [refusal_response(), incomplete_response()])
def test_refusal_or_incomplete_is_not_saved_as_success(tmp_path, data, settings, bad_response):
    out_dir = tmp_path / "outputs"
    client = FakeClient(bad_response, completed_response())  # first image bad, rest fine

    code = run_batch(data, out_dir, settings=settings, client=client, out=Output())

    assert code == EXIT_SOME_FAILED
    s = summary(out_dir)
    assert s["counts"] == {"success": 2, "failed": 1, "skipped": 0, "not_attempted": 0}
    failed = next(f for f in s["files"] if f["status"] == "failed")
    assert not (out_dir / failed["output_file"]).exists()


def test_authentication_failure_stops_further_api_calls(tmp_path, data, settings):
    out_dir = tmp_path / "outputs"
    client = FakeClient(api_status_error(openai.AuthenticationError, 401, "invalid_api_key"))
    out = Output()

    code = run_batch(data, out_dir, settings=settings, client=client, out=out)

    assert code == EXIT_FATAL
    assert len(client.responses.calls) == 1
    s = summary(out_dir)
    assert s["stopped_early"] is True
    assert s["counts"] == {"success": 0, "failed": 1, "skipped": 0, "not_attempted": 2}
    assert list(out_dir.rglob("*.png.json")) == []
    assert "Authentication failed" in out.text
    assert settings.api_key not in out.text and "sk-abc" not in out.text


@pytest.fixture
def empty_env(tmp_path, monkeypatch):
    """Point settings loading at a .env with an empty key instead of the project's .env."""
    env_file = tmp_path / "empty.env"
    env_file.write_text("OPENAI_API_KEY=\nOPENAI_MODEL=test-model\n", encoding="utf-8")
    monkeypatch.setattr(
        batch,
        "load_settings",
        lambda require_api_key: config.load_settings(require_api_key=require_api_key, env_file=env_file),
    )
    return env_file


def test_dry_run_makes_no_api_calls_and_needs_no_key(tmp_path, data, monkeypatch, empty_env):
    def fail(*args, **kwargs):
        raise AssertionError("dry run must not create an API client")

    monkeypatch.setattr(batch, "build_client", fail)
    out_dir = tmp_path / "outputs"
    out = Output()

    code = run_batch(data, out_dir, dry_run=True, out=out)

    assert code == EXIT_OK
    assert not out_dir.exists()  # nothing written
    assert "scan one.png" in out.text and "scan one.jpg" in out.text
    assert "3 image(s) would be sent" in out.text


def test_missing_api_key_gives_clear_message(tmp_path, data, empty_env):
    out = Output()

    code = run_batch(data, tmp_path / "outputs", out=out)

    assert code == EXIT_FATAL
    assert "OPENAI_API_KEY is not set" in out.text
    assert str(empty_env) in out.text


def test_input_dir_matched_case_insensitively(tmp_path, settings):
    make_image(tmp_path / "Data" / "a.png")
    client = FakeClient()
    code = run_batch(tmp_path / "data", tmp_path / "outputs", settings=settings, client=client, out=Output())
    assert code == EXIT_OK
    assert (tmp_path / "outputs" / "a.png.json").is_file()


def test_missing_input_dir(tmp_path, settings):
    out = Output()
    assert run_batch(tmp_path / "nope", tmp_path / "o", settings=settings, client=FakeClient(), out=out) == EXIT_FATAL
    assert "not found" in out.text
