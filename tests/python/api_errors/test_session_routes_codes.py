
from __future__ import annotations

import pytest

from src.core.sessions.errors import TmuxError

from .conftest import LEAK


class _Boom:

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def create_session(self, **_kwargs):
        raise self.exc

    async def send_command(self, *_args, **_kwargs):
        raise self.exc


def _assert_fixed(response, status: int, code: str, events: list) -> None:
    assert response.status_code == status, response.text
    assert LEAK not in response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["detail"] and LEAK not in detail["detail"]
    failures = [e for e in events if e.get("event") == "api_request_failed" and e.get("code") == code]
    assert failures and LEAK in failures[0]["error"]


@pytest.mark.parametrize("exc, status, code", [
    (TmuxError(f"agent failed to launch: {LEAK}"), 502, "session_launch_failed"),
    (RuntimeError(f"unexpected {LEAK}"), 500, "session_create_failed"),
    (OSError(f"no such file {LEAK}"), 500, "session_create_failed"),
])
def test_create_session_failure_answers_a_code(driver, exc, status, code):
    response, events = driver.call("POST", "/sessions", _Boom(exc), json={})
    _assert_fixed(response, status, code, events)


def test_send_command_failure_answers_a_code(driver, monkeypatch):
    from src.api import session_input_routes

    async def _no_dialog(_request):
        return None

    monkeypatch.setattr(session_input_routes, "_refuse_open_dialog", _no_dialog)
    response, events = driver.call("POST", "/sessions/command", _Boom(OSError(f"tmux: {LEAK}")), json={"command": "ls"})
    _assert_fixed(response, 500, "session_input_failed", events)
