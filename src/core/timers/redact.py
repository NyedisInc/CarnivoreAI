
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.core.message_model_secrets import (
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_PEM_PRIVATE_KEY,
    scan_text,
)

SUMMARY_CHARS: int = 160

REDACTED: str = "[redacted]"

_PEM_END_RE = re.compile(r"-----END[^\r\n]*?-----")

_MINISIGN_BODY_RE = re.compile(r"[^A-Za-z0-9+/=]*[A-Za-z0-9+/]+=*")


def _span_end(text: str, detector: str, start: int, end: int) -> int:
    if detector == DETECTOR_PEM_PRIVATE_KEY:
        match = _PEM_END_RE.search(text, end)
        return match.end() if match else len(text)
    if detector == DETECTOR_MINISIGN_SECRET_KEY:
        match = _MINISIGN_BODY_RE.match(text, end)
        return match.end() if match else len(text)
    return end


def redact(text: str) -> str:
    spans: List[Tuple[int, int]] = []
    for finding in sorted(scan_text(text, trust_vendor_marker=True), key=lambda item: item.offset):
        end = _span_end(text, finding.detector, finding.offset, finding.offset + finding.length)
        if spans and finding.offset < spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((finding.offset, end))
    for start, end in reversed(spans):
        text = text[:start] + REDACTED + text[end:]
    return text


def summary(text: object, limit: int = SUMMARY_CHARS) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None
    flat = " ".join(redact(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."
