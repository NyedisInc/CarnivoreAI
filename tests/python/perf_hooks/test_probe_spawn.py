
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from src.core.attention_reader import AttentionEvidenceReader
from src.core.claude_resume_argv import list_process_table
from src.core.tmux_backend import TmuxBackend
from tests import socket_guard

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not getattr(subprocess, "_USE_POSIX_SPAWN", False),
    reason="the posix_spawn fast path is the macOS one being measured",
)


@pytest.fixture
def spawned(monkeypatch):
    seen = []
    real = os.posix_spawn

    def spy(path, argv, env, **kwargs):
        seen.append(list(argv))
        return real(path, argv, env, **kwargs)

    monkeypatch.setattr(os, "posix_spawn", spy)
    return seen


@pytest.fixture
def tmux_socket():
    if shutil.which("tmux") is None:
        pytest.skip("tmux not on PATH")
    name = socket_guard.derive_test_socket("probespawn")
    subprocess.run([shutil.which("tmux"), "-L", name, "new-session", "-d", "-s", "cloude_ps",
                    "sleep", "60"], check=True)
    yield name
    os.system(f"{shutil.which('tmux')} -L {name} kill-server >/dev/null 2>&1")


def test_listing_capture_and_process_table_are_posix_spawned(spawned, tmux_socket):
    probe = TmuxBackend.for_external(session_name="cloude_ps", on_output=None,
                                     working_dir=Path(tempfile.gettempdir()),
                                     socket_name=tmux_socket)
    listing = probe.list_pane_status_all()
    assert listing.ok and [row["name"] for row in listing.sessions] == ["cloude_ps"]
    assert AttentionEvidenceReader._capture(tmux_socket, "cloude_ps") is not None
    assert list_process_table()
    verbs = [argv[3] if "tmux" in argv[0] else os.path.basename(argv[0]) for argv in spawned]
    assert "list-panes" in verbs and "capture-pane" in verbs and "ps" in verbs
