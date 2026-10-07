"""Integration-level configuration (upload limits, PDF timeout).

All values come from the process environment with safe defaults, so a teammate can
run the branch with no extra setup. The OpenAI key/model for the image path live
in :mod:`supplier_packing_list.image.config` (read from the environment only).
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# Largest upload accepted by the draft endpoint (applies to both PDF and image).
# Kept at the portal's existing attachment limit (10 MB) by default.
MAX_UPLOAD_BYTES = _int_env("SPL_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)

# Per-attempt timeout (seconds) for the isolated Docling conversion. Uses the same
# single env var that ``isolation.py``, docker-compose.yml and .env.example use, so
# one value controls the timeout everywhere (default 600).
PDF_CONVERT_TIMEOUT_S = _int_env("PACKING_CONVERT_TIMEOUT_S", 600)

ALLOWED_PDF_EXT = {".pdf"}
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_EXT = ALLOWED_PDF_EXT | ALLOWED_IMAGE_EXT
