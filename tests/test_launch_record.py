
from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.agent_wrappers import AgentWrapper
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.launch_record import launch_record, record_launch_on_row
from src.core.session_create_persist import persist_creation
from src.core.trail_entry import utc_now
from src.core.tmux_listing import TmuxListing

SKIP = AgentWrapper(id="claude-skip-permissions", label="skip", script="claude", default=True)
CLX = AgentWrapper(id="keyc", label="keyc", script="claude")
CODEX = AgentWrapper(id="codex-yolo", family="codex", label="codex", script="codex")
WRAPPERS = [CLX, SKIP, CODEX]




def test_the_bare_family_records_the_default_wrapper_that_ran():
    rec = launch_record("claude", WRAPPERS)
    assert (rec.family, rec.agent_type) == ("claude", "claude-skip-permissions")


def test_nothing_named_records_the_default_wrapper_too():
    assert launch_record(None, WRAPPERS).agent_type == "claude-skip-permissions"


def test_a_named_wrapper_records_itself():
    assert launch_record("keyc", WRAPPERS).agent_type == "keyc"
    assert launch_record("codex-yolo", WRAPPERS).family == "codex"


def test_an_unknown_value_records_the_wrapper_the_launch_falls_back_to():
    assert launch_record("gone-wrapper", WRAPPERS).agent_type == "claude-skip-permissions"


def test_with_no_wrapper_for_the_family_the_family_name_is_what_ran():
    assert launch_record("claude", [CODEX]).agent_type == "claude"
    assert launch_record("shell", WRAPPERS).agent_type == "shell"


def test_the_family_default_follows_list_order_when_none_is_marked():
    plain = [CLX, AgentWrapper(id="clxor", label="clxor", script="claude")]
    assert launch_record("claude", plain).agent_type == "keyc"



OLD_EPOCH = 1700000000
NEW_EPOCH = 1800000000
NAME = "carnivore_3d_work"


@pytest.fixture
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    c = connect(db_path_for(state))
    yield c
    c.close()


def _insert(conn, **overrides):
    row = {
        "session_uuid": "u-3d", "origin": "adopted", "tmux_socket": "cloude",
        "tmux_name": NAME, "tmux_created_epoch": OLD_EPOCH, "working_dir": "/w/3d",
        "agent_type": "claude", "agent_family": "claude",
        "agent_family_source": "launched", "claude_session_uuid": "conv-3d",
        "lifecycle": "stopped", "lifecycle_source": "slept_by_timer",
        "created_at": utc_now(), "updated_at": utc_now(),
    }
    row.update(overrides)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO sessions ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            list(row.values()),
        )
    return int(cur.lastrowid)


def _listing(epoch=NEW_EPOCH):
    return TmuxListing.answered([
        {"name": NAME, "created_at_epoch": epoch, "session_id": "$9",
         "window_count": 1, "working_dir": "/w/3d"},
    ])


def _reuse(conn, row_id, **kw):
    args = dict(agent_type="claude-skip-permissions", agent_family="claude", agent_launched=True)
    args.update(kw)
    with transaction(conn):
        return persist_creation(
            conn, socket="cloude", name=NAME, listing=_listing(),
            working_dir="/w/3d", reuse_session_id=row_id, **args,
        )


def test_a_recreate_records_the_wrapper_it_launched_on_the_reused_row(conn):
    row_id = _insert(conn)
    assert _reuse(conn, row_id).recorded
    row = dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (row_id,)).fetchone())
    assert int(row["tmux_created_epoch"]) == NEW_EPOCH, "the rebind itself must still run"
    assert row["agent_type"] == "claude-skip-permissions"
    assert row["agent_family"] == "claude"
    assert row["agent_family_source"] == "launched"


def test_a_recreate_replaces_an_inference_with_the_launch_fact(conn):
    row_id = _insert(conn, agent_family_source="inferred_process")
    _reuse(conn, row_id, agent_type="keyc")
    row = conn.execute("SELECT agent_type, agent_family_source FROM sessions WHERE id = ?",
                       (row_id,)).fetchone()
    assert (row["agent_type"], row["agent_family_source"]) == ("keyc", "launched")


def test_a_bare_shell_recreate_records_no_agent(conn):
    row_id = _insert(conn)
    _reuse(conn, row_id, agent_launched=False)
    row = conn.execute("SELECT agent_type, agent_family, agent_family_source FROM sessions "
                       "WHERE id = ?", (row_id,)).fetchone()
    assert tuple(row) == (None, None, "not_launched")


def test_a_caller_that_did_not_say_writes_nothing(conn):
    row_id = _insert(conn, agent_type="keyc")
    _reuse(conn, row_id, agent_type=None, agent_family=None, agent_launched=None)
    assert conn.execute("SELECT agent_type FROM sessions WHERE id = ?",
                        (row_id,)).fetchone()[0] == "keyc"
    assert record_launch_on_row(conn, row_id=row_id, agent_type="x", agent_family="y",
                                family_source=None) is False




@pytest.fixture
def env(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state_dir = tmp_path / "state"
    log_dir.mkdir()
    state_dir.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    ensure_db_migrated(state_dir)
    return state_dir


@pytest.mark.asyncio
async def test_create_with_nothing_named_records_the_default_wrapper(env, tmp_path, monkeypatch):
    from src.core import session_manager as sm

    asked = []

    def _command(agent_type, model=None, extra_args=None):
        asked.append(agent_type)
        return "sleep 30"

    monkeypatch.setattr(type(settings), "get_agent_command",
                        lambda self, a, model=None, extra_args=None, **_kw: _command(a, model, extra_args))
    monkeypatch.setattr(sm, "_configured_wrappers", lambda: WRAPPERS)
    work = tmp_path / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]
    mgr = sm.SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}", working_dir=str(work),
            auto_start_claude=True, project_name=f"lr{token}",
        )
        assert asked == ["claude"], "the launch itself still resolves the family"
        with closing(connect(db_path_for(env))) as handle:
            row = handle.execute(
                "SELECT agent_type, agent_family, agent_family_source FROM sessions "
                "WHERE tmux_name = ?", (session.tmux_session,),
            ).fetchone()
        assert row is not None
        assert tuple(row) == ("claude-skip-permissions", "claude", "launched"), (
            "the row must name the wrapper that ran, not the bare family"
        )
        assert session.agent_type == "claude-skip-permissions"
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)
