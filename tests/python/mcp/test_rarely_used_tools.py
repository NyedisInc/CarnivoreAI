
from __future__ import annotations

from src.core.mcp import tool_switches, tools
from src.core.mcp.deprecated_tools import DEPRECATED


def test_rarely_used_tools_are_registered_and_default_off() -> None:
    assert "session_external_stop" in tool_switches.RARELY_USED
    assert tool_switches.RARELY_USED <= set(tools.tool_names())
    assert not (tool_switches.RARELY_USED & DEPRECATED), "a name is either deprecated or rarely used, never both"
    assert tool_switches.SHIPPED_DEFAULT_OFF == DEPRECATED | tool_switches.RARELY_USED
