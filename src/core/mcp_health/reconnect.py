
from __future__ import annotations

from typing import Optional

from src.core.mcp_health.fold import McpHealth, server_key

REFUSE_NOT_MEASURED: str = "mcp_not_measured"
REFUSE_NOTHING_DROPPED: str = "nothing_dropped"
REFUSE_UNKNOWN_SERVER: str = "unknown_server"

RECONNECT_ALL: str = "all"
COMMAND_PREFIX: str = "/mcp reconnect "


class ReconnectRefused(Exception):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _typable(name: str) -> bool:
    return bool(name) and all(ch.isprintable() for ch in name)


def reconnect_command(health: Optional[McpHealth], server: Optional[str] = None) -> str:
    if health is None:
        raise ReconnectRefused(REFUSE_NOT_MEASURED, "no MCP state was read from this session's transcript yet")
    if not health.dropped:
        raise ReconnectRefused(REFUSE_NOTHING_DROPPED, "no MCP server is shown as dropped for this session")
    if server is not None:
        wanted = [d for d in health.dropped if server_key(d.name) == server_key(server)]
        if not wanted:
            raise ReconnectRefused(REFUSE_UNKNOWN_SERVER, f"{server!r} is not one of the dropped servers")
        targets = wanted
    else:
        targets = list(health.dropped)
    if len(targets) == 1 and targets[0].exact and _typable(targets[0].name):
        return COMMAND_PREFIX + targets[0].name
    return COMMAND_PREFIX + RECONNECT_ALL
