
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.python.swarm.test_swarm_membership import _join, members  # noqa: F401
from tests.python.swarm.test_swarm_project_promote import _db, _row_id, env, world  # noqa: F401
from src.core.swarm import body, plain_wake, store


def _joined_asleep(members):
    row = _row_id(members, "other")
    agent = _join(members, confirm_restart=True)
    _db(members, lambda c: c.execute("UPDATE sessions SET claude_session_uuid = 'conv-own' WHERE id = ?", (row,)))
    return _db(members, lambda c: store.get_agent(c, agent["id"])), row


def test_an_auto_wake_of_a_joined_member_with_no_open_work_resumes_its_own_conversation(members):
    agent, _row = _joined_asleep(members)
    assert agent["state"] == "asleep" and store.is_member(agent)
    assert _db(members, lambda c: body._has_open_work(c, agent)) is False
    assert _db(members, lambda c: body._resolve_mode(c, agent, "auto")) == "resume"
    assert _db(members, lambda c: body._resolve_mode(c, agent, "fresh")) == "fresh"
    spawned = {**agent, "job": "refactor the parser"}
    assert _db(members, lambda c: body._resolve_mode(c, spawned, "auto")) == "fresh"


def test_a_plain_session_wake_of_a_bound_body_marks_the_agent_awake_on_an_owner_wake(members, monkeypatch):
    agent, row = _joined_asleep(members)
    finished = []

    async def finish_start(app_state, a, wake_id, ident):
        finished.append((a["id"], wake_id, ident.row_id, ident.session_uuid, ident.tmux_name))
        _db(members, lambda c: store.cas_state(c, a["id"], "waking", "awake"))

    async def get_session_info(session_id):
        return SimpleNamespace(session_row_id=row, tmux_session="carnivore_other", session=SimpleNamespace(tmux_created_epoch=7))

    monkeypatch.setattr(body, "finish_start", finish_start)
    app_state = SimpleNamespace(session_manager=SimpleNamespace(get_session_info=get_session_info))
    wake_id = asyncio.run(plain_wake.adopt(app_state, "u-other", "ses_other", False))
    assert wake_id is not None and finished == [(agent["id"], wake_id, row, "u-other", "carnivore_other")]
    assert _db(members, lambda c: store.get_agent(c, agent["id"]))["state"] == "awake"
    wake = _db(members, lambda c: store.get_open_wake(c, agent["id"]))
    assert (wake["id"], wake["mode"], wake["authority"], wake["reason"]) == (wake_id, "resume", "owner", "manual")
    assert asyncio.run(plain_wake.adopt(app_state, "u-other", "ses_other", False)) is None
