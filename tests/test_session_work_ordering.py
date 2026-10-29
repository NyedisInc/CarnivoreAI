
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_workord_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_workord_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core import claude_hooks
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_writes import create_project, list_projects_ordered, touch_project_by_path
from src.core.session_work_stamp import SOURCE_EXACT_EPOCH, stamp_work

SOCKET = "cloude"


@pytest.fixture
def conn(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    result = ensure_db_migrated(state, 4, "0.0.0")
    assert result.status == "ok", result.message
    with closing(connect(db_path_for(state))) as c:
        yield c


def _session(conn, *, name: str, epoch: int, project_id=None, last_work_at=None) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, "
        "tmux_created_epoch, lifecycle, project_attribution, project_id, "
        "last_work_at, created_at, updated_at) "
        "VALUES (?, 'created', ?, ?, ?, 'running', 'explicit', ?, ?, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (f"uuid-{name}-{epoch}", SOCKET, name, epoch, project_id, last_work_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def _order(conn) -> list:
    return [row["display_name"] for row in list_projects_ordered(conn)]




def test_the_column_exists_at_the_current_schema(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "last_work_at" in cols


def test_a_stamp_lands_on_the_exact_instance_when_the_epoch_is_known(conn):
    _session(conn, name="cloude_Mac", epoch=100)
    row_id = _session(conn, name="cloude_Mac", epoch=200)
    assert stamp_work(
        conn, "cloude_Mac", tmux_socket=SOCKET, tmux_created_epoch=200,
        now="2026-09-03T10:00:00Z",
    ) == SOURCE_EXACT_EPOCH
    conn.commit()
    stamps = dict(conn.execute("SELECT id, last_work_at FROM sessions"))
    assert stamps[row_id] == "2026-09-03T10:00:00Z"
    assert set(stamps.values()) == {"2026-09-03T10:00:00Z", None}


def test_without_an_epoch_NOTHING_is_written(conn):
    old = _session(conn, name="cloude_Mac", epoch=100)
    new = _session(conn, name="cloude_Mac", epoch=200)
    assert stamp_work(
        conn, "cloude_Mac", tmux_socket=SOCKET, tmux_created_epoch=None,
    ) is None
    conn.commit()
    stamps = dict(conn.execute("SELECT id, last_work_at FROM sessions"))
    assert stamps[old] is None and stamps[new] is None


def test_an_unknown_name_writes_NOTHING_rather_than_guessing(conn):
    _session(conn, name="cloude_Mac", epoch=100)
    assert stamp_work(
        conn, "cloude_Nobody", tmux_socket=SOCKET, tmux_created_epoch=100,
    ) is None
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT last_work_at FROM sessions")] == [None]


def test_a_wrong_epoch_is_a_refusal_not_a_name_match(conn):
    _session(conn, name="cloude_Mac", epoch=100)
    assert stamp_work(
        conn, "cloude_Mac", tmux_socket=SOCKET, tmux_created_epoch=999,
    ) is None
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT last_work_at FROM sessions")] == [None]


def test_a_wrong_socket_is_a_refusal_not_a_name_match(conn):
    _session(conn, name="cloude_Mac", epoch=100)
    assert stamp_work(
        conn, "cloude_Mac", tmux_socket="other-socket", tmux_created_epoch=100,
    ) is None




def test_resuming_a_conversation_is_not_work(conn):
    assert "SessionStart" not in claude_hooks.WORK_EVENTS
    assert "SessionEnd" not in claude_hooks.WORK_EVENTS
    for kind in claude_hooks.LIFECYCLE_EVENTS:
        assert kind not in claude_hooks.WORK_EVENTS


def test_every_non_lifecycle_managed_event_IS_work(conn):
    managed = set(
        claude_hooks.TOAST_EVENTS
        + claude_hooks.ACTIVITY_ONLY_EVENTS
        + claude_hooks.LIFECYCLE_EVENTS
    )
    assert set(claude_hooks.WORK_EVENTS) == managed - set(claude_hooks.LIFECYCLE_EVENTS)
    for kind in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert kind in claude_hooks.WORK_EVENTS




def test_projects_are_ordered_by_work_not_by_id(conn):
    a = create_project(conn, name="alpha", path="/tmp/alpha")["id"]
    b = create_project(conn, name="beta", path="/tmp/beta")["id"]
    c = create_project(conn, name="gamma", path="/tmp/gamma")["id"]
    _session(conn, name="s_a", epoch=1, project_id=a, last_work_at="2026-09-01T00:00:00Z")
    _session(conn, name="s_b", epoch=2, project_id=b, last_work_at="2026-09-03T00:00:00Z")
    _session(conn, name="s_c", epoch=3, project_id=c, last_work_at="2026-09-02T00:00:00Z")
    assert _order(conn) == ["beta", "gamma", "alpha"]


def test_the_rollup_takes_the_MAX_across_a_projects_sessions(conn):
    a = create_project(conn, name="alpha", path="/tmp/alpha")["id"]
    b = create_project(conn, name="beta", path="/tmp/beta")["id"]
    _session(conn, name="s_a1", epoch=1, project_id=a, last_work_at="2026-01-01T00:00:00Z")
    _session(conn, name="s_a2", epoch=2, project_id=a, last_work_at="2026-09-09T00:00:00Z")
    _session(conn, name="s_b1", epoch=3, project_id=b, last_work_at="2026-09-08T00:00:00Z")
    assert _order(conn) == ["alpha", "beta"]
    rows = {r["display_name"]: r["work_at"] for r in list_projects_ordered(conn)}
    assert rows["alpha"] == "2026-09-09T00:00:00Z"


def test_touching_a_project_does_not_reorder_it(conn):
    a = create_project(conn, name="alpha", path="/tmp/alpha")["id"]
    b = create_project(conn, name="beta", path="/tmp/beta")["id"]
    _session(conn, name="s_a", epoch=1, project_id=a, last_work_at="2026-09-01T00:00:00Z")
    _session(conn, name="s_b", epoch=2, project_id=b, last_work_at="2026-09-03T00:00:00Z")
    before = _order(conn)
    assert before == ["beta", "alpha"]

    touched = touch_project_by_path(conn, "/tmp/alpha", now="2026-12-31T23:59:59Z")
    assert touched is not None
    assert touched["last_opened_at"] == "2026-12-31T23:59:59Z", (
        "last_opened_at must still be written - it is kept, just not ordered by"
    )
    assert _order(conn) == before, (
        "opening a project reordered the launcher - this is the regression"
    )


def test_work_reorders_it_and_a_touch_still_does_not(conn):
    a = create_project(conn, name="alpha", path="/tmp/alpha")["id"]
    b = create_project(conn, name="beta", path="/tmp/beta")["id"]
    _session(conn, name="s_a", epoch=1, project_id=a, last_work_at="2026-09-01T00:00:00Z")
    _session(conn, name="s_b", epoch=2, project_id=b, last_work_at="2026-09-03T00:00:00Z")
    assert _order(conn) == ["beta", "alpha"]

    assert stamp_work(
        conn, "s_a", tmux_socket=SOCKET, tmux_created_epoch=1,
        now="2026-09-04T00:00:00Z",
    ) == SOURCE_EXACT_EPOCH
    conn.commit()
    assert _order(conn) == ["alpha", "beta"]


def test_a_project_with_no_recorded_work_sorts_below_every_one_that_has(conn):
    create_project(conn, name="never", path="/tmp/never")
    b = create_project(conn, name="worked", path="/tmp/worked")["id"]
    _session(conn, name="s_b", epoch=1, project_id=b, last_work_at="1970-01-01T00:00:01Z")
    assert _order(conn) == ["worked", "never"]
    rows = {r["display_name"]: r["work_at"] for r in list_projects_ordered(conn)}
    assert rows["never"] is None, "unrecorded must be NULL, never a date nobody measured"


def test_unrecorded_projects_keep_a_stable_insertion_order(conn):
    for name in ("first", "second", "third"):
        create_project(conn, name=name, path=f"/tmp/{name}")
    assert _order(conn) == ["first", "second", "third"]
    touch_project_by_path(conn, "/tmp/third", now="2026-12-31T23:59:59Z")
    assert _order(conn) == ["first", "second", "third"]


def test_a_projects_own_sessions_are_the_only_ones_counted(conn):
    a = create_project(conn, name="alpha", path="/tmp/alpha")["id"]
    b = create_project(conn, name="beta", path="/tmp/beta")["id"]
    _session(conn, name="s_a", epoch=1, project_id=a, last_work_at="2026-09-01T00:00:00Z")
    _session(conn, name="s_b", epoch=2, project_id=b, last_work_at="2026-09-09T00:00:00Z")
    _session(conn, name="s_none", epoch=3, project_id=None,
             last_work_at="2026-12-31T00:00:00Z")
    assert _order(conn) == ["beta", "alpha"]




def _routing_probe():
    import types

    calls: list = []
    probe = types.SimpleNamespace(
        _last_work_stamp_at={},
        _instance_epochs={},
        _work_stamp_epoch=lambda sid, name: calls.append((sid, name)) or None,
    )
    return probe, calls


@pytest.mark.parametrize(
    "kind,is_work",
    [
        ("UserPromptSubmit", True),
        ("PreToolUse", True),
        ("PostToolUse", True),
        ("Stop", True),
        ("Notification", True),
        ("PermissionRequest", True),
        ("SubagentStart", True),
        ("SubagentStop", True),
        ("SessionStart", False),
        ("SessionEnd", False),
    ],
)
def test_only_work_events_reach_the_stamp(kind, is_work):
    from src.core.session_manager import SessionManager

    probe, calls = _routing_probe()
    SessionManager._persist_work_stamp(probe, "ses_1", "cloude_x", kind)
    assert bool(calls) is is_work, kind


def test_the_first_event_is_never_throttled_and_the_second_is():
    from src.core.session_manager import SessionManager

    probe, calls = _routing_probe()
    SessionManager._persist_work_stamp(probe, "ses_2", "cloude_x", "PreToolUse")
    SessionManager._persist_work_stamp(probe, "ses_2", "cloude_x", "PreToolUse")
    assert len(calls) == 1


def test_a_session_with_no_tmux_name_is_not_stamped():
    from src.core.session_manager import SessionManager

    probe, calls = _routing_probe()
    SessionManager._persist_work_stamp(probe, "ses_3", None, "PreToolUse")
    assert calls == []
