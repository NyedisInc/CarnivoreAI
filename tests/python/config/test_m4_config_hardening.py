
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import structlog

from src.config import startup_error_log, state_paths
from src.config.settings import Settings
from src.core import config_writer


def test_failed_legacy_migration_is_attempted_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    support = tmp_path / "Library" / "Application Support"
    legacy = support / state_paths.product_identity.LEGACY_STATE_DIR_NAMES[0]
    legacy.mkdir(parents=True)
    state_paths._legacy_migration_outcomes.clear()
    attempts: list[int] = []

    def failing(legacy_path: Path, new_path: Path) -> Path:
        attempts.append(1)
        return legacy_path

    monkeypatch.setattr(state_paths, "_migrate_legacy_state_dir_once", failing)
    for _ in range(5):
        assert state_paths.state_dir(None) == legacy
    assert attempts == [1]
    state_paths._legacy_migration_outcomes.clear()


def test_any_config_writer_commit_clears_the_auth_cache(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_version": 1}))
    s = Settings(auth_config_file=str(path), totp_secret="x" * 16, jwt_secret="y" * 32)
    config_writer.on_commit(s.on_config_commit)
    sentinel = object()
    s._auth_config_cache = sentinel  # type: ignore[assignment]

    config_writer.commit(path, lambda doc: {**doc, "ui": {}})
    assert s._auth_config_cache is None

    s._auth_config_cache = sentinel  # type: ignore[assignment]
    other = tmp_path / "other.json"
    other.write_text("{}")
    config_writer.commit(other, lambda doc: {"a": 1})
    assert s._auth_config_cache is sentinel
    config_writer._listeners.remove(s.on_config_commit)


def test_get_agent_command_logs_when_config_is_unreadable(tmp_path: Path) -> None:
    s = Settings(auth_config_file=str(tmp_path / "missing.json"), totp_secret="x" * 16, jwt_secret="y" * 32)
    with structlog.testing.capture_logs() as logs:
        s.get_agent_command("claude")
    assert any(e["event"] == "agent_command_config_unavailable" for e in logs)


def test_startup_banner_lives_in_a_private_per_user_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "Logs" / "Carnivore"
    monkeypatch.setattr(startup_error_log, "STARTUP_ERROR_DIR", log_dir)
    written = startup_error_log.write_startup_error("boom")
    assert written == log_dir / startup_error_log.STARTUP_ERROR_NAME
    assert stat.S_IMODE(os.stat(written).st_mode) == 0o600
    assert not str(startup_error_log.STARTUP_ERROR_FILE).startswith("/tmp")

    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    written.unlink()
    written.symlink_to(victim)
    startup_error_log.write_startup_error("boom2")
    assert victim.read_text() == "keep"
