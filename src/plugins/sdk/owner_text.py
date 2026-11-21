
from __future__ import annotations

import re

from src.plugins.sdk.visible_text import TextRefused, keep_visible, normalize, visible

OWNER_KEEP = "\n\t"
RAW_FACTOR = 4
REFUSAL = "may not contain hidden or control characters"
_ANSI = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]|(?:\x1b\]|\x9d)[^\x07\x1b\x80-\x9f]*(?:\x07|\x1b\\|\x9c)")
_STRIPPED = re.compile("[\ufeff\u200b\u00ad\x7f\x80-\x9f]")


def raw_cap(limit: int) -> int:
    return limit * RAW_FACTOR


def sanitize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalize(_STRIPPED.sub("", _ANSI.sub("", text)))


def owner_text(text: str) -> str:
    text = sanitize(text)
    if not all(visible(text, OWNER_KEEP, private_use=True)):
        raise TextRefused(REFUSAL)
    return text


def stored_text(text: str) -> str:
    return keep_visible(sanitize(text), OWNER_KEEP, private_use=True)
