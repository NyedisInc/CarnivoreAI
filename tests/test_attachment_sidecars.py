
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_as_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_as_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.session_manager import SessionManager
from src.core.sessions.sidecars import AttachmentSidecars
from src.models import Session, SessionStatus




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path) -> None:
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.log_buffer_size = 1000

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
def sidecars() -> AttachmentSidecars:
    return AttachmentSidecars()


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




def test_leg_a_the_facade_containers_are_the_sidecar_containers(manager):
    assert manager._sidecars.adopt_fifo_offsets is manager._sidecars.adopt_fifo_offsets


def test_leg_b_the_facade_holds_no_field_of_its_own(manager):
    for name in ("adopt_fifo_offsets", "pending_terminal_commands"):
        assert not hasattr(manager, name), (
            f"{name} resolves on the facade again; the sidecars own it and "
            "a caller holds the sidecars"
        )
    assert manager._sidecars.adopt_fifo_offsets is not None


def test_leg_c_writes_cross_in_both_directions(manager):
    manager._sidecars.set_fifo_offset("ses_from_sidecars", 512)
    assert manager._sidecars.adopt_fifo_offsets["ses_from_sidecars"] == 512

    manager._sidecars.adopt_fifo_offsets["ses_from_facade"] = 1024
    assert manager._sidecars.peek_fifo_offset("ses_from_facade") == 1024



def test_the_offset_name_is_read_only(manager):
    assert not hasattr(manager, "adopt_fifo_offsets")

    real = manager._sidecars.adopt_fifo_offsets
    manager.adopt_fifo_offsets = {}  # type: ignore[attr-defined]

    assert manager._sidecars.adopt_fifo_offsets is real, (
        "a stray assignment on the facade reached the sidecars' container"
    )


def test_leg_d_the_public_surface_reads_and_writes_the_sidecars(
    manager, tmp_path
):
    _register(manager, "ses_d", tmp_path)
    manager._sidecars.set_fifo_offset("ses_d", 4096)

    assert manager.adopt_fifo_start_offset == 4096


def test_leg_d_the_teardown_clears_the_sidecars(manager, tmp_path):
    _register(manager, "ses_wipe", tmp_path)
    manager._sidecars.set_fifo_offset("ses_wipe", 4096)

    manager._wipe_session_state("ses_wipe")

    assert "ses_wipe" not in manager._sidecars.adopt_fifo_offsets


def test_leg_f_injected_sidecars_are_the_ones_the_facade_uses(stub_settings):
    injected = AttachmentSidecars()
    manager = SessionManager(sidecars=injected)

    assert manager._sidecars is injected

    injected.set_fifo_offset("ses_1", 77)
    assert manager._sidecars.adopt_fifo_offsets["ses_1"] == 77


def test_the_constructor_still_takes_no_arguments(stub_settings):
    manager = SessionManager()
    assert isinstance(manager._sidecars, AttachmentSidecars)




def test_the_fifo_offset_is_consumed_exactly_once(manager, tmp_path):
    _register(manager, "ses_1", tmp_path)
    manager._sidecars.set_fifo_offset("ses_1", 4096)

    assert manager.consume_adopt_fifo_offset("ses_1") == 4096
    assert manager.consume_adopt_fifo_offset("ses_1") is None
    assert "ses_1" not in manager._sidecars.adopt_fifo_offsets


def test_reading_the_offset_property_does_not_consume_it(manager, tmp_path):
    _register(manager, "ses_1", tmp_path)
    manager._sidecars.set_fifo_offset("ses_1", 4096)

    assert manager.adopt_fifo_start_offset == 4096
    assert manager.adopt_fifo_start_offset == 4096
    assert manager.consume_adopt_fifo_offset("ses_1") == 4096


def test_consuming_an_offset_for_an_unknown_session_answers_none(manager):
    assert manager.consume_adopt_fifo_offset("ses_never_adopted") is None





def test_reads_of_an_unknown_session_answer_none(sidecars):
    assert sidecars.peek_fifo_offset("ses_ghost") is None
    assert sidecars.take_fifo_offset("ses_ghost") is None


def test_reads_of_an_unknown_session_create_nothing(sidecars):
    sidecars.peek_fifo_offset("ses_ghost")
    sidecars.take_fifo_offset("ses_ghost")

    assert sidecars.adopt_fifo_offsets == {}


def test_a_zero_offset_is_a_real_offset_and_not_a_miss(sidecars):
    sidecars.set_fifo_offset("ses_1", 0)

    assert sidecars.peek_fifo_offset("ses_1") == 0
    assert sidecars.take_fifo_offset("ses_1") == 0
    assert sidecars.take_fifo_offset("ses_1") is None


def test_forget_drops_the_offset(sidecars):
    sidecars.set_fifo_offset("ses_1", 4096)

    sidecars.forget("ses_1")

    assert "ses_1" not in sidecars.adopt_fifo_offsets


def test_forget_leaves_every_other_session_alone(sidecars):
    sidecars.set_fifo_offset("ses_1", 512)
    sidecars.set_fifo_offset("ses_2", 4096)

    sidecars.forget("ses_1")

    assert sidecars.peek_fifo_offset("ses_1") is None
    assert sidecars.peek_fifo_offset("ses_2") == 4096


def test_forgetting_an_unknown_session_is_a_noop(sidecars):
    sidecars.forget("ses_never_seen")

    assert sidecars.adopt_fifo_offsets == {}




def test_the_login_line_is_one_shot_like_the_command(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")

    assert sidecars.take_pending_login("ses_1") == "claude1"
    assert sidecars.take_pending_login("ses_1") is None


def test_the_account_to_session_record_outlives_the_flush(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")
    sidecars.take_pending_login("ses_1")

    assert sidecars.login_session_for("claude1") == "ses_1"


def test_an_account_with_no_login_answers_none(sidecars):
    assert sidecars.login_session_for("never-logged-in") is None
    assert sidecars.login_sessions == {}


def test_forget_drops_the_pending_login(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")

    sidecars.forget("ses_1")

    assert sidecars.pending_logins == {}


def test_forget_drops_that_sessions_login_record(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")

    sidecars.forget("ses_1")

    assert sidecars.login_session_for("claude1") is None


def test_forget_leaves_another_accounts_login_alone(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")
    sidecars.set_pending_login("ses_2", "codex1")

    sidecars.forget("ses_1")

    assert sidecars.login_sessions == {"codex1": "ses_2"}
    assert sidecars.pending_logins == {"ses_2": "codex1"}


def test_a_second_login_for_one_account_replaces_the_record(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")
    sidecars.set_pending_login("ses_2", "claude1")

    assert sidecars.login_session_for("claude1") == "ses_2"


def test_forgetting_the_older_session_leaves_the_newer_record(sidecars):
    sidecars.set_pending_login("ses_1", "claude1")
    sidecars.set_pending_login("ses_2", "claude1")

    sidecars.forget("ses_1")

    assert sidecars.login_session_for("claude1") == "ses_2"
