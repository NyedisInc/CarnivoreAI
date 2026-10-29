
from __future__ import annotations

import os
import signal
import subprocess
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest

from src.core.db import connect, db_path_for
from src.core.swarm import body, store, turn_off, watch
from src.core.unread_store import UnreadStore
from tests.python.swarm.test_swarm_agent_real_tmux import _bodies, _until, world  # noqa: F401

API = "/swarm"


def _pane_dead(manager, name: str) -> bool:
    out = subprocess.run(["tmux", "-L", manager.tmux_socket_name(), "display-message", "-t", f"={name}:", "-p", "#{pane_dead}"],
                         capture_output=True, text=True, check=False).stdout
    return out.strip() == "1"


def _kill_pane_process(manager, name: str, *, husk: bool) -> None:
    if husk:
        subprocess.run(["tmux", "-L", manager.tmux_socket_name(), "set-option", "-w", "-t", f"={name}:", "remain-on-exit", "on"], check=True)
    pid = subprocess.run(["tmux", "-L", manager.tmux_socket_name(), "list-panes", "-t", f"={name}", "-F", "#{pane_pid}"],
                         capture_output=True, text=True, check=True).stdout.split()[0]
    os.kill(int(pid), signal.SIGKILL)


async def _woken(client, world, job: str) -> dict:
    made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": job, "rank": "feature",
                                                    "effort": "high", "effort_reason": "wide change"})
    assert made.status_code == 201, made.text
    agent_id = made.json()["id"]
    sent = await client.post(f"{API}/agents/{agent_id}/messages", json={"text": "go"})
    assert sent.status_code == 200, sent.text
    return (await client.get(f"{API}/agents/{agent_id}")).json()


def _read(world, agent_id: int) -> tuple:
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        wake = conn.execute("SELECT end_reason, ended_at FROM swarm_wakes WHERE agent_id = ? ORDER BY id DESC", (agent_id,)).fetchone()
        return store.get_agent(conn, agent_id), (wake[0], wake[1]) if wake else (None, None)


@pytest.mark.asyncio
async def test_a_body_whose_pane_dies_reads_asleep_with_its_wake_closed_and_turn_off_succeeds(world, monkeypatch):  # noqa: F811
    closed = []

    async def close_open_cards(thread_key, prefix):
        closed.append((thread_key, prefix))

    monkeypatch.setattr(world.port, "close_open_cards", close_open_cards)
    world.busy["on"] = True
    watch.reset()
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        first = await _woken(client, world, "swap models")
        assert _bodies(world.manager) == [first["tmux_session"]]

        _kill_pane_process(world.manager, first["tmux_session"], husk=True)
        await _until(lambda: _pane_dead(world.manager, first["tmux_session"]), "the husk to hold a dead pane")
        dead_reading = SimpleNamespace(verdict=SimpleNamespace(reason="pane_dead"))
        watch.on_observation(SimpleNamespace(key=UnreadStore.compose_key(first['tmux_session'], watch._epochs.get(first['tmux_session']))), dead_reading)
        await _until(lambda: _read(world, first["id"])[0]["state"] == "asleep", "the dead body to be buried")
        agent, wake = _read(world, first["id"])
        assert wake[0] == "died" and wake[1] is not None
        assert _bodies(world.manager) == []
        assert (agent["thread_key"], "trust:") in closed

        second = await _woken(client, world, "tidy the docs")
        _kill_pane_process(world.manager, second["tmux_session"], husk=True)
        await _until(lambda: _pane_dead(world.manager, second["tmux_session"]), "the husk to hold a dead pane")
        out = await turn_off.run(world.app.state, second["id"])
        assert out["state"] == "torn_down"
        agent, wake = _read(world, second["id"])
        assert agent["torn_down_at"] is not None and wake[0] == "died"
        assert _bodies(world.manager) == []
    watch.reset()


@pytest.mark.asyncio
async def test_every_wake_sleep_and_death_publishes_a_change_notice_that_drops_the_roster_cache(world, monkeypatch):  # noqa: F811
    from src.api.swarm_routes import ROSTER_BODIES_CACHE
    from src.core import session_change_notice

    reasons = []
    real = session_change_notice.publish

    def spy(app_state, frame):
        reasons.append(frame.get("reason"))
        return real(app_state, frame)

    monkeypatch.setattr(session_change_notice, "publish", spy)
    world.busy["on"] = True
    watch.reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.app), base_url="http://t/api/v1") as client:
        first = await _woken(client, world, "swap models")
        assert "swarm_woken" in reasons
        await client.get(f"{API}/roster")
        assert ROSTER_BODIES_CACHE._value is not None
        assert (await client.post(f"{API}/agents/{first['id']}/sleep")).status_code == 200
        assert "swarm_slept" in reasons and ROSTER_BODIES_CACHE._value is None
        second = await _woken(client, world, "tidy the docs")
        _kill_pane_process(world.manager, second["tmux_session"], husk=True)
        await _until(lambda: _pane_dead(world.manager, second["tmux_session"]), "the husk to hold a dead pane")
        await turn_off.run(world.app.state, second["id"])
        assert "swarm_died" in reasons
    watch.reset()
