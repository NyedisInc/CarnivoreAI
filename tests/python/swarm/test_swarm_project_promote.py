
from __future__ import annotations

import asyncio
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_s7_smokefix import _db, env  # noqa: F401,E402
from src.core.db import connect, db_path_for
from src.core.swarm import body, body_create, project_agent, project_promote, store

ORION = "Orion"


@pytest.fixture()
def world(env, monkeypatch):
    folder = env.root / ORION
    folder.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    live, slept = set(), []
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        orion = body_create.register_project(conn, str(folder), ORION)
        for name in ("lead", "other", "third"):
            conn.execute("INSERT INTO sessions (session_uuid, project_id, working_dir, title, origin, lifecycle, agent_family, created_at, updated_at)"
                         " VALUES (?, ?, ?, ?, 'created', 'stopped', 'claude', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')",
                         (f"u-{name}", orion["id"], str(folder), name))
    async def live_info(app_state, agent):
        return SimpleNamespace() if agent["session_row_id"] in live else None

    async def sleep_by_uuid(app_state, session_uuid, **kw):
        slept.append(session_uuid)
        row = _db(env, lambda c: c.execute("SELECT id FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()[0])
        live.discard(row)
        return SimpleNamespace(status="asleep", detail="")

    monkeypatch.setattr(body, "live_info", live_info)
    import src.api.session_sleep_routes as sleep_routes
    monkeypatch.setattr(sleep_routes, "sleep_by_uuid", sleep_by_uuid)
    env.orion, env.slept, env.live, env.folder = orion, slept, live, folder
    return env


def _row_id(world, name: str) -> int:
    return _db(world, lambda c: c.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"u-{name}",)).fetchone()[0])


def _promote(world, name: str, project_id=None):
    return asyncio.run(project_promote.promote_session(SimpleNamespace(), f"u-{name}", project_id or world.orion["id"]))


def _agents(world):
    return _db(world, lambda c: [a for a in store.list_agents(c) if a["rank"] == "project" and a["project_id"] == world.orion["id"]])


def test_an_asleep_session_becomes_the_project_agent_on_its_own_row_and_stays_asleep(world):
    agent = _promote(world, "lead")
    assert agent["session_row_id"] == _row_id(world, "lead") and agent["rank"] == "project" and agent["state"] == "asleep"
    assert agent["thread_key"] == str(world.orion["id"]) and [a["id"] for a in _agents(world)] == [agent["id"]]
    assert world.slept == [] and world.woke == []
    assert (world.folder / ".claude" / "agents" / f"{agent['slug']}.md").is_file()


def test_a_running_session_is_stopped_then_woken_resuming_its_conversation(world, monkeypatch):
    world.live.add(_row_id(world, "lead"))
    woke = []

    async def wake(app_state, agent_id, reason, authority, **kw):
        woke.append((agent_id, reason, authority, kw["mode"]))

    monkeypatch.setattr(body, "wake", wake)
    agent = _promote(world, "lead")
    assert world.slept == ["u-lead"] and woke == [(agent["id"], "manual", "data", "resume")]


def test_a_session_in_the_middle_of_a_turn_refuses_and_nothing_is_written(world, monkeypatch):
    world.live.add(_row_id(world, "lead"))

    async def busy(app_state, session_uuid, **kw):
        return SimpleNamespace(status="refused", detail="cannot sleep: the session is working")

    import src.api.session_sleep_routes as sleep_routes
    monkeypatch.setattr(sleep_routes, "sleep_by_uuid", busy)
    with pytest.raises(project_promote.PromoteRefused, match="working"):
        _promote(world, "lead")
    assert _agents(world) == [] and world.woke == []


@pytest.mark.parametrize("change, message", [
    ("UPDATE sessions SET archived_at = '2026-10-01T00:00:00Z' WHERE session_uuid = 'u-lead'", "was deleted"),
    ("UPDATE sessions SET agent_family = 'codex' WHERE session_uuid = 'u-lead'", "not a Claude session"),
    ("UPDATE sessions SET working_dir = '/elsewhere' WHERE session_uuid = 'u-lead'", "not in the project's folder"),
    ("UPDATE sessions SET host_key = 'peer-1' WHERE session_uuid = 'u-lead'", "another machine"),
    ("UPDATE sessions SET project_id = NULL WHERE session_uuid = 'u-lead'", "another project"),
])
def test_an_unfit_session_is_refused_before_anything_is_written(world, change, message):
    _db(world, lambda c: c.execute(change))
    with pytest.raises(project_promote.PromoteRefused, match=message):
        _promote(world, "lead")
    assert _agents(world) == [] and world.slept == [] and world.woke == []


def test_a_session_that_is_another_agents_body_is_refused(world):
    _db(world, lambda c: store.create_agent(c, slug="kid", rank="task", job="j", display_name="Kid", repo_dir=str(world.folder),
                                           effort="low", project_id=world.orion["id"], session_row_id=_row_id(world, "other")))
    with pytest.raises(project_promote.PromoteRefused, match="already Kid"):
        _promote(world, "other")


def test_a_project_with_an_agent_has_it_repointed_and_the_old_body_goes_back_to_a_plain_session(world):
    first = _promote(world, "lead")
    again = _promote(world, "other")
    assert again["id"] == first["id"] and again["slug"] == first["slug"] and again["session_row_id"] == _row_id(world, "other")
    assert [a["id"] for a in _agents(world)] == [first["id"]]
    assert _db(world, lambda c: store.get_agent_by_session_row(c, _row_id(world, "lead"))) is None


def test_promoting_the_session_that_already_is_the_agent_changes_nothing(world):
    first = _promote(world, "lead")
    assert _promote(world, "lead")["id"] == first["id"] and world.slept == [] and world.woke == []


def test_a_missing_project_and_a_missing_session_are_refused(world):
    with pytest.raises(project_agent.ProjectMissing):
        _promote(world, "lead", project_id=9999)
    with pytest.raises(project_promote.PromoteRefused, match="no such session"):
        asyncio.run(project_promote.promote_session(SimpleNamespace(), "u-nobody", world.orion["id"]))


def test_the_owner_route_answers_404_for_a_missing_project_and_409_for_a_refused_session(world):
    from fastapi import HTTPException

    from src.api import swarm_routes
    from src.models.swarm import SwarmPromoteRequest

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    def call(project_id, uuid):
        return asyncio.run(swarm_routes.promote_session_to_project_agent(project_id, SwarmPromoteRequest(session_uuid=uuid), request))

    with pytest.raises(HTTPException) as missing:
        call(9999, "u-lead")
    assert missing.value.status_code == 404 and missing.value.detail["code"] == "project_not_found"
    with pytest.raises(HTTPException) as refused:
        call(world.orion["id"], "u-nobody")
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "swarm_refused"


def test_a_repoint_to_a_fresh_session_leaves_the_old_body_launching_with_no_swarm_flags(world):
    from src.core.swarm import launch

    _promote(world, "lead")
    assert _db(world, lambda c: launch.swarm_launch_args(_row_id(world, "lead"), conn=c)) != []
    _promote(world, "third")
    assert _db(world, lambda c: launch.swarm_launch_args(_row_id(world, "lead"), conn=c)) == []
    assert _db(world, lambda c: launch.swarm_launch_args(_row_id(world, "third"), conn=c)) != []
