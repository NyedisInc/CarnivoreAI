
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from src.core.mcp import merged_tools
from src.core.mcp.registry import index as registry_index
from src.cplugs.host import runtime

_built: Optional[Tuple[Any, Dict[str, str], Dict[str, str]]] = None


def _tables() -> Tuple[Dict[str, str], Dict[str, str]]:
    global _built
    defs = runtime.definitions()
    if _built is None or _built[0] is not defs:
        forward = {old: new for d in defs for old, new in d.manifest.mcp_tool_aliases.items()}
        _built = (defs, forward, {new: old for old, new in forward.items()})
    return _built[1], _built[2]


def table() -> Mapping[str, str]:
    return {**_tables()[0], **{old: m.into for old, m in merged_tools.MERGED.items()}}


def canonical(name: Any) -> Any:
    return merged_tools.into(_tables()[0].get(name, name)) if isinstance(name, str) else name


def is_alias(name: Any) -> bool:
    return isinstance(name, str) and (name in _tables()[0] or name in merged_tools.MERGED)


def retired_name(name: str) -> Optional[str]:
    return _tables()[1].get(name)


def was_renamed(name: str) -> bool:
    forward, reverse = _tables()
    return name in forward or name in reverse


def names_both_ways(names: Tuple[str, ...]) -> Tuple[str, ...]:
    out: Dict[str, None] = {}
    for name in names:
        out[name] = None
        old = retired_name(name)
        if old is not None:
            out[old] = None
    return tuple(out)


def id_table() -> Dict[str, str]:
    current = {name: cap.id for name, cap in registry_index.entries().items()}
    return {**current, **{old: current[new] for old, new in table().items() if new in current}}


def capability_id(name: Any) -> Optional[str]:
    if not isinstance(name, str):
        return None
    if "." in name:
        return name if flat_name(name) is not None else None
    return id_table().get(name)


def flat_name(name: Any) -> Optional[str]:
    if not isinstance(name, str):
        return None
    entries = registry_index.entries()
    if "." not in name:
        current = canonical(name)
        return current if current in entries else None
    return next((n for n, cap in entries.items() if cap.id == name), None)
