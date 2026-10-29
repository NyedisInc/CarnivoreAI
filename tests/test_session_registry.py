
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
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


@pytest.fixture()
def registry() -> SessionRegistry:
    return SessionRegistry(log_cap=lambda: 1000)


@pytest.fixture()
def stub_settings(monkeypatch, tmp_path: Path) -> _StubSettings:
    (tmp_path / "logs").mkdir(exist_ok=True)
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
    )
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return stub


@pytest.fixture()
def manager(stub_settings) -> SessionManager:
    return SessionManager()


def _register(manager: SessionManager, session_id: str, work: Path) -> Session:
    sess = Session(
        id=session_id,
        pty_pid=0,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=f"cloude_{session_id}",
    )
    manager._registry.sessions[session_id] = sess
    manager._registry.last_session_id = session_id
    return sess




def test_leg_a_the_facade_containers_are_the_registry_containers(manager):
    assert manager._registry.log_buffers is manager._registry.log_buffers
    assert manager._registry.command_counts is manager._registry.command_counts


def test_leg_b_the_facade_holds_no_field_of_its_own(manager):
    for name in ("log_buffers", "command_counts"):
        assert not hasattr(manager, name), (
            f"{name} resolves on the facade again; the registry owns it and "
            "a caller holds the registry"
        )
    assert manager._registry.log_buffers is not None


def test_leg_c_writes_cross_in_both_directions(manager):
    manager._registry.log_buffers["ses_from_registry"] = []
    assert "ses_from_registry" in manager._registry.log_buffers

    manager._registry.log_buffers["ses_from_facade"] = []
    assert "ses_from_facade" in manager._registry.log_buffers

    manager._registry.command_counts["ses_from_registry"] = 7
    assert manager._registry.command_counts["ses_from_registry"] == 7

    manager._registry.command_counts["ses_from_facade"] = 3
    assert manager._registry.command_counts["ses_from_facade"] == 3


def test_leg_d_the_public_methods_read_and_write_the_registry(manager, tmp_path):
    _register(manager, "ses_d", tmp_path)

    manager.add_log_entry("first line", session_id="ses_d")
    assert [e.content for e in manager._registry.log_buffers["ses_d"]] == [
        "first line"
    ]

    manager._registry.append_log("ses_d", "second line")
    assert [e.content for e in manager.get_recent_logs(session_id="ses_d")] == [
        "first line",
        "second line",
    ]


def test_leg_d_the_teardown_clears_the_registry(manager, tmp_path):
    _register(manager, "ses_wipe", tmp_path)
    manager.add_log_entry("something", session_id="ses_wipe")
    manager._registry.count_command("ses_wipe")
    assert "ses_wipe" in manager._registry.log_buffers

    manager._wipe_session_state("ses_wipe")

    assert "ses_wipe" not in manager._registry.log_buffers
    assert "ses_wipe" not in manager._registry.command_counts


def test_leg_e_an_injected_registry_is_the_one_the_facade_uses(
    stub_settings, tmp_path
):
    injected = SessionRegistry(log_cap=lambda: 3)
    manager = SessionManager(registry=injected)

    assert manager._registry is injected
    assert manager._registry.log_buffers is injected.log_buffers

    _register(manager, "ses_inject", tmp_path)
    manager.add_log_entry("via the facade", session_id="ses_inject")
    assert [e.content for e in injected.log_buffers["ses_inject"]] == [
        "via the facade"
    ]


def test_the_constructor_still_takes_no_arguments(stub_settings):
    manager = SessionManager()
    assert isinstance(manager._registry, SessionRegistry)




def test_the_cap_is_read_through_the_patched_settings_object(
    stub_settings, manager, tmp_path
):
    stub_settings.log_buffer_size = 2
    _register(manager, "ses_cap", tmp_path)

    for i in range(5):
        manager.add_log_entry(f"line {i}", session_id="ses_cap")

    kept = [e.content for e in manager.get_recent_logs(session_id="ses_cap")]
    assert kept == ["line 3", "line 4"]


