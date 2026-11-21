
from __future__ import annotations

from src.core.mcp import route_adapters as ra

SPECS = (
    ra.RouteTool(
        name="codex_helpers_status", route="src.api.codex_helpers_routes:get_codex_helpers", gate=ra.READ,
        description="Can the installed Codex start its helper programs? The last check: verdict (ok, blocked: macOS "
                    "quarantined helpers nobody approved; host_failed; not_applicable), version, unapproved helper "
                    "names, each helper's quarantine flag, the code-mode host handshake and a readable text when "
                    "failing. check is null until one ran.",
        invoke=lambda call: call.route(),
    ),
    ra.RouteTool(
        name="codex_helpers_check", route="src.api.codex_helpers_routes:check_codex_helpers", gate=ra.ARRANGE,
        description="Run the Codex helper check now (a few seconds; read only: reads quarantine flags and sends the "
                    "code-mode host one handshake). Raises or clears the version's alert. Answers like codex_helpers_status.",
        invoke=lambda call: call.route(),
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
