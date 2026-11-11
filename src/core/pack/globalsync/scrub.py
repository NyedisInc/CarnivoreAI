
from __future__ import annotations

import json
import re
import tomllib
from typing import Any, List, Optional, Set, Tuple

from src.core.message_model_secrets import scan_text
from src.core.pack.globalsync import rules

SENSITIVE_DICTS = ("env", "headers")
_TABLE_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_\-]+|\"[^\"]+\"|'[^']+')\s*=")


def looks_secret(key: str, value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return bool(scan_text(value) or scan_text(f"{key}={value}"))


def _scrub_json(node: Any, dropped: List[str], path: str = "") -> Any:
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in SENSITIVE_DICTS and isinstance(value, dict):
                kept = {}
                for name, val in value.items():
                    if looks_secret(str(name), val):
                        dropped.append(f"{path}{key}.{name}")
                    else:
                        kept[name] = val
                out[key] = kept
            else:
                out[key] = _scrub_json(value, dropped, f"{path}{key}.")
        return out
    if isinstance(node, list):
        return [_scrub_json(v, dropped, path) for v in node]
    return node


def _toml_flagged(node: Any, trail: Tuple[str, ...], found: Set[Tuple[str, ...]]) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in SENSITIVE_DICTS and isinstance(value, dict):
            found.update((*trail, key, str(n)) for n, v in value.items() if looks_secret(str(n), v))
        _toml_flagged(value, (*trail, str(key)), found)


def _split_table(header: str) -> Tuple[str, ...]:
    return tuple(p.strip().strip("\"'") for p in header.split("."))


def _scrub_toml(text: str, dropped: List[str]) -> Optional[str]:
    flagged: Set[Tuple[str, ...]] = set()
    _toml_flagged(tomllib.loads(text), (), flagged)
    if not flagged:
        return text
    names = {k[-1] for k in flagged}
    out: List[str] = []
    table: Tuple[str, ...] = ()
    for line in text.splitlines(keepends=True):
        head = _TABLE_RE.match(line)
        if head:
            table = _split_table(head.group(1))
        else:
            key = _KEY_RE.match(line)
            if key and (*table, key.group(2).strip("\"'")) in flagged:
                dropped.append(".".join((*table, key.group(2).strip("\"'"))))
                continue
            if key and key.group(2).strip("\"'") in SENSITIVE_DICTS and "{" in line:
                for name in names:
                    line = re.sub(r"(?:(?<=[{,\s]))\"?%s\"?\s*=\s*(\"[^\"]*\"|'[^']*'|[^,}\s]+)\s*,?\s*" % re.escape(name), "", line)
        out.append(line)
    cleaned = "".join(out)
    again: Set[Tuple[str, ...]] = set()
    _toml_flagged(tomllib.loads(cleaned), (), again)
    return cleaned if not again else None


def scrub_text(name: str, data: bytes) -> Tuple[Optional[bytes], List[str]]:
    dropped: List[str] = []
    try:
        text = data.decode("utf-8")
        if name.endswith(".toml"):
            cleaned = _scrub_toml(text, dropped)
            return (cleaned.encode("utf-8") if cleaned is not None else None), dropped
        cleaned_json = _scrub_json(json.loads(text), dropped)
    except (ValueError, UnicodeDecodeError):
        return data, dropped
    if not dropped:
        return data, dropped
    return (json.dumps(cleaned_json, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), dropped


def tokenise_home(data: bytes, home: str) -> bytes:
    if len(data) > rules.MAX_TEXT_BYTES or b"\x00" in data[:4096] or not home or home == "/":
        return data
    pattern = re.compile(re.escape(home.encode("utf-8")) + rb"(?![A-Za-z0-9_.\-])")
    return pattern.sub(rules.HOME_TOKEN.encode("ascii"), data)


def localise_home(data: bytes, home: str) -> bytes:
    token = rules.HOME_TOKEN.encode("ascii")
    return data.replace(token, home.encode("utf-8")) if token in data else data


def merge_keep_local(received: Any, existing: Any) -> Any:
    if isinstance(received, dict) and isinstance(existing, dict):
        out = {}
        for key, value in received.items():
            old = existing.get(key)
            if key in SENSITIVE_DICTS and isinstance(value, dict) and isinstance(old, dict):
                out[key] = {**{k: v for k, v in old.items() if k not in value}, **value}
            else:
                out[key] = merge_keep_local(value, old)
        for key, old in existing.items():
            if key in SENSITIVE_DICTS and key not in received and isinstance(old, dict):
                out[key] = old
        return out
    if isinstance(received, list) and isinstance(existing, list) and len(received) == len(existing):
        return [merge_keep_local(r, e) for r, e in zip(received, existing)]
    return received
