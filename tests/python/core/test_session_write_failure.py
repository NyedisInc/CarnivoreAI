from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_input_routes
from src.core.session_manager import SessionManager
from src.models import CommandRequest


class _BrokenBackend:

    async def write(self, _data: bytes) -> None:
        raise BrokenPipeError("pane closed")


def _manager_with_broken_pane() -> SimpleNamespace:
    return SimpleNamespace(_require_running=lambda _sid: ("ses_a", SimpleNamespace(last_activity=None), _BrokenBackend()))


@pytest.mark.parametrize("method,arg", [("send_command", "ls"), ("send_input", "x")])
def test_manager_write_failure_is_not_a_plain_value_error(method: str, arg: str) -> None:
    from src.core.sessions.errors import SessionInputFailed

    fake = _manager_with_broken_pane()
    with pytest.raises(SessionInputFailed):
        asyncio.run(getattr(SessionManager, method)(fake, arg))


def test_send_command_route_answers_502_not_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.sessions.errors import SessionInputFailed

    async def checked(_request: object) -> str:
        return "ses_a"

    async def boom(*_a: object, **_k: object) -> None:
        raise SessionInputFailed("Failed to send command: pane closed")

    monkeypatch.setattr(session_input_routes, "_refuse_open_dialog", checked)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(send_command=boom))))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(session_input_routes.send_command(request, CommandRequest(command="ls")))
    assert caught.value.status_code == 502


def _command_through_route(monkeypatch: pytest.MonkeyPatch, error: Exception) -> HTTPException:

    async def checked(_request: object) -> str:
        return "ses_a"

    async def boom(*_a: object, **_k: object) -> None:
        raise error

    monkeypatch.setattr(session_input_routes, "_refuse_open_dialog", checked)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(send_command=boom))))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(session_input_routes.send_command(request, CommandRequest(command="ls")))
    return caught.value


def test_command_route_answers_404_for_an_unknown_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.sessions.errors import SessionNotFound

    assert _command_through_route(monkeypatch, SessionNotFound("No active session")).status_code == 404


def test_command_route_answers_409_for_a_stopped_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.sessions.errors import SessionNotRunning

    assert _command_through_route(monkeypatch, SessionNotRunning("Session is not running")).status_code == 409


class _GoodBackend:

    async def write(self, _data: bytes) -> None:
        return None


def test_bookkeeping_failure_after_a_good_write_is_not_a_write_failure() -> None:
    from src.core.sessions.errors import SessionInputFailed

    def boom(_sid: str) -> None:
        raise KeyError("registry row vanished")

    fake = SimpleNamespace(
        _require_running=lambda _sid: ("ses_a", SimpleNamespace(last_activity=None), _GoodBackend()),
        _registry=SimpleNamespace(count_command=boom),
        _save_session_metadata=lambda _s: None,
    )
    with pytest.raises(KeyError):
        asyncio.run(SessionManager.send_command(fake, "ls"))
    assert not issubclass(KeyError, SessionInputFailed)
