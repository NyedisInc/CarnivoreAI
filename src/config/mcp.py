
from typing import Any

from pydantic import BaseModel, Field

MCP_KEY = "mcp"


class McpConfig(BaseModel):
    """Switches for ``POST /mcp``.

    Fields:
        enabled: the kill switch. False makes ``/mcp`` answer 404.
        gate_cross_session_actions: when True (default OFF, Alex (Adoom666), 2026-10-12) an agent's
            keystroke, restart or stop aimed at ANOTHER session waits for
            the owner's decision. Read by the write-tool slice; unused by
            the read-only tools.
        agent_notify: the ``notify`` tool and ``POST /sessions/{id}/agent-message`` (D9, default on).
        channels: push Task Manager tells into claude sessions as Claude Code channel events (research preview,
            default OFF). On, every NEW claude pane launch adds the dev channel flag and ``GET /mcp`` serves the
            push stream; running sessions are untouched. ``src/core/mcp/channel.py``, ``docs/task-manager.md`` 37.
        beast_mode / beast_mode_since: the owner's Beast Mode switch and when it was armed (#1268).
        beast_prompts: Beast Mode's second scope, "also answer session permission prompts" (Joe (ccsliinc),
            2026-10-07): while armed, a plain yes is pressed on every eligible permission dialog
            (``src/core/beast_prompts/``). Meaningless while ``beast_mode`` is off; a disarm clears it.
        beast_grid: the owner's boxes of the beast mode grid, ``{cell key: bool}`` (``beast_grid.cell_defaults`` names every key; a missing key
            is its default, anything but a literal true reads as unticked). Beast Mode became core in #1899; ``beast_store.write_grid`` is the writer.
        beast_trust_scope: ``projects`` or ``every``, the folders the folder trust and external imports rules apply to (``auto_answer.catalog.SCOPES``).
        beast_mode_until: ISO time the whole of Beast Mode (both scopes) switches itself off, or None for
            "until I turn it off". A passed time reads as disarmed everywhere (``beast_mode.beast_enabled``).
        bridge_migration: after a boot, resume each IDLE claude session still on the carnivore MCP over plain HTTP
            onto the stdio bridge, one at a time, never a busy one (Joe (ccsliinc), 2026-10-12, Task Manager 510, #1672;
            default ON, and it does nothing where no session is on HTTP). ``src/core/mcp_bridge/migration/``.
        agent_huddle_tools: every ``huddle_*`` tool, the Task Manager lines of the guide and the global Task Manager skill, for
            every MCP caller on this computer (Joe (ccsliinc), 2026-10-12, #1685; default OFF: the Task Manager is Joe's and
            plugins ship off). Off, the Task Manager plugin, its tab, its data and swarm's storage keep working.
        agent_swarm_tools: every ``swarm_*`` tool and the swarm words of the guide (#1685; default ON, Alex's).
        agent_app_settings_tools: the app-settings tools (drawer pins and groups, preferences, colors, skills, mods,
            catalog, plugin rebuild, system settings; ``tool_families.py`` lists them) for every MCP caller on this
            computer (#1754, Alex (Adoom666), 2026-10-13; default OFF: an agent rarely needs to rearrange the app).
            All three are read live by ``src/core/mcp/agent_tool_switches.py``.
        trusted_proxy_hosts: exact IP addresses of a reverse proxy the owner runs (Joe (ccsliinc), 2026-10-13, #1741;
            default EMPTY, which is the loopback-only gate exactly). A request from one of them may reach ``/mcp`` with
            an owner-minted token only; a pane token, an Origin and the phone link stay refused. Validated by the
            admin route and again at match time (``src/core/mcp/trusted_proxy.py``).
        tool_overrides: the owner's per-tool on/off choices, ``{tool_name: bool}``, explicit choices only (default EMPTY,
            which leaves every tool at its default: on, except the names in ``tool_switches.DEFAULT_OFF``). Written only
            by ``PUT /mcp-admin/tools``; read live by ``src/core/mcp/tool_switches.py`` (issue #1824).
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
