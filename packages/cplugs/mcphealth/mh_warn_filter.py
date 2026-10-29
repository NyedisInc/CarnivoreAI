
from __future__ import annotations

import re
from typing import Any, FrozenSet, Iterable, Mapping, Tuple

from mh_vocab import Health, server_key

MODE_ALL, MODE_ALLOW, MODE_BLOCK = "all", "allow", "block"
_SPLIT = re.compile(r"[,;\n]+")


def parse_names(value: Any) -> FrozenSet[str]:
    parts = value if isinstance(value, list) else _SPLIT.split(value) if isinstance(value, str) else []
    return frozenset(k for k in (server_key(p) for p in parts if isinstance(p, str)) if k)


def warns(settings: Mapping[str, Any], name: str) -> bool:
    mode, keys = settings.get("warnMode"), parse_names(settings.get("servers", ""))
    if mode == MODE_ALLOW:
        return server_key(name) in keys
    if mode == MODE_BLOCK:
        return server_key(name) not in keys
    return True


def apply(settings: Mapping[str, Any], servers: Iterable[Health]) -> Tuple[Health, ...]:
    return tuple(s for s in servers if warns(settings, s.name))
