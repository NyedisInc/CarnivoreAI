from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_taa_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_taa_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
import src.api.toast_routes as toast_routes_mod
from src.core.composition import build_services

from src.api.auth import require_auth
from src.core import toast_auto_ack, toast_history
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus, Toast

ANSWERED = toast_auto_ack.ACK_REASON_ANSWERED
DISMISSED = toast_auto_ack.ACK_REASON_DISMISSED




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


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    stub = _StubSettings(tmp_path / "pinned_themes.json", tmp_path / "logs")
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _session(mgr: SessionManager, sid: str, work: Path) -> Session:
    work.mkdir(exist_ok=True, parents=True)
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=f"cloude_{sid}",
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


def _toast(kind: str, toast_id: str, *, created_at: datetime, acked: bool = False):
    return Toast(
        id=toast_id,
        session_id="ses_x",
        kind=kind,
        title=f"{kind} title",
        created_at=created_at,
        acknowledged=acked,
        ack_reason=DISMISSED if acked else None,
    )


def _one_of_each(now: datetime):
    kinds = ["Stop", "PermissionRequest", "Notification"]
    records = [_toast(k, f"id_{k}", created_at=now) for k in kinds]
    return records, {k: f"id_{k}" for k in kinds}




def test_a_prompt_answers_every_kind_of_toast():
    now = datetime.utcnow()
    records, ids = _one_of_each(now)
    acked = toast_auto_ack.resolve_auto_acks(
        records, "UserPromptSubmit", cutoff=now + timedelta(seconds=1)
    )
    assert set(acked) == set(ids.values()), (
        "a submitted prompt answers the permission he approved in the pane, "
        "the notice he read on the way past, and the turn he has plainly taken"
    )


def test_pre_tool_use_answers_a_permission_and_nothing_else():
    now = datetime.utcnow()
    records, ids = _one_of_each(now)
    acked = toast_auto_ack.resolve_auto_acks(
        records, "PreToolUse", cutoff=now + timedelta(seconds=1)
    )
    assert acked == [ids["PermissionRequest"]]

    assert ids["Notification"] not in acked
    assert ids["Stop"] not in acked


def test_stop_answers_a_permission_and_a_notice_but_never_a_your_turn():
    now = datetime.utcnow()
    records, ids = _one_of_each(now)
    acked = toast_auto_ack.resolve_auto_acks(
        records, "Stop", cutoff=now + timedelta(seconds=1)
    )
    assert set(acked) == {
        ids["PermissionRequest"],
        ids["Notification"],
    }
    assert ids["Stop"] not in acked, (
        "the card a Stop raises says the user's turn has come; only the user "
        "turning up may clear it"
    )


def test_a_stop_cannot_clear_an_older_stop_toast_either():
    now = datetime.utcnow()
    older = _toast("Stop", "id_older_stop", created_at=now - timedelta(minutes=5))
    acked = toast_auto_ack.resolve_auto_acks([older], "Stop", cutoff=now)
    assert acked == []


def test_an_event_that_answers_nothing_returns_nothing():
    now = datetime.utcnow()
    records, _ = _one_of_each(now)
    for kind in ("PostToolUse", "SubagentStart", "SubagentStop", "SessionStart"):
        assert toast_auto_ack.resolve_auto_acks(records, kind, cutoff=now) == []
    assert toast_auto_ack.kinds_answered_by("PostToolUse") == frozenset()




def test_an_already_answered_toast_is_never_returned_again():
    now = datetime.utcnow()
    done = _toast("PermissionRequest", "id_done", created_at=now, acked=True)
    still_open = _toast("Notification", "id_open", created_at=now)
    acked = toast_auto_ack.resolve_auto_acks(
        [done, still_open], "UserPromptSubmit", cutoff=now
    )
    assert acked == ["id_open"]


