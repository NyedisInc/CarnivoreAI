
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Protocol, Sequence

import structlog

from src.api.subagent_listing import fresh_claude_observation
from src.config import settings as _settings
from src.core.account_switch.pane_account import read_pane_profile
from src.core.attention.registry_index import default_registry_directory
from src.core.background_work.listing import SNAPSHOT_MARK
from src.core.conversation_writers import MeasureError, ProcessTable, read_process_table
from src.core.hosts.identity import is_remote_info
from src.core.mcp_health.agent_process import FAMILY_CLAUDE, FAMILY_CODEX, find_agent, lstart_to_datetime
from src.core.mcp_health.cached_files import read_json, read_toml
from src.core.mcp_health.client_log import READER, ClientLogReader, LinkState
from src.core.mcp_health.config_argv import mcp_config_values
from src.core.mcp_health.disabled import disabled_servers
from src.core.mcp_health.monitor import McpMonitor, Measure, Target, measure_target
from src.core.mcp_health.first_hand import (
    CARNIVORE_SERVER, LINK_CONNECTED, LINK_DROPPED, LINK_UNKNOWN, LINKS, apply_carnivore_link, carnivore_state,
)
from src.core.mcp_health.fold import (
    SOURCE_SERVER, STATE_DROPPED, STATE_FAILED, STATE_NEEDS_AUTH as FOLD_STATE_NEEDS_AUTH, McpDrop, McpHealth,
    fold_mcp_health, server_key,
)
from src.core.mcp_health.probe import ProbeResult, ProbeTable
from src.core.mcp_health.targets import monitor_target, tmux_name
from src.core.mcp_health.servers import (
    ALERT_STATES, REASON_AUTH_REQUIRED, REASON_CLOSED, REASON_CONNECT_FAILED, REASON_CONNECTED, REASON_DNS,
    REASON_GAVE_UP, REASON_NEEDS_AUTH, REASON_NOT_FOUND, REASON_NOT_SEEN, REASON_PROCESS_GONE, REASON_PROCESS_RUNNING,
    REASON_REACHABLE, REASON_RECONNECTING, REASON_REFUSED, REASON_SERVER_ERROR, REASON_TIMEOUT, REASON_TLS,
    REASON_TRANSCRIPT, REASON_UNREACHABLE, REMOTE_TRANSPORTS, SOURCE_CLIENT_LOG, SOURCE_FIRST_HAND, SOURCE_PROBE,
    SOURCE_PROCESS, SOURCE_TRANSCRIPT, STATE_CONNECTED, STDIO_GRACE, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN, TRANSPORT_HTTP,
    TRANSPORT_PROXY, TRANSPORT_SSE, TRANSPORT_STDIO, TRANSPORT_UNKNOWN, ServerHealth, ServerSpec, spec_from_entry,
)
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.session_status_seed_records import parse_timestamp
from src.core.tmux_discovery import tmux_argv_prefix

log = structlog.get_logger()

PORT_NAME: str = "mcphealth.listing"


class McpHealthPort(Protocol):

    def stamp(self, app_state: Any, rows: Sequence[Any], now: datetime) -> List[Optional[McpHealth]]:
        pass

    def health_for(self, app_state: Any, row: Any, now: datetime) -> Optional[McpHealth]:
        pass


def fresh_claude_observation(watcher: Any, info: Any, now: datetime) -> Any:
    return fresh_claude_observation(watcher, info, now)


def attention_watcher(app_state: Any) -> Any:
    return getattr(getattr(app_state, "session_manager", None), "_attention_watcher", None)


def tmux_socket(app_state: Any) -> Optional[str]:
    manager = getattr(app_state, "session_manager", None)
    return manager.tmux_socket_name() if manager is not None else None


def carnivore_mcp_enabled() -> bool:
    try:
        return bool(_settings.load_auth_config().mcp.enabled)
    except (ValueError, OSError) as exc:
        log.debug("mcp_config_unreadable", error=str(exc))
        return False


__all__ = [
    "PORT_NAME", "McpHealthPort", "fresh_claude_observation", "attention_watcher", "tmux_socket",
    "carnivore_mcp_enabled", "read_pane_profile", "SNAPSHOT_MARK", "MeasureError", "ProcessTable", "read_process_table",
    "is_remote_info", "FAMILY_CLAUDE", "FAMILY_CODEX", "find_agent", "lstart_to_datetime", "read_json", "read_toml",
    "mcp_config_values", "CARNIVORE_SERVER", "LINK_CONNECTED", "LINK_DROPPED", "LINK_UNKNOWN", "LINKS",
    "apply_carnivore_link", "carnivore_state", "SOURCE_SERVER", "STATE_DROPPED", "STATE_FAILED", "FOLD_STATE_NEEDS_AUTH",
    "McpDrop", "McpHealth", "fold_mcp_health", "server_key", "ALERT_STATES", "REASON_AUTH_REQUIRED", "REASON_CLOSED",
    "REASON_CONNECT_FAILED", "REASON_CONNECTED", "REASON_DNS", "REASON_GAVE_UP", "REASON_NEEDS_AUTH", "REASON_NOT_FOUND",
    "REASON_NOT_SEEN", "STDIO_GRACE", "REASON_PROCESS_GONE", "REASON_PROCESS_RUNNING", "REASON_REACHABLE", "REASON_RECONNECTING",
    "REASON_REFUSED", "REASON_SERVER_ERROR", "REASON_TIMEOUT", "REASON_TLS", "REASON_TRANSCRIPT", "REASON_UNREACHABLE",
    "REMOTE_TRANSPORTS", "SOURCE_CLIENT_LOG", "SOURCE_FIRST_HAND", "SOURCE_PROBE", "SOURCE_PROCESS", "SOURCE_TRANSCRIPT",
    "STATE_CONNECTED", "STATE_DOWN", "STATE_NEEDS_AUTH", "STATE_UNKNOWN", "TRANSPORT_HTTP", "TRANSPORT_PROXY",
    "TRANSPORT_SSE", "TRANSPORT_STDIO", "TRANSPORT_UNKNOWN", "ServerHealth", "ServerSpec", "spec_from_entry",
    "READER", "ClientLogReader", "LinkState", "disabled_servers", "McpMonitor", "Measure", "Target", "measure_target", "monitor_target", "tmux_name",
    "ProbeResult", "ProbeTable", "PROFILE_ENV_VARS", "parse_timestamp", "default_registry_directory", "tmux_argv_prefix",
]
