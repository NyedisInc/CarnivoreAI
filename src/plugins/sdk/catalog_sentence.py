
from __future__ import annotations

from src.core.keymap.catalog_text import catalog_text as _catalog_text


def catalog_sentence(key: str, **fields: str) -> str:
    return _catalog_text(key, **fields)


__all__ = ["catalog_sentence"]
