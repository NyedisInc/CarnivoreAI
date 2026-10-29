
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_srl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_srl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.session_manager import SessionManager
from src.core.sessions.registry import ORPHAN_BUCKET, SessionRegistry
from src.models import Session, SessionStatus


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path, log_buffer_size: int = 1000):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.log_buffer_size = log_buffer_size

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

    def __init__(self, tmux_session: str, alive: bool = True) -> None:
        self.tmux_session = tmux_session
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


@pytest.fixture()
def manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings",
        _StubSettings(
            pin_path=tmp_path / "pinned_themes.json",
            log_dir=tmp_path / "logs",
        ),
    )
    return SessionManager()


def _session(session_id: str, tmux_name: str | None = None) -> Session:
    return Session(
        id=session_id,
        pty_pid=0,
        working_dir="/tmp",
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name or f"cloude_{session_id}",
    )




def test_leg_a_the_manager_resolves_none_of_the_moved_names(manager):
    for name in ("sessions", "backends", "_subscribers", "_last_session_id"):
        assert not hasattr(manager, name), (
            f"SessionManager.{name} resolves again; the registry owns that "
            "container and a caller holds the registry"
        )
    assert manager._registry.sessions == {}
    assert manager._registry.backends == {}


def test_leg_b_a_write_through_the_manager_lands_on_a_reference_taken_first(
    manager,
):
    held = manager._registry
    sessions_before = held.sessions
    backends_before = held.backends

    session = _session("ses_fwd")
    backend = _FakeBackend("cloude_ses_fwd")
    manager._registry.register(session, backend)

    assert "ses_fwd" in sessions_before, (
        "a session registered through the manager is invisible to a "
        "registry reference taken before the write; there are two dicts"
    )
    assert backends_before["ses_fwd"] is backend
    assert held.last_session_id == "ses_fwd"


def test_leg_c_a_write_through_the_registry_is_seen_by_the_manager(manager):
    session = _session("ses_rev")
    backend = _FakeBackend("cloude_ses_rev")
    manager._registry.sessions["ses_rev"] = session
    manager._registry.backends["ses_rev"] = backend
    manager._registry.last_session_id = "ses_rev"

    assert manager._registry.current_session() is session
    assert [s.id for s in manager._registry.list_sessions()] == ["ses_rev"]
    assert manager.has_active_session() is True
    assert manager.is_session_live("ses_rev") is True
    assert manager.active_tmux_names() == {"cloude_ses_rev"}


def test_leg_d_one_pane_registered_twice_is_visible_as_two_ids(manager):
    name = "cloude_one_pane"
    manager._registry.register(_session("ses_first", name), _FakeBackend(name))
    manager._registry.backends["ses_second"] = _FakeBackend(name)

    found = manager._registry.registered_ids_for_tmux_name(name)

    assert sorted(found) == ["ses_first", "ses_second"], (
        "one tmux pane is registered under two session ids and the query "
        f"reports {found}; a teardown keyed on this leaves the other "
        "backend on the same FIFO"
    )


def test_leg_d_negative_control_an_unregistered_name_finds_nothing(manager):
    manager._registry.register(
        _session("ses_real", "cloude_real"), _FakeBackend("cloude_real")
    )

    assert manager._registry.registered_ids_for_tmux_name("cloude_ghost") == []
    assert (
        manager._registry.registered_ids_for_tmux_name(
            "cloude_ghost", also="ses_never_registered"
        )
        == []
    ), "``also`` named an id with no backend and the query invented it"
    assert manager._registry.registered_ids_for_tmux_name(
        "cloude_ghost", also="ses_real"
    ) == ["ses_real"]


def test_leg_e_the_teardown_empties_the_reference_taken_first(manager):
    held_sessions = manager._registry.sessions
    held_backends = manager._registry.backends
    held_subscribers = manager._registry.subscribers

    manager._registry.register(_session("ses_gone"), _FakeBackend("cloude_gone"))
    assert "ses_gone" in held_sessions

    manager._wipe_session_state("ses_gone")

    assert "ses_gone" not in held_sessions, (
        "the manager's teardown left the session on a registry reference "
        "taken earlier; the pop landed on a different dict"
    )
    assert "ses_gone" not in held_backends
    assert "ses_gone" not in held_subscribers
    assert manager._registry.last_session_id is None




def test_the_current_pointer_repairs_itself_when_its_session_goes(manager):
    manager._registry.register(_session("ses_old"), None)
    manager._registry.register(_session("ses_new"), None)
    assert manager._registry.last_session_id == "ses_new"

    manager._registry.sessions.pop("ses_new")

    assert manager._registry.current_session().id == "ses_old"
    assert manager._registry.last_session_id == "ses_old"


def test_forget_moves_the_pointer_to_the_newest_survivor(manager):
    manager._registry.register(_session("ses_a"), None)
    manager._registry.register(_session("ses_b"), None)

    manager._registry.forget("ses_b")

    assert manager._registry.last_session_id == "ses_a"
    assert manager._registry.current_session().id == "ses_a"


def test_forget_leaves_every_other_session_untouched(manager):
    manager._registry.register(_session("ses_keep"), _FakeBackend("cloude_keep"))
    manager._registry.register(_session("ses_drop"), _FakeBackend("cloude_drop"))
    manager._registry.append_log("ses_keep", "still here")

    manager._registry.forget("ses_drop")

    assert "ses_keep" in manager._registry.sessions
    assert "ses_keep" in manager._registry.backends
    assert manager._registry.log_line_count("ses_keep") == 1


def test_resolve_session_id_refuses_an_id_that_is_not_registered(manager):
    manager._registry.register(_session("ses_live"), None)

    assert manager._registry.resolve_session_id("ses_live") == "ses_live"
    assert manager._registry.resolve_session_id("ses_never") is None
    assert manager._registry.resolve_session_id(None) == "ses_live"


def test_an_orphan_subscriber_never_receives_another_session_s_bytes():
    registry = SessionRegistry(log_cap=lambda: 1000)

    orphan = registry.subscribe(None)

    assert ORPHAN_BUCKET in registry.subscribers
    registry.register(_session("ses_late"), None)
    registry.publish("ses_late", b"hello")
    assert orphan.queued_items == 0, (
        "an orphan stream received a real session's bytes"
    )


def test_output_reaches_only_the_subscribers_of_that_session():
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(_session("ses_a"), None)
    registry.register(_session("ses_b"), None)
    stream_a = registry.subscribe("ses_a")
    stream_b = registry.subscribe("ses_b")

    registry.publish("ses_a", b"only for a")

    assert stream_a.queued_items == 1
    assert stream_b.queued_items == 0, (
        "session A's bytes landed in session B's stream"
    )


def test_unsubscribe_without_a_session_id_searches_every_bucket():
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(_session("ses_x"), None)
    queue = registry.subscribe("ses_x")

    registry.unsubscribe(queue)

    assert registry.subscribers["ses_x"] == []
    registry.unsubscribe(queue)
    registry.unsubscribe(queue, "ses_x")


def test_the_manager_s_output_handler_is_bound_to_one_session():
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(_session("ses_1"), None)
    registry.register(_session("ses_2"), None)
    stream_1 = registry.subscribe("ses_1")
    stream_2 = registry.subscribe("ses_2")

    class _Manager:
        _registry = registry
        _make_output_handler = SessionManager._make_output_handler

    handler = _Manager()._make_output_handler("ses_1")
    handler(b"for one")

    assert stream_1.queued_items == 1
    assert stream_2.queued_items == 0
