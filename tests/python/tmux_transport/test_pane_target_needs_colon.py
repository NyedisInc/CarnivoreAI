
from __future__ import annotations

import re
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

from tests.socket_guard import derive_test_socket

SRC = Path(__file__).resolve().parents[3] / "src"
PANE_COMMANDS = ("capture-pane", "pipe-pane", "select-pane", "resize-pane", "respawn-pane",
                 "display-message", "send-keys", "paste-buffer", "clear-history")
BARE_EXACT = re.compile(r'f"=\{[^}]+\}"|"=" *\+')
LOOKBACK = 4


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", *args], capture_output=True, text=True,
                          check=False)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")
def test_pane_commands_resolve_the_colon_form_and_session_commands_take_both() -> None:
    socket = derive_test_socket("pane_target_colon")
    try:
        assert _tmux(socket, "new-session", "-d", "-s", "ab", "sleep 60").returncode == 0
        assert _tmux(socket, "pipe-pane", "-t", "=ab:").returncode == 0
        assert _tmux(socket, "capture-pane", "-p", "-t", "=ab:").returncode == 0
        for command in ("has-session", "show-environment"):
            assert _tmux(socket, command, "-t", "=ab").returncode == 0
    finally:
        _tmux(socket, "kill-server")


def _bare_pane_targets() -> list[str]:
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            if not BARE_EXACT.search(line):
                continue
            window = "\n".join(lines[max(0, number - LOOKBACK):number + 1])
            if any(f'"{command}"' in window for command in PANE_COMMANDS):
                hits.append(f"{path.relative_to(SRC.parent)}:{number + 1}")
    return hits


def test_no_pane_command_in_src_targets_a_bare_exact_session_name() -> None:
    assert _bare_pane_targets() == []


def test_the_scan_goes_red_on_a_bare_pane_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "bad.py").write_text('run("capture-pane", "-p", "-t", f"={name}")\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SRC", root)
    assert _bare_pane_targets() != []
