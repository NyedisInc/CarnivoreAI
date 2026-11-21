
from __future__ import annotations

import functools

from src.core.argent.lifecycle import PORT_NAME
from src.core.notifications import catalog_lines
from src.plugins.sdk import ports

CATALOG_KEY = "argent.mcp.instructions"


@functools.lru_cache(maxsize=1)
def _wording() -> str:
    return catalog_lines.read_prefixed((CATALOG_KEY,))[CATALOG_KEY]


def text(room: int) -> str:
    if ports.get(PORT_NAME) is None:
        return ""
    line = f"- {_wording()}\n"
    return line if len(line) <= room else ""
