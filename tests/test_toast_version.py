from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import toast_auto_ack
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus, Toast


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path):
        self._pin_path = pin_path
        self._log_dir = log_dir

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


@pytest.fixture()
def mgr(monkeypatch, tmp_path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings",
        _StubSettings(tmp_path / "pinned_themes.json", tmp_path / "logs"),
    )
    manager = SessionManager()
    work = tmp_path / "proj"
    work.mkdir()
    manager._registry.sessions["ses_a"] = Session(
        id="ses_a",
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=None,
    )
    manager._registry.subscribers.setdefault("ses_a", [])
    return manager




def test_the_model_defaults_a_bare_toast_to_version_one():
    t = Toast(id="x", session_id="ses_a", kind="Notification", title="hi")
    assert t.version == 1




def test_a_new_toast_starts_at_version_one(mgr):
    t = mgr.record_toast("ses_a", "Notification", "look at this", "first")
    assert t.version == 1


def test_a_real_content_change_on_supersede_bumps_the_version(mgr):
    first = mgr.record_toast("ses_a", "Stop", "Your turn", body="turn one")
    assert first.version == 1
    second = mgr.record_toast("ses_a", "Stop", "Your turn", body="turn two")
    assert second.id == first.id, "supersession must keep the id"
    assert second.version == 2, "a genuinely different body is a real change"


def test_an_identical_reraise_does_not_bump_the_version(mgr):
    first = mgr.record_toast("ses_a", "Stop", "Your turn", body="same body")
    again = mgr.record_toast("ses_a", "Stop", "Your turn", body="same body")
    assert again.id == first.id
    assert again.version == 1, (
        "an identical re-raise must not move the version - it carries no "
        "new information for a client to apply"
    )


def test_three_identical_reraises_still_hold_version_one(mgr):
    for _ in range(3):
        mgr.record_toast("ses_a", "Stop", "Your turn", body="steady")
    stored = mgr._toast_inbox.get("ses_a", unacked_only=True)
    assert len(stored) == 1
    assert stored[0].version == 1


def test_repeated_real_changes_bump_once_each(mgr):
    bodies = ["a", "b", "c", "d"]
    last = None
    for i, body in enumerate(bodies, start=1):
        last = mgr.record_toast("ses_a", "Stop", "Your turn", body=body)
        assert last.version == i
    assert last.body == "d"


def test_a_color_only_change_still_counts_as_real(mgr):
    first = mgr.record_toast("ses_a", "Stop", "Your turn", body="same")
    first.color = "#111111"
    second = mgr.record_toast("ses_a", "Stop", "Your turn", body="same")
    assert second.version == 2




def test_duplicate_hook_delivered_toast_creation_is_not_double_counted(mgr):
    a = mgr.record_toast("ses_a", "Stop", "Your turn", body=None)
    b = mgr.record_toast("ses_a", "Stop", "Your turn", body=None)
    assert a.id == b.id
    assert b.version == 1


def test_duplicate_ack_does_not_bump_twice(mgr):
    t = mgr.record_toast("ses_a", "Notification", "hi", "body")
    assert t.version == 1
    first_ack = mgr._toast_inbox.ack("ses_a", t.id, toast_auto_ack.ACK_REASON_DISMISSED)
    assert first_ack is True
    after_first = mgr._toast_inbox.get("ses_a")[0]
    assert after_first.version == 2, "the ack transition is a real change"

    second_ack = mgr._toast_inbox.ack("ses_a", t.id, toast_auto_ack.ACK_REASON_DISMISSED)
    assert second_ack is False
    after_second = mgr._toast_inbox.get("ses_a")[0]
    assert after_second.version == 2, (
        "a duplicated ack of the same record must not move the version "
        "a second time"
    )


def test_duplicate_auto_ack_does_not_bump_twice(mgr):
    from datetime import datetime, timedelta

    t = mgr.record_toast("ses_a", "PermissionRequest", "allow?", "cmd")
    cutoff = datetime.utcnow() + timedelta(seconds=1)
    first = mgr.auto_ack_toasts("ses_a", "PreToolUse", cutoff=cutoff)
    assert first == [t.id]
    after_first = mgr._toast_inbox.get("ses_a")[0]
    assert after_first.version == 2

    second = mgr.auto_ack_toasts("ses_a", "PreToolUse", cutoff=cutoff)
    assert second == [], "already answered - nothing changed the second time"
    after_second = mgr._toast_inbox.get("ses_a")[0]
    assert after_second.version == 2




def test_notifications_never_supersede_so_each_starts_at_version_one(mgr):
    for i in range(3):
        mgr.record_toast("ses_a", "Notification", "Waiting", body=f"msg {i}")
    stored = mgr._toast_inbox.get("ses_a")
    assert len(stored) == 3
    assert all(t.version == 1 for t in stored)


def test_acking_one_toast_does_not_touch_anothers_version(mgr):
    a = mgr.record_toast("ses_a", "Notification", "a", "body a")
    b = mgr.record_toast("ses_a", "PermissionRequest", "b", "body b")
    mgr._toast_inbox.ack("ses_a", a.id, toast_auto_ack.ACK_REASON_DISMISSED)
    by_id = {t.id: t for t in mgr._toast_inbox.get("ses_a")}
    assert by_id[a.id].version == 2
    assert by_id[b.id].version == 1, "acking a lives entirely on a's record"
