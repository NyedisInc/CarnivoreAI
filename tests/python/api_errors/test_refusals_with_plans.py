
from __future__ import annotations

import pytest
import structlog
from fastapi import HTTPException

from src.core.project_move.apply import MoveBusy
from src.core.session_move.apply import SessionMoveRefused

from .conftest import LEAK, assert_fixed


def test_session_move_refusal_keeps_the_plan_and_drops_the_text(driver, monkeypatch):
    from src.api import session_move_routes

    async def refuse(*_a, **_k):
        raise SessionMoveRefused(None, "target_busy", f"folder {LEAK} is in use")

    monkeypatch.setattr(session_move_routes, "plan_move", refuse)
    response, events = driver.call("POST", "/sessions/abc/move-folder", object(), json={"project_id": 1})
    detail = assert_fixed(response, 409, "target_busy", events)
    assert detail["plan"] is None


def test_project_move_busy_answers_a_code():
    from src.api import project_move_routes
    from contextlib import contextmanager

    @contextmanager
    def busy():
        raise MoveBusy(f"another move {LEAK}")
        yield  # pragma: no cover

    body = project_move_routes.ProjectMoveRequest(new_root="/x", move_folder=False, apply=True)
    original = project_move_routes.one_move_at_a_time
    project_move_routes.one_move_at_a_time = busy
    try:
        with structlog.testing.capture_logs() as events, pytest.raises(HTTPException) as caught:
            project_move_routes._plan_and_maybe_apply("p", body)
    finally:
        project_move_routes.one_move_at_a_time = original
    assert caught.value.detail["code"] == "move_busy" and LEAK not in str(caught.value.detail)
    assert any(LEAK in str(e.get("error")) for e in events)
