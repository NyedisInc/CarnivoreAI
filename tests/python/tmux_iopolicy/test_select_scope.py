
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sel_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sel_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import tmux_discovery
from src.core.tmux_control import reader as reader_mod
from src.core.tmux_control.reader import ControlReader, close_readers, control_server_version
from tests.socket_guard import derive_test_socket


def test_selecting_a_binary_for_an_unrelated_socket_starts_no_reader(monkeypatch):
    if shutil.which("tmux") is None:
        pytest.skip("real tmux binary not available")
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("selscope")
    tmux = lambda *a: subprocess.run(["tmux", "-L", name, *a], capture_output=True, check=False, timeout=15)  # noqa: E731
    assert tmux("new-session", "-d", "-s", "jobs", "cat").returncode == 0
    try:
        tmux_discovery.reset_probe_cache()
        assert tmux_discovery.select_tmux(name)
        time.sleep(1.5)
        assert name not in reader_mod._READERS
        assert "_carnivore_ctl" not in tmux("list-sessions", "-F", "#{session_name}").stdout.decode()
    finally:
        close_readers()
        tmux_discovery.reset_probe_cache()
        tmux("kill-server")


def _fake_tmux(path: Path, version: str) -> None:
    tmp = path.with_suffix(".new")
    tmp.write_text(f"#!/bin/sh\necho 'tmux {version}'\n")
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR)
    os.replace(tmp, path)


def test_an_upgraded_binary_is_caught_as_skew_while_the_old_client_answers(monkeypatch, tmp_path):
    fake = tmp_path / "tmux"
    _fake_tmux(fake, "3.8")
    tmux_discovery.reset_probe_cache()
    monkeypatch.setattr(tmux_discovery, "candidate_tmux_paths", lambda: [str(fake)])
    monkeypatch.setattr(tmux_discovery, "_live_version_source", lambda socket: "3.8")
    assert tmux_discovery.select_tmux("skewsock") == str(fake)
    _fake_tmux(fake, "3.9")
    tmux_discovery._selection_cache.clear()
    with pytest.raises(tmux_discovery.TmuxVersionSkewError):
        tmux_discovery.select_tmux("skewsock")
    tmux_discovery.reset_probe_cache()


def test_the_lock_holder_never_waits_on_its_own_lock(monkeypatch):
    reader = ControlReader("holdersock")
    reader_mod._READERS["holdersock"] = reader
    seen = []

    def argv(socket):
        started = time.monotonic()
        seen.append((control_server_version(socket), time.monotonic() - started))
        return ["true"]

    monkeypatch.setattr(reader_mod, "tmux_argv_prefix", argv)
    try:
        reader.close()
    finally:
        reader_mod._READERS.pop("holdersock", None)
    assert seen and seen[0][0] is None and seen[0][1] < 0.1, seen
