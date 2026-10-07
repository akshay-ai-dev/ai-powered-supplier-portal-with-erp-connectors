"""Image discovery, validation, and EXIF orientation correction (all in memory)."""

from __future__ import annotations

import base64
import io
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Pillow format name -> MIME type. The MIME type comes from the decoded file
# contents, not the extension, so a mislabeled file is still sent correctly.
FORMAT_MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

EXIF_ORIENTATION_TAG = 0x0112


class ImageValidationError(ValueError):
    """The file is not a usable image (corrupt, animated, too large, unsupported)."""


@dataclass
class Discovery:
    images: list[Path] = field(default_factory=list)
    ignored: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedImage:
    mime_type: str
    data: bytes = field(repr=False)  # never printed
    width: int
    height: int
    orientation_corrected: bool

    def to_data_url(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.data).decode('ascii')}"


def _is_hidden(path: Path, root: Path) -> bool:
    # Skips .DS_Store, macOS "._" resource-fork files, and hidden folders.
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def discover_images(input_dir: Path) -> Discovery:
    """Recursively find supported images (by extension, case-insensitive), sorted."""
    result = Discovery()
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or _is_hidden(path, input_dir):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            result.images.append(path)
        else:
            result.ignored.append(path)
    return result


def prepare_image(
    path: Path,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> PreparedImage:
    """Validate an image and return the bytes to send, with EXIF orientation applied.

    The source file is only read, never modified.
    """
    _check_size(path.stat().st_size, max_bytes)
    return prepare_image_bytes(path.read_bytes(), max_bytes=max_bytes, max_pixels=max_pixels)


def _check_size(size: int, max_bytes: int) -> None:
    if size == 0:
        raise ImageValidationError("file is empty")
    if size > max_bytes:
        raise ImageValidationError(f"file is {size:,} bytes; the limit is {max_bytes:,} bytes")


def prepare_image_bytes(
    raw: bytes,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> PreparedImage:
    """Same validation as prepare_image, for image bytes already in memory (uploads)."""
    _check_size(len(raw), max_bytes)

    try:
        with warnings.catch_warnings():
            # Treat Pillow's decompression-bomb warning as an error.
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            # Pass 1: structural check without decoding pixels.
            with Image.open(io.BytesIO(raw)) as img:
                fmt = img.format
                width, height = img.size
                if fmt not in FORMAT_MIME_TYPES:
                    raise ImageValidationError(
                        f"unsupported image format {fmt!r}; only PNG, JPEG, and static WEBP are supported"
                    )
                if width * height > max_pixels:
                    raise ImageValidationError(
                        f"image is {width}x{height} ({width * height:,} pixels); "
                        f"the limit is {max_pixels:,} pixels"
                    )
                if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
                    raise ImageValidationError("animated images are not supported")
                img.verify()

            # Pass 2: fully decode (catches truncated data) and fix orientation.
            with Image.open(io.BytesIO(raw)) as img:
                img.load()
                orientation = img.getexif().get(EXIF_ORIENTATION_TAG, 1)
                if orientation in (None, 1):
                    return PreparedImage(FORMAT_MIME_TYPES[fmt], raw, width, height, False)

                rotated = ImageOps.exif_transpose(img)
                data = _encode(rotated, fmt)
                if len(data) > max_bytes:
                    raise ImageValidationError(
                        f"orientation-corrected image is {len(data):,} bytes; "
                        f"the limit is {max_bytes:,} bytes"
                    )
                return PreparedImage(
                    FORMAT_MIME_TYPES[fmt], data, rotated.width, rotated.height, True
                )
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageValidationError("image exceeds the decoded pixel limit") from exc
    except UnidentifiedImageError as exc:
        raise ImageValidationError("not a recognizable image (corrupt or unsupported)") from exc
    except (OSError, SyntaxError, ValueError, EOFError) as exc:
        raise ImageValidationError(f"corrupt or truncated image ({type(exc).__name__})") from exc


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L", "CMYK"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=95)
    elif fmt == "WEBP":
        img.save(buf, format="WEBP", quality=95)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()
