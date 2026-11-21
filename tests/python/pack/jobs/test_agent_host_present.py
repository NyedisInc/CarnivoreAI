
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.pack.jobs import agent_host
from src.core.pack.jobs.agent_host import AgentDeps
from src.core.tmux_transport import run as run_mod
from src.core.tmux_transport.run import ERROR_NOT_STARTED, ERROR_TIMEOUT, TmuxRunResult


def _present(monkeypatch: pytest.MonkeyPatch, result: TmuxRunResult, calls: List[Any]) -> bool:
    async def fake_run(socket: str, *args: str, timeout: float, **_kwargs: Any) -> TmuxRunResult:
        calls.append((socket, args, timeout))
        return result

    monkeypatch.setattr(run_mod, "tmux_run", fake_run)
    manager = SimpleNamespace(tmux_socket_name=lambda: "sock")
    present = AgentDeps.from_app(SimpleNamespace(state=SimpleNamespace(session_manager=manager))).present
    return asyncio.run(present("w1"))


@pytest.mark.parametrize("result", [TmuxRunResult(None, b"", b"", ERROR_TIMEOUT),
                                    TmuxRunResult(None, b"", b"", ERROR_NOT_STARTED)])
def test_a_has_session_that_timed_out_or_never_ran_reads_as_present(monkeypatch, result):
    calls: List[Any] = []
    assert _present(monkeypatch, result, calls) is True
    assert calls == [("sock", ("has-session", "-t", "=w1"), agent_host._PRESENT_WAIT_S)]


def test_only_tmuxs_not_there_reads_as_absent(monkeypatch):
    assert _present(monkeypatch, TmuxRunResult(1, b"", b""), []) is False
    assert _present(monkeypatch, TmuxRunResult(0, b"", b""), []) is True
