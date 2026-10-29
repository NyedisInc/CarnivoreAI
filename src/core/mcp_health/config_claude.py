
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

from src.core.mcp_health.disabled import DISABLED_KEY, name_keys, project_settings
from src.core.mcp_health.cached_files import read_json
from src.core.mcp_health.config_argv import mcp_config_values
from src.core.mcp_health.servers import ServerSpec, spec_from_entry

STRICT_FLAG: str = "--strict-mcp-config"
ENABLED_KEY: str = "enabledMcpjsonServers"
ENABLE_ALL_KEY: str = "enableAllProjectMcpServers"
DISABLED_ANY_KEY: str = "disabledMcpServers"
SCOPE_FLAG: str = "mcp-config"
SCOPE_FLAG_FILE: str = "mcp-config-file"
CLAUDE_JSON: str = ".claude.json"
PROJECT_MCP_FILE: str = ".mcp.json"
USER_SETTINGS: str = "settings.json"
DEFAULT_CONFIG_DIR: str = os.path.join(os.path.expanduser("~"), ".claude")

def _servers_of(doc: Any, scope: str) -> List[ServerSpec]:
    if not isinstance(doc, dict):
        return []
    table = doc.get("mcpServers")
    if not isinstance(table, dict):
        return []
    return [s for s in (spec_from_entry(n, e, scope) for n, e in table.items()) if s is not None]


def _approved(cwd: str, project_entry: Dict[str, Any], user_settings: Optional[dict]) -> Tuple[bool, FrozenSet[str], FrozenSet[str]]:
    docs = list(project_settings(cwd)) + [project_entry] + ([user_settings] if isinstance(user_settings, dict) else [])
    enable_all = any(d.get(ENABLE_ALL_KEY) is True for d in docs)
    enabled: FrozenSet[str] = frozenset()
    disabled: FrozenSet[str] = frozenset()
    for doc in docs:
        enabled |= name_keys(doc.get(ENABLED_KEY))
        disabled |= name_keys(doc.get(DISABLED_KEY))
    return enable_all, enabled, disabled


def _merge(groups: Iterable[List[ServerSpec]], skip: FrozenSet[str]) -> Tuple[ServerSpec, ...]:
    seen: Dict[str, ServerSpec] = {}
    for group in groups:
        for spec in group:
            if spec.key and spec.key not in skip and spec.key not in seen:
                seen[spec.key] = spec
    return tuple(seen.values())


@dataclass(frozen=True)
class ClaudeConfig:

    servers: Tuple[ServerSpec, ...] = ()
    excluded: FrozenSet[str] = frozenset()


def claude_servers(command: str, cwd: Optional[str], config_dir: Optional[str]) -> ClaudeConfig:
    flag_groups: List[List[ServerSpec]] = []
    for value in mcp_config_values(command or ""):
        doc = read_json(value) if isinstance(value, str) else value
        flag_groups.append(_servers_of(doc, SCOPE_FLAG_FILE if isinstance(value, str) else SCOPE_FLAG))
    if STRICT_FLAG in (command or "").split():
        return ClaudeConfig(servers=_merge(flag_groups, frozenset()))
    claude_json_path = os.path.join(config_dir, CLAUDE_JSON) if config_dir else os.path.join(
        os.path.expanduser("~"), CLAUDE_JSON)
    claude_json = read_json(claude_json_path)
    claude_json = claude_json if isinstance(claude_json, dict) else {}
    projects = claude_json.get("projects")
    project_entry = projects.get(cwd) if isinstance(projects, dict) and cwd else None
    project_entry = project_entry if isinstance(project_entry, dict) else {}
    user_settings = read_json(os.path.join(config_dir or DEFAULT_CONFIG_DIR, USER_SETTINGS))
    local = _servers_of({"mcpServers": project_entry.get("mcpServers")}, "local")
    user = _servers_of(claude_json, "user")
    excluded = name_keys(project_entry.get(DISABLED_ANY_KEY))
    project: List[ServerSpec] = []
    unapproved: FrozenSet[str] = frozenset()
    if cwd:
        enable_all, enabled, disabled = _approved(cwd, project_entry, user_settings)
        excluded |= disabled
        for spec in _servers_of(read_json(os.path.join(cwd, PROJECT_MCP_FILE)), "project"):
            if spec.key not in disabled and (enable_all or spec.key in enabled):
                project.append(spec)
            else:
                unapproved |= {spec.key}
    servers = _merge(flag_groups + [local, project, user], excluded)
    unapproved -= {s.key for s in servers}
    return ClaudeConfig(servers=servers, excluded=excluded | unapproved)


def not_started(servers: Iterable[ServerSpec], attempted: Optional[FrozenSet[str]]) -> FrozenSet[str]:
    if attempted is None:
        return frozenset()
    return frozenset(s.key for s in servers if s.scope != SCOPE_FLAG and s.key not in attempted)
