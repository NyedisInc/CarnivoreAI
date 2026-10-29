
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.tmux_stderr import listing_env
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def test_accented_name_and_path_come_back_exact_under_lc_all_c(tmp_path: Path) -> None:
    folder = tmp_path / "dossier_été"
    folder.mkdir()
    name = "café-naïve"
    socket = derive_test_socket("utf8_names")
    base = ["tmux", "-L", socket, "-f", "/dev/null"]
    made = subprocess.run([*base, "new-session", "-d", "-s", name, "-c", str(folder), "-x", "80", "-y", "24", "cat"],
                          capture_output=True, check=False)
    assert made.returncode == 0, made.stderr
    try:
        assert listing_env()["LC_ALL"] == "C"
        done = subprocess.run([*base, "list-panes", "-a", "-F", "#{session_name}\t#{pane_current_path}"],
                              capture_output=True, env=listing_env(), check=False)
        row = done.stdout.decode("utf-8").rstrip("\n").split("\t")
        assert row[0] == name
        assert Path(row[1]).name == folder.name
    finally:
        subprocess.run([*base, "kill-server"], check=False)
