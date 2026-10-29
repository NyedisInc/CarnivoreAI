from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tsr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tsr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus


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


def _session(mgr: SessionManager, sid: str, work: Path, tmux_name: str) -> Session:
    work.mkdir(exist_ok=True, parents=True)
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.subscribers.setdefault(sid, [])
    mgr.hook_tokens.tmux_names[sid] = tmux_name
    return sess




def test_live_session_with_empty_bucket_does_not_enter_remap(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_live", tmp_path / "live", "cloude_ses_live")
    assert "ses_live" not in mgr._toast_inbox.pending, "sanity: bucket genuinely empty"

    calls = []
    original = SessionManager._live_session_id_for_stale_id

    def _spy(self, session_id):
        calls.append(session_id)
        return original(self, session_id)

    with patch.object(SessionManager, "_live_session_id_for_stale_id", _spy):
        changed = mgr.auto_ack_toasts("ses_live", "UserPromptSubmit")

    assert changed == []
    assert calls == [], (
        "a live, registered session must never reach the stale-id "
        "resolver just because its toast bucket happens to be empty"
    )


def test_toast_session_id_remapped_never_logs_for_a_live_known_session(
    monkeypatch, tmp_path, caplog
):
    import logging

    caplog.set_level(logging.INFO)
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_live2", tmp_path / "live2", "cloude_ses_live2")

    mgr.auto_ack_toasts("ses_live2", "PreToolUse")

    assert "toast_session_id_remapped" not in caplog.text




def test_genuinely_stale_id_still_remaps_and_acks(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    live = _session(mgr, "ses_live3", tmp_path / "live3", "cloude_ses_live3")
    mgr.hook_tokens.tmux_names["ses_stale"] = "cloude_ses_live3"

    toast = mgr.record_toast("ses_live3", "Stop", "Your turn")
    assert mgr._toast_inbox.get("ses_live3", unacked_only=True) == [toast]

    now = toast.created_at + timedelta(seconds=1)
    changed = mgr.auto_ack_toasts("ses_stale", "UserPromptSubmit", cutoff=now)

    assert changed == [toast.id], (
        "a hook arriving under the pre-restart id must still be able to "
        "ack the surviving session's toast"
    )
    assert mgr._toast_inbox.get("ses_live3", unacked_only=True) == []




def test_live_session_id_for_stale_id_returns_none_on_self_match(
    monkeypatch, tmp_path, caplog
):
    import logging

    caplog.set_level(logging.INFO)
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_self", tmp_path / "self", "cloude_ses_self")

    result = mgr._live_session_id_for_stale_id("ses_self")

    assert result is None
    assert "toast_session_id_remapped" not in caplog.text


def test_live_session_id_for_stale_id_still_finds_a_different_live_session(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    _session(mgr, "ses_new", tmp_path / "new", "cloude_shared_name")
    mgr.hook_tokens.tmux_names["ses_old"] = "cloude_shared_name"

    result = mgr._live_session_id_for_stale_id("ses_old")

    assert result == "ses_new"
