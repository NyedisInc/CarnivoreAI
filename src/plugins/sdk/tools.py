
from __future__ import annotations

from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.read_tools import scrub


def tool_result(payload: Any) -> dict:
    return _ok(payload)


__all__ = ["AgentCaller", "ToolError", "scrub", "tool_result"]
