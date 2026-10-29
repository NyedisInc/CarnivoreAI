
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_adead_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_adead_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_CREATED
from src.core.session_adopt_dead_gate import (
    PERSIST_PANE_DEAD,
    make_pane_dead_probe,
    probe_session_pane_dead,
    should_refuse_dead_husk,
)
from src.core.session_adopt_persist import persist_adoption
from src.core.session_identity import ADOPT_CLAIMED, record_instance
from src.core.session_manager import SessionManager
from src.core.tmux_backend import TmuxBackend
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

DEAD_WAIT_SECONDS: float = 15.0
PANE_READY = "CC_DEAD_PANE_READY"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _field(name: str, fmt: str) -> str:
    out = _tmux("list-panes", "-a", "-F", "#{session_name}\t" + fmt).stdout
    for line in out.splitlines():
        session_name, _, value = line.partition("\t")
        if session_name == name:
            return value.strip()
    return ""


def _new_session(name: str) -> int:
    command = f"/bin/sh -c 'printf {PANE_READY}; read line'"
    result = _tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "40", command)
    assert result.returncode == 0, result.stderr
    return int(_field(name, "#{session_created}"))


def _kill_pane_process(name: str) -> None:
    option = _tmux("set-option", "-t", name, "remain-on-exit", "on")
    assert option.returncode == 0, option.stderr
    deadline = time.monotonic() + DEAD_WAIT_SECONDS
    while time.monotonic() < deadline:
        screen = _tmux("capture-pane", "-p", "-t", name)
        assert screen.returncode == 0, screen.stderr
        if PANE_READY in screen.stdout:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the pane child never became ready for input")
    sent = _tmux("send-keys", "-t", name, "exit", "Enter")
    assert sent.returncode == 0, sent.stderr
    deadline = time.monotonic() + DEAD_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _field(name, "#{pane_dead}") == "1":
            return
        time.sleep(0.1)
    raise AssertionError("could not get the pane into the dead state")


def _listing():
    probe = TmuxBackend(
        session_id="probe",
        working_dir=Path.home(),
        on_output=None,
        socket_name=TEST_SOCKET_NAME,
    )
    return probe.list_attachable_sessions()


def _rows_named(state: Path, name: str) -> list:
    with closing(connect(db_path_for(state))) as conn:
        rows = conn.execute(
            "SELECT tmux_created_epoch, origin FROM sessions WHERE tmux_name = ?",
            (name,),
        ).fetchall()
    return [tuple(row) for row in rows]


def _adopt(state: Path, name: str, probe=None):
    with closing(connect(db_path_for(state))) as conn:
        result = persist_adoption(
            conn,
            socket=TEST_SOCKET_NAME,
            name=name,
            listing=_listing(),
            pane_dead_probe=probe or make_pane_dead_probe(TEST_SOCKET_NAME),
        )
        conn.commit()
    return result


@pytest.fixture
def live_state(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass
    try:
        yield state
    finally:
        _tmux("kill-server")




def test_rule_refuses_only_a_measured_dead_pane_with_no_row():
    assert should_refuse_dead_husk(stored_row=None, pane_dead=True) is True
    assert should_refuse_dead_husk(stored_row={}, pane_dead=True) is True
    assert should_refuse_dead_husk(stored_row=None, pane_dead=False) is False
    assert should_refuse_dead_husk(stored_row=None, pane_dead=None) is False
    assert should_refuse_dead_husk(stored_row={"id": 1}, pane_dead=True) is False




@requires_tmux
def test_probe_reads_live_dead_and_missing_as_three_answers(live_state):
    name = f"ext_probe_{uuid.uuid4().hex[:6]}"
    _new_session(name)
    assert probe_session_pane_dead(name, socket=TEST_SOCKET_NAME) is False
    _kill_pane_process(name)
    assert probe_session_pane_dead(name, socket=TEST_SOCKET_NAME) is True
    assert probe_session_pane_dead("no_such_session_x", socket=TEST_SOCKET_NAME) is None


@requires_tmux
def test_a_dead_husk_is_not_persisted(live_state):
    name = f"ext_husk_{uuid.uuid4().hex[:6]}"
    _new_session(name)
    _kill_pane_process(name)

    result = _adopt(live_state, name)

    assert result.outcome == PERSIST_PANE_DEAD
    assert result.persisted is False
    assert _rows_named(live_state, name) == []


@requires_tmux
def test_control_a_live_external_pane_is_still_persisted(live_state):
    name = f"ext_live_{uuid.uuid4().hex[:6]}"
    epoch = _new_session(name)

    result = _adopt(live_state, name)

    assert result.outcome == ADOPT_CLAIMED
    assert _rows_named(live_state, name) == [(epoch, "adopted")]


@requires_tmux
def test_a_dead_husk_sharing_a_rows_name_at_another_epoch_mints_nothing(live_state):
    name = f"ext_twin_{uuid.uuid4().hex[:6]}"
    epoch = _new_session(name)
    earlier = epoch - 86400
    with closing(connect(db_path_for(live_state))) as conn:
        record_instance(
            conn, socket=TEST_SOCKET_NAME, name=name, epoch=earlier,
            origin=SESSION_ORIGIN_CREATED, working_dir=str(Path.home()),
        )
        conn.commit()
    _kill_pane_process(name)

    result = _adopt(live_state, name)

    assert result.outcome == PERSIST_PANE_DEAD
    assert _rows_named(live_state, name) == [(earlier, "created")]


@requires_tmux
def test_a_dead_pane_that_already_has_a_row_keeps_todays_behaviour(live_state):
    name = f"ext_known_{uuid.uuid4().hex[:6]}"
    epoch = _new_session(name)
    with closing(connect(db_path_for(live_state))) as conn:
        record_instance(
            conn, socket=TEST_SOCKET_NAME, name=name, epoch=epoch,
            origin=SESSION_ORIGIN_CREATED, working_dir=str(Path.home()),
        )
        conn.commit()
    _kill_pane_process(name)

    result = _adopt(live_state, name)

    assert result.outcome != PERSIST_PANE_DEAD
    assert len(_rows_named(live_state, name)) == 1


@requires_tmux
def test_an_unmeasured_pane_is_not_treated_as_dead(live_state):
    name = f"ext_unk_{uuid.uuid4().hex[:6]}"
    epoch = _new_session(name)
    _kill_pane_process(name)

    result = _adopt(live_state, name, probe=lambda _name: None)

    assert result.outcome == ADOPT_CLAIMED
    assert _rows_named(live_state, name) == [(epoch, "adopted")]


@requires_tmux
def test_the_manager_wires_the_real_probe(live_state):
    name = f"ext_mgr_{uuid.uuid4().hex[:6]}"
    _new_session(name)
    _kill_pane_process(name)

    result = SessionManager().persist_adoption(name)

    assert result.outcome == PERSIST_PANE_DEAD
    assert _rows_named(live_state, name) == []
