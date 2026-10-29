from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_interrupt_routes as routes
from src.core.sessions.errors import SessionNotFound, SessionNotRunning


def _escape_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> HTTPException:
    info = SimpleNamespace(activity_status="idle", agent_family="claude", tmux_session="t",
                           subagents_running=0, background_open=False)

    async def get_session_info(_sid: str) -> SimpleNamespace:
        return info

    async def send_input(*_a: object, **_k: object) -> None:
        raise error

    manager = SimpleNamespace(get_session_info=get_session_info, send_input=send_input,
                              tmux_socket_name=lambda: "cloude")
    allowed = SimpleNamespace(allowed=True, code="", detail="")
    monkeypatch.setattr(routes.bw_interrupt, "check_facts", lambda **_k: allowed)
    monkeypatch.setattr(routes.bw_interrupt, "check_pane", lambda _tree: allowed)
    monkeypatch.setattr(routes.bw_tree, "measure", lambda *_a, **_k: SimpleNamespace(agent_pid=1))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.send_escape(manager, "ses_a"))
    return caught.value


def test_unknown_session_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _escape_with(monkeypatch, SessionNotFound("No active session")).status_code == 404


def test_stopped_session_is_the_409_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    caught = _escape_with(monkeypatch, SessionNotRunning("Session is not running"))
    assert caught.status_code == 409 and caught.detail["code"] == routes.REFUSE_NOT_RUNNING
