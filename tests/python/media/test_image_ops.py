
from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.api.phone_link_routes import _qr_png
from src.core.media.image_ops import (
    crop_16_9_png,
    qr_matrix_to_png,
    render_thumbnail,
    verify_image_bytes,
)


def _make_img(fmt: str, size=(40, 30), color=(20, 120, 220)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_verify_image_bytes_valid_formats(fmt: str) -> None:
    assert verify_image_bytes(_make_img(fmt)) == fmt


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"not an image",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,
        _make_img("PNG")[:24],
        _make_img("JPEG")[:16],
        _make_img("GIF")[:-1],
        _make_img("WEBP")[:16],
    ],
)
def test_verify_image_bytes_rejects_corrupt_or_truncated(bad: bytes) -> None:
    with pytest.raises(ValueError):
        verify_image_bytes(bad)


def _sips_writes_avif(tmp_path: Path) -> bool:
    src = tmp_path / "probe.png"
    src.write_bytes(_make_img("PNG", (8, 8)))
    try:
        proc = subprocess.run(["/usr/bin/sips", "-s", "format", "avif", str(src), "--out", str(tmp_path / "probe.avif")],
                              capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def test_render_thumbnail_scales_down_and_never_upscales(tmp_path: Path) -> None:
    if not _sips_writes_avif(tmp_path):
        pytest.skip("this computer's sips cannot write AVIF (macOS before 15); the product serves the original there (thumb_for returns None)")
    big = tmp_path / "big.png"
    big.write_bytes(_make_img("PNG", (640, 480)))
    data, ext, mime = render_thumbnail(big, 128)
    assert ext == "avif" and mime == "image/avif" and len(data) > 0
    assert max(Image.open(io.BytesIO(data)).size) == 128

    small = tmp_path / "small.png"
    small.write_bytes(_make_img("PNG", (80, 60)))
    data2, ext2, mime2 = render_thumbnail(small, 1400)
    assert ext2 == "avif" and mime2 == "image/avif"
    assert Image.open(io.BytesIO(data2)).size == (80, 60)


def test_crop_16_9_png_preserves_16_9_and_crops_3_2() -> None:
    already = _make_img("PNG", (160, 90))
    assert crop_16_9_png(already) == already

    tall = _make_img("PNG", (1536, 1024))
    cropped = crop_16_9_png(tall)
    assert Image.open(io.BytesIO(cropped)).size == (1536, 864)

    with pytest.raises(ValueError):
        crop_16_9_png(b"not-an-image")


def test_qr_matrix_to_png_and_phone_link_qr_png() -> None:
    mat = [[True, False, True], [False, True, False], [True, True, False]]
    raw = qr_matrix_to_png(mat, box_size=4, border=2)
    assert verify_image_bytes(raw) == "PNG"
    im = Image.open(io.BytesIO(raw))
    assert im.size == ((3 + 4) * 4, (3 + 4) * 4)
    assert im.getpixel((0, 0)) == 255
    assert im.getpixel((8, 8)) == 0

    data_url = _qr_png("https://example.com/pair#secret")
    assert data_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(data_url.split(",", 1)[1])
    assert verify_image_bytes(decoded) == "PNG"


def test_no_pil_imports_in_src() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    offenders = []
    for py in (repo_root / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("import PIL", "from PIL")):
                offenders.append(f"{py}:{idx}: {stripped}")
    assert offenders == []