def test_a_toast_raised_after_the_event_is_never_answered_by_it():
    typed_at = datetime.utcnow()
    older = _toast(
        "PermissionRequest", "id_before", created_at=typed_at - timedelta(seconds=30)
    )
    newer = _toast(
        "Notification", "id_after", created_at=typed_at + timedelta(seconds=30)
    )
    acked = toast_auto_ack.resolve_auto_acks(
        [older, newer], "UserPromptSubmit", cutoff=typed_at
    )
    assert acked == ["id_before"]
    assert "id_after" not in acked, (
        "a record raised after the user acted describes something the act "
        "cannot have answered; eating it would destroy a notice never seen"
    )


def test_a_stop_toast_already_recorded_survives_that_stops_own_ack_pass():
    stop_at = datetime.utcnow()
    own = _toast("Stop", "id_own", created_at=stop_at + timedelta(milliseconds=5))
    older_perm = _toast(
        "PermissionRequest", "id_perm", created_at=stop_at - timedelta(minutes=2)
    )
    acked = toast_auto_ack.resolve_auto_acks(
        [own, older_perm], "Stop", cutoff=stop_at
    )
    assert acked == ["id_perm"]

    assert toast_auto_ack.resolve_auto_acks([own, older_perm], "Stop") == ["id_perm"]




def test_auto_ack_stamps_answered_and_is_a_no_op_on_replay(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    perm = mgr.record_toast("ses_a", "PermissionRequest", "run rm -rf")

    changed = mgr.auto_ack_toasts("ses_a", "UserPromptSubmit", datetime.utcnow())
    assert changed == [perm.id]
    stored = mgr._toast_inbox.get("ses_a")[0]
    assert stored.acknowledged is True
    assert stored.ack_reason == ANSWERED

    assert mgr.auto_ack_toasts("ses_a", "UserPromptSubmit", datetime.utcnow()) == []


def test_a_human_dismissal_still_records_dismissed(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    t = mgr.record_toast("ses_a", "Notification", "look at this")

    assert mgr._toast_inbox.ack("ses_a", t.id, toast_auto_ack.ACK_REASON_DISMISSED) is True
    assert mgr._toast_inbox.get("ses_a")[0].ack_reason == DISMISSED
    assert mgr._toast_inbox.ack("ses_a", t.id, reason=ANSWERED) is False
    assert mgr._toast_inbox.get("ses_a")[0].ack_reason == DISMISSED


def test_auto_ack_is_scoped_to_its_own_session(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    _session(mgr, "ses_b", tmp_path / "b")
    a = mgr.record_toast("ses_a", "PermissionRequest", "a's decision")
    b = mgr.record_toast("ses_b", "PermissionRequest", "b's decision")

    assert mgr.auto_ack_toasts("ses_a", "UserPromptSubmit", datetime.utcnow()) == [a.id]
    assert mgr._toast_inbox.get("ses_b")[0].id == b.id
    assert mgr._toast_inbox.get("ses_b")[0].acknowledged is False


def test_history_summary_reports_answered_beside_dismissed(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    clicked = mgr.record_toast("ses_a", "Notification", "clicked away")
    auto = mgr.record_toast("ses_a", "PermissionRequest", "answered in the pane")
    mgr.record_toast("ses_a", "Notification", "still open")
    mgr._toast_inbox.ack("ses_a", clicked.id, toast_auto_ack.ACK_REASON_DISMISSED)
    mgr.auto_ack_toasts("ses_a", "PreToolUse", datetime.utcnow())

    summary = toast_history.summarize(mgr._toast_inbox.get("ses_a"))
    assert summary["total"] == 3
    assert summary["open"] == 1
    assert summary["dismissed"] == 2
    assert summary["answered"] == 1
    assert mgr._toast_inbox.get("ses_a")
    assert any(t.id == auto.id and t.ack_reason == ANSWERED
               for t in mgr._toast_inbox.get("ses_a"))


def test_a_record_acked_without_a_reason_is_not_counted_as_answered():
    now = datetime.utcnow()
    legacy = Toast(
        id="legacy", session_id="s", kind="Stop", title="Your turn",
        created_at=now, acknowledged=True, ack_reason=None,
    )
    summary = toast_history.summarize([legacy])
    assert summary["dismissed"] == 1
    assert summary["answered"] == 0
