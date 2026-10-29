
from __future__ import annotations

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]")


_INVISIBLE = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})


def strip_invisible(value: str) -> str:
    return "".join(
        " " if ch in "\n\t" else ch
        for ch in value
        if ch in "\n\t" or unicodedata.category(ch) not in _INVISIBLE
    )


def one_line(value: str, limit: int) -> str:
    flat = " ".join(_CONTROL.sub(" ", strip_invisible(value)).split())
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)].rstrip() + "."
