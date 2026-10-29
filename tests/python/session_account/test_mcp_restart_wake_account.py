
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.api import session_sleep_routes  # noqa: E402
from src.core.mcp import session_control_tools, session_target, write_tools  # noqa: E402
from src.core.mcp.common import ToolError  # noqa: E402
from tests.python.session_account.test_session_account_pin import config  # noqa: E402,F401

CALLER = SimpleNamespace(tmux_name="agent")


@pytest.fixture()
def harness(config, monkeypatch):  # noqa: F811
    h = SimpleNamespace(asked=[], respawn=AsyncMock(return_value={"ok": True}), wake=[], target=None)
    info = SimpleNamespace(session=SimpleNamespace(id="s1", agent_type="claude", tmux_created_epoch=1),
                           tmux_session="carnivore_s1", host_key="local")
    h.target = session_target.SessionTarget(kind=session_target.KIND_LIVE, info=info, session_uuid="u1", tmux_name="carnivore_s1")
    app = SimpleNamespace(state=SimpleNamespace(
        session_manager=SimpleNamespace(respawn_session=h.respawn, list_session_infos=AsyncMock(return_value=[info]))))
    h.manager = SimpleNamespace(app=app)

    async def resolve(manager, args, reach, tool):
        return h.target

    async def gated(manager, caller, info_, action, summary, args, run, **kw):
        h.asked.append(summary)
        return await run(True)

    async def park(manager, caller, target_id, tmux, action, summary, args, run, **kw):
        h.asked.append(summary)
        return await run(True)

    async def wake_route(request, session_uuid, body=None):
        h.wake.append((session_uuid, body))
        return {"status": "woke"}

    async def uuid_of(self, target):
        return target.session_uuid

    monkeypatch.setattr(session_target, "resolve_target", resolve)
    monkeypatch.setattr(session_target.TargetResolver, "resolve", lambda self, args, reach, tool: resolve(None, args, reach, tool))
    monkeypatch.setattr(session_target.TargetResolver, "uuid_of", uuid_of)
    monkeypatch.setattr(write_tools, "_pane_live", AsyncMock(return_value=True))
    monkeypatch.setattr(write_tools, "_gated", gated)
    monkeypatch.setattr(write_tools, "park", park)
    monkeypatch.setattr(session_sleep_routes, "wake_session", wake_route)
    return h


def _restart(h, **args):
    return asyncio.run(write_tools.session_restart(h.manager, CALLER, {"target": "carnivore_s1", **args}))


def _wake(h, **args):
    return asyncio.run(session_control_tools.WRITE_TOOLS["session_wake"][3](h.manager, CALLER, {"target": "u1", **args}))


def test_restart_passes_a_launchable_account_and_the_box_to_the_respawn(harness):
    _restart(harness, account="work", always_use_account=True)
    kwargs = harness.respawn.call_args.kwargs
    assert (kwargs["account_id"], kwargs["account_pinned"], kwargs["live_restart_confirmed"]) == ("work", True, True)
    assert "on account work (always)" in harness.asked[0]


def test_restart_with_no_account_keeps_the_old_path(harness):
    _restart(harness)
    kwargs = harness.respawn.call_args.kwargs
    assert (kwargs["account_id"], kwargs["account_pinned"]) == (None, False)
    assert "account" not in harness.asked[0]


def test_restart_refuses_a_bad_account_before_the_owner_is_asked(harness):
    with pytest.raises(ToolError, match=r"launchable account ids: .*work"):
        _restart(harness, account="nope")
    with pytest.raises(ToolError, match="needs account"):
        _restart(harness, always_use_account=True)
    harness.target.info.session.agent_type = "codex"
    with pytest.raises(ToolError, match="launchable account ids"):
        _restart(harness, account="work")
    harness.target.info.session.agent_type = "claude"
    harness.target.info.host_key, harness.target.info.activity_status = "remote:peer-x", "idle"
    with pytest.raises(ToolError, match="computer that runs the session"):
        _restart(harness, account="work")
    assert harness.asked == [] and not harness.respawn.called


def test_wake_passes_the_account_and_box_to_the_wake_route(harness):
    harness.target = session_target.SessionTarget(kind=session_target.KIND_ASLEEP, row={"agent_type": "claude"},
                                                  session_uuid="u1", tmux_name="carnivore_s1")
    _wake(harness, account="work", always_use_account=True)
    uuid, body = harness.wake[0]
    assert (uuid, body.account_id, body.account_pinned) == ("u1", "work", True)
    assert "on account work (always)" in harness.asked[0]
    _wake(harness)
    assert harness.wake[1] == ("u1", None)


def test_wake_refuses_a_bad_account_before_the_owner_is_asked(harness):
    harness.target = session_target.SessionTarget(kind=session_target.KIND_ASLEEP, row={"agent_type": "claude"},
                                                  session_uuid="u1", tmux_name="carnivore_s1")
    with pytest.raises(ToolError, match=r"launchable account ids: .*work"):
        _wake(harness, account="handmade")
    assert harness.asked == [] and harness.wake == []


def test_restart_of_an_asleep_target_hands_the_account_to_the_wake(harness):
    harness.target = session_target.SessionTarget(kind=session_target.KIND_ASLEEP, row={"agent_type": "claude"},
                                                  session_uuid="u1", tmux_name="carnivore_s1")
    _restart(harness, account="play")
    assert harness.wake[0][1].account_id == "play"


def test_wake_passes_start_fresh_only_when_given(harness):
    harness.target = session_target.SessionTarget(kind=session_target.KIND_ASLEEP, row={"agent_type": "claude"},
                                                  session_uuid="u1", tmux_name="carnivore_s1")
    _wake(harness, start_fresh=True)
    assert harness.wake[0][1].start_fresh is True
    assert "starts a new conversation" in harness.asked[0]
    _wake(harness)
    assert harness.wake[1] == ("u1", None)
