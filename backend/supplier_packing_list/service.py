"""Orchestration: validate the upload, dispatch to the PDF or image extractor,
and normalise the result. This layer never touches the database, never creates a
shipment, and never submits anything — it returns a draft only.

External collaborators (the isolated PDF conversion, the OpenAI settings loader,
client factory, and extract call) are injected so tests can run without Docling or
a real OpenAI account.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Callable

from starlette.concurrency import run_in_threadpool

from app.services.errors import DomainError

from . import normalize
from .config import PDF_CONVERT_TIMEOUT_S
from .detect import detect
from .image.config import MissingAPIKeyError, load_settings
from .image.extraction import (
    ExtractionError,
    FatalAPIError,
    build_client,
    extract_image,
)
from .image.image_processing import ImageValidationError, prepare_image_bytes
from .pdf.isolation import convert_isolated
from .schemas import DraftExtraction


async def extract_draft(
    filename: str,
    data: bytes,
    *,
    # Injectable collaborators. Left as None, the module-level defaults are read at
    # call time, so a test can monkeypatch ``supplier_packing_list.service.<name>`` instead.
    convert: Callable[..., tuple[dict[str, Any], Any]] | None = None,
    settings_loader: Callable[..., Any] | None = None,
    client_factory: Callable[[Any], Any] | None = None,
    extract_image_fn: Callable[..., tuple[Any, str]] | None = None,
) -> DraftExtraction:
    """Validate ``data`` and return a normalised :class:`DraftExtraction`.

    Raises :class:`DomainError` (mapped to HTTP by the portal) for every
    client-facing failure.
    """
    kind, _mime = detect(filename, data)
    if kind == "pdf":
        return await _extract_pdf(filename, data, convert=convert or convert_isolated)
    return await _extract_image(
        filename,
        data,
        settings_loader=settings_loader or load_settings,
        client_factory=client_factory or build_client,
        extract_image_fn=extract_image_fn or extract_image,
    )


async def _extract_pdf(
    filename: str,
    data: bytes,
    *,
    convert: Callable[..., tuple[dict[str, Any], Any]],
) -> DraftExtraction:
    """Write the PDF to a temp file and convert it in the isolated child process,
    off the event loop. The native Docling crash cannot reach this process, and the
    temp file is always removed."""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="spl-pl-", suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        # convert_isolated spawns the child, enforces the timeout, retries once,
        # and returns a conversion-error document rather than raising on failure.
        result, _markdown = await run_in_threadpool(
            convert, tmp_path, timeout_s=PDF_CONVERT_TIMEOUT_S
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return normalize.from_pdf(result, filename)


async def _extract_image(
    filename: str,
    data: bytes,
    *,
    settings_loader: Callable[..., Any],
    client_factory: Callable[[Any], Any],
    extract_image_fn: Callable[..., tuple[Any, str]],
) -> DraftExtraction:
    try:
        settings = settings_loader(require_api_key=True)
    except MissingAPIKeyError as exc:
        raise DomainError(str(exc), 503) from exc

    try:
        prepared = await run_in_threadpool(
            prepare_image_bytes,
            data,
            max_bytes=settings.max_image_bytes,
            max_pixels=settings.max_image_pixels,
        )
    except ImageValidationError as exc:
        raise DomainError(f"The image could not be used: {exc}.", 422) from exc

    try:
        client = client_factory(settings)
        extraction, model_used = await run_in_threadpool(
            extract_image_fn, client, settings, prepared
        )
    except FatalAPIError as exc:
        # Account/config problem (bad key, quota, model). Message is safe (no key).
        raise DomainError(f"Image extraction is unavailable: {exc}", 502) from exc
    except ExtractionError as exc:
        raise DomainError(f"Image extraction failed: {exc}.", 502) from exc

    return normalize.from_image(extraction, filename, model_used)
