"""Sequential batch processing: discover, validate, extract, and save JSON results."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pydantic

from app.config import SCHEMA_VERSION, MissingAPIKeyError, Settings, load_settings
from app.extraction import ExtractionError, FatalAPIError, build_client, extract_image
from app.image_processing import ImageValidationError, discover_images, prepare_image
from app.schemas import SHIPMENT_FIELDS, ShipmentExtraction

SUMMARY_FILENAME = "batch_summary.json"
DEFAULT_OUTPUT_DIR = Path("outputs_shipments")

EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_FATAL = 2

SUCCESS, FAILED, SKIPPED, NOT_ATTEMPTED = "success", "failed", "skipped", "not_attempted"


@dataclass
class FileRecord:
    source_file: str  # relative to the input folder
    output_file: str  # relative to the output folder
    status: str
    error: str | None = None
    # Operational metadata lives here, never inside the six-key result file.
    model: str | None = None
    processed_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_input_dir(path: Path) -> Path | None:
    """Return the input folder, matching its name case-insensitively if needed
    (e.g. "data" finds "Data" on a case-sensitive file system)."""
    if path.is_dir():
        return path
    parent = path.parent if str(path.parent) else Path(".")
    if parent.is_dir():
        for candidate in parent.iterdir():
            if candidate.is_dir() and candidate.name.lower() == path.name.lower():
                return candidate
    return None


def output_path_for(image: Path, input_dir: Path, output_dir: Path) -> Path:
    """photo.png -> <output_dir>/<same subfolders>/photo.png.json"""
    rel = image.relative_to(input_dir)
    return output_dir / rel.parent / f"{rel.name}.json"


def is_successful_output(path: Path) -> bool:
    """True if path holds a complete, valid six-key shipment result from a previous run."""
    if not path.is_file():
        return False
    try:
        ShipmentExtraction.model_validate_json(path.read_bytes())
    except (pydantic.ValidationError, OSError, ValueError):
        return False
    return True


def is_old_format_result(path: Path) -> bool:
    """True for a result file from the earlier general-extraction version
    (metadata plus an "extraction" object with text/fields/tables/warnings)."""
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "extraction" in data and "schema_version" in data


def find_old_format_results(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return [
        p
        for p in sorted(output_dir.rglob("*.json"))
        if p.name != SUMMARY_FILENAME and is_old_format_result(p)
    ]


def write_json_atomic(path: Path, data: Any) -> None:
    """Write UTF-8, indented JSON via a temp file + rename, so a crash never
    leaves a half-written file at the final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    settings: Settings | None = None,
    client: Any = None,
    out: Callable[[str], None] = print,
) -> int:
    resolved = resolve_input_dir(input_dir)
    if resolved is None:
        out(f"Error: input folder not found: {input_dir.resolve()}")
        return EXIT_FATAL
    if resolved.name != input_dir.name:
        out(f"Note: using input folder {resolved} (name matched case-insensitively).")
    input_dir = resolved

    discovery = discover_images(input_dir)
    images = discovery.images
    out(f"Found {len(images)} supported image(s) in {input_dir}")
    if discovery.ignored:
        out(f"Ignored {len(discovery.ignored)} file(s) without a .png/.jpg/.jpeg/.webp extension.")
    if not images:
        out("Nothing to do. Put PNG, JPEG, or WEBP images in the input folder.")
        return EXIT_OK

    # Never mix shipment results with (or overwrite) results from the earlier
    # general-extraction version.
    old_results = find_old_format_results(output_dir)
    if old_results:
        out(
            f"Error: {output_dir} contains {len(old_results)} result file(s) in the previous "
            "(general extraction) format. They are left untouched.\n"
            f"Write shipment results to a separate folder, for example:\n"
            f"  python main.py --input-dir {input_dir} --output-dir {DEFAULT_OUTPUT_DIR}"
        )
        return EXIT_FATAL

    if dry_run:
        return _dry_run(images, input_dir, output_dir, overwrite, settings, out)

    if settings is None:
        try:
            settings = load_settings(require_api_key=True)
        except MissingAPIKeyError as exc:
            out(f"Error: {exc}")
            return EXIT_FATAL
    if client is None:
        client = build_client(settings)

    out(f"Model: {settings.model}   Output folder: {output_dir}")
    out("Images are sent to the OpenAI API; this may incur charges.\n")

    started_at = _now()
    records: list[FileRecord] = []
    stop_reason: str | None = None
    total = len(images)

    for index, image in enumerate(images, start=1):
        rel = image.relative_to(input_dir).as_posix()
        out_path = output_path_for(image, input_dir, output_dir)
        record = FileRecord(rel, out_path.relative_to(output_dir).as_posix(), FAILED)
        records.append(record)
        prefix = f"[{index}/{total}] {rel}"

        if stop_reason is not None:
            record.status, record.error = NOT_ATTEMPTED, "batch stopped after a fatal API error"
            continue

        if not overwrite and is_successful_output(out_path):
            record.status = SKIPPED
            out(f"{prefix} ... skipped (result exists; use --overwrite to redo)")
            continue

        try:
            prepared = prepare_image(
                image,
                max_bytes=settings.max_image_bytes,
                max_pixels=settings.max_image_pixels,
            )
        except (ImageValidationError, OSError) as exc:
            record.error = f"invalid image: {exc}"
            out(f"{prefix} ... FAILED ({record.error})")
            continue

        t0 = time.monotonic()
        try:
            extraction, model_used = extract_image(client, settings, prepared)
            # The result file holds only the six shipment keys.
            write_json_atomic(out_path, extraction.model_dump(mode="json"))
            record.model, record.processed_at = model_used, _now()
        except FatalAPIError as exc:
            stop_reason = str(exc)
            record.error = stop_reason.splitlines()[0]
            out(f"{prefix} ... FAILED ({record.error})")
            continue
        except ExtractionError as exc:
            record.error = str(exc)
            out(f"{prefix} ... FAILED ({record.error})")
            continue
        except Exception as exc:  # unexpected: record only the type, never contents
            record.error = f"unexpected error ({type(exc).__name__})"
            out(f"{prefix} ... FAILED ({record.error})")
            continue

        record.status = SUCCESS
        out(f"{prefix} ... ok ({time.monotonic() - t0:.1f}s) -> {out_path}")

    counts = {s: sum(r.status == s for r in records) for s in (SUCCESS, FAILED, SKIPPED, NOT_ATTEMPTED)}
    summary = {
        "schema_version": SCHEMA_VERSION,
        "result_fields": list(SHIPMENT_FIELDS),
        "started_at": started_at,
        "finished_at": _now(),
        "model": settings.model,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "overwrite": overwrite,
        "stopped_early": stop_reason is not None,
        "counts": counts,
        "files": [asdict(r) for r in records],
    }
    summary_path = output_dir / SUMMARY_FILENAME
    write_json_atomic(summary_path, summary)

    out(
        f"\nDone. success: {counts[SUCCESS]}, failed: {counts[FAILED]}, "
        f"skipped: {counts[SKIPPED]}"
        + (f", not attempted: {counts[NOT_ATTEMPTED]}" if counts[NOT_ATTEMPTED] else "")
    )
    out(f"Summary saved to {summary_path}")

    if stop_reason is not None:
        out(f"\nStopped making API calls:\n{stop_reason}")
        return EXIT_FATAL
    if counts[FAILED]:
        out("Some images failed. Fix the cause and rerun; successful results will be skipped.")
        return EXIT_SOME_FAILED
    return EXIT_OK


