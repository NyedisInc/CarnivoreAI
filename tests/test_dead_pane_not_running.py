
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dpr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dpr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.core.session_status import (
    LIVENESS_GONE,
    LIVENESS_LIVE,
    LIVENESS_UNKNOWN,
    STATUS_DEAD,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    resolve_listing_liveness,
)
from src.models import Session, SessionStatus


class _StubSettings:
    def __init__(self, pin_path: Path, log_dir: Path, port: int = 5001):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.port = port

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

    def __init__(self, tmux_session: str, exists: bool = True):
        self.tmux_session = tmux_session
        self._exists = exists
        self.pid = 4321

    def is_alive(self) -> bool:
        return self._exists


@pytest.fixture()
def mgr(monkeypatch, tmp_path):
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json", log_dir=tmp_path / "logs"
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    m = SessionManager()
    monkeypatch.setattr(m, "_persist_settled_activity_state", lambda *a, **k: None)
    return m


def _register(m: SessionManager, sid: str, tmux_name: str, wd: Path, exists=True):
    m._registry.sessions[sid] = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(wd),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    m._registry.backends[sid] = _FakeBackend(tmux_name, exists=exists)
    m._registry.subscribers.setdefault(sid, [])


def _row(name: str, status: str):
    return {
        name: {
            "name": name,
            "status": status,
            "pid": 4321,
            "pane_dead": "1" if status == STATUS_DEAD else "0",
            "pane_current_command": "zsh",
            "created_at_epoch": 1755000000,
        }
    }




def test_resolver_dead_pane_is_gone():
    assert resolve_listing_liveness(True, STATUS_DEAD) == LIVENESS_GONE


def test_resolver_live_pane_is_live():
    assert resolve_listing_liveness(True, STATUS_IDLE) == LIVENESS_LIVE
    assert resolve_listing_liveness(True, STATUS_RUNNING) == LIVENESS_LIVE


def test_resolver_unmeasurable_pane_is_its_own_outcome():
    verdict = resolve_listing_liveness(True, STATUS_UNKNOWN)
    assert verdict == LIVENESS_UNKNOWN
    assert verdict != LIVENESS_LIVE
    assert verdict != LIVENESS_GONE


def test_resolver_unknown_existence_is_unknown():
    assert resolve_listing_liveness(None, STATUS_IDLE) == LIVENESS_UNKNOWN


def test_resolver_pty_backend_has_no_pane_and_existence_is_liveness():
    assert resolve_listing_liveness(True, None) == LIVENESS_LIVE
    assert resolve_listing_liveness(False, None) == LIVENESS_GONE




def test_dead_pane_session_is_not_listed_as_running(mgr, tmp_path):
    _register(mgr, "husk", "cloude_ses_husk", tmp_path)
    info = mgr._session_info_for(
        "husk", status_map=_row("cloude_ses_husk", STATUS_DEAD)
    )
    assert info is None, "a dead husk must not appear in the running list"


def test_live_pane_session_is_still_listed_as_running(mgr, tmp_path):
    _register(mgr, "real", "cloude_ses_real", tmp_path)
    info = mgr._session_info_for(
        "real", status_map=_row("cloude_ses_real", STATUS_IDLE)
    )
    assert info is not None, "a session with a live pane must stay listed"
    assert info.tmux_session == "cloude_ses_real"


def test_missing_tmux_session_is_still_dropped(mgr, tmp_path):
    _register(mgr, "gone", "cloude_ses_gone", tmp_path, exists=False)
    assert mgr._session_info_for("gone", status_map={}) is None


def test_unmeasurable_pane_renders_as_unknown_not_running_and_not_ended(
    mgr, tmp_path
):
    _register(mgr, "murky", "cloude_ses_murky", tmp_path)
    info = mgr._session_info_for("murky", status_map={})
    assert info is not None, "could-not-determine must not render as ended"
    assert info.activity_status == STATUS_UNKNOWN, (
        "could-not-determine must not render as running"
    )




def test_persisted_idle_cannot_overwrite_a_measured_dead(mgr, tmp_path, monkeypatch):
    _register(mgr, "husk", "cloude_ses_husk", tmp_path)

    info = mgr._session_info_for(
        "husk", status_map=_row("cloude_ses_husk", STATUS_DEAD)
    )
    assert info is None, (
        "a persisted idle must not resurrect a pane tmux measured as dead"
    )


def test_a_persisted_state_no_longer_paints_a_live_pane_at_all(
    mgr, tmp_path, monkeypatch
):
    _register(mgr, "real", "cloude_ses_real", tmp_path)

    info = mgr._session_info_for(
        "real", status_map=_row("cloude_ses_real", STATUS_IDLE)
    )
    assert info is not None
    assert info.activity_status == STATUS_UNKNOWN
    assert info.activity_status != "working"


def test_persisted_state_does_not_manufacture_a_status_when_unmeasurable(
    mgr, tmp_path, monkeypatch
):
    _register(mgr, "murky", "cloude_ses_murky", tmp_path)

    info = mgr._session_info_for("murky", status_map={})
    assert info is not None
    assert info.activity_status == STATUS_UNKNOWN
