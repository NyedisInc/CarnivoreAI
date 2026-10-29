
from __future__ import annotations

import json
import re
import tomllib
from typing import Any, Dict, List, Tuple

from src.core.skill_manager.types import OverrideError

_HEADER = re.compile(r"^\s*\[\[\s*skills\s*\.\s*config\s*\]\]\s*(#.*)?$")
_ANY_TABLE = re.compile(r"^\s*\[")


def _blocks(lines: List[str]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for i, line in enumerate(lines):
        if not _HEADER.match(line.rstrip("\r\n")):
            continue
        end = i + 1
        while end < len(lines) and not _ANY_TABLE.match(lines[end]):
            end += 1
        while end > i + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        out.append((i, end))
    return out


def _rule_of(block: str) -> Dict[str, Any]:
    try:
        found = tomllib.loads(block).get("skills", {}).get("config", [])
    except tomllib.TOMLDecodeError:
        return {}
    return found[0] if found and isinstance(found[0], dict) else {}


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def set_skill_rule(text: str, kind: str, value: str, enabled: bool) -> str:
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    matching: List[Tuple[int, int, bool]] = []
    for start, end in _blocks(lines):
        rule = _rule_of("".join(lines[start:end]))
        if rule.get(kind) == value and ("name" in rule) != ("path" in rule):
            matching.append((start, end, rule.get("enabled") is True))
    if enabled:
        doomed = [(s, e) for s, e, on in matching if not on]
    elif matching and not matching[-1][2]:
        return text
    else:
        doomed = [(s, e) for s, e, _ in matching]
    for start, end in reversed(doomed):
        if start > 0 and not lines[start - 1].strip() and (end >= len(lines) or not lines[end].strip()):
            start -= 1
        del lines[start:end]
    body = "".join(lines)
    if enabled:
        return body if doomed else text
    if body and not body.endswith("\n"):
        body += nl
    if body.strip():
        body += nl
    return body + f"[[skills.config]]{nl}{kind} = {_quote(value)}{nl}enabled = false{nl}"


def _without_rules(data: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in data.items() if k != "skills"}
    block = data.get("skills")
    if isinstance(block, dict):
        rest = {k: v for k, v in block.items() if k != "config"}
        if rest:
            out["skills"] = rest
    elif "skills" in data:
        out["skills"] = block
    return out


def check_edit_safe(before: str, after: str) -> None:
    unsafe = OverrideError(
        409,
        "codex_config_edit_unsafe",
        "config.toml has a layout the editor cannot change safely; edit skills.config by hand",
    )
    try:
        was, now = tomllib.loads(before), tomllib.loads(after)
    except tomllib.TOMLDecodeError as exc:
        raise unsafe from exc
    if _without_rules(was) != _without_rules(now):
        raise unsafe
