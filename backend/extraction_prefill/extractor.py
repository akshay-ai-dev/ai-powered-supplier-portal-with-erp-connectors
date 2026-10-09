"""The OpenAI call: a PDF or image in, a reviewable draft out.

PDFs go as a Chat Completions `file` content part (base64 data URL); images go as an `image_url`
part. Both use the strict `json_schema` structured-output format against a caller-supplied schema,
on the configured vision-capable model (gpt-4o by default). The file is validated (type and size)
before any network call, so a bad upload never reaches OpenAI. This mirrors the existing
`app.ai.llm.OpenAILLM` pattern rather than importing it (that one is text-only).

`run()` is the shared upload-and-call core: it classifies and size-checks the file, builds the
PDF/image content part, calls OpenAI with the given system prompt, user instruction and strict JSON
schema, and returns the raw parsed dict. The supplier shipment `extract()` here and the buyer
requirement extractor both go through it, so the OpenAI PDF/image handling lives in one place.
"""

import base64
import json
import logging
import os

from app.config import settings
from app.services.errors import DomainError

from . import rules
from .prompts import DRAFT_JSON_SCHEMA, SYSTEM_PROMPT, USER_INSTRUCTION
from .schemas import ExtractionDraft

log = logging.getLogger("erp.extraction_prefill")

MAX_BYTES = 10 * 1024 * 1024  # same ceiling as requirement attachments; well under OpenAI's 50 MB
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _classify(filename: str, content_type: str | None) -> tuple[str, str]:
    """Return ("pdf"|"image", mime). Raises 415 for anything else. Extension wins; MIME is a fallback."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf" or content_type == "application/pdf":
        return "pdf", "application/pdf"
    if ext in _IMAGE_MIME:
        return "image", _IMAGE_MIME[ext]
    if content_type in set(_IMAGE_MIME.values()):
        return "image", content_type  # type: ignore[return-value]
    raise DomainError(
        "Only a PDF or an image (PNG, JPG, GIF, WEBP) can be used for extraction.", 415
    )


def build_client():
    """The OpenAI client. Kept behind a function so tests pass a fake client instead."""
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key, timeout=60, max_retries=1)


def _content_parts(
    kind: str, mime: str, filename: str, data: bytes, instruction: str
) -> list[dict]:
    b64 = base64.b64encode(data).decode()
    if kind == "pdf":
        file_part = {
            "type": "file",
            "file": {
                "filename": filename or "document.pdf",
                "file_data": f"data:{mime};base64,{b64}",
            },
        }
    else:
        file_part = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    return [{"type": "text", "text": instruction}, file_part]


def run(
    filename: str,
    data: bytes,
    content_type: str | None,
    *,
    system_prompt: str,
    user_instruction: str,
    json_schema: dict,
    schema_name: str,
    client=None,
    model: str | None = None,
) -> dict:
    """Validate the upload and ask OpenAI for a structured draft against `json_schema`.

    Returns the raw parsed dict (no domain shaping). The file type and size are checked before any
    network call, so a bad upload never reaches OpenAI. Shared by the shipment and buyer extractors
    so the PDF/image upload handling is not duplicated.
    """
    kind, mime = _classify(filename, content_type)  # 415 before any network call
    if not data:
        raise DomainError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise DomainError(f"File is larger than {MAX_BYTES // (1024 * 1024)} MB.", 413)

    client = client or build_client()
    model = model or settings.openai_model
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": _content_parts(kind, mime, filename, data, user_instruction),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001  network, auth, quota or bad JSON -> one clear message
        log.warning("extraction call failed: %s", exc)
        raise DomainError(
            "Could not read the document right now. You can still fill the form yourself.", 503
        ) from None


def extract(
    filename: str,
    data: bytes,
    content_type: str | None,
    *,
    client=None,
    model: str | None = None,
) -> dict:
    """Validate the upload, ask OpenAI for a structured shipment draft, tidy it, return a dict."""
    raw = run(
        filename,
        data,
        content_type,
        system_prompt=SYSTEM_PROMPT,
        user_instruction=USER_INSTRUCTION,
        json_schema=DRAFT_JSON_SCHEMA,
        schema_name="shipment_draft",
        client=client,
        model=model,
    )
    draft = rules.finalize(ExtractionDraft.model_validate(raw))
    return draft.model_dump()
