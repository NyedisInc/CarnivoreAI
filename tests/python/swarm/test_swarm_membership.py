
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_project_promote import _db, _row_id, env, world  # noqa: F401
from src.core.swarm import launch, membership, project_agent, store


@pytest.fixture()
def members(world, monkeypatch):
    leader = _db(world, lambda c: project_agent.insert_project_agent(c, project_agent._project(c, world.orion["id"]), session_row_id=_row_id(world, "lead")))
    plain = []

    async def wake_by_uuid(app_state, session_uuid, **kw):
        plain.append(session_uuid)

    async def held_cards(agent_id):
        return []

    import src.api.session_sleep_routes as sleep_routes
    from src.core.swarm.cards import ops
    monkeypatch.setattr(sleep_routes, "wake_by_uuid", wake_by_uuid)
    monkeypatch.setattr(ops, "held_cards", held_cards)
    world.leader, world.plain = leader, plain
    return world


def _join(world, **kw):
    return asyncio.run(membership.join(SimpleNamespace(), "u-other", **kw))


def _leave(world, **kw):
    return asyncio.run(membership.leave(SimpleNamespace(), "u-other", **kw))


def test_join_binds_the_row_under_the_project_agent_and_resumes_the_same_uuid_with_swarm_flags_and_leave_reverses_it(members):
    row = _row_id(members, "other")
    members.live.add(row)
    with pytest.raises(membership.MembershipRefused) as warned:
        _join(members)
    assert warned.value.code == "restart_needed" and warned.value.extra["name"] == "other" and members.slept == []
    agent = _join(members, confirm_restart=True, specialty="search")
    assert (agent["session_row_id"], agent["rank"], agent["parent_id"], agent["specialty"]) == (row, "feature", members.leader["id"], "search")
    assert members.slept == ["u-other"]
    assert [w.agent_id for w in members.woke] == [agent["id"]]
    assert _db(members, lambda c: launch.swarm_launch_args(row, conn=c))[:2] == ["--agent", agent["slug"]]
    assert any(t.agent_id == members.leader["id"] and t.text.startswith("member_joined:") for t in members.told)

    members.live.add(row)
    with pytest.raises(membership.MembershipRefused, match="leaving the swarm restarts other"):
        _leave(members)
    assert _leave(members, confirm_restart=True) == {"session_uuid": "u-other", "agent_id": agent["id"], "released_cards": 0}
    assert _db(members, lambda c: launch.swarm_launch_args(row, conn=c)) == [] and members.plain == ["u-other"]
    parked = _db(members, lambda c: store.get_agent(c, agent["id"]))
    assert parked["state"] == "torn_down" and parked["session_row_id"] is None and parked["parked_row_id"] == row

    again = _join(members, confirm_restart=True)
    assert (again["id"], again["slug"], again["thread_key"], again["session_row_id"]) == (agent["id"], agent["slug"], agent["thread_key"], row)
    assert again["torn_down_at"] is None and again["parked_row_id"] is None


def test_a_project_with_no_agent_says_so_and_a_paired_computer_needs_an_update(world):
    with pytest.raises(membership.MembershipRefused) as none:
        asyncio.run(membership.join(SimpleNamespace(), "u-other", confirm_restart=True))
    assert none.value.code == "no_project_agent" and "the project agent has to be created first" in none.value.sentence
    _db(world, lambda c: c.execute("UPDATE sessions SET host_key = 'studio' WHERE session_uuid = 'u-other'"))
    with pytest.raises(membership.MembershipRefused, match="studio has to be updated before a session there can join the swarm"):
        asyncio.run(membership.join(SimpleNamespace(), "u-other", confirm_restart=True))


def test_a_new_session_of_a_project_whose_new_sessions_join_launches_as_a_member_with_no_restart(members, monkeypatch):
    from src.core.swarm import body

    folder = str(members.folder)
    assert asyncio.run(membership.new_session_member(folder, "fresh", None)) is None
    _db(members, lambda c: c.execute("UPDATE projects SET new_sessions_join_swarm = 1 WHERE id = ?", (members.orion["id"],)))
    assert asyncio.run(membership.new_session_member(folder, "sh", "shell")) is None

    plan = asyncio.run(membership.new_session_member(folder, "fresh", None))
    agent = plan["agent"]
    assert (agent["rank"], agent["parent_id"], agent["state"], agent["session_row_id"]) == ("feature", members.leader["id"], "waking", None)
    assert plan["argv"][:2] == ["--agent", agent["slug"]]

    _db(members, lambda c: c.execute("INSERT INTO sessions (session_uuid, project_id, working_dir, title, origin, lifecycle, agent_family, "
                                     "created_at, updated_at) VALUES ('u-fresh', ?, ?, 'fresh', 'created', 'running', 'claude', "
                                     "'2026-10-28T00:00:00Z', '2026-10-28T00:00:00Z')", (members.orion["id"], folder)))
    row = _row_id(members, "fresh")
    started = []

    async def finish_start(app_state, a, wake_id, ident):
        started.append((a["id"], wake_id, ident.row_id, ident.session_uuid))

    async def get_session_info(session_id):
        return SimpleNamespace(session_row_id=row, tmux_session="carnivore_fresh", session=SimpleNamespace(tmux_created_epoch=1))

    monkeypatch.setattr(body, "finish_start", finish_start)
    app_state = SimpleNamespace(session_manager=SimpleNamespace(get_session_info=get_session_info))
    asyncio.run(membership.bind_new_session(app_state, plan, "ses_fresh"))
    assert started == [(agent["id"], plan["wake_id"], row, "u-fresh")]
    assert _db(members, lambda c: launch.swarm_launch_args(row, conn=c))[:2] == ["--agent", agent["slug"]]
    assert any(t.agent_id == members.leader["id"] and t.text.startswith("member_joined: fresh") for t in members.told)

    dropped = asyncio.run(membership.new_session_member(folder, "doomed", "codex"))
    asyncio.run(membership.drop_new_session_member(dropped))
    gone = _db(members, lambda c: store.get_agent(c, dropped["agent"]["id"]))
    assert gone["torn_down_at"] is not None and gone["harness"] == "codex"


def test_a_join_whose_resume_fails_is_undone_and_the_session_wakes_plain(members, monkeypatch):
    from src.core.swarm import body

    row = _row_id(members, "other")
    members.live.add(row)

    async def failed_wake(app_state, agent_id, *a, **kw):
        _db(members, lambda c: c.execute("UPDATE swarm_agents SET state = 'asleep' WHERE id = ?", (agent_id,)))
        raise body.BodyError("the new body is not on the agent's own session row")

    async def plain_wake(app_state, session_uuid, **kw):
        members.plain.append(session_uuid)
        return SimpleNamespace(status="started")

    import src.api.session_sleep_routes as sleep_routes
    monkeypatch.setattr(body, "wake", failed_wake)
    monkeypatch.setattr(sleep_routes, "wake_by_uuid", plain_wake)
    with pytest.raises(membership.MembershipRefused, match="The join was undone and other is running again as a plain session"):
        _join(members, confirm_restart=True)
    assert members.plain == ["u-other"] and _db(members, lambda c: launch.swarm_launch_args(row, conn=c)) == []
    assert _db(members, lambda c: store.get_agent_by_session_row(c, row)) is None
