
from __future__ import annotations

from typing import Mapping, Optional

import structlog

from src.config import settings
from src.core.mcp.caller import AgentCaller
from src.core.mcp.deprecated_tools import DEPRECATED

logger = structlog.get_logger()

RARELY_USED: frozenset[str] = frozenset({
    "session_external_stop",
    "stats_coverage_get", "stats_maintenance_get", "stats_contributions_list", "stats_dimensions_list",
    "stats_conversations_list", "stats_impact_get", "stats_events_list", "stats_annotations_list",
    "stats_charts_list", "stats_chart_get", "stats_tripwires_list", "stats_tripwire_get",
    "projects_authority_get", "projects_presence_get", "project_storage_get", "project_root_check", "company_accounts_get",
    "item_settings_list", "row_looks_list", "project_storage_check", "company_accounts_set", "session_group_icon_set",
    "session_group_rule_set", "project_merge_run",
})
SHIPPED_DEFAULT_OFF: frozenset[str] = DEPRECATED | RARELY_USED
DEFAULT_OFF: frozenset[str] = SHIPPED_DEFAULT_OFF
ALWAYS_ON: frozenset[str] = frozenset({"whoami"})
PANEL = "settings > advanced > mcp tools"


class ToolSwitchError(ValueError):
    pass


def overrides() -> dict[str, bool]:
    try:
        held = getattr(settings.load_auth_config().mcp, "tool_overrides", None)
        return {k: bool(v) for k, v in (held or {}).items()}
    except (ValueError, OSError) as exc:
        logger.warning("mcp_tool_switches_unreadable", error=type(exc).__name__)
        return {}


def is_on(name: str, chosen: Optional[Mapping[str, bool]] = None) -> bool:
    if name in ALWAYS_ON:
        return True
    state = overrides() if chosen is None else chosen
    return bool(state[name]) if name in state else name not in DEFAULT_OFF


def hidden_reason(caller: Optional[AgentCaller], name: str, chosen: Optional[Mapping[str, bool]] = None,
                  called_as: str = "") -> str:
    if caller is None or is_on(name, chosen):
        return ""
    return f"{called_as or name} is switched off ({PANEL})"


def merged(changes: Mapping[str, bool], registered: frozenset[str], current: Mapping[str, bool]) -> dict[str, bool]:
    result = dict(current)
    for name, wanted in changes.items():
        if name not in registered:
            raise ToolSwitchError(f"{name} is not a registered tool")
        if name in ALWAYS_ON and not wanted:
            raise ToolSwitchError(f"{name} cannot be switched off")
        if wanted == (name not in DEFAULT_OFF):
            result.pop(name, None)
        else:
            result[name] = wanted
    return {k: v for k, v in result.items() if k in registered}
