"""Validate an upload by BOTH its extension and its actual content, and decide
which extraction path handles it.

The client-supplied filename is never trusted on its own: the magic bytes must
agree with the extension's family (document vs. image), and the extension must be
one we support. The image path then does a second, deeper validation (full decode,
animation/decompression-bomb checks) in :mod:`supplier_packing_list.image.image_processing`.
"""

from __future__ import annotations

import os

from app.services.errors import DomainError

from .config import ALLOWED_EXT, ALLOWED_IMAGE_EXT, ALLOWED_PDF_EXT

# MIME reported for the detected content (not the extension).
_IMAGE_MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


def _sniff_content(data: bytes) -> str | None:
    """Return 'pdf' | 'png' | 'jpeg' | 'webp' from the leading bytes, else None."""
    if data[:5] == b"%PDF-" or data[:4] == b"%PDF":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def extension_of(filename: str) -> str:
    return os.path.splitext((filename or "").replace("\\", "/"))[1].lower()


def detect(filename: str, data: bytes) -> tuple[str, str | None]:
    """Validate and classify an upload.

    Returns ``("pdf", None)`` or ``("image", <mime>)``.

    Raises :class:`DomainError` with the right HTTP status for an empty file
    (400), an unsupported extension (415), or content that is unreadable or does
    not match the extension's family (422).
    """
    if not data:
        raise DomainError("The uploaded file is empty.", 400)

    ext = extension_of(filename)
    if ext not in ALLOWED_EXT:
        raise DomainError(
            f"File type '{ext or 'unknown'}' is not supported. Upload a PDF, PNG, JPEG, or WEBP "
            "packing list.",
            415,
        )

    detected = _sniff_content(data)
    if detected is None:
        raise DomainError(
            "The file content is not a readable PDF or image (it may be corrupt or the wrong "
            "type).",
            422,
        )

    ext_is_pdf = ext in ALLOWED_PDF_EXT
    detected_is_pdf = detected == "pdf"
    if ext_is_pdf != detected_is_pdf:
        raise DomainError(
            f"The file content ({detected}) does not match its '{ext}' extension. Upload the file "
            "with the correct extension.",
            422,
        )

    if detected_is_pdf:
        return "pdf", None

    # Both extension and content are images. A mislabelled-but-valid image
    # (e.g. .jpg that is really a PNG) is accepted: the content decides the MIME,
    # and the extension stays within the image family. Guard the family only.
    if ext not in ALLOWED_IMAGE_EXT:  # pragma: no cover - unreachable given checks above
        raise DomainError(f"Unsupported image extension '{ext}'.", 415)
    return "image", _IMAGE_MIME[detected]
