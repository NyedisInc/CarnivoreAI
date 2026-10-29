from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "session_journal.py"


def _load_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("session_journal", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sj():
    return _load_module()


def test_venv_python_found_beside_script(sj, tmp_path, monkeypatch):
    fake_server = tmp_path / "server"
    fake_venv_python = fake_server / "venv" / "bin" / "python3"
    fake_venv_python.parent.mkdir(parents=True)
    fake_venv_python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        sj, "__file__", str(fake_server / "scripts" / "session_journal.py")
    )
    assert sj._venv_python() == fake_venv_python


def test_venv_python_none_when_absent(sj, tmp_path, monkeypatch):
    fake_server = tmp_path / "server"
    (fake_server / "scripts").mkdir(parents=True)
    monkeypatch.setattr(
        sj, "__file__", str(fake_server / "scripts" / "session_journal.py")
    )
    assert sj._venv_python() is None


def test_default_state_dir_prefers_current_name(sj, tmp_path, monkeypatch):
    app_support = tmp_path / "Library" / "Application Support"
    (app_support / "Carnivore").mkdir(parents=True)
    (app_support / "CloudeCode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert sj._default_state_dir() == app_support / "Carnivore"


def test_default_state_dir_falls_back_to_legacy_name(sj, tmp_path, monkeypatch):
    app_support = tmp_path / "Library" / "Application Support"
    (app_support / "CloudeCode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert sj._default_state_dir() == app_support / "CloudeCode"


def test_default_state_dir_none_when_nothing_exists(sj, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert sj._default_state_dir() is None


def test_resolve_state_dir_env_respects_explicit_value(sj, tmp_path, monkeypatch):
    explicit = tmp_path / "explicit-state"
    explicit.mkdir()
    guessable = tmp_path / "Library" / "Application Support" / "Carnivore"
    guessable.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(explicit))
    sj._resolve_state_dir_env()
    assert sj.os.environ["CLOUDE_STATE_DIR"] == str(explicit)


def test_resolve_state_dir_env_uses_guess_when_unset(sj, tmp_path, monkeypatch):
    guessable = tmp_path / "Library" / "Application Support" / "Carnivore"
    guessable.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    sj._resolve_state_dir_env()
    assert sj.os.environ["CLOUDE_STATE_DIR"] == str(guessable)


def test_resolve_state_dir_env_exits_when_nothing_to_guess(sj, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    with pytest.raises(SystemExit):
        sj._resolve_state_dir_env()
