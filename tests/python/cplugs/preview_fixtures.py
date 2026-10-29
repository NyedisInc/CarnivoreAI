
from __future__ import annotations

import struct
import zlib


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(width: int, height: int, pad: int = 0) -> bytes:
    rows = zlib.compress((b"\x00" + b"\x20\x40\x60" * width) * height, 9)
    extra = _chunk(b"tEXt", b"k\x00" + b"x" * pad) if pad else b""
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + extra + _chunk(b"IDAT", rows) + _chunk(b"IEND", b"")


def jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def webp_lossy(width: int, height: int) -> bytes:
    body = b"\x10\x02\x00\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 8
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(body)) + b"WEBP" + b"VP8 " + struct.pack("<I", len(body)) + body


def webp_animated() -> bytes:
    return b"RIFF" + struct.pack("<I", 4 + 8 + 20) + b"WEBP" + b"ANIM" + struct.pack("<I", 20) + b"\x00" * 20


GOOD = {"png": png(1280, 800), "jpeg": jpeg(1280, 800), "webp": webp_lossy(1280, 800)}
BAD = {
    "gif": b"GIF89a" + b"\x00" * 40,
    "svg": b"<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='800'/>",
    "empty": b"",
    "too_big": png(1280, 800, pad=520 * 1024),
    "portrait": jpeg(1280, 2000),
    "too_wide": jpeg(1800, 500),
    "square": jpeg(1500, 1500),
    "too_small": png(900, 500),
    "huge_side": jpeg(9000, 3000),
    "too_many_pixels": jpeg(5000, 3300),
    "animated_webp": webp_animated(),
    "damaged_png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
}
