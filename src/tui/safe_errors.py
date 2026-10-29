
from __future__ import annotations

import re
import traceback

_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"eyJ[\w.\-]+"),
    re.compile(r"[A-Za-z0-9_\-.=+/]{24,}"),
    re.compile(r"(?<!\d)\d{6}(?!\d)"),
)


def scrub(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[hidden]", text)
    return text


def crash_summary(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    where = "\n".join(f"  {f.filename}:{f.lineno} in {f.name}" for f in frames)
    return f"carnivore tui crashed: {type(exc).__name__}: {scrub(str(exc))}\n{where}"
