
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.federation import peer_app_update
from src.core.mcp import app_update_tools, route_adapters as ra
from src.core.mcp.common import ToolError


def test_status_is_a_read_and_the_writes_are_one_gated_tool_with_no_feed_argument():
    by = {s.name: s for s in app_update_tools.SPECS}
    assert by["app_update_status"].gate == ra.READ and by["app_update"].gate == ra.ACT
    assert set(by["app_update"].properties) == {"action", "enabled", "peer"}
    assert "app_update" in app_update_tools.WRITE_TOOLS and "app_update_status" in app_update_tools.READ_TOOLS


def test_a_peer_call_goes_through_the_one_peer_client(monkeypatch):
    seen = []

    async def fake(open_db, host_key, action, enabled=None, links=None):
        seen.append((host_key, action, enabled))
        return {"status": "unsupported"}

    monkeypatch.setattr(peer_app_update, "call", fake)
    call = lambda **a: SimpleNamespace(route=None, request=None, args=a)  # noqa: E731
    assert asyncio.run(app_update_tools._act(call(action="install", peer="peer-x"))) == {"status": "unsupported"}
    asyncio.run(app_update_tools._act(call(action="set_auto", enabled=True, peer="peer-x")))
    asyncio.run(app_update_tools._status(call(peer="peer-x")))
    assert seen == [("peer-x", "install", None), ("peer-x", "auto", True), ("peer-x", "status", None)]


def test_set_auto_needs_a_bool_and_enabled_goes_only_with_set_auto():
    call = lambda **a: SimpleNamespace(route=None, request=None, args=a)  # noqa: E731
    with pytest.raises(ToolError):
        asyncio.run(app_update_tools._act(call(action="set_auto")))
    with pytest.raises(ToolError):
        asyncio.run(app_update_tools._act(call(action="check", enabled=True)))
