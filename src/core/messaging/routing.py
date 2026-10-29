
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from src.core.crosstalk.directory import resolve_handle

NO_TARGET = "no_target"

ALL = "all"

_ADDRESS = re.compile(r"^@(\S+)(?:\s+(.*))?$", re.DOTALL)


@dataclass(frozen=True)
class Target:

    binding_id: str
    session_uuid: str
    name: str
    is_default: bool = False


@dataclass(frozen=True)
class Route:

    binding_ids: Tuple[str, ...]
    text: str
    reason: Optional[str] = None
    via: str = ""


def _by_name(query: str, targets: Sequence[Target]) -> Optional[Target]:
    cards = [{"name": t.name, "id": t.binding_id, "session_uuid": t.session_uuid, "tmux_name": None,
              "former_names": []} for t in targets]
    found = resolve_handle(query, cards)
    if found.ambiguous or not found.matches:
        return None
    return next(t for t in targets if t.binding_id == found.matches[0]["id"])


def route(text: str, targets: Sequence[Target], *, reply_binding: Optional[str] = None) -> Route:
    if reply_binding and any(t.binding_id == reply_binding for t in targets):
        return Route((reply_binding,), text, via="thread")
    match = _ADDRESS.match(text)
    if match:
        rest = (match.group(2) or "").strip()
        if match.group(1).casefold() == ALL:
            return Route(tuple(t.binding_id for t in targets), rest, None if targets else NO_TARGET, via="all")
        named = _by_name(match.group(1), targets)
        if named is None:
            return Route((), text, NO_TARGET, via="name")
        return Route((named.binding_id,), rest, via="name")
    default = [t for t in targets if t.is_default]
    if default:
        return Route((default[0].binding_id,), text, via="default")
    if len(targets) == 1:
        return Route((targets[0].binding_id,), text, via="only")
    return Route((), text, NO_TARGET, via="ambiguous")


def handles(targets: Sequence[Target]) -> str:
    return " ".join("@" + "-".join(t.name.split()) for t in targets)
