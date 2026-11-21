
from __future__ import annotations

from typing import Dict

from src.core.notifications.catalog_lines import read_prefixed


def catalog_lines(prefix: str) -> Dict[str, str]:
    try:
        return read_prefixed((prefix,))
    except (OSError, ValueError):
        return {}


def catalog_text(key: str, **fields: str) -> str:
    line = catalog_lines(key).get(key)
    if line is None:
        return key
    try:
        return line.format(**fields)
    except (KeyError, IndexError, ValueError):
        return line
