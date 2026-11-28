
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Optional, Sequence, Tuple


class ImageOpsError(ValueError):
    pass


_SIPS = "/usr/bin/sips"
_SIPS_TIMEOUT_S = 15.0

_SIPS_FORMAT_MAP: dict[str, str] = {
    "png": "PNG",
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "gif": "GIF",
    "webp": "WEBP",
    "avif": "AVIF",
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_AVIF_BRANDS = (b"avif", b"avis", b"mif1")


def _has_sips() -> bool:
    return os.path.isfile(_SIPS) and os.access(_SIPS, os.X_OK)


def _sips_probe(path: Path) -> Tuple[str, int, int]:
    try:
        proc = subprocess.run(
            [_SIPS, "-g", "format", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True,
            text=True,
            timeout=_SIPS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageOpsError(f"sips probe failed: {exc}") from exc
    if proc.returncode != 0:
        raise ImageOpsError(f"sips refused image (rc={proc.returncode})")
    props: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            props[key.strip()] = val.strip()
    fmt = _SIPS_FORMAT_MAP.get(props.get("format", "").lower())
    try:
        width = int(props.get("pixelWidth", "0"))
        height = int(props.get("pixelHeight", "0"))
    except ValueError as exc:
        raise ImageOpsError("sips reported non-integer image dimensions") from exc
    if not fmt or width <= 0 or height <= 0:
        raise ImageOpsError("sips could not determine valid image format/dimensions")
    return fmt, width, height


def _verify_png(data: bytes) -> bool:
    if len(data) < 33 or not data.startswith(_PNG_SIGNATURE):
        return False
    pos = 8
    saw_ihdr = False
    saw_iend = False
    n = len(data)
    while pos + 12 <= n:
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4 : pos + 8]
        chunk_start = pos + 8
        chunk_end = chunk_start + length
        crc_end = chunk_end + 4
        if crc_end > n:
            return False
        expected_crc = struct.unpack_from(">I", data, chunk_end)[0]
        actual_crc = zlib.crc32(data[pos + 4 : chunk_end]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return False
        if not saw_ihdr:
            if ctype != b"IHDR" or length != 13:
                return False
            width, height = struct.unpack_from(">II", data, chunk_start)
            if width == 0 or height == 0:
                return False
            saw_ihdr = True
        if ctype == b"IEND":
            saw_iend = True
            break
        pos = crc_end
    return saw_ihdr and saw_iend


def _verify_jpeg(data: bytes) -> bool:
    n = len(data)
    if n < 4 or data[0:2] != b"\xff\xd8":
        return False
    pos = 2
    saw_sof = False
    saw_sos = False
    while pos < n:
        if data[pos] != 0xFF:
            return False
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            return False
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            return saw_sof and saw_sos
        if marker == 0x01 or (0xD0 <= marker <= 0xD7):
            continue
        if pos + 2 > n:
            return False
        seg_len = struct.unpack_from(">H", data, pos)[0]
        if seg_len < 2 or pos + seg_len > n:
            return False
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if seg_len < 7:
                return False
            height, width = struct.unpack_from(">HH", data, pos + 3)
            if width == 0 or height == 0:
                return False
            saw_sof = True
        pos += seg_len
        if marker == 0xDA:
            saw_sos = True
            i = pos
            while i + 1 < n:
                idx = data.find(b"\xff", i)
                if idx == -1 or idx + 1 >= n:
                    return False
                nxt = data[idx + 1]
                if nxt == 0x00 or (0xD0 <= nxt <= 0xD7):
                    i = idx + 2
                    continue
                if nxt == 0xFF:
                    i = idx + 1
                    continue
                if nxt == 0xD9:
                    return saw_sof
                pos = idx
                break
            else:
                return False
    return False


def _verify_gif(data: bytes) -> bool:
    if len(data) < 14 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return False
    width, height = struct.unpack_from("<HH", data, 6)
    if width == 0 or height == 0:
        return False
    return data.rstrip(b"\x00").endswith(b";")


def _verify_webp(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    riff_size = struct.unpack_from("<I", data, 4)[0]
    if riff_size < 12 or 8 + riff_size > len(data):
        return False
    chunk_fourcc = data[12:16]
    chunk_size = struct.unpack_from("<I", data, 16)[0]
    if 20 + chunk_size > len(data):
        return False
    if chunk_fourcc == b"VP8X":
        if chunk_size < 10 or len(data) < 30:
            return False
        w_minus_1 = int.from_bytes(data[24:27], "little")
        h_minus_1 = int.from_bytes(data[27:30], "little")
        return w_minus_1 >= 0 and h_minus_1 >= 0
    if chunk_fourcc == b"VP8L":
        return chunk_size >= 5 and data[20] == 0x2F
    if chunk_fourcc == b"VP8 ":
        return chunk_size >= 10 and data[23:26] == b"\x9d\x01\x2a"
    return False


def _verify_avif(data: bytes) -> bool:
    if len(data) < 16 or data[4:8] != b"ftyp":
        return False
    box_size = struct.unpack_from(">I", data, 0)[0]
    if box_size < 16 or box_size > len(data):
        return False
    ftyp_body = data[8:box_size]
    return any(brand in ftyp_body for brand in _AVIF_BRANDS)


def _sniff_and_verify_pure(data: bytes) -> Optional[str]:
    if data.startswith(_PNG_SIGNATURE):
        if _verify_png(data):
            return "PNG"
        raise ImageOpsError("corrupt or truncated PNG image")
    if data.startswith(b"\xff\xd8"):
        if _verify_jpeg(data):
            return "JPEG"
        raise ImageOpsError("corrupt or truncated JPEG image")
    if data[:6] in (b"GIF87a", b"GIF89a"):
        if _verify_gif(data):
            return "GIF"
        raise ImageOpsError("corrupt or truncated GIF image")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if _verify_webp(data):
            return "WEBP"
        raise ImageOpsError("corrupt or truncated WEBP image")
    if len(data) >= 12 and data[4:8] == b"ftyp":
        if _verify_avif(data):
            return "AVIF"
        raise ImageOpsError("unsupported or corrupt ISO BMFF image")
    return None


def verify_image_bytes(data: bytes) -> str:
    if not data or len(data) < 12:
        raise ImageOpsError("empty or truncated image payload")
    fmt = _sniff_and_verify_pure(data)
    if fmt is None:
        raise ImageOpsError("unrecognized image format")
    if _has_sips():
        ext = "jpg" if fmt == "JPEG" else fmt.lower()
        with tempfile.TemporaryDirectory(prefix="cc_img_verify_") as tmpdir:
            tmp_path = Path(tmpdir) / f"in.{ext}"
            tmp_path.write_bytes(data)
            sips_fmt, _w, _h = _sips_probe(tmp_path)
            if sips_fmt != fmt:
                raise ImageOpsError(f"image format mismatch: header={fmt}, decoder={sips_fmt}")
    return fmt


def image_dimensions(path: Path) -> Tuple[int, int]:
    if not _has_sips():
        raise ImageOpsError("sips is not available on this platform")
    _fmt, width, height = _sips_probe(path)
    return width, height


def render_thumbnail(original: Path, max_px: int, quality: int = 80) -> Tuple[bytes, str, str]:
    if max_px <= 0:
        raise ImageOpsError(f"max_px must be positive, got {max_px}")
    if not original.is_file():
        raise FileNotFoundError(str(original))
    if not _has_sips():
        raise OSError("sips is unavailable for thumbnail rendering")
    _fmt, width, height = _sips_probe(original)
    with tempfile.TemporaryDirectory(prefix="cc_thumb_") as tmpdir:
        out_path = Path(tmpdir) / "thumb.avif"
        cmd = [_SIPS]
        if max(width, height) > max_px:
            cmd.extend(["-Z", str(int(max_px))])
        cmd.extend([
            "-s", "format", "avif",
            "-s", "formatOptions", str(int(quality)),
            str(original),
            "--out", str(out_path),
        ])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SIPS_TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ImageOpsError(f"sips thumbnail failed: {exc}") from exc
        if proc.returncode != 0 or not out_path.is_file():
            raise ImageOpsError(f"sips thumbnail failed (rc={proc.returncode})")
        data = out_path.read_bytes()
        if not data:
            raise ImageOpsError("sips produced empty thumbnail")
        return data, "avif", "image/avif"


def crop_16_9_png(raw: bytes) -> bytes:
    fmt = verify_image_bytes(raw)
    if not _has_sips():
        raise ImageOpsError("sips is unavailable for 16:9 cropping")
    ext = "jpg" if fmt == "JPEG" else fmt.lower()
    with tempfile.TemporaryDirectory(prefix="cc_crop_") as tmpdir:
        in_path = Path(tmpdir) / f"in.{ext}"
        in_path.write_bytes(raw)
        _sips_fmt, w, h = _sips_probe(in_path)
        if w * 9 == h * 16:
            return raw
        if w * 9 > h * 16:
            new_w, new_h = h * 16 // 9, h
        else:
            new_w, new_h = w, w * 9 // 16
        out_path = Path(tmpdir) / "cropped.png"
        try:
            proc = subprocess.run(
                [_SIPS, "-c", str(new_h), str(new_w), "-s", "format", "png", str(in_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
                timeout=_SIPS_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ImageOpsError(f"sips crop failed: {exc}") from exc
        if proc.returncode != 0 or not out_path.is_file():
            raise ImageOpsError(f"sips crop failed (rc={proc.returncode})")
        out = out_path.read_bytes()
        if not out:
            raise ImageOpsError("sips produced empty cropped PNG")
        return out


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def qr_matrix_to_png(matrix: Sequence[Sequence[bool]], box_size: int = 8, border: int = 3) -> bytes:
    if not matrix or not matrix[0]:
        raise ImageOpsError("QR matrix must be non-empty")
    if box_size < 1:
        raise ImageOpsError("box_size must be >= 1")
    if border < 0:
        raise ImageOpsError("border must be >= 0")

    mat_rows = len(matrix)
    mat_cols = len(matrix[0])
    total_cols = mat_cols + 2 * border
    width = total_cols * box_size
    height = (mat_rows + 2 * border) * box_size
    row_bytes = (width + 7) // 8

    white_row = b"\x00" + bytes([0xFF] * row_bytes)
    scanlines: list[bytes] = [white_row] * (border * box_size)

    for row in matrix:
        bits = bytearray([0xFF] * row_bytes)
        for col_idx, is_dark in enumerate(row):
            if is_dark:
                px_start = (border + col_idx) * box_size
                for px in range(px_start, px_start + box_size):
                    bits[px >> 3] &= ~(0x80 >> (px & 7))
        line = b"\x00" + bytes(bits)
        scanlines.extend([line] * box_size)

    scanlines.extend([white_row] * (border * box_size))

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    idat = zlib.compress(b"".join(scanlines), level=6)
    return _PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")
