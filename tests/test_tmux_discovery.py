
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from src.core import tmux_discovery
from src.core.tmux_discovery import (
    TMUX_ABSENT,
    TMUX_AVAILABLE,
    TMUX_UNDETERMINED,
    probe_tmux,
    reset_probe_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_probe_cache()
    yield
    reset_probe_cache()


def _make_fake_tmux(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_absent_when_nothing_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    probe = probe_tmux()
    assert probe.state == TMUX_ABSENT
    assert probe.path is None
    assert probe.detail


def test_available_requires_the_binary_to_actually_run(tmp_path, monkeypatch):
    fake = _make_fake_tmux(tmp_path / "tmux", 'echo "tmux 3.7c"')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    probe = probe_tmux()
    assert probe.state == TMUX_AVAILABLE
    assert probe.path == str(fake)
    assert probe.version == "tmux 3.7c"


def test_resolvable_but_unrunnable_is_UNDETERMINED_not_available(tmp_path, monkeypatch):
    _make_fake_tmux(tmp_path / "tmux", "exit 127")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    probe = probe_tmux()
    assert probe.state == TMUX_UNDETERMINED, (
        "a tmux that resolves but will not run was reported as "
        f"{probe.state!r}; the only two honest answers are UNDETERMINED or a "
        "measured failure, never 'available'"
    )
    assert probe.path is not None
    assert "127" in probe.detail or "exit" in probe.detail.lower()


def test_timeout_is_UNDETERMINED_not_absent(tmp_path, monkeypatch):
    _make_fake_tmux(tmp_path / "tmux", "/bin/sleep 30")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    monkeypatch.setattr(tmux_discovery, "PROBE_TIMEOUT_SECONDS", 1.0)
    probe = probe_tmux()
    assert probe.state == TMUX_UNDETERMINED
    assert "timed out" in probe.detail.lower()


def test_found_off_PATH_at_a_well_known_location(tmp_path, monkeypatch):
    brew = tmp_path / "brewbin"
    brew.mkdir()
    fake = _make_fake_tmux(brew / "tmux", 'echo "tmux 3.7c"')
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", (str(fake),))
    probe = probe_tmux()
    assert probe.state == TMUX_AVAILABLE
    assert probe.path == str(fake)


def test_well_known_list_covers_the_real_install_locations():
    joined = " ".join(tmux_discovery.WELL_KNOWN_PATHS)
    for expected in (
        "/opt/homebrew/bin/tmux",
        "/usr/local/bin/tmux",
        "/opt/local/bin/tmux",
        "/usr/bin/tmux",
    ):
        assert expected in joined, f"{expected} is not in WELL_KNOWN_PATHS"


def test_probe_is_cached(tmp_path, monkeypatch):
    _make_fake_tmux(tmp_path / "tmux", 'echo "tmux 3.7c"')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    calls = []
    real_run = subprocess.run

    def counting_run(*a, **kw):
        calls.append(a)
        return real_run(*a, **kw)

    monkeypatch.setattr(tmux_discovery.subprocess, "run", counting_run)
    probe_tmux()
    probe_tmux()
    probe_tmux()
    assert len(calls) == 1, f"probe executed tmux {len(calls)} times, expected 1"


def test_factory_refuses_to_claim_tmux_when_undetermined(tmp_path, monkeypatch):
    from src.core.session_backend import build_backend
    from src.utils.pty_session import PTYBackend

    _make_fake_tmux(tmp_path / "tmux", "exit 127")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(tmux_discovery, "WELL_KNOWN_PATHS", ())
    backend = build_backend(None, "ses_x", tmp_path, lambda _c: None)
    assert isinstance(backend, PTYBackend), (
        "the factory selected the tmux backend against a tmux that cannot "
        "run - a backend claim the app cannot honour"
    )
