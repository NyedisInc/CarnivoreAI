from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pvd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pvd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import session_permission_verify_apply as verify_apply
from tests.attention_claim_helpers import open_claims
from src.core.session_activity import EVENT_PERMISSION_REQUEST, SessionActivityTracker
from src.core.session_permission_verify import (
    PERMISSION_CLEARED_PANE_DEAD,
    PERMISSION_NOT_CHECKED,
)


class _FakeManager:

    def __init__(self, tracker: SessionActivityTracker):
        self._activity_tracker = tracker


class _FakeBackend:
    pass




def test_measured_dead_pane_clears_the_open_permission_flag():
    tracker = SessionActivityTracker()
    t0 = datetime(2026, 9, 10, 12, 0, 0)
    open_claims(tracker, "ses_1", permission=True, at=t0)
    assert tracker.permission_open_since("ses_1") == t0, "sanity: claim is open"

    manager = _FakeManager(tracker)
    verdict = verify_apply.verify_open_permission(
        manager,
        session_id="ses_1",
        backend=_FakeBackend(),
        tmux_name="cloude_ses_1",
        pane_alive=False,
        now=t0 + timedelta(seconds=5),
    )

    assert verdict == PERMISSION_CLEARED_PANE_DEAD
    assert tracker.permission_open_since("ses_1") is None, (
        "the flag must actually be cleared, not merely reported cleared"
    )


def test_measured_dead_pane_with_no_open_claim_is_a_no_op():
    tracker = SessionActivityTracker()
    manager = _FakeManager(tracker)

    verdict = verify_apply.verify_open_permission(
        manager,
        session_id="ses_2",
        backend=_FakeBackend(),
        tmux_name="cloude_ses_2",
        pane_alive=False,
    )

    assert verdict == PERMISSION_NOT_CHECKED




def test_unmeasured_pane_liveness_keeps_the_open_permission_flag():
    tracker = SessionActivityTracker()
    t0 = datetime(2026, 9, 10, 12, 0, 0)
    open_claims(tracker, "ses_3", permission=True, at=t0)

    manager = _FakeManager(tracker)
    verdict = verify_apply.verify_open_permission(
        manager,
        session_id="ses_3",
        backend=_FakeBackend(),
        tmux_name="cloude_ses_3",
        pane_alive=None,
        now=t0 + timedelta(seconds=5),
    )

    assert verdict == PERMISSION_NOT_CHECKED
    assert tracker.permission_open_since("ses_3") == t0, (
        "an unmeasured pane must never clear an open permission claim - "
        "only a POSITIVE measurement of death may"
    )



from src.core.session_manager import SessionManager  # noqa: E402
from src.core.session_status import STATUS_DEAD, STATUS_IDLE  # noqa: E402
from src.core.session_status_map import StatusMap  # noqa: E402
from src.models import Session, SessionStatus  # noqa: E402

TEST_SOCKET = "cloude_pvd_test"


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.port = 5001

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


class _SocketBackend:

    def __init__(self, tmux_session: str, exists: bool = True):
        self.tmux_session = tmux_session
        self.socket_name = TEST_SOCKET
        self._exists = exists
        self.pid = 4321

    def is_alive(self) -> bool:
        return self._exists


@pytest.fixture()
def mgr(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings",
        _StubSettings(tmp_path / "pinned_themes.json", tmp_path / "logs"),
    )
    manager = SessionManager()
    monkeypatch.setattr(
        manager, "_persist_settled_activity_state", lambda *a, **k: None
    )
    return manager


def _register_with_open_permission(
    manager: SessionManager,
    sid: str,
    tmux_name: str,
    wd: Path,
    *,
    exists: bool = True,
) -> datetime:
    manager._registry.sessions[sid] = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(wd),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    manager._registry.backends[sid] = _SocketBackend(tmux_name, exists=exists)
    manager._registry.subscribers.setdefault(sid, [])
    opened_at = datetime(2026, 9, 11, 12, 0, 0)
    open_claims(manager, sid, permission=True, at=opened_at)
    assert manager._activity_tracker.permission_open_since(sid) == opened_at
    return opened_at


def _listing(name: str, status: str, *, socket: str = TEST_SOCKET) -> StatusMap:
    return StatusMap(
        {
            name: {
                "name": name,
                "status": status,
                "pid": 4321,
                "pane_dead": "1" if status == STATUS_DEAD else "0",
                "pane_current_command": "zsh",
                "created_at_epoch": 1755000000,
            }
        },
        complete=True,
        socket=socket,
    )


def test_a_measured_dead_pane_still_clears_the_flag_through_the_listing_pass(
    mgr, tmp_path
):
    _register_with_open_permission(mgr, "ses_dead", "cloude_dead", tmp_path)

    info = mgr._session_info_for(
        "ses_dead", status_map=_listing("cloude_dead", STATUS_DEAD)
    )

    assert info is None, "sanity: a dead husk still drops off the running list"
    assert mgr._activity_tracker.permission_open_since("ses_dead") is None, (
        "a POSITIVELY measured dead pane cannot be showing a dialog, so the "
        "claim must be retired here or it is stuck forever"
    )


def test_a_failed_liveness_probe_keeps_the_open_permission_flag(mgr, tmp_path):
    opened_at = _register_with_open_permission(
        mgr, "ses_murky", "cloude_murky", tmp_path, exists=False
    )

    info = mgr._session_info_for(
        "ses_murky",
        status_map=StatusMap({}, complete=True, socket=TEST_SOCKET),
    )

    assert info is None, "a session the backend says is absent is still dropped"
    assert mgr._activity_tracker.permission_open_since("ses_murky") == opened_at, (
        "an unmeasured pane must never clear an open permission claim - "
        "has-session cannot tell absence from a failed call"
    )


def test_a_dead_reading_from_an_unstated_socket_keeps_the_flag(mgr, tmp_path):
    opened_at = _register_with_open_permission(
        mgr, "ses_xsock", "cloude_xsock", tmp_path
    )

    info = mgr._session_info_for(
        "ses_xsock", status_map=_listing("cloude_xsock", STATUS_DEAD, socket="")
    )

    assert info is None
    assert mgr._activity_tracker.permission_open_since("ses_xsock") == opened_at, (
        "a listing with no stated socket proves nothing about this pane"
    )


def test_a_live_pane_is_untouched_by_any_of_this(mgr, tmp_path):
    opened_at = _register_with_open_permission(
        mgr, "ses_live", "cloude_live", tmp_path
    )

    info = mgr._session_info_for(
        "ses_live", status_map=_listing("cloude_live", STATUS_IDLE)
    )

    assert info is not None, "a live pane must stay in the running list"
    assert mgr._activity_tracker.permission_open_since("ses_live") == opened_at
