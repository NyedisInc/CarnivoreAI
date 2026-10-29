
from __future__ import annotations

from src.cplugs.reviewboard import attachment_types as types
from src.cplugs.reviewboard.errors import FileTypeRefused


def extension_of(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _is_utf8_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_media(ext: str, data: bytes) -> bool:
    if ext in (".mp4", ".mov"):
        return data[types.MP4_BRAND_OFFSET:types.MP4_BRAND_OFFSET + len(types.MP4_BRAND)] == types.MP4_BRAND
    if ext == ".webm":
        return data.startswith(types.WEBM_MAGIC)
    if ext == ".mp3":
        has_sync = len(data) >= 2 and data[0] == types.MP3_SYNC_FIRST and data[1] & types.MP3_SYNC_MASK == types.MP3_SYNC_MASK
        return data.startswith(types.MP3_ID3) or has_sync
    if ext == ".wav":
        end = types.WAV_WAVE_OFFSET + len(types.WAV_WAVE)
        return data.startswith(types.WAV_RIFF) and data[types.WAV_WAVE_OFFSET:end] == types.WAV_WAVE
    return False


def _looks_like(kind: str, ext: str, data: bytes) -> bool:
    if kind == types.PDF:
        return types.PDF_HEADER in data[:types.PDF_HEADER_WINDOW]
    if kind == types.OFFICE:
        return data.startswith(types.ZIP_HEADER)
    if kind == types.MEDIA:
        return _is_media(ext, data)
    return True


def check_type(name: str, data: bytes) -> str:
    ext = extension_of(name)
    shown = name[:80]
    if not ext:
        raise FileTypeRefused(f"{shown} has no file extension, so its type cannot be checked", reason=types.REASON_NO_EXTENSION, file=shown)
    kind = types.CLASS_BY_EXTENSION.get(ext)
    if kind is None:
        raise FileTypeRefused(f"{shown}: {ext} files are not accepted as attachments", reason=types.REASON_EXTENSION, file=shown, extension=ext)
    if kind == types.TEXT and not _is_utf8_text(data):
        raise FileTypeRefused(f"{shown} is not UTF-8 text", reason=types.REASON_NOT_UTF8, file=shown, extension=ext)
    if not _looks_like(kind, ext, data):
        raise FileTypeRefused(f"{shown} is not a real {ext} file", reason=types.REASON_CONTENT, file=shown, extension=ext)
    return kind
