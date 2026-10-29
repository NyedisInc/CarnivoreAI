
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from src.core import session_view_clears
from src.core.attention.evidence import (
    ALL_STATES,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    STATE_UNKNOWN,
    AttentionVerdict,
)
from src.core.attention.watcher import Observation
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus

SID = "ses_view749"
TMUX = "cloude_view749"
EPOCH = 1790000000


class _StubSettings:

    def __init__(self, root: Path) -> None:
        self._root = root
        self.port = 5001

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str) -> None:
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


class _FakeWatcher:

    def __init__(self, observation: Optional[Observation]) -> None:
        self.observation = observation
        self.asked: list[str] = []

    def observation_for(self, session_id: str, now=None) -> Optional[Observation]:
        self.asked.append(session_id)
        return self.observation


def _observation(state: str) -> Observation:
    return Observation(
        verdict=AttentionVerdict(state, "test", "registry"),
        evidence=None,
        new_user_prompt_at=None,
        transcript_appended=False,
    )


@pytest.fixture()
def mgr(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr("src.core.session_manager.settings", _StubSettings(tmp_path))
    manager = SessionManager()
    manager._registry.sessions[SID] = Session(
        id=SID, pty_pid=None, working_dir=str(tmp_path),
        status=SessionStatus.RUNNING, tmux_session=TMUX,
    )
    manager._registry.backends[SID] = _FakeBackend(TMUX)
    manager._registry.subscribers.setdefault(SID, [])
    manager._unread_epochs[TMUX] = EPOCH
    manager.set_manual_unread(TMUX, True)
    assert manager._is_unread(TMUX, EPOCH) is True
    return manager


def test_a_view_of_a_session_at_rest_marks_it_read(mgr: SessionManager) -> None:
    watcher = _FakeWatcher(_observation(STATE_DONE_IDLE))
    mgr._attention_watcher = watcher

    mgr.mark_session_viewed(SID)

    assert mgr._is_unread(TMUX, EPOCH) is False
    assert watcher.asked == [SID]


@pytest.mark.parametrize("state", [STATE_BUSY, STATE_NEEDS_USER, STATE_UNKNOWN])
def test_a_view_of_a_session_not_at_rest_leaves_it_unread(
    mgr: SessionManager, state: str
) -> None:
    mgr._attention_watcher = _FakeWatcher(_observation(state))

    mgr.mark_session_viewed(SID)

    assert mgr._is_unread(TMUX, EPOCH) is True


def test_the_gate_names_every_state() -> None:
    assert ALL_STATES == {STATE_DONE_IDLE, STATE_BUSY, STATE_NEEDS_USER, STATE_UNKNOWN}


def test_a_session_the_watcher_never_observed_is_still_clearable(
    mgr: SessionManager,
) -> None:
    mgr._attention_watcher = _FakeWatcher(None)

    mgr.mark_session_viewed(SID)

    assert mgr._is_unread(TMUX, EPOCH) is False


def test_the_explicit_mark_read_control_is_not_gated(mgr: SessionManager) -> None:
    mgr._attention_watcher = _FakeWatcher(_observation(STATE_BUSY))

    mgr.set_manual_unread(TMUX, False)

    assert mgr._is_unread(TMUX, EPOCH) is False


def test_a_refused_view_leaves_the_unread_flag_alone(mgr: SessionManager) -> None:
    mgr._attention_watcher = _FakeWatcher(_observation(STATE_NEEDS_USER))

    assert session_view_clears.clear_on_view(mgr, SID) is False

    assert mgr._is_unread(TMUX, EPOCH) is True


def test_a_repeated_view_is_idempotent(mgr: SessionManager) -> None:
    mgr._attention_watcher = _FakeWatcher(_observation(STATE_BUSY))
    mgr.mark_session_viewed(SID)
    mgr.mark_session_viewed(SID)
    assert mgr._is_unread(TMUX, EPOCH) is True

    mgr._attention_watcher = _FakeWatcher(_observation(STATE_DONE_IDLE))
    mgr.mark_session_viewed(SID)
    mgr.mark_session_viewed(SID)
    assert mgr._is_unread(TMUX, EPOCH) is False
