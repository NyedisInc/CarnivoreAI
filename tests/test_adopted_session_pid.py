
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pid_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pid_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path, port: int = 5001):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.port = port

    def load_auth_config(self):
        raise FileNotFoundError("no config.json in this stub")

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


def _bare_manager(monkeypatch, tmp_path: Path, port: int = 5001) -> SessionManager:
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
        port=port,
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _register_adopted_session(
    mgr: SessionManager, sid: str, tmux_name: str, working_dir: Path
) -> Session:
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(working_dir),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.backends[sid] = _FakeBackend(tmux_name)
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


@pytest.mark.asyncio
async def test_adopted_session_reports_real_pid_from_bulk_status_map(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_adopted_session(mgr, "adopted:proj", "cloude_proj", tmp_path)

    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {"cloude_proj": {"status": "idle", "pid": 50694}},
    )

    info = await mgr.get_session_info(session_id="adopted:proj")
    assert info is not None
    assert info.session.pty_pid == 50694


@pytest.mark.asyncio
async def test_pid_refreshes_rather_than_freezing_at_adopt_time(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_adopted_session(mgr, "adopted:proj", "cloude_proj", tmp_path)

    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {"cloude_proj": {"status": "running", "pid": 111}},
    )
    first = await mgr.get_session_info(session_id="adopted:proj")
    assert first.session.pty_pid == 111

    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {"cloude_proj": {"status": "running", "pid": 222}},
    )
    second = await mgr.get_session_info(session_id="adopted:proj")
    assert second.session.pty_pid == 222

    assert mgr._registry.sessions["adopted:proj"].pty_pid is None


@pytest.mark.asyncio
async def test_falls_back_to_backend_pid_when_status_map_has_no_row(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_adopted_session(mgr, "adopted:proj", "cloude_proj", tmp_path)
    mgr._registry.backends["adopted:proj"].pid = 333  # type: ignore[attr-defined]

    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {})

    info = await mgr.get_session_info(session_id="adopted:proj")
    assert info.session.pty_pid == 333


def test_stopped_placeholder_session_still_reports_none(tmp_path):
    placeholder = Session(
        id="pinned:some-project",
        pty_pid=None,
        working_dir=str(tmp_path),
        status=SessionStatus.STOPPED,
    )
    assert placeholder.pty_pid is None
