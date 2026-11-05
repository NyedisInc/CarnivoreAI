
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.mcp import write_tools
from src.core.swarm import spawn


def _caller(external: bool = False):
    return SimpleNamespace(external=external, proxied_agent_id=None, current_session_id="ses_a", tmux_name="carnivore_a")


def test_a_swarm_agent_restarts_wakes_and_joins_local_sessions_with_no_approval(monkeypatch):
    agents = {"carnivore_a"}

    async def parent_agent(view, caller):
        if caller.tmux_name not in agents:
            raise spawn.SpawnRefused("swarm tools are for Swarm agents")
        return {"id": 5}

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    skip = lambda action, target, caller=None: asyncio.run(  # noqa: E731
        write_tools._swarm_agent_skip(None, caller or _caller(), action, target))
    assert skip("session_restart", "ses_b") and skip("session_wake", "uuid-1") and skip("swarm_join", "ses_b")
    assert not skip("session_restart", "remote:peer-1:ses_b")
    assert not skip("session_delete", "ses_b") and not skip("session_send_keys", "ses_b")
    assert not skip("session_restart", "ses_b", _caller(external=True))
    agents.clear()
    assert not skip("session_restart", "ses_b")


def test_a_proxied_swarm_body_never_skips_the_approval(monkeypatch):
    async def parent_agent(view, caller):
        return {"id": 5}

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    proxied = _caller()
    proxied.proxied_agent_id = 7
    assert not asyncio.run(write_tools._swarm_agent_skip(None, proxied, "swarm_join", "ses_b"))
    assert asyncio.run(write_tools._swarm_agent_skip(None, _caller(), "swarm_join", "ses_b"))
