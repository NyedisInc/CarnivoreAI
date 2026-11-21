
from __future__ import annotations

import os
import re
import stat
import struct
from pathlib import Path
from typing import Tuple

MAX_BYTES = 512 * 1024
MIN_WIDTH, MIN_HEIGHT = 1200, 500
MAX_SIDE = 8192
MAX_PIXELS = 16_000_000
RATIO_MIN, RATIO_MAX = 1.5, 3.0
SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
PREVIEW_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")


class PreviewError(ValueError):
    pass


def _png(raw: bytes) -> Tuple[int, int]:
    if len(raw) < 24 or raw[12:16] != b"IHDR":
        raise PreviewError("the png header is damaged")
    return struct.unpack(">II", raw[16:24])


def _jpeg(raw: bytes) -> Tuple[int, int]:
    i = 2
    while i + 9 < len(raw):
        if raw[i] != 0xFF:
            raise PreviewError("the jpeg is damaged")
        marker = raw[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        (length,) = struct.unpack(">H", raw[i + 2:i + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", raw[i + 5:i + 9])
            return w, h
        i += 2 + length
    raise PreviewError("the jpeg has no size header")


def _webp(raw: bytes) -> Tuple[int, int]:
    if len(raw) < 30 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise PreviewError("the webp header is damaged")
    fourcc, body = raw[12:16], raw[20:]
    if fourcc == b"VP8 " and body[3:6] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", body[6:10])
        return w & 0x3FFF, h & 0x3FFF
    if fourcc == b"VP8L" and body[:1] == b"\x2f":
        bits = int.from_bytes(body[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if fourcc == b"VP8X":
        return int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1
    raise PreviewError("the webp is not a still image")


def check_preview(raw: bytes) -> Tuple[str, int, int]:
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise PreviewError("the preview is empty")
    if len(raw) > MAX_BYTES:
        raise PreviewError("the preview is over 512 KiB")
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        kind, (w, h) = "png", _png(bytes(raw))
    elif raw[:3] == b"\xff\xd8\xff":
        kind, (w, h) = "jpeg", _jpeg(bytes(raw))
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        kind, (w, h) = "webp", _webp(bytes(raw))
    else:
        raise PreviewError("the preview must be a png, jpeg or webp")
    if w < MIN_WIDTH or h < MIN_HEIGHT or w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
        raise PreviewError(f"the preview is {w}x{h}; it must be at least {MIN_WIDTH}x{MIN_HEIGHT} and at most {MAX_PIXELS // 1_000_000} megapixels")
    if not RATIO_MIN <= w / h <= RATIO_MAX:
        raise PreviewError(f"the preview is {w}x{h}; its width must be 1.5 to 3 times its height")
    return kind, w, h


def check_preview_path(rel: object) -> str:
    if not isinstance(rel, str) or len(rel) > 120 or not PREVIEW_PATH.match(rel) or ".." in rel.split("/") or Path(rel).suffix.lower() not in SUFFIXES:
        raise PreviewError("preview must be a plain relative path to a .png, .jpg, .jpeg or .webp file")
    return rel


def read_preview(code_root: Path, rel: object) -> Tuple[str, bytes]:
    rel = check_preview_path(rel)
    root = Path(code_root)
    node = root
    try:
        for part in rel.split("/"):
            node = node / part
            if node.is_symlink():
                raise PreviewError("the preview may not be reached through a symbolic link")
        if not node.resolve().is_relative_to(root.resolve()):
            raise PreviewError("the preview must stay inside the plugin folder")
        if not stat.S_ISREG(os.lstat(node).st_mode):
            raise PreviewError("the preview is not a file in the plugin folder")
        fd = os.open(node, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise PreviewError("the preview is not a file in the plugin folder")
            raw = fh.read(MAX_BYTES + 1)
    except OSError as exc:
        raise PreviewError("the preview file cannot be read") from exc
    return check_preview(raw)[0], raw
