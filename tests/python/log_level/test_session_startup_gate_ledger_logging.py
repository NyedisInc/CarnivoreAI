from __future__ import annotations

import logging

import pytest

from src.core import session_startup_gate_ledger as ledger
from src.core.tmux_backend import TmuxBackend


def test_capture_failure_logs_without_typeerror_at_debug(monkeypatch: pytest.MonkeyPatch) -> None:

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("tmux gone")

    monkeypatch.setattr(TmuxBackend, "for_external", staticmethod(boom))
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    try:
        assert ledger.capture_pane_tail(socket="cloude", name="cloude_a") is None
    finally:
        root.setLevel(previous)
