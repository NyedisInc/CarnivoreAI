
from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping, Optional

MAX_VARS = 600
MAX_VALUE = 200
MAX_BYTES = 48 * 1024 - 256
MAX_OFFERED = 4096
_NAME = re.compile(r"--oc-[a-z0-9-]{1,60}", re.ASCII)
_BREAKOUT = re.compile(r"[<>{};\\\x00-\x1f\x7f]")
_BANNED = re.compile(r"@import|expression\(|javascript:", re.IGNORECASE)
_URL = re.compile(r"url\(\s*['\"]?([^)'\"]*)", re.IGNORECASE)


class ThemeRefused(ValueError):
    pass


def safe_value(value: Any) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_VALUE:
        return False
    if _BREAKOUT.search(value) or _BANNED.search(value):
        return False
    return all(url.strip().lower().startswith("data:") for url in _URL.findall(value))


def clean_theme(raw: Any) -> Optional[Dict[str, str]]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or len(raw) > MAX_OFFERED:
        raise ThemeRefused("theme must be an object of css custom properties")
    kept: Dict[str, str] = {}
    size = 2
    for name, value in raw.items():
        if len(kept) >= MAX_VARS:
            break
        if not (isinstance(name, str) and _NAME.fullmatch(name) and safe_value(value)):
            continue
        entry = len(json.dumps({name: value}, separators=(",", ":"), ensure_ascii=False)) - 1
        if size + entry > MAX_BYTES:
            break
        kept[name] = value
        size += entry
    return kept or None


def dumps(theme: Optional[Mapping[str, str]]) -> Optional[str]:
    return None if not theme else json.dumps(dict(theme), separators=(",", ":"), sort_keys=True)


def loads(text: Optional[str]) -> Optional[Dict[str, str]]:
    if not text:
        return None
    try:
        return clean_theme(json.loads(text))
    except ValueError:
        return None
