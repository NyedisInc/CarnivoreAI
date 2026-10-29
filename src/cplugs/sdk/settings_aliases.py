
from __future__ import annotations

from typing import Any, Dict, Mapping, Set

from src.cplugs.sdk import old_names

_counted: Set[str] = set()


def declare(aliases: Mapping[str, str]) -> None:
    old_names.declare(old_names.KIND_SETTING, list(aliases.values()))


def _count_once(retired: str) -> None:
    if retired not in _counted:
        _counted.add(retired)
        old_names.note(old_names.KIND_SETTING, retired)


def merged(defaults: Mapping[str, Any], stored: Mapping[str, Any], aliases: Mapping[str, str]) -> Dict[str, Any]:
    out = {**defaults, **stored}
    for current, retired in aliases.items():
        if current not in stored and retired in stored:
            out[current] = stored[retired]
            _count_once(retired)
    return out


def translate(incoming: Mapping[str, Any], aliases: Mapping[str, str]) -> Dict[str, Any]:
    retired_to_current = {retired: current for current, retired in aliases.items()}
    out: Dict[str, Any] = {}
    for key, value in incoming.items():
        if key in retired_to_current:
            _count_once(key)
        out[retired_to_current.get(key, key)] = value
    return out
