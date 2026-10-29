from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_oss_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_oss_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config import settings  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.models import Session  # noqa: E402


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch) -> Tuple[Path, Path]:
    log_dir = tmp_path / "logs"
    state_dir = tmp_path / "state"
    log_dir.mkdir()
    state_dir.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    return log_dir, state_dir


def _write_metadata(state_dir: Path, session_id: str, name: str, owned: list) -> Path:
    payload = Session(
        id=session_id,
        working_dir="/tmp/wd",
        tmux_session=name,
        agent_type="claude",
    ).model_dump()
    payload["owned_tmux_sessions"] = sorted(owned)
    path = state_dir / "session_metadata.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def test_clearing_a_stale_pointer_keeps_the_owned_set(dirs):
    _log_dir, state_dir = dirs
    owned = ["cloude_alpha", "cloude_beta", "cloude_gone"]
    _write_metadata(state_dir, "sess-gone", "cloude_gone", owned)

    mgr = SessionManager()
    mgr._load_session_metadata()
    assert mgr._owned.names == set(owned)

    mgr._clear_stale_metadata("sess-gone")

    reloaded = SessionManager()
    reloaded._load_session_metadata()

    assert reloaded._owned.names >= {"cloude_alpha", "cloude_beta"}, (
        "clearing ONE session's stale pointer destroyed the ownership "
        "record for every other session; every launcher-created session "
        "reads EXTERNAL from here on"
    )


def test_cleared_metadata_no_longer_rehydrates_the_dead_session(dirs):
    _log_dir, state_dir = dirs
    _write_metadata(
        state_dir, "sess-gone", "cloude_gone", ["cloude_alpha", "cloude_gone"]
    )

    mgr = SessionManager()
    mgr._load_session_metadata()
    mgr._clear_stale_metadata("sess-gone")

    reloaded = SessionManager()
    reloaded._load_session_metadata()

    assert reloaded._registry.current_session() is None, (
        "the dead session was rehydrated anyway"
    )
