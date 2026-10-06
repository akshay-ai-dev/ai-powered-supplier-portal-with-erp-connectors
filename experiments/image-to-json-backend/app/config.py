"""Configuration: paths, limits, and settings loaded from the project's .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

# The project root is the folder that contains main.py and .env, regardless of
# the directory the command is run from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_MODEL = "gpt-6.1-sol"
SCHEMA_VERSION = "2.0"  # 2.0 = six-key shipment schema (1.0 was general extraction)

# Image limits (checked locally before anything is sent to the API).
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB per file
MAX_IMAGE_PIXELS = 40_000_000  # 40 megapixels decoded (width * height)

# API call limits.
REQUEST_TIMEOUT_SECONDS = 180.0  # per request attempt
MAX_RETRIES = 3  # SDK retries for timeouts, connection errors, 408/409/429/5xx
MAX_OUTPUT_TOKENS = 32_000  # includes any reasoning tokens
IMAGE_DETAIL = "high"  # full-fidelity image understanding for text-heavy images

# Web API (app/api.py).
WEB_RESULTS_DIR = PROJECT_ROOT / "outputs_shipments" / "web"  # <id>.json (six keys) + <id>.meta.json
MAX_CONCURRENT_EXTRACTIONS = 2  # further uploads get HTTP 429 until a slot frees up


class MissingAPIKeyError(RuntimeError):
    """Raised when OPENAI_API_KEY is not set."""


def missing_key_message(env_file: Path = ENV_FILE) -> str:
    return (
        "OPENAI_API_KEY is not set.\n"
        f"Open this file in your editor:\n  {env_file}\n"
        "and put your key after the equals sign, like:\n"
        "  OPENAI_API_KEY=sk-...\n"
        "Save the file and run the command again. "
        "(Never paste your key into chat or commit it to git.)"
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


def load_settings(*, require_api_key: bool, env_file: Path = ENV_FILE) -> Settings:
    """Load settings from env_file (project-root .env by default).

    Variables already set in the shell environment take precedence over .env.
    The file is re-read on every call (without copying it into os.environ), so
    a running web backend picks up .env edits on the next request.
    """
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def get(name: str) -> str:
        return (os.environ.get(name) or file_values.get(name) or "").strip()

    api_key = get("OPENAI_API_KEY") or None
    model = get("OPENAI_MODEL") or DEFAULT_MODEL

    if require_api_key and api_key is None:
        raise MissingAPIKeyError(missing_key_message(env_file))

    return Settings(api_key=api_key, model=model)
