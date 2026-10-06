from __future__ import annotations

import base64
import hashlib

import pytest
from PIL import Image

from app.image_processing import ImageValidationError, discover_images, prepare_image
from tests.helpers import make_image


def test_discovery_is_recursive_handles_spaces_and_skips_other_files(tmp_path):
    data = tmp_path / "data"
    make_image(data / "5 images" / "first scan.png")
    make_image(data / "5 images" / "nested folder" / "b.JPG", fmt="JPEG")
    make_image(data / "c.jpeg", fmt="JPEG")
    make_image(data / "d.webp", fmt="WEBP")
    (data / "notes.txt").write_text("not an image")
    (data / "5 images" / ".DS_Store").write_bytes(b"\x00")
    (data / "5 images" / "._first scan.png").write_bytes(b"\x00")  # macOS metadata file

    found = discover_images(data)

    rel = [p.relative_to(data).as_posix() for p in found.images]
    assert rel == sorted(rel)
    assert set(rel) == {
        "5 images/first scan.png",
        "5 images/nested folder/b.JPG",
        "c.jpeg",
        "d.webp",
    }
    assert [p.name for p in found.ignored] == ["notes.txt"]


@pytest.mark.parametrize(
    ("name", "fmt", "mime"),
    [("a.png", "PNG", "image/png"), ("a.jpg", "JPEG", "image/jpeg"), ("a.webp", "WEBP", "image/webp")],
)
def test_valid_images_get_correct_mime_type(tmp_path, name, fmt, mime):
    path = make_image(tmp_path / name, fmt=fmt)
    prepared = prepare_image(path)
    assert prepared.mime_type == mime
    assert (prepared.width, prepared.height) == (40, 30)
    assert prepared.to_data_url().startswith(f"data:{mime};base64,")


def test_mime_type_comes_from_contents_not_extension(tmp_path):
    path = make_image(tmp_path / "actually_jpeg.png", fmt="JPEG")
    assert prepare_image(path).mime_type == "image/jpeg"


def test_corrupt_image_rejected(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n this is not really a png")
    with pytest.raises(ImageValidationError):
        prepare_image(path)


def test_truncated_image_rejected(tmp_path):
    good = make_image(tmp_path / "good.jpg", fmt="JPEG", size=(400, 400), color="red")
    truncated = tmp_path / "truncated.jpg"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    with pytest.raises(ImageValidationError):
        prepare_image(truncated)


def test_empty_file_rejected(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    with pytest.raises(ImageValidationError, match="empty"):
        prepare_image(path)


def test_unsupported_format_with_supported_extension_rejected(tmp_path):
    path = make_image(tmp_path / "really_a_gif.png", fmt="GIF")
    with pytest.raises(ImageValidationError, match="unsupported image format"):
        prepare_image(path)


def test_animated_webp_rejected(tmp_path):
    path = tmp_path / "anim.webp"
    frames = [Image.new("RGB", (20, 20), c) for c in ("red", "blue")]
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(ImageValidationError, match="animated"):
        prepare_image(path)


def test_byte_limit_enforced(tmp_path):
    path = make_image(tmp_path / "a.png")
    with pytest.raises(ImageValidationError, match="limit"):
        prepare_image(path, max_bytes=10)


def test_pixel_limit_enforced(tmp_path):
    path = make_image(tmp_path / "a.png", size=(100, 100))
    with pytest.raises(ImageValidationError, match="pixels"):
        prepare_image(path, max_pixels=9_999)


def test_exif_orientation_corrected_in_memory_and_source_untouched(tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise to display
    Image.new("RGB", (60, 20), "white").save(path, format="JPEG", exif=exif)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    prepared = prepare_image(path)

    assert prepared.orientation_corrected
    assert (prepared.width, prepared.height) == (20, 60)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    b64 = prepared.to_data_url().split(",", 1)[1]
    assert base64.b64decode(b64)[:2] == b"\xff\xd8"  # still a JPEG


def test_unrotated_image_sent_byte_for_byte(tmp_path):
    path = make_image(tmp_path / "a.png")
    prepared = prepare_image(path)
    assert not prepared.orientation_corrected
    assert prepared.data == path.read_bytes()
    assert "data=" not in repr(prepared)  # image bytes never appear in repr/logs
