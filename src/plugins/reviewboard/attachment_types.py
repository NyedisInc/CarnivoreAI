
from __future__ import annotations

from typing import Dict, FrozenSet

IMAGE = "image"
TEXT = "text"
PDF = "pdf"
OFFICE = "office"
MEDIA = "media"

CLASS_BY_EXTENSION: Dict[str, str] = {
    **{ext: IMAGE for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")},
    **{ext: TEXT for ext in (".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".xml", ".patch", ".diff", ".html", ".htm", ".svg", ".css", ".js")},
    ".pdf": PDF,
    **{ext: MEDIA for ext in (".mp4", ".mov", ".webm", ".mp3", ".wav")},
    **{ext: OFFICE for ext in (".docx", ".xlsx", ".pptx")},
}
ALLOWED_EXTENSIONS: FrozenSet[str] = frozenset(CLASS_BY_EXTENSION)

PDF_HEADER = b"%PDF-"
PDF_HEADER_WINDOW = 1024
ZIP_HEADER = b"PK\x03\x04"

REASON_NO_EXTENSION = "no_extension"
REASON_EXTENSION = "extension_not_allowed"
REASON_CONTENT = "content_mismatch"
REASON_NOT_UTF8 = "not_utf8"

MP4_BRAND_OFFSET = 4
MP4_BRAND = b"ftyp"
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
MP3_ID3 = b"ID3"
MP3_SYNC_FIRST = 0xFF
MP3_SYNC_MASK = 0xE0
WAV_RIFF = b"RIFF"
WAV_WAVE_OFFSET = 8
WAV_WAVE = b"WAVE"
