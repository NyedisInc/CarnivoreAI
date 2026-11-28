
from __future__ import annotations

import re
from typing import AbstractSet, Any, Tuple

FIELD = "renamed_from"
KEEPS_FIELD = "renamed_from_keeps"
KEEP_STRINGS = "strings"
KEEP_WIDGETS = "widgets"
KEEPS = frozenset({KEEP_STRINGS, KEEP_WIDGETS})


class RenamedFromError(ValueError):
    pass


def parse_renamed_from(cplug_id: str, raw: Any, id_pattern: "re.Pattern[str]", reserved: AbstractSet[str]) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str) or not id_pattern.match(raw):
        raise RenamedFromError(f"{cplug_id}: {FIELD} must be one old plugin id matching {id_pattern.pattern}")
    if raw == cplug_id:
        raise RenamedFromError(f"{cplug_id}: {FIELD} cannot be the plugin's own id")
    if raw in reserved:
        raise RenamedFromError(f"{cplug_id}: {FIELD} {raw} is a reserved word, never a plugin id")
    return raw


def parse_keeps(cplug_id: str, raw: Any, renamed_from: str) -> Tuple[str, ...]:
    if raw is None:
        return ()
    if not renamed_from:
        raise RenamedFromError(f"{cplug_id}: {KEEPS_FIELD} needs {FIELD}")
    if not isinstance(raw, list) or not all(isinstance(k, str) and k in KEEPS for k in raw) or len(set(raw)) != len(raw):
        raise RenamedFromError(f"{cplug_id}: {KEEPS_FIELD} must list distinct values from {sorted(KEEPS)}")
    return tuple(sorted(raw))


def kept_old_id(renamed_from: str, keeps: Tuple[str, ...], kind: str) -> str:
    return renamed_from if kind in keeps else ""


def string_prefixes(cplug_id: str, renamed_from: str) -> Tuple[str, ...]:
    return (f"cplug.{cplug_id}.",) + ((f"cplug.{renamed_from}.",) if renamed_from else ())


def key_allowed(cplug_id: str, renamed_from: str, key: str, expected_tail: str) -> bool:
    return key in tuple(f"{prefix}{expected_tail}" for prefix in string_prefixes(cplug_id, renamed_from))


def bare_widget_name(renamed_from: str, name: str) -> str:
    qualifier = f"{renamed_from}."
    return name[len(qualifier):] if renamed_from and name.startswith(qualifier) else name


def tab_allowed(cplug_id: str, renamed_from: str, name: str) -> bool:
    owners = (cplug_id,) + ((renamed_from,) if renamed_from else ())
    return any(name == owner or name.startswith(f"{owner}-") for owner in owners)


def widget_id(cplug_id: str, renamed_from: str, name: str) -> str:
    return name if bare_widget_name(renamed_from, name) != name else f"{cplug_id}.{name}"
