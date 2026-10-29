
from __future__ import annotations

from typing import Any, List

from src.core import session_adopt_dead_gate
from src.core.tmux_backend import TmuxBackend


def test_the_probe_targets_the_exact_session_name(monkeypatch):
    calls: List[tuple] = []

    def fake_run(self: TmuxBackend, *args: Any, **kwargs: Any):
        calls.append(args)
        return 0, b"1\n", b""

    monkeypatch.setattr(TmuxBackend, "_run_tmux_sync", fake_run)
    assert session_adopt_dead_gate.probe_session_pane_dead("carnivore_Shopify", socket="carnivore") is True
    target = calls[0][calls[0].index("-t") + 1]
    assert target == "=carnivore_Shopify:"
