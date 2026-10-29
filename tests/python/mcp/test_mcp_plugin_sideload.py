
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import beast_mode, pending, plugin_sideload_tools, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.cplugs.host import sideload, sideload_git_routes, sideload_routes  # noqa: E402
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

PANE = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a")
TOOLS = ("plugin_sideload_add", "plugin_sideload_remove")


class View:

    gate_waited = True

    def __init__(self, state):
        self.app = SimpleNamespace(state=SimpleNamespace(sidecar_runtime=SimpleNamespace(state_dir=state)))

    async def list_session_infos(self):
        return []

    async def list_peer_infos(self):
        return []

    def fresh(self):
        return self


@pytest.fixture()
def world(tmp_path, monkeypatch):
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    arm_beast(monkeypatch, lambda: True)
    calls: list = []

    async def post(body, request):
        calls.append(("folder", body.path, body.name))
        return {"id": "clock"}

    async def post_git(body, request):
        calls.append(("git", body.url, body.ref, body.subdir))
        return {"id": "clock"}

    async def delete(request, name):
        calls.append(("delete", name))
        return {"removed": name}

    monkeypatch.setattr(sideload_routes, "post_sideload", post)
    monkeypatch.setattr(sideload_git_routes, "post_sideload_git", post_git)
    monkeypatch.setattr(sideload_routes, "delete_sideload", delete)
    state = tmp_path / "state"
    state.mkdir()
    return SimpleNamespace(view=View(state), state=state, calls=calls, store=store)


def _call(w, name, args) -> dict:
    return asyncio.run(tools.call_tool(w.view, PANE, name, args))


def _text(answer) -> str:
    return answer["content"][0]["text"]


def test_both_are_owner_approved_writes_and_no_tool_reaches_the_switch():
    assert set(TOOLS) <= tools.WRITE_TOOLS and set(TOOLS) <= beast_mode.ALWAYS_WAITS
    routes = {s.route for m in tools._ROUTE_MODULES for s in getattr(m, "SPECS", ())}
    assert not any(r.endswith(":put_switch") and "sideload" in r for r in routes)
    for name, row in tools._TOOLS.items():
        assert not ("sideload" in name and "switch" in name), name
    assert set(plugin_sideload_tools.WRITE_TOOLS) == set(TOOLS) and plugin_sideload_tools.READ_TOOLS == {}


@pytest.mark.parametrize("name,args", [("plugin_sideload_add", {"path": "/tmp/clock"}),
                                       ("plugin_sideload_add", {"git_url": "https://github.com/me/clock.git", "ref": "main"}),
                                       ("plugin_sideload_remove", {"name": "clock"})])
def test_switch_off_refuses_before_any_card_is_filed(world, name, args):
    answer = _call(world, name, args)
    assert answer["isError"] is True and "sideload_off" in _text(answer), answer
    assert world.store.list() == [] and world.calls == []


def test_switch_on_files_a_card_even_under_beast_and_the_approve_runs_the_route(world):
    sideload.set_switch(world.state, True)
    held = json.loads(_text(_call(world, "plugin_sideload_add", {"git_url": "https://github.com/me/clock.git", "subdir": "plugin"})))
    assert held["status"] == "pending" and world.calls == []
    asyncio.run(world.store.approve(world.store.list()[0]["id"]))
    assert world.calls == [("git", "https://github.com/me/clock.git", None, "plugin")]


def test_a_switch_turned_off_before_the_approve_still_refuses(world):
    sideload.set_switch(world.state, True)
    _call(world, "plugin_sideload_remove", {"name": "clock"})
    sideload.set_switch(world.state, False)
    asyncio.run(world.store.approve(world.store.list()[0]["id"]))
    assert world.calls == []


def test_path_and_git_url_are_exclusive(world):
    sideload.set_switch(world.state, True)
    with pytest.raises(Exception, match="exactly one"):
        asyncio.run(plugin_sideload_tools._load(SimpleNamespace(request=SimpleNamespace(app=world.view.app), args={})))
    with pytest.raises(Exception, match="only go with git_url"):
        asyncio.run(plugin_sideload_tools._load(SimpleNamespace(request=SimpleNamespace(app=world.view.app),
                                                                args={"path": "/x", "ref": "main"})))



def _catalog_warning() -> str:
    from src.core.notifications.catalog_lines import read_prefixed

    return read_prefixed(("plugins.page.sideload.warning.risk",))["plugins.page.sideload.warning.risk"]


def test_the_add_tool_says_the_catalog_warning_in_its_description_and_its_approval_card():
    warning = _catalog_warning()
    assert "not reviewed or signed" in warning
    assert plugin_sideload_tools.SIDELOAD_WARNING == warning
    assert warning in tools._TOOLS["plugin_sideload_add"][0]
    assert warning in plugin_sideload_tools._load_summary({"path": "/tmp/clock"}, None)


@pytest.mark.parametrize("args", [{"path": "/tmp/clock"}, {"git_url": "https://github.com/me/clock.git"}])
def test_a_load_answers_with_the_warning(world, args):
    sideload.set_switch(world.state, True)
    answer = asyncio.run(plugin_sideload_tools._load(SimpleNamespace(request=SimpleNamespace(app=world.view.app), args=args)))
    assert answer["id"] == "clock" and answer["warning"] == _catalog_warning()


def test_an_approved_add_reaches_the_agent_with_the_warning(world):
    sideload.set_switch(world.state, True)
    _call(world, "plugin_sideload_add", {"path": "/tmp/clock"})
    done = asyncio.run(world.store.approve(world.store.list()[0]["id"]))
    assert _catalog_warning() in json.dumps(done.result, default=str)