def _dry_run(
    images: list[Path],
    input_dir: Path,
    output_dir: Path,
    overwrite: bool,
    settings: Settings | None,
    out: Callable[[str], None],
) -> int:
    """List images and check them locally. No API calls; no API key needed."""
    if settings is None:
        settings = load_settings(require_api_key=False)

    out(f"Dry run: no API calls will be made. Model that would be used: {settings.model}")
    out(f"OPENAI_API_KEY: {'set' if settings.api_key else 'NOT set (required for a real run)'}\n")

    to_process = 0
    for index, image in enumerate(images, start=1):
        rel = image.relative_to(input_dir).as_posix()
        out_path = output_path_for(image, input_dir, output_dir)
        try:
            prepared = prepare_image(
                image,
                max_bytes=settings.max_image_bytes,
                max_pixels=settings.max_image_pixels,
            )
        except (ImageValidationError, OSError) as exc:
            out(f"[{index}/{len(images)}] {rel} ... INVALID ({exc})")
            continue

        info = f"{prepared.mime_type}, {prepared.width}x{prepared.height}, {image.stat().st_size:,} bytes"
        if prepared.orientation_corrected:
            info += ", EXIF rotation will be applied"
        if not overwrite and is_successful_output(out_path):
            action = "would skip (result exists)"
        else:
            action = f"would process -> {out_path}"
            to_process += 1
        out(f"[{index}/{len(images)}] {rel} ({info}) ... {action}")

    out(f"\n{to_process} image(s) would be sent to the API.")
    return EXIT_OK
