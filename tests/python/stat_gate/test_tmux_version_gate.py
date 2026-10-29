from __future__ import annotations

import os

import pytest

from src.core import tmux_discovery as td


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))
    sock_dir = tmp_path / ("tmux-%d" % os.getuid())
    sock_dir.mkdir()
    sock = sock_dir / "perfsock"
    sock.write_text("a")
    calls = []
    monkeypatch.setattr(td, "candidate_tmux_paths", lambda: ["/fake/tmux"])
    monkeypatch.setattr(td, "binary_version", lambda path: "3.6a")
    monkeypatch.setattr(td, "server_version", lambda path, name: calls.append(name) or ("answered", "3.6a"))
    td.reset_probe_cache()
    yield sock, calls
    td.reset_probe_cache()


def _expire(monkeypatch, step):
    base = td.time.monotonic()
    monkeypatch.setattr(td.time, "monotonic", lambda: base + step)


def test_probe_skipped_while_socket_unchanged_and_redone_after_restart(fake, monkeypatch):
    sock, calls = fake
    assert td.select_tmux("perfsock") == "/fake/tmux"
    for step in (6, 12, 40, 200):
        _expire(monkeypatch, step)
        td.select_tmux("perfsock")
    assert len(calls) == 1
    sock.unlink()
    sock.write_text("b")
    os.utime(sock, ns=(1, 1))
    _expire(monkeypatch, 250)
    td.select_tmux("perfsock")
    assert len(calls) == 2


def test_probe_redone_after_stable_max_age(fake, monkeypatch):
    _, calls = fake
    td.select_tmux("perfsock")
    _expire(monkeypatch, td.SELECTION_STABLE_MAX_SECONDS + 1)
    td.select_tmux("perfsock")
    assert len(calls) == 2


def test_no_server_is_never_remembered(fake, monkeypatch):
    _, calls = fake
    monkeypatch.setattr(td, "server_version", lambda path, name: calls.append(name) or ("no_server", None))
    td.select_tmux("perfsock")
    _expire(monkeypatch, 6)
    td.select_tmux("perfsock")
    assert len(calls) == 2
