
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid

import pytest

from src.core.claude_resume_argv import list_process_table
from src.core.session_agent_infer_families import infer_pane_agent
from tests.socket_guard import TEST_SOCKET_NAME

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")


def _tmux(*args):
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()


def _start(name, command):
    _tmux("new-session", "-d", "-s", name, command)
    return int(_tmux("display-message", "-p", "-t", name, "#{pane_pid}"))


def _verdict(pane_pid):
    deadline = time.monotonic() + 20
    while True:
        verdict = infer_pane_agent(
            pane_pid=pane_pid, table=list_process_table(),
            pane_current_command=None, wrappers=[],
        )
        if verdict.named or time.monotonic() > deadline:
            return verdict
        time.sleep(0.1)


def test_a_real_codex_pane_is_named_and_a_real_shell_pane_is_not(tmp_path):
    fake = tmp_path / "codex"
    os.symlink(shutil.which("sleep"), fake)
    tag = uuid.uuid4().hex[:8]
    codex_name, shell_name = f"codexpane_{tag}", f"shellpane_{tag}"
    try:
        codex_pid = _start(codex_name, f"sh -c '{fake} 300; true'")
        shell_pid = _start(shell_name, "sh -c 'sleep 300; true'")
        codex = _verdict(codex_pid)
        assert codex.family == "codex"
        assert codex.inference.agent_type == "codex"
        shell = infer_pane_agent(
            pane_pid=shell_pid, table=list_process_table(),
            pane_current_command=None, wrappers=[],
        )
        assert shell.family is None
        assert shell.named is False
    finally:
        for name in (codex_name, shell_name):
            subprocess.run(
                ["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", name],
                capture_output=True, timeout=10,
            )
