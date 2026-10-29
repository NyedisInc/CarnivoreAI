
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.mcp_health.host_methods import basename
from src.cplugs.host import sidecar_boot
from src.cplugs.host.sidecar_boot import MCP_HEALTH_ID


@pytest.mark.parametrize("command,expected", [
    ("/usr/bin/node --token=abc", "node"),
    ("npx foo", "npx"),
    ("API_KEY=S7 npx foo", None),
    ("node?key=S2 a", None),
    ("--token=S3", None),
    ("user@host:path", None),
    ("", None),
    (None, None),
])
def test_basename_is_a_whitelist(command, expected):
    assert basename(command) == expected


@pytest.mark.parametrize("reason,withdrawn", [("uninstalled", True), ("updated", True), ("sideload", True), ("revoked", True),
                                              ("index_expired", True), ("idle", False), ("restart", False)])
def test_a_stop_withdraws_the_host_port_except_idle_and_restart(tmp_path, reason, withdrawn):
    async def go():
        host = SimpleNamespace(state_dir=tmp_path)
        rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(),
                                         env_safe=lambda: False, app_version="9.9.9")
        calls = []

        async def switched(plugin_id, enabled):
            calls.append((plugin_id, enabled))

        rt.mcp_health_switched = switched
        await rt.supervisor.disable(MCP_HEALTH_ID, reason)
        return calls

    assert asyncio.run(go()) == ([(MCP_HEALTH_ID, False)] if withdrawn else [])
