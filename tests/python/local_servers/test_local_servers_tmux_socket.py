
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from src.core.auto_sleep import port_owner

ROOT = Path(__file__).resolve().parents[3]


def test_the_pane_pid_query_is_addressed_to_the_given_socket(monkeypatch) -> None:
    seen: List[List[str]] = []

    def runner(argv, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="x\t41\n", stderr="")

    monkeypatch.setattr("src.core.tmux_transport.run.tmux_argv_prefix", lambda socket: ["tmuxbin", "-L", socket])
    assert port_owner.pane_pid_sessions("private_sock", runner=runner) == {41: "x"}
    assert seen[0][:3] == ["tmuxbin", "-L", "private_sock"]


def test_the_tracker_and_owner_modules_hold_no_bare_tmux_argv() -> None:
    for name in ("src/core/local_servers.py", "src/core/auto_sleep/port_owner.py"):
        text = (ROOT / name).read_text()
        assert '["tmux"' not in text and "['tmux'" not in text, name
