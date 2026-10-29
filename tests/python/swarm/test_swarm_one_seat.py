
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_s7_smokefix import _db, _suggest, env  # noqa: F401,E402
from src.core.db import connect, db_path_for
from src.core.mcp.common import ToolError
from src.core.swarm import body_create, company_desk, project_agent, store, stream_sources


def _count(env):
    return _db(env, lambda c: c.execute("SELECT COUNT(*) FROM swarm_agents").fetchone()[0]), len(env.port.cards), len(env.woke)


def test_a_company_hq_and_alpha_folder_take_no_project_agent_and_nothing_is_written(env):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        (env.root / "Alpha Home").mkdir()
        home = body_create.register_project(conn, str(env.root / "Alpha Home"), "Alpha Home")
        store.update_agent(conn, env.agents["alpha"]["id"], project_id=home["id"])
    before = _count(env)
    for project in (env.hq, home):
        with pytest.raises(project_agent.TurnOnError, match="already runs|already sits"):
            asyncio.run(project_agent.turn_on(SimpleNamespace(), project["id"]))
    with pytest.raises(ToolError):
        _suggest(env, "acmeboss", kind="project", name="Acme HQ", reason="turn on its agent")
    assert _count(env) == before
    lines, _ = _db(env, lambda c: company_desk.lines(c, env.agents["acmeboss"]))
    assert not any("Acme HQ" in line for line in lines) and "- no projects yet" in lines
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        (env.root / "Plain").mkdir()
        plain = body_create.register_project(conn, str(env.root / "Plain"), "Plain")
        made = store.create_agent(conn, slug="plain-agent", rank="project", job="j", display_name="Plain agent",
                                  repo_dir=str(env.root / "Plain"), effort="high", project_id=plain["id"], parent_id=env.agents["acmeboss"]["id"])
        events = stream_sources._events(conn, made["id"], 10)
    assert [e["text"] for e in events] == ["Plain agent was turned on"]


def test_a_project_on_a_paired_computer_takes_no_agent_here_and_says_why(env):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        cur = conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, created_at, updated_at, last_opened_at)"
                           " VALUES ('peer://peer-ab12/Users/a/SoundDesk', 'peer://peer-ab12/Users/a/SoundDesk', 'SoundDesk (2)', 'adoption',"
                           " 'unchecked', 'peer-ab12', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')")
        conn.commit()
        remote_id = cur.lastrowid
    before = _count(env)
    with pytest.raises(project_agent.TurnOnError, match="another computer") as caught:
        asyncio.run(project_agent.turn_on(SimpleNamespace(), remote_id))
    assert "missing" not in str(caught.value)
    assert _count(env) == before
