"""Local HTTP API for the frontend. Reuses the CLI's validation, extraction, and schemas.

Start with:
    python -m uvicorn app.api:app --host 127.0.0.1 --port 8000

Endpoints
---------
GET  /health
    200 {"status": "ok", "model": str, "api_key_configured": bool}

POST /api/v1/extractions        (multipart/form-data, field "file")
    Waits for the extraction to finish, then returns
    201 {"id": str, "download_url": str, "source_file": str, "model": str,
         "processed_at": str, "result": ShipmentExtraction}
    Operational metadata stays in the envelope; "result" has exactly the six
    shipment keys (see app/schemas.py).

GET  /api/v1/extractions/{id}/download
    200 the six-key result JSON only, as an attachment

Every error response has the shape
    {"error": {"code": str, "message": str}}
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.batch import write_json_atomic
from app.config import (
    MAX_CONCURRENT_EXTRACTIONS,
    SCHEMA_VERSION,
    WEB_RESULTS_DIR,
    MissingAPIKeyError,
    Settings,
    load_settings,
)
from app.extraction import ExtractionError, FatalAPIError, build_client, extract_image
from app.image_processing import SUPPORTED_EXTENSIONS, ImageValidationError, prepare_image_bytes
from app.schemas import ShipmentExtraction

EXTRACTIONS_PATH = "/api/v1/extractions"
_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_MULTIPART_OVERHEAD = 64 * 1024  # allowance for multipart headers/boundaries


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ExtractionResponse(BaseModel):
    id: str
    download_url: str
    source_file: str
    model: str
    processed_at: str
    result: ShipmentExtraction


class ExtractionMetadata(BaseModel):
    """Saved next to each web result as <id>.meta.json, never inside it."""

    schema_version: str
    source_file: str
    model: str
    processed_at: str


class HealthResponse(BaseModel):
    status: str
    model: str
    api_key_configured: bool


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _safe_filename(name: str | None) -> str:
    """Keep only the base name of the uploaded file, without control characters."""
    base = Path((name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return base[:200] or "upload"


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks, total = [], 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise ApiError(413, "file_too_large", f"The image is larger than the {limit // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(
    *,
    settings_loader: Callable[..., Settings] = load_settings,
    client_factory: Callable[[Settings], Any] = build_client,
    results_dir: Path = WEB_RESULTS_DIR,
    max_concurrent: int = MAX_CONCURRENT_EXTRACTIONS,
) -> FastAPI:
    app = FastAPI(
        title="Image to JSON API",
        description="Local API that extracts text, fields, and tables from one image using OpenAI.",
        version=SCHEMA_VERSION,
    )
    slots = asyncio.Semaphore(max_concurrent)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(400, "invalid_request", "The request was not a valid image upload.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Only the type is reported; never request contents or credentials.
        return _error(500, "internal_error", f"Unexpected server error ({type(exc).__name__}).")

    @app.middleware("http")
    async def _reject_oversized_uploads(request: Request, call_next):
        # Rejects obviously oversized uploads before the body is read.
        if request.method == "POST" and request.url.path == EXTRACTIONS_PATH:
            length = request.headers.get("content-length")
            limit = settings_loader(require_api_key=False).max_image_bytes
            if length and length.isdigit() and int(length) > limit + _MULTIPART_OVERHEAD:
                return _error(413, "file_too_large", f"The image is larger than the {limit // (1024 * 1024)} MB limit.")
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        settings = settings_loader(require_api_key=False)
        return HealthResponse(status="ok", model=settings.model, api_key_configured=bool(settings.api_key))

    @app.post(
        EXTRACTIONS_PATH,
        status_code=201,
        response_model=ExtractionResponse,
        responses={
            400: {"model": ErrorResponse, "description": "No file was uploaded"},
            413: {"model": ErrorResponse, "description": "Image exceeds the byte limit"},
            415: {"model": ErrorResponse, "description": "Not a .png/.jpg/.jpeg/.webp file"},
            422: {"model": ErrorResponse, "description": "Corrupt, animated, or oversized image"},
            429: {"model": ErrorResponse, "description": "Too many extractions running"},
            502: {"model": ErrorResponse, "description": "OpenAI request failed"},
            503: {"model": ErrorResponse, "description": "OPENAI_API_KEY not configured"},
        },
    )
    async def create_extraction(file: UploadFile | None = File(None)) -> ExtractionResponse:
        if file is None or not file.filename:
            raise ApiError(400, "missing_file", 'No image was uploaded. Send it in the multipart field "file".')
        filename = _safe_filename(file.filename)
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ApiError(415, "unsupported_file_type", "Only PNG, JPEG, and WEBP images are supported.")

        try:
            settings = settings_loader(require_api_key=True)
        except MissingAPIKeyError:
            raise ApiError(
                503,
                "api_key_missing",
                "The server has no OpenAI API key. Add OPENAI_API_KEY to the project's .env file "
                "and restart the backend.",
            )

        raw = await _read_limited(file, settings.max_image_bytes)
        try:
            prepared = await run_in_threadpool(
                prepare_image_bytes, raw, max_bytes=settings.max_image_bytes, max_pixels=settings.max_image_pixels
            )
        except ImageValidationError as exc:
            raise ApiError(422, "invalid_image", f"The image could not be used: {exc}.")

        # Bound concurrent paid extractions. asyncio is single-threaded, so the
        # check-then-acquire below cannot race.
        if slots.locked():
            raise ApiError(429, "busy", "Another extraction is already running. Wait for it to finish, then try again.")
        async with slots:
            try:
                client = client_factory(settings)
                extraction, model_used = await run_in_threadpool(extract_image, client, settings, prepared)
            except FatalAPIError as exc:
                raise ApiError(502, "openai_account_error", str(exc))
            except ExtractionError as exc:
                raise ApiError(502, "extraction_failed", f"Extraction failed: {exc}.")

        extraction_id = uuid.uuid4().hex
        metadata = ExtractionMetadata(
            schema_version=SCHEMA_VERSION,
            source_file=filename,
            processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            model=model_used,
        )
        # Metadata first: a result file then always has its metadata.
        await run_in_threadpool(write_json_atomic, results_dir / f"{extraction_id}.meta.json", metadata.model_dump())
        await run_in_threadpool(write_json_atomic, results_dir / f"{extraction_id}.json", extraction.model_dump(mode="json"))
        return ExtractionResponse(
            id=extraction_id,
            download_url=f"{EXTRACTIONS_PATH}/{extraction_id}/download",
            source_file=metadata.source_file,
            model=metadata.model,
            processed_at=metadata.processed_at,
            result=extraction,
        )

    @app.get(
        EXTRACTIONS_PATH + "/{extraction_id}/download",
        responses={200: {"content": {"application/json": {}}}, 404: {"model": ErrorResponse}},
    )
    async def download_extraction(extraction_id: str) -> FileResponse:
        path = results_dir / f"{extraction_id}.json"
        # The strict ID pattern also prevents path traversal.
        if not _ID_PATTERN.fullmatch(extraction_id) or not path.is_file():
            raise ApiError(404, "not_found", "No saved extraction has this ID.")
        try:
            # Only a valid six-key result is ever served.
            ShipmentExtraction.model_validate_json(path.read_bytes())
        except ValueError:
            raise ApiError(500, "corrupt_result", "The saved extraction file is unreadable.")
        try:
            meta = ExtractionMetadata.model_validate_json((results_dir / f"{extraction_id}.meta.json").read_bytes())
            filename = f"{_safe_filename(meta.source_file)}.json"
        except (OSError, ValueError):
            filename = f"shipment-{extraction_id}.json"
        return FileResponse(path, media_type="application/json", filename=filename)

    return app


app = create_app()
