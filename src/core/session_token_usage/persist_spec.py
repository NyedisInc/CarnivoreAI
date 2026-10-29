
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Tuple


@dataclass(frozen=True)
class PersistSpec:

    name: str
    manual_version: int
    sources: Tuple[str, ...]
    encode: Callable[[Any], Any]
    decode: Callable[[Any], Any]


def encode_instant(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def decode_instant(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("instant must be a string")
    return datetime.fromisoformat(value)
