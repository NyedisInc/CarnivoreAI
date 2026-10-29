
from __future__ import annotations

import json

import pytest

from src.core.mcp import beast_mode, federated, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.protocol import BatchView
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402
from tests.python.sessions import test_companion_shell_route as base
from tests.python.sessions.test_companion_shell_route import requires_tmux, world  # noqa: F401

CALLER = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop")


def _view(world, monkeypatch):
    async def no_peers(force: bool = False):
        return []

    monkeypatch.setattr(federated, "peer_infos", no_peers)
    return BatchView(world.manager, world.request.app)


async def _call(world, monkeypatch, name: str, target: str) -> dict:
    return await tools.call_tool(_view(world, monkeypatch), CALLER, name, {"target": target})


@requires_tmux
@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["id", "adopted", "bare"])
async def test_every_local_target_form_opens_and_reads_the_shell(world, monkeypatch, form):
    arm_beast(monkeypatch, lambda: True)
    registry = world.manager._registry
    if form == "adopted":
        session, backend = registry.get_session(base.AGENT_ID), registry.get_backend(base.AGENT_ID)
        registry.sessions.pop(base.AGENT_ID, None)
        registry.backends.pop(base.AGENT_ID, None)
        agent_id = f"adopted:{world.agent_name}"
        session = session.model_copy(update={"id": agent_id})
        registry.backends[agent_id] = backend
        registry.register(session, backend)
    else:
        agent_id = base.AGENT_ID
    target = {"id": agent_id, "adopted": agent_id, "bare": world.agent_name}[form]

    opened = await _call(world, monkeypatch, "session_shell_open", target)
    assert not opened.get("isError"), opened
    shell = json.loads(opened["content"][0]["text"])
    assert shell["state"] == "created" and shell["agent_session_id"] == agent_id

    got = await _call(world, monkeypatch, "session_shell_get", target)
    assert not got.get("isError"), got
    assert json.loads(got["content"][0]["text"])["session_id"] == shell["session_id"]


@pytest.mark.asyncio
async def test_a_remote_target_gets_the_answer_other_tools_give(world, monkeypatch):
    refused = {}
    for name in ("session_shell_open", "session_shell_get", "session_read_output"):
        answer = await _call(world, monkeypatch, name, "remote:peer-abc:ses_x")
        assert answer.get("isError") is True, (name, answer)
        refused[name] = answer["content"][0]["text"]
    assert refused["session_shell_open"] == refused["session_shell_get"] == refused["session_read_output"]


def test_a_remote_host_session_sharing_a_companion_name_is_not_hidden():
    from datetime import datetime

    from src.core.companion_shell import index as companion_index
    from pathlib import Path
    from types import SimpleNamespace

    from src.core.hosts.remote_backend import make_remote_backend
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session, SessionStatus

    registry = SessionRegistry(log_cap=lambda: 10)
    index = companion_index.CompanionIndex()
    index.link(agent_row=4, shell_row=9, tmux_name="carnivore_sh-1")
    registry.hide_when(index.is_hidden_session)

    def make(sid: str):
        return Session(id=sid, status=SessionStatus.RUNNING, working_dir="/w", created_at=datetime.utcnow(),
                       tmux_session="carnivore_sh-1")

    registry.register(make("ses_local_shell"), None)
    registry.register(make("ses_on_a_remote_host"), make_remote_backend(SimpleNamespace(host_key="studio", socket="far"), "s", Path("/far")))
    assert registry.listable_ids() == ["ses_on_a_remote_host"]
    assert registry.is_hidden("ses_local_shell") and not registry.is_hidden("ses_on_a_remote_host")
    assert registry.find_hidden_id("carnivore_sh-1") == "ses_local_shell"
