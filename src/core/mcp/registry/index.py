
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.mcp.registry import core_projects, core_sessions, core_swarm, core_system, core_ui
from src.core.mcp.registry.model import Capability, problems as rule_problems
from src.cplugs.host import runtime

_CORE_TABLES = (core_sessions.TABLE, core_projects.TABLE, core_swarm.TABLE, core_ui.TABLE, core_system.TABLE)

_built: Optional[Tuple[Any, Dict[str, Capability]]] = None


def _core_rows() -> List[Tuple[str, str, str]]:
    return [(name, cid, summary) for table in _CORE_TABLES for name, (cid, summary) in table.items()]


def _plugin_rows() -> List[Tuple[str, str, str]]:
    return [(name, spec.capability_id, spec.summary) for d in runtime.definitions() for name, spec in d.tools.items()]


def entries() -> Mapping[str, Capability]:
    global _built
    defs = runtime.definitions()
    if _built is None or _built[0] is not defs:
        rows = _core_rows() + [r for r in _plugin_rows() if r[1]]
        _built = (defs, {name: Capability(name, cid, summary) for name, cid, summary in rows})
    return dict(_built[1])


def get(name: str) -> Optional[Capability]:
    return entries().get(name)


def problems(registered: Optional[List[str]] = None) -> List[str]:
    core, plugin = _core_rows(), _plugin_rows()
    names = [r[0] for r in core]
    out = [f"{n}: in two core tables" for n in sorted({n for n in names if names.count(n) > 1})]
    out += [f"{n}: in a core table and a plugin" for n, _i, _s in plugin if n in set(names)]
    out += rule_problems(entries().values())
    if registered is not None:
        have = entries()
        out += [f"{n}: registered tool with no registry record" for n in registered if n not in have]
        out += [f"{n}: registry record for no registered tool" for n in have if n not in set(registered)]
    return out

