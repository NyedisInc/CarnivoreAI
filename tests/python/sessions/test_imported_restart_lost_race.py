
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api import imported_restart_routes as routes
from src.core.session_respawn import RESPAWN_AGENT
from src.core.sessions.reuse_guard import ReuseRowTakenError


@pytest.mark.asyncio
async def test_a_lost_race_answers_refused_naming_the_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_hold(_uuid):
        return None

    monkeypatch.setattr("src.api.swarm_switch_routes.refuse_held_body", no_hold)
    monkeypatch.setattr(routes, "_read_row", lambda _uuid: object())
    monkeypatch.setattr(routes, "_require_imported", lambda _state, _uuid: {"model": None, "working_dir": "/x"})
    monkeypatch.setattr(routes, "imported_extra_args", lambda *_a, **_k: [])
    monkeypatch.setattr(routes, "resume_directory", lambda *_a, **_k: "/x")
    monkeypatch.setattr(routes, "validate_agent_choice", lambda *_a, **_k: SimpleNamespace(verdict="ok", command="c", detail=None))
    plan = SimpleNamespace(kind=RESPAWN_AGENT, actionable=True, conversation="resumed", command="c", working_dir="/x",
                           label="l", reuse_session_id=7, detail=None)
    monkeypatch.setattr(routes, "plan_imported_restart", lambda *_a, **_k: plan)
    monkeypatch.setattr(routes.account_launch, "launch_for_session", lambda *_a, **_k: {"extra_env": {}, "account_id": None})

    async def lost(**_kwargs):
        raise ReuseRowTakenError(7, "carnivore_adopted")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(create_session=lost))))
    answer = await routes._imported_restart(request, routes.ImportedRestartRequest(session_uuid="row-7", agent_type="claude"))
    assert answer.status == "refused"
    assert "carnivore_adopted" in answer.detail and "the new copy was stopped" in answer.detail
