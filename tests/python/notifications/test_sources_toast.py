
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s5_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s5_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.attention.evidence import REASON_PERMISSION, REASON_QUESTION, REASON_TURN_ENDED
from src.core.notifications import contracts
from src.core.notifications.sources import open_checks
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus


class _Settings:

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "logs" / "session_metadata.json"


@pytest.fixture()
def mgr(monkeypatch, tmp_path) -> SessionManager:
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr("src.core.session_manager.settings", _Settings(tmp_path))
    manager = SessionManager()
    work = tmp_path / "proj"
    work.mkdir()
    manager._registry.sessions["ses_a"] = Session(
        id="ses_a", pty_pid=None, working_dir=str(work), status=SessionStatus.RUNNING, tmux_session=None)
    manager._registry.subscribers.setdefault("ses_a", [])
    return manager


def test_one_toast_emits_exactly_one_event_with_id_and_version_in_the_key(mgr, captured) -> None:
    toast = mgr.record_toast("ses_a", "Stop", "Your turn", body="done", notify_type="session.finished")
    assert len(captured) == 1
    event = captured[0]
    assert event.type_id == "session.finished" and event.session_id == "ses_a"
    assert event.toast_id == toast.id and event.toast_version == toast.version == 1
    assert event.instance_key == f"toast:{toast.id}:1" and event.details == "done"
    assert event.open_item is False


def test_a_superseded_stop_is_a_new_version_and_an_identical_reraise_keeps_the_key(mgr, captured) -> None:
    mgr.record_toast("ses_a", "Stop", "Your turn", body="one", notify_type="session.finished")
    mgr.record_toast("ses_a", "Stop", "Your turn", body="two", notify_type="session.finished")
    mgr.record_toast("ses_a", "Stop", "Your turn", body="two", notify_type="session.finished")
    keys = [e.instance_key for e in captured]
    assert keys[0] != keys[1] and keys[1] == keys[2] and keys[1].endswith(":2")


def test_a_toast_without_a_notify_type_emits_nothing(mgr, captured) -> None:
    mgr.record_toast("ses_a", "Stop", "Your turn", notify_type=None)
    assert captured == []


def test_a_needs_you_toast_is_an_open_item(mgr, captured) -> None:
    mgr.record_toast("ses_a", "PermissionRequest", "needs permission", notify_type="session.permission")
    assert captured[0].open_item is True and captured[0].severity == contracts.SEVERITY_WARN


class _Watcher:

    def __init__(self, reason: str, fingerprint: str = "fp1") -> None:
        self.set(reason, fingerprint)

    def set(self, reason: str, fingerprint: str = "fp1") -> None:
        dialog = SimpleNamespace(fingerprint=fingerprint) if reason != REASON_TURN_ENDED else None
        self._obs = SimpleNamespace(verdict=SimpleNamespace(reason=reason), evidence=SimpleNamespace(dialog=dialog))

    def observation_for(self, session_id):
        return self._obs if session_id == "ses_a" else None


def _event(key: str = "toast:t:1", type_id: str = "session.permission") -> contracts.NotifyEvent:
    return contracts.NotifyEvent(type_id=type_id, kind="PermissionRequest", title="t", ts=1.0,
                                 session_id="ses_a", instance_key=key, open_item=True)


def test_the_open_check_flips_when_the_dialog_closes_and_ignores_acknowledgement() -> None:
    watcher = _Watcher(REASON_PERMISSION)
    open_checks.remember_dialog("toast:t:1", watcher, "ses_a")
    event = _event()
    assert open_checks.session_still_waiting(watcher, event) is True
    assert open_checks.session_still_waiting(watcher, event) is True
    watcher.set(REASON_TURN_ENDED)
    assert open_checks.session_still_waiting(watcher, event) is False


def test_a_different_dialog_of_the_same_kind_is_not_the_same_item() -> None:
    watcher = _Watcher(REASON_PERMISSION, "fpA")
    open_checks.remember_dialog("toast:t:2", watcher, "ses_a")
    watcher.set(REASON_PERMISSION, "fpB")
    assert open_checks.session_still_waiting(watcher, _event("toast:t:2")) is False


def test_a_question_toast_is_not_open_for_a_permission_dialog_and_a_missing_watcher_is_closed() -> None:
    watcher = _Watcher(REASON_PERMISSION)
    assert open_checks.session_still_waiting(watcher, _event("toast:q:1", "session.question")) is False
    watcher.set(REASON_QUESTION)
    assert open_checks.session_still_waiting(watcher, _event("toast:q:1", "session.question")) is True
    assert open_checks.session_still_waiting(None, _event()) is False


def test_register_open_checks_registers_all_five_needs_you_types() -> None:
    registered = {}
    engine = SimpleNamespace(register_open_check=lambda type_id, fn: registered.update({type_id: fn}))
    store = SimpleNamespace(list=lambda: [{"id": "act_1"}])
    open_checks.register_open_checks(engine, lambda: None, lambda: store)
    from src.core.notifications import types
    assert set(registered) == set(types.NEEDS_YOU) and len(registered) == 5
    action = registered["approval.agent_action"]
    assert action(contracts.NotifyEvent(type_id="approval.agent_action", kind="a", title="t", ts=1.0,
                                        instance_key="act_1")) is True
    store_empty = SimpleNamespace(list=lambda: [])
    open_checks.register_open_checks(engine, lambda: None, lambda: store_empty)
    assert registered["approval.agent_action"](contracts.NotifyEvent(
        type_id="approval.agent_action", kind="a", title="t", ts=1.0, instance_key="act_1")) is False
