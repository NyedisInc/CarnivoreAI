
from __future__ import annotations

from typing import Dict

from src.core.mcp import aliases, beast_mode, pane_only, route_adapters, tools
from src.core.mcp.approvals import call_context
from src.cplugs.host import mcp as cplug_mcp

READ = "read"
ARRANGE = "arrange"
ACT = "act"
ALWAYS_WAITS_CLASS = "always_waits"
AGENT = "agent"
AGENT_DIRECT = "agent_direct"
PANE_ONLY = "pane_only"
UNDECLARED = "undeclared"
CLASSES = (READ, ARRANGE, ACT, ALWAYS_WAITS_CLASS, AGENT, AGENT_DIRECT, PANE_ONLY, UNDECLARED)
_PLUGIN_CLASSES = {"read": READ, "agent": AGENT, "agent_direct": AGENT_DIRECT, "inbox": ALWAYS_WAITS_CLASS}

UNDECLARED_WRITES: frozenset = frozenset()


def gate_class(name: str) -> str:
    name = aliases.canonical(name)
    live = cplug_mcp.live_tools().get(name) if cplug_mcp.SIDECAR_SEP in name else None
    if live is not None:
        return _PLUGIN_CLASSES[live.gate]
    if name not in tools.WRITE_TOOLS:
        return READ
    spec = cplug_mcp.spec_of(name)
    if spec is not None:
        return _PLUGIN_CLASSES[spec.gate]
    route = tools.ROUTE_GATES.get(name)
    if name in beast_mode.ALWAYS_WAITS or name in beast_mode.RETAINED_APPROVALS:
        return ALWAYS_WAITS_CLASS
    if name in call_context.GATED_TOOLS or route == route_adapters.ACT:
        return ACT
    if name in tools._UNGATED_WRITES or route == route_adapters.ARRANGE:
        return ARRANGE
    if name in pane_only.STANDING:
        return PANE_ONLY
    if name in tools.DIRECT_WRITES:
        return AGENT_DIRECT
    return UNDECLARED


def gate_classes() -> Dict[str, str]:
    return {name: gate_class(name) for name in tools.tool_names() if not aliases.is_alias(name)}
