
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_s7_smokefix import _db, env  # noqa: F401,E402
from src.core.db import connect, db_path_for
from src.core.swarm import body, body_create, company_agent, project_agent, store, thread_port, turn_off


class CardPort:

    def __init__(self) -> None:
        self.cards = [{"thread_key": "70", "swarm_ref": "naming:99"}, {"thread_key": "70", "swarm_ref": "trust:99:x"},
                      {"thread_key": "agent:1", "swarm_ref": "naming:1"}]
        self.closed, self.archived = [], []

    async def ensure_thread(self, key, title): ...
    async def open_cards(self):
        return [c for c in self.cards if c["swarm_ref"] not in {r for _, r in self.closed}]

    async def close_open_cards(self, key, prefix):
        self.closed.append((key, prefix))

    async def archive_thread(self, key):
        self.archived.append(key)


def _make(env, name):  # noqa: F811
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        folder = env.root / name
        folder.mkdir()
        body_create.ensure_repo(str(folder))
        project = body_create.register_project(conn, str(folder), name)
        agent = store.create_agent(conn, slug=f"{name.lower()}-agent", rank="project", job="j", display_name=f"{name} agent", repo_dir=str(folder),
                                   effort="high", project_id=project["id"], parent_id=env.agents["acmeboss"]["id"])
        return project, agent, folder


def test_turn_off_tombstones_closes_cards_keeps_files_and_a_turn_on_afterwards_works(env, monkeypatch):  # noqa: F811
    project, agent, folder = _make(env, "Plain")
    (folder / ".claude" / "agents").mkdir(parents=True)
    definition_file = folder / ".claude" / "agents" / f"{agent['slug']}.md"
    definition_file.write_text("keep me")
    port = CardPort()
    port.cards[0]["thread_key"] = port.cards[1]["thread_key"] = agent["thread_key"]
    thread_port.register(port)
    slept = []

    async def sleep(app_state, agent_id, reason="sleep"):
        slept.append((agent_id, reason))
        return SimpleNamespace(state="asleep", commit={"status": "committed", "sha": "abc"})

    monkeypatch.setattr(body, "sleep", sleep)
    _db(env, lambda c: store.cas_state(c, agent["id"], "asleep", "awake"))
    done = asyncio.run(turn_off.run(SimpleNamespace(), agent["id"]))
    assert done["state"] == "torn_down" and slept == [(agent["id"], "teardown")]
    row = _db(env, lambda c: store.get_agent(c, agent["id"]))
    assert row["torn_down_at"] is not None and _db(env, lambda c: store.get_project_agent(c, project["id"])) is None
    assert {r for _, r in port.closed} == {"naming:99", "trust:99:x"} and port.archived == []
    assert definition_file.read_text() == "keep me"
    assert all(a["id"] != agent["id"] for a in _db(env, store.list_agents))
    with pytest.raises(store.AgentNotFound):
        asyncio.run(turn_off.run(SimpleNamespace(), agent["id"]))
    again = asyncio.run(project_agent.turn_on(SimpleNamespace(), project["id"]))
    assert again["id"] != agent["id"] and again["project_id"] == project["id"] and again["torn_down_at"] is None
    boss = env.agents["acmeboss"]
    asyncio.run(turn_off.run(SimpleNamespace(), again["id"]))
    _db(env, lambda c: store.cas_state(c, boss["id"], "awake", "asleep"))
    asyncio.run(turn_off.run(SimpleNamespace(), boss["id"]))
    back = asyncio.run(company_agent.turn_on(SimpleNamespace(), env.acme["id"]))
    assert back["id"] != boss["id"] and back["project_id"] == env.hq["id"] and back["torn_down_at"] is None


def test_alpha_and_a_parent_with_live_children_are_refused_and_nothing_changes(env):  # noqa: F811
    _, child, _ = _make(env, "Kid")
    port = CardPort()
    thread_port.register(port)
    for target in (env.agents["alpha"]["id"], env.agents["acmeboss"]["id"]):
        with pytest.raises(turn_off.TurnOffRefused) as raised:
            asyncio.run(turn_off.run(SimpleNamespace(), target))
        assert ("SysOp" in str(raised.value)) or ("Kid agent" in str(raised.value))
    assert port.closed == [] and all(_db(env, lambda c: store.get_agent(c, i))["torn_down_at"] is None for i in (env.agents["alpha"]["id"], env.agents["acmeboss"]["id"]))
