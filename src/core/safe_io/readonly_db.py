
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

READONLY_TIMEOUT_QUICK_S: float = 1.0
READONLY_TIMEOUT_DEFAULT_S: float = 5.0
READONLY_TIMEOUT_LONG_S: float = 30.0


def readonly_uri(path: Union[str, Path], *, extra: str = "") -> str:
    return f"{Path(path).resolve().as_uri()}?mode=ro{extra}"


def connect_readonly(
    path: Union[str, Path],
    *,
    timeout: float = READONLY_TIMEOUT_DEFAULT_S,
    immutable: bool = False,
    isolation_level: Union[str, None] = "",
    factory: Union[type, None] = None,
) -> sqlite3.Connection:
    uri = readonly_uri(path, extra="&immutable=1" if immutable else "")
    kwargs = {"factory": factory} if factory is not None else {}
    return sqlite3.connect(uri, uri=True, timeout=timeout, isolation_level=isolation_level, **kwargs)
