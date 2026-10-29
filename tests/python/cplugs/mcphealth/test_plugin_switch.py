
from __future__ import annotations

import asyncio
import importlib
import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import mcp_health_listing, mcp_reconnect_routes
from src.cplugs.host import runtime
from src.cplugs.sdk import ports
from src.cplugs.sdk.mcp_health import PORT_NAME
from src.models import Session, SessionInfo


class _Manager:

    def __init__(self):
        self.info = SessionInfo(session=Session(id="ses_1", working_dir="/tmp", tmux_session="t1"), tmux_session="t1",
                                activity_status="idle", agent_family="claude")

    async def get_session_info(self, _sid):
        return self.info


def test_no_port_means_null_on_every_row():
    assert ports.get(PORT_NAME) is None
    manager = _Manager()
    mcp_health_listing.mark_mcp_health(SimpleNamespace(session_manager=manager), [manager.info])
    assert manager.info.mcp_health is None


def test_no_port_means_the_reconnect_route_has_nothing_measured(monkeypatch):
    monkeypatch.setattr(mcp_reconnect_routes, "refuse_remote", lambda *a, **k: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=_Manager())))
    with pytest.raises(HTTPException) as err:
        asyncio.run(mcp_reconnect_routes.reconnect_mcp(request, "ses_1", mcp_reconnect_routes.McpReconnectRequest()))
    assert err.value.detail["code"] == "mcp_not_measured"


def test_the_compiled_in_copy_is_gone_and_the_other_plugins_still_import():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.cplugs.mcphealth")
    assert runtime.find("mcphealth") is None and "mcphealth" not in [d.id for d in runtime.definitions()]
    shipped = [d.id for d in runtime.definitions()]
    assert len(shipped) >= 9
    for plugin_id in shipped:
        assert importlib.import_module(f"src.cplugs.{plugin_id}") is not None, plugin_id


def test_the_measuring_is_core_and_the_judge_is_not_in_src():
    for moved in ("monitor", "probe", "client_log", "process_match", "config_claude", "config_codex", "disabled"):
        assert importlib.util.find_spec(f"src.core.mcp_health.{moved}") is not None, moved
    for core in ("fold", "history", "first_hand", "servers", "cached_files", "reconnect", "agent_process", "config_argv"):
        assert importlib.util.find_spec(f"src.core.mcp_health.{core}") is not None, core
    assert importlib.util.find_spec("src.core.mcp_health.combine") is None
    assert not hasattr(mcp_health_listing, "MONITOR") and not hasattr(mcp_health_listing, "mcp_health_for")
