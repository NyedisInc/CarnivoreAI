
from __future__ import annotations

import re
from typing import Any, List, Tuple

from src.core.message_model_secrets import VENDOR_DETECTORS, scan_text

_SECRET_NAME = re.compile(
    r"(token|secret|passw(or)?d|passphrase|api[_-]?key|webhook|credential|"
    r"cookie|bearer|private[_-]?key|authorization|ntfy_topic|_key$|^key$)",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(
    r"([a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@|hooks\.slack\.com/services/)",
    re.IGNORECASE,
)

_DROP = object()


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def _carries_data(value: Any) -> bool:
    if isinstance(value, str):
        return value != ""
    return isinstance(value, (dict, list)) and len(value) > 0


def value_looks_secret(text: str) -> bool:
    if _URL_USERINFO.search(text):
        return True
    return bool(scan_text(text, detectors=VENDOR_DETECTORS))


def _is_secret_rows(key: str, path: str) -> bool:
    return key == "secrets" and "launch_profiles.profiles[" in path


def _walk(value: Any, path: str, dropped: List[str]) -> Any:
    if isinstance(value, str):
        if value_looks_secret(value):
            dropped.append(path)
            return _DROP
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and is_secret_name(key) and _carries_data(item) and not _is_secret_rows(key, path):
                dropped.append(child)
                continue
            cleaned = _walk(item, child, dropped)
            if cleaned is not _DROP:
                out[key] = cleaned
        return out
    if isinstance(value, list):
        kept = []
        for index, item in enumerate(value):
            cleaned = _walk(item, f"{path}[{index}]", dropped)
            if cleaned is not _DROP:
                kept.append(cleaned)
        return kept
    return value


def redact(value: Any, path: str = "") -> Tuple[Any, List[str]]:
    dropped: List[str] = []
    cleaned = _walk(value, path, dropped)
    return (None if cleaned is _DROP else cleaned), sorted(dropped)
