from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import List

import pytest

from src.core.session_manager import SessionManager
from tests.socket_guard import TEST_SOCKET_NAME


class _Proc:
    returncode = 1

    async def communicate(self):
        return b"", b""


@pytest.mark.asyncio
async def test_external_cwd_probe_runs_on_the_probed_socket(monkeypatch) -> None:
    mgr = SessionManager()
    mgr._probe_health.record_socket(TEST_SOCKET_NAME)
    argvs: List[tuple] = []

    async def fake_exec(*argv, **_kw):
        argvs.append(argv)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await mgr._resolve_external_cwd("some_session") == Path.home()
    assert argvs and TEST_SOCKET_NAME in argvs[0]
    assert argvs[0][argvs[0].index("-L") + 1] == TEST_SOCKET_NAME


def test_no_action_path_reads_the_config_socket_directly() -> None:
    source = inspect.getsource(SessionManager)
    assert "load_auth_config().session.tmux_socket_name" not in source


def test_output_handler_is_annotated_as_the_synchronous_callable_it_is() -> None:
    from typing import Callable

    assert inspect.signature(SessionManager._make_output_handler).return_annotation == Callable[[bytes], None]


def test_spawn_env_without_a_readable_port_logs_instead_of_vanishing(monkeypatch) -> None:
    import src.core.session_manager as sm

    class _NoPort:
        @property
        def port(self) -> int:
            raise AttributeError("port")

    seen: list = []
    mgr = SessionManager()
    monkeypatch.setattr(sm, "settings", _NoPort())
    monkeypatch.setattr(sm.logger, "warning", lambda event, **kw: seen.append(event))
    assert mgr.get_env_for_spawn("ses_x") == {}
    assert seen == ["spawn_env_port_unreadable"]
