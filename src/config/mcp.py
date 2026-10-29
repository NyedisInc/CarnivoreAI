
from typing import Any

from pydantic import BaseModel, Field

MCP_KEY = "mcp"


class McpConfig(BaseModel):
    """Switches for ``POST /mcp``.
    """

    enabled: bool = True
    gate_cross_session_actions: bool = False
    beast_mode: bool = False
    agent_notify: bool = True
    beast_mode_since: str | None = None
    beast_prompts: bool = False
    beast_mode_until: str | None = None
    beast_grid: dict[str, Any] = Field(default_factory=dict)
    beast_trust_scope: str = "projects"
    channels: bool = False
    bridge_migration: bool = True
    agent_huddle_tools: bool = False
    agent_swarm_tools: bool = True
    agent_app_settings_tools: bool = False
    trusted_proxy_hosts: list[str] = Field(default_factory=list)
    tool_overrides: dict[str, bool] = Field(default_factory=dict)