def test_the_cap_is_re_read_per_append_not_captured(stub_settings, manager, tmp_path):
    stub_settings.log_buffer_size = 10
    _register(manager, "ses_recap", tmp_path)
    for i in range(6):
        manager.add_log_entry(f"line {i}", session_id="ses_recap")
    assert len(manager._registry.log_buffers["ses_recap"]) == 6

    stub_settings.log_buffer_size = 2
    manager.add_log_entry("line 6", session_id="ses_recap")

    kept = [e.content for e in manager._registry.log_buffers["ses_recap"]]
    assert kept == ["line 5", "line 6"]




def test_the_trim_drops_the_oldest_and_keeps_the_newest():
    registry = SessionRegistry(log_cap=lambda: 3)
    for i in range(6):
        registry.append_log("ses_1", f"line {i}")

    assert [e.content for e in registry.log_buffers["ses_1"]] == [
        "line 3",
        "line 4",
        "line 5",
    ]


def test_append_creates_the_buffer_for_an_unseen_session(registry):
    entry = registry.append_log("ses_new", "hello", "stderr")

    assert registry.log_buffers["ses_new"] == [entry]
    assert entry.log_type == "stderr"
    assert entry.session_id == "ses_new"


def test_ensure_is_idempotent_and_never_clobbers(registry):
    registry.append_log("ses_1", "already here")
    registry.count_command("ses_1")

    registry.ensure("ses_1")

    assert len(registry.log_buffers["ses_1"]) == 1
    assert registry.command_counts["ses_1"] == 1


def test_ensure_gives_a_fresh_session_both_containers(registry):
    registry.ensure("ses_fresh")

    assert registry.log_buffers["ses_fresh"] == []
    assert registry.command_counts["ses_fresh"] == 0


def test_forget_drops_both_containers_for_one_session(registry):
    registry.append_log("ses_1", "x")
    registry.count_command("ses_1")

    registry.forget("ses_1")

    assert "ses_1" not in registry.log_buffers
    assert "ses_1" not in registry.command_counts


def test_forget_leaves_every_other_session_alone(registry):
    registry.append_log("ses_1", "mine")
    registry.append_log("ses_2", "theirs")
    registry.count_command("ses_2")

    registry.forget("ses_1")

    assert [e.content for e in registry.log_buffers["ses_2"]] == ["theirs"]
    assert registry.command_counts["ses_2"] == 1


def test_forgetting_an_unknown_session_is_a_noop(registry):
    registry.forget("ses_never_seen")

    assert registry.log_buffers == {}
    assert registry.command_counts == {}


def test_counting_creates_the_counter_for_an_unseen_session(registry):
    assert registry.count_command("ses_x") == 1
    assert registry.count_command("ses_x") == 2
    assert registry.command_count("ses_x") == 2


def test_counts_are_scoped_to_the_session(registry):
    registry.count_command("ses_1")
    registry.count_command("ses_1")
    registry.count_command("ses_2")

    assert registry.command_count("ses_1") == 2
    assert registry.command_count("ses_2") == 1


def test_reads_of_an_unknown_session_answer_empty_and_create_nothing(registry):
    assert registry.recent_logs("ses_ghost", 100) == []
    assert registry.command_count("ses_ghost") == 0
    assert registry.log_line_count("ses_ghost") == 0

    assert registry.log_buffers == {}
    assert registry.command_counts == {}


def test_recent_logs_honours_the_limit_and_returns_the_newest(registry):
    for i in range(5):
        registry.append_log("ses_1", f"line {i}")

    assert [e.content for e in registry.recent_logs("ses_1", 2)] == [
        "line 3",
        "line 4",
    ]


def test_recent_logs_hands_back_a_new_list_not_the_live_buffer(registry):
    registry.append_log("ses_1", "line 0")

    view = registry.recent_logs("ses_1", 100)
    view.clear()

    assert registry.log_line_count("ses_1") == 1
