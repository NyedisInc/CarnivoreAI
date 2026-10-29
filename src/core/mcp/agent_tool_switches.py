"""
The family table is ``tool_families.FAMILIES``. Three families follow a checkbox in ``config.json``'s ``mcp`` block
(``src/config/mcp.py``, written only by ``PUT /mcp-admin/agent-tools`` through ``src/core/config_writer.py``):
``agent_huddle_tools`` (default OFF), ``agent_swarm_tools`` (default ON) and ``agent_app_settings_tools`` (default OFF).
Three follow the computer's own durable records (``family_signals``): Pack tools appear once any Pack state exists,
messaging tools once a messaging provider is stored, AI tools once an AI connection is saved.

READ LIVE, ON EVERY CALL: ``tools.tool_definitions`` and ``instructions.guide`` ask here each time, and both feed the
fingerprint in ``protocol.tool_fingerprint``, so a change moves the fingerprint at once: a connected client's next
request on its old ``Mcp-Session-Id`` is stale (it re-initializes), and an open channel stream sends
``notifications/tools/list_changed`` at its next idle tick. No restart. (A Codex or plain-HTTP pane ignores
``list_changed``: it needs a restart or ``/mcp`` reconnect.)

ONE REFUSAL PATH: :func:`hidden_reason` serves both the listing (``tools.allowed``) and the pre-check in
``tools.call_tool``, so a stale call to a hidden tool gets the named refusal, never the read-only-token one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from src.config import settings
from src.config.mcp import McpConfig
from src.core.mcp import family_signals, tool_families
from src.core.mcp.caller import AgentCaller
from src.core.swarm import switch as swarm_switch

logger = structlog.get_logger()

TASK_MANAGER_FIELD = "agent_huddle_tools"
SWARM_FIELD = "agent_swarm_tools"
APP_SETTINGS_FIELD = "agent_app_settings_tools"

_SWITCH_TAILS = {"huddle": "Do not retry; tell the owner in your reply instead.", "swarm": "Do not retry."}


@dataclass(frozen=True)
class AgentToolSwitches:

    huddle: bool
    swarm: bool
    app_settings: bool = True
    pack: bool = True
    messaging: bool = True
    ai: bool = True
    swarm_off: bool = False

    def shows(self, key: str) -> bool:
        return bool(getattr(self, key))


_DEFAULT_BLOCK = McpConfig()
DEFAULTS = AgentToolSwitches(huddle=_DEFAULT_BLOCK.agent_huddle_tools, swarm=_DEFAULT_BLOCK.agent_swarm_tools,
                             app_settings=_DEFAULT_BLOCK.agent_app_settings_tools)


def current() -> AgentToolSwitches:
    try:
        block = settings.load_auth_config().mcp
    except (ValueError, OSError) as exc:
        logger.warning("mcp_agent_tool_switches_unreadable", error=type(exc).__name__)
        return DEFAULTS
    swarm_on = swarm_switch.is_on()
    return AgentToolSwitches(
        huddle=bool(block.agent_huddle_tools), swarm=bool(block.agent_swarm_tools) and swarm_on, swarm_off=not swarm_on,
        app_settings=bool(block.agent_app_settings_tools),
        pack=family_signals.in_use("pack"), messaging=family_signals.in_use("messaging"), ai=family_signals.in_use("ai"))


def _swarm_switched_off(family: tool_families.Family, state: AgentToolSwitches) -> bool:
    return family.key == "swarm" and state.swarm_off


def _refusal(family: tool_families.Family, name: str, state: Optional[AgentToolSwitches] = None) -> str:
    if state is not None and _swarm_switched_off(family, state):
        return f"{name} is off: the owner turned the swarm off on this computer (sysop menu, swarm_switch_status). Do not retry."
    if family.key in _SWITCH_TAILS:
        return (f"{name} is off: {family.why} (settings > sessions & agents > mcp server). {_SWITCH_TAILS[family.key]}")
    return f"{name} is hidden: {family.why}. {family.how}"


def hidden_reason(caller: Optional[AgentCaller], name: str, switches: Optional[AgentToolSwitches] = None) -> str:
    if caller is None:
        return ""
    family = tool_families.family_of(name)
    if family is None:
        return ""
    state = switches or current()
    if state.shows(family.key):
        return ""
    return _refusal(family, name, state)


def hidden_families(caller: Optional[AgentCaller], switches: Optional[AgentToolSwitches] = None) -> list[dict]:
    return [] if caller is None else hidden_family_rows(switches)


def hidden_family_rows(switches: Optional[AgentToolSwitches] = None) -> list[dict]:
    state = switches or current()
    return [_family_row(f, state) for f in tool_families.FAMILIES if not state.shows(f.key)]


def _family_row(family: tool_families.Family, state: AgentToolSwitches) -> dict:
    if _swarm_switched_off(family, state):
        return {"family": family.label, "why": swarm_switch.OFF_MESSAGE, "how_to_enable": "The owner turns the swarm on in the sysop menu."}
    return {"family": family.label, "why": family.why, "how_to_enable": family.how}
