
from __future__ import annotations

import json
import os
import threading
import tomllib
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

log = structlog.get_logger()

MAX_CACHED: int = 1024
MAX_FILE_BYTES: int = 8 * 1024 * 1024

_CACHE: Dict[Tuple[str, str], Tuple[Tuple[int, int], Any]] = {}
_LOCK = threading.Lock()


def _read(path: str, kind: str, parse: Callable[[bytes], Any]) -> Optional[Any]:
    try:
        info = os.stat(path)
    except OSError:
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    key = (kind, path)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    value: Any = None
    if info.st_size <= MAX_FILE_BYTES:
        try:
            with open(path, "rb") as handle:
                value = parse(handle.read(MAX_FILE_BYTES))
        except (OSError, ValueError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            log.debug("mcp_config_file_unreadable", path=path, error=type(exc).__name__)
            value = None
    with _LOCK:
        if len(_CACHE) >= MAX_CACHED:
            _CACHE.clear()
        _CACHE[key] = (stamp, value)
    return value


def read_json(path: str) -> Optional[Any]:
    return _read(path, "json", lambda blob: json.loads(blob.decode("utf-8")))


def read_toml(path: str) -> Optional[Dict[str, Any]]:
    return _read(path, "toml", lambda blob: tomllib.loads(blob.decode("utf-8")))


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
