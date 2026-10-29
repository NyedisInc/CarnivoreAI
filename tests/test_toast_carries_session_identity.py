
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ti_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ti_logs_"))
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
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json", log_dir=tmp_path / "logs"
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _register(mgr, sid, work, tmux_session):
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_session,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


def test_a_toast_carries_the_tmux_name_of_its_session(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, "cloude_alpha")
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_name == "cloude_alpha"


def test_a_toast_carries_the_label_when_the_session_has_one(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, "cloude_alpha")
    monkeypatch.setattr(
        SessionManager,
        "_label_for_tmux_name",
        lambda self, name: "Media Compression" if name == "cloude_alpha" else None,
    )
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_label == "Media Compression"
    assert toast.session_name == "cloude_alpha"


def test_no_label_is_none_and_never_an_empty_string(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, "cloude_alpha")
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_label is None


def test_a_non_tmux_session_yields_two_nones_rather_than_raising(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, None)
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_name is None
    assert toast.session_label is None


def test_a_label_read_that_throws_does_not_fail_the_toast(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, "cloude_alpha")

    def _boom(self, name):
        raise RuntimeError("datastore on fire")

    monkeypatch.setattr(SessionManager, "_label_for_tmux_name", _boom)
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_label is None
    assert toast.session_name == "cloude_alpha"


def test_a_label_with_punctuation_survives_onto_the_toast(monkeypatch, tmp_path):
    hairy = 'client: acme v2.1 "prod" $rate'
    mgr = _manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register(mgr, "s1", work, "cloude_client_acme")
    monkeypatch.setattr(
        SessionManager, "_label_for_tmux_name", lambda self, name: hairy
    )
    toast = mgr.record_toast(session_id="s1", kind="Stop", title="Your turn")
    assert toast.session_label == hairy
