
from __future__ import annotations

import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.crosstalk import spawn_layout
from src.core.db import connect, db_path_for
from src.core.mcp import beast_mode, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.protocol import BatchView
from src.core.swarm import body, brief, spawn, store
from tests.python.swarm.test_swarm_agent_real_tmux import _bodies, _until, world  # noqa: F401

GOAL = "Replace every hard-coded model name with the shared constant."
ARGS = {"job": "swap the model names", "goal": GOAL, "task_type": "refactor", "rank": "task", "effort": "high",
        "effort_reason": "touches the whole call graph", "persona": "a careful refactorer", "launch_profile": "swarm-upper"}


def _caller(info) -> AgentCaller:
    return AgentCaller(session_id=info.session.id, tmux_name=info.tmux_session, current_session_id=info.session.id)


async def _info_of(manager, agent_id: int, state):
    with closing(connect(db_path_for(state), create=False)) as conn:
        row_id = store.get_agent(conn, agent_id)["session_row_id"]
    return next(i for i in await manager.list_session_infos() if i.session_row_id == row_id)


@pytest.mark.asyncio
async def test_swarm_spawn_from_a_project_agent_and_its_refusals(world, monkeypatch):  # noqa: F811
    launches, cards, tabs = [], [], []
    real = type(settings).get_agent_command

    def record(self, agent_type, model=None, extra_args=None, **kw):
        launches.append((agent_type, list(extra_args or [])))
        return real(self, agent_type, model, extra_args, **kw)

    async def post_card(key, kind, title, text, ref):
        cards.append((key, title, ref))
        return 1

    async def persist(*a, **k):
        tabs.append(a)

    monkeypatch.setattr(type(settings), "get_agent_command", record)
    monkeypatch.setattr(world.port, "post_card", post_card)
    monkeypatch.setattr(spawn_layout, "persist", persist)

    with closing(connect(db_path_for(world.state), create=False)) as conn:
        parent = store.create_agent(conn, slug="boss", rank="project", job="run the project", display_name="Boss",
                                    repo_dir=str(world.repo), effort="high")
    await body.wake(world.app.state, parent["id"], "manual", "data")
    view = BatchView(world.manager, world.app)
    parent_caller = _caller(await _info_of(world.manager, parent["id"], world.state))

    assert "swarm_spawn" in tools.WRITE_TOOLS and "swarm_spawn" in beast_mode.AGENT_ACTIONS

    plan = await spawn.prepare(view, parent_caller, ARGS)
    made = await spawn.run(view, parent_caller, plan)
    child_id, slug = made["agent_id"], made["slug"]

    text = (world.repo / ".claude" / "agents" / f"{slug}.md").read_text()
    assert GOAL in text and "high" in text
    for section in (brief.SECTION_WHO, brief.SECTION_READ, brief.SECTION_TODO, brief.SECTION_RULES, brief.SECTION_REPORT,
                    brief.SECTION_DONE):
        assert section in text
    assert "spawned by Boss" in text and "a careful refactorer" in text

    assert launches[-1][0] == "swarm-upper" and launches[-1][1][:4] == ["--agent", slug, "--effort", "high"]
    await _until(lambda: world.argv_log.exists() and world.argv_log.read_text().splitlines()[:2] == ["--agent", slug],
                 "the child's stub agent to start")
    assert len(_bodies(world.manager)) == 2

    with closing(connect(db_path_for(world.state), create=False)) as conn:
        assert [r[0] for r in conn.execute("SELECT source FROM crosstalk_contacts")] == ["swarm"]
        assert store.get_agent(conn, child_id)["parent_id"] == parent["id"]
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        queued = conn.execute("SELECT receiver_id, text, status FROM crosstalk_messages").fetchall()
    child_info = await _info_of(world.manager, child_id, world.state)
    assert len(queued) == 1 and queued[0][0] == child_info.session.id and queued[0][2] == "queued"
    assert GOAL in queued[0][1] and "Your effort level is high" in queued[0][1]
    assert "This order comes from your parent agent, Boss" in queued[0][1]

    assert tabs == []

    view = view.fresh()
    child_caller = _caller(await _info_of(world.manager, child_id, world.state))
    with pytest.raises(spawn.SpawnRefused, match="cannot spawn"):
        await spawn.prepare(view, child_caller, {**ARGS, "job": "grandchild"})

    config = json.loads(open(settings.auth_config_file).read())
    config["swarm"] = {"max_children_per_parent": 1}
    open(settings.auth_config_file, "w").write(json.dumps(config))
    again = await spawn.prepare(view.fresh(), parent_caller, {**ARGS, "job": "one more", "launch_profile": ""})
    with pytest.raises(spawn.SpawnRefused, match="not spawned"):
        await spawn.run(view.fresh(), parent_caller, again)
    assert [c[2] for c in cards] == [f"spawn_refused:{parent['id']}"]
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM swarm_agents WHERE parent_id = ?", (parent["id"],)).fetchone()[0] == 1
    assert len(_bodies(world.manager)) == 2
