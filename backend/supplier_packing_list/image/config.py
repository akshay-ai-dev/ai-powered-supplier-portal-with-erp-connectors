"""Configuration for the image (OpenAI) extraction path.

Adapted from ``experiments/image-to-json-backend/app/config.py``. The one
behavioural change for production: the API key and model are read from the
process environment only (never from a committed file), so the key lives wherever
the rest of the backend's secrets live (Docker Compose env / the ignored root
``.env``). Nothing here reads, logs, or returns the key value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "gpt-4o"  # portal default; must support image input + Structured Outputs
SCHEMA_VERSION = "2.0"  # six-key shipment schema

# Human-readable hint used in error messages (never an actual key or path).
ENV_FILE = "the backend environment (OPENAI_API_KEY in Docker Compose env or the root .env)"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# Image limits (checked locally before anything is sent to the API).
MAX_IMAGE_BYTES = _int_env("SPL_MAX_IMAGE_BYTES", 20 * 1024 * 1024)  # 20 MB per file
MAX_IMAGE_PIXELS = _int_env("SPL_MAX_IMAGE_PIXELS", 40_000_000)  # 40 MP decoded (w * h)

# API call limits.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("SPL_OCR_TIMEOUT_SECONDS", "").strip() or 180.0)
MAX_RETRIES = _int_env("SPL_OCR_MAX_RETRIES", 3)
MAX_OUTPUT_TOKENS = _int_env("SPL_OCR_MAX_OUTPUT_TOKENS", 32_000)
IMAGE_DETAIL = os.environ.get("SPL_OCR_IMAGE_DETAIL", "").strip() or "high"


class MissingAPIKeyError(RuntimeError):
    """Raised when OPENAI_API_KEY is not set."""


def missing_key_message() -> str:
    return (
        "OPENAI_API_KEY is not configured. Set it in the backend environment "
        "(Docker Compose passes OPENAI_API_KEY to the backend service; locally it "
        "comes from the project-root .env). Never paste the key into source or commit it."
    )


@dataclass(frozen=True)
class Settings:
    # repr=False keeps the key out of tracebacks, debug output, and logs.
    api_key: str | None = field(repr=False)
    model: str
    timeout: float = REQUEST_TIMEOUT_SECONDS
    max_retries: int = MAX_RETRIES
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    image_detail: str = IMAGE_DETAIL
    max_image_bytes: int = MAX_IMAGE_BYTES
    max_image_pixels: int = MAX_IMAGE_PIXELS


def load_settings(*, require_api_key: bool) -> Settings:
    """Load OpenAI settings from the process environment only.

    ``OPENAI_API_KEY`` is the key. The model is ``SPL_OCR_MODEL`` if set, else the
    shared ``OPENAI_MODEL``, else :data:`DEFAULT_MODEL`.
    """

    def get(name: str) -> str:
        return (os.environ.get(name) or "").strip()

    api_key = get("OPENAI_API_KEY") or None
    model = get("SPL_OCR_MODEL") or get("OPENAI_MODEL") or DEFAULT_MODEL

    if require_api_key and api_key is None:
        raise MissingAPIKeyError(missing_key_message())

    return Settings(api_key=api_key, model=model)
