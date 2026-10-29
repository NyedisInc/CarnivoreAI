
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from src.core import tmux_discovery as td


def _fake_bin(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _keyed(path, stage):
    key = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    dest = stage / key / "tmux"
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)
    return dest


def test_a_planted_staged_copy_is_never_a_candidate(tmp_path, monkeypatch):
    stage = tmp_path / "ud" / "tmux"
    planted = _fake_bin(stage / "0123456789abcdef" / "tmux")
    good = _keyed(_fake_bin(stage / "x" / "tmux"), stage)
    monkeypatch.setenv(td.STAGE_DIR_ENV, str(stage))
    assert td._staged_tmux_paths() == [str(good)]
    assert str(planted) not in td._staged_tmux_paths()


def test_staged_copies_are_candidates_so_a_server_born_from_an_old_bundle_still_matches(tmp_path, monkeypatch):
    stage = tmp_path / "ud" / "tmux"
    old = _fake_bin(stage / "x" / "tmux")
    old = _keyed(old, stage)
    new = _fake_bin(tmp_path / "bundle" / "bin" / "tmux")
    versions = {str(old): "tmux 3.7c", str(new): "tmux 3.8"}
    monkeypatch.setenv(td.BUNDLED_TMUX_ENV, str(new))
    monkeypatch.setenv(td.STAGE_DIR_ENV, str(stage))
    monkeypatch.setattr(td, "WELL_KNOWN_PATHS", ())
    monkeypatch.setattr(td, "resolve_tmux_path", lambda: None)
    monkeypatch.setattr(td, "binary_version", lambda p: versions.get(p))
    monkeypatch.setattr(td, "server_version", lambda p, sock: ("answered", "tmux 3.7c"))
    assert td.candidate_tmux_paths()[0] == str(new)
    assert str(old) in td.candidate_tmux_paths()
    assert td._select("sock") == str(old)


def test_pane_client_env_strips_the_payload_variables(monkeypatch):
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setenv("CARNIVORE_PAYLOAD_PYTHON", "/P/python3")
    monkeypatch.setenv(td.BUNDLED_TMUX_ENV, "/P/tmux")
    monkeypatch.setenv(td.STAGE_DIR_ENV, "/ud/tmux")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/C/pycache")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")
    env = td.pane_client_env()
    for name in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "CARNIVORE_PAYLOAD_PYTHON", td.BUNDLED_TMUX_ENV, td.STAGE_DIR_ENV):
        assert name not in env
    assert env["KEEP_ME"] == "yes"
    assert os.environ["PYTHONNOUSERSITE"] == "1", "the engine's own environment is not touched"


def test_new_session_uses_pane_client_env():
    src = Path(td.__file__).with_name("tmux_backend.py").read_text()
    assert "tmux_env = pane_client_env()" in src
    assert "tmux_env = os.environ.copy()" not in src
