
from __future__ import annotations

from typing import Any, Optional

from src.config.mcp_launch import SERVER_NAME
from src.core.conversation_writers import ProcessTable
from src.core.mcp_health.cached_files import read_json
from src.core.mcp_health.agent_process import FAMILY_CLAUDE, find_agent
from src.core.mcp_health.config_argv import mcp_config_values
from src.core.mcp_health.servers import REMOTE_TRANSPORTS, TRANSPORT_STDIO, spec_from_entry

TRANSPORT_NONE: str = "none"
FLAG_SCOPE: str = "mcp-config"


def carnivore_transport(command: str) -> str:
    for value in mcp_config_values(command or ""):
        doc: Any = read_json(value) if isinstance(value, str) else value
        table = doc.get("mcpServers") if isinstance(doc, dict) else None
        if not isinstance(table, dict) or SERVER_NAME not in table:
            continue
        spec = spec_from_entry(SERVER_NAME, table[SERVER_NAME], FLAG_SCOPE)
        if spec is not None:
            return spec.transport
    return TRANSPORT_NONE


def needs_bridge(transport: Optional[str]) -> bool:
    return transport in REMOTE_TRANSPORTS


def on_bridge(transport: Optional[str]) -> bool:
    return transport == TRANSPORT_STDIO


def session_transport(table: ProcessTable, pane_pid: Optional[int], agent_pid: Optional[int]) -> Optional[str]:
    pid = agent_pid if agent_pid in table.rows else find_agent(table, pane_pid, FAMILY_CLAUDE)
    if pid is None:
        return None
    return carnivore_transport(table.rows[pid].command)
