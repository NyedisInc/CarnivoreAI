
from __future__ import annotations

from fastapi import Response

from src.core.mcp import route_adapters as ra, session_target

SPECS = (
    ra.RouteTool(
        name="session_shell_open", route="src.api.companion_shell_routes:open_shell", gate=ra.ACT,
        description="Open the plain shell of a live agent on this computer: a terminal in the agent's folder, created "
                    "on first use and kept while the agent runs. Answers its session id, tmux name and state "
                    "(created, existing or restarted). It is hidden from session lists; use the returned id with "
                    "session_read_output and session_send_keys.",
        reach=session_target.LIVE,
        invoke=lambda call: call.route(request=call.request, response=Response(), session_id=call.session_id),
        summary=lambda args, target: f"open a shell in the folder of {target.shown if target else args.get('target')}",
    ),
    ra.RouteTool(
        name="session_shell_get", route="src.api.companion_shell_routes:get_shell", gate=ra.READ,
        description="The running companion shell of a live agent on this computer (its session id, tmux name and "
                    "whether its pane is live, dead or unknown), or an error when it has none. Never creates one.",
        reach=session_target.LIVE,
        invoke=lambda call: call.route(call.request, call.session_id),
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
