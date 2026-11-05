
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_TEXT = 4096

_LINE_SUFFIX = re.compile(r":(\d{1,9})(?::\d{1,9})?$")


@dataclass(frozen=True)
class Resolved:

    path: str
    kind: str
    line: Optional[int]


def split_line(text: str) -> tuple[str, Optional[int]]:
    found = _LINE_SUFFIX.search(text)
    if not found or found.start() == 0:
        return text, None
    return text[: found.start()], int(found.group(1))


def resolve(text: str, cwd: Optional[str]) -> Optional[Resolved]:
    raw = text.strip()
    if not raw or len(raw) > MAX_TEXT or "\0" in raw:
        return None
    name, line = split_line(raw)
    candidate = Path(name).expanduser()
    if not candidate.is_absolute():
        if not cwd or not os.path.isabs(cwd):
            return None
        candidate = Path(cwd) / candidate
    absolute = os.path.normpath(str(candidate))
    try:
        if os.path.isdir(absolute):
            return Resolved(absolute, "dir", None)
        if os.path.isfile(absolute):
            return Resolved(absolute, "file", line)
    except (OSError, ValueError):
        return None
    return None
