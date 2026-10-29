
from __future__ import annotations

import os
import tempfile
import types
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_subwork_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_subwork_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.attention.evidence import FAMILY_CODEX
from src.core.attention.subagent_work import THROTTLE_SUFFIX, SubagentWorkStamp, iso_utc
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_work_stamp import stamp_work
from src.core.subagents.tally import (
    NOT_APPLICABLE,
    STATE_OK,
    UNCHECKED,
    SubagentTally,
)
from tests.test_attention_side_effects import (  # noqa: F401
    SESSION_ID,
    TARGET,
    TMUX_NAME,
    observation,
    wired,
)

SOCKET = "cloude"
EPOCH = 1789095742
PARENT_WORK = "2026-09-26T12:00:00Z"
T_PARENT = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def tally_at(at):
    return SubagentTally(STATE_OK, running=1, total=1, unknown=0, last_activity_at=at)


@pytest.fixture
def db(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    path = db_path_for(state)
    with closing(connect(path)) as c:
        cur = c.execute(
            "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, "
            "tmux_created_epoch, lifecycle, project_attribution, last_work_at, "
            "created_at, updated_at) VALUES ('u-parent', 'created', ?, ?, ?, "
            "'running', 'explicit', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (SOCKET, TMUX_NAME, EPOCH, PARENT_WORK),
        )
        c.commit()
        row_id = int(cur.lastrowid)
    updates: list = []

    def open_connection():
        conn = connect(path)
        conn.set_trace_callback(
            lambda sql: updates.append(sql) if sql.lstrip().upper().startswith("UPDATE SESSIONS") else None
        )
        return conn

    def read():
        with closing(connect(path)) as c:
            return c.execute("SELECT last_work_at FROM sessions WHERE id = ?", (row_id,)).fetchone()[0]

    return open_connection, updates, read


def real_manager(open_connection):
    from src.core.session_manager import SessionManager

    probe = types.SimpleNamespace(
        _last_work_stamp_at={},
        _work_stamp_epoch=lambda sid, name: EPOCH,
        _writable_datastore_connection=open_connection,
        _tmux_socket_name=lambda: SOCKET,
    )
    probe._persist_work_stamp = types.MethodType(SessionManager._persist_work_stamp, probe)
    return probe




def test_a_newer_subagent_line_moves_the_parents_last_work_at(db):
    open_connection, updates, read = db
    stamp = SubagentWorkStamp(real_manager(open_connection))
    newer = T_PARENT + timedelta(minutes=7)
    assert stamp.observe(SESSION_ID, TMUX_NAME, tally_at(newer)) is True
    assert read() == iso_utc(newer)
    assert len(updates) == 1


def test_an_older_subagent_line_does_not_move_it_backward(db):
    open_connection, updates, read = db
    stamp = SubagentWorkStamp(real_manager(open_connection))
    stamp.observe(SESSION_ID, TMUX_NAME, tally_at(T_PARENT - timedelta(hours=3)))
    assert read() == PARENT_WORK
    assert updates == []


def test_an_equal_instant_in_another_spelling_is_not_newer(db):
    open_connection, updates, read = db
    stamp = SubagentWorkStamp(real_manager(open_connection))
    stamp.observe(SESSION_ID, TMUX_NAME, tally_at(T_PARENT))
    assert read() == PARENT_WORK
    assert updates == []


def test_an_unchanged_instant_costs_no_write_on_later_cycles(db):
    open_connection, updates, read = db
    manager = real_manager(open_connection)
    stamp = SubagentWorkStamp(manager)
    newer = T_PARENT + timedelta(minutes=1)
    stamp.observe(SESSION_ID, TMUX_NAME, tally_at(newer))
    manager._last_work_stamp_at.clear()
    for _ in range(5):
        assert stamp.observe(SESSION_ID, TMUX_NAME, tally_at(newer)) is False
    assert len(updates) == 1
    assert read() == iso_utc(newer)


def test_a_subagent_stamp_never_uses_up_the_parents_own_throttle_slot(db):
    open_connection, updates, read = db
    manager = real_manager(open_connection)
    SubagentWorkStamp(manager).observe(
        SESSION_ID, TMUX_NAME, tally_at(T_PARENT + timedelta(minutes=1)))
    assert set(manager._last_work_stamp_at) == {f"{SESSION_ID}{THROTTLE_SUFFIX}"}
    assert manager._persist_work_stamp(SESSION_ID, TMUX_NAME, None) is True
    assert len(updates) == 2


def test_a_throttled_instant_is_retried_not_forgotten(db):
    open_connection, updates, read = db
    manager = real_manager(open_connection)
    stamp = SubagentWorkStamp(manager)
    first = T_PARENT + timedelta(minutes=1)
    second = T_PARENT + timedelta(minutes=2)
    stamp.observe(SESSION_ID, TMUX_NAME, tally_at(first))
    assert stamp.observe(SESSION_ID, TMUX_NAME, tally_at(second)) is False
    assert read() == iso_utc(first)
    manager._last_work_stamp_at.clear()
    assert stamp.observe(SESSION_ID, TMUX_NAME, tally_at(second)) is True
    assert read() == iso_utc(second)


def test_stamp_work_refuses_an_older_instant_on_the_real_row(db):
    open_connection, _updates, read = db
    with closing(open_connection()) as conn:
        assert stamp_work(conn, TMUX_NAME, tmux_socket=SOCKET, tmux_created_epoch=EPOCH,
                          now="2026-09-26T11:00:00Z") is None
        assert stamp_work(conn, TMUX_NAME, tmux_socket=SOCKET, tmux_created_epoch=EPOCH,
                          now="2026-09-26T13:00:00Z") is not None
    assert read() == "2026-09-26T13:00:00Z"




@pytest.mark.parametrize(
    "tally",
    [NOT_APPLICABLE, UNCHECKED, None, SubagentTally(STATE_OK, running=0, total=0, unknown=0)],
    ids=["codex-or-shell", "unchecked", "unmeasured", "no-agent-activity"],
)
def test_rows_with_no_measured_subagent_instant_are_untouched(db, tally):
    open_connection, updates, read = db
    manager = real_manager(open_connection)
    assert SubagentWorkStamp(manager).observe(SESSION_ID, TMUX_NAME, tally) is False
    assert updates == [] and manager._last_work_stamp_at == {}
    assert read() == PARENT_WORK




def with_subagents(obs, tally, family=None):
    fields = {"subagents": tally}
    if family is not None:
        fields["agent_family"] = family
    return replace(obs, evidence=replace(obs.evidence, **fields))


def test_on_observation_hands_a_claude_rows_instant_to_the_writer(wired):
    manager, effects, _calls = wired
    at = T_PARENT + timedelta(minutes=3)
    effects.on_observation(TARGET, with_subagents(observation(), tally_at(at)))
    assert manager.work_stamps == [(SESSION_ID, TMUX_NAME, None)]
    assert manager.work_stamp_kwargs == [
        {"at": iso_utc(at), "throttle_key": f"{SESSION_ID}{THROTTLE_SUFFIX}"}]
    effects.on_observation(TARGET, with_subagents(observation(), tally_at(at)))
    assert len(manager.work_stamps) == 1


def test_on_observation_never_stamps_a_codex_row(wired):
    manager, effects, _calls = wired
    reading = with_subagents(observation(), tally_at(T_PARENT), family=FAMILY_CODEX)
    effects.on_observation(TARGET, reading)
    assert manager.work_stamps == []


def test_on_observation_without_a_tally_stamps_nothing(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation())
    assert manager.work_stamps == []




def test_the_tally_carries_the_newest_agent_activity_of_the_conversation(tmp_path):
    from src.core.subagents import files
    from src.core.subagents.parent_index import parse_timestamp
    from src.core.subagents.reader import read_subagents
    from src.core.subagents.tally import SubagentTallyCache
    from tests.helpers.subagent_fixture import CONV, build_corpus

    files.reset_caches_for_tests()
    try:
        root = tmp_path / "projects"
        parent = build_corpus(root)
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        rows = read_subagents(parent, conversation_uuid=CONV, now=now).subagents
        expected = max(parse_timestamp(r.last_activity_at) for r in rows if r.last_activity_at)
        cache = SubagentTallyCache(projects_dir=root)
        assert cache.tally("claude", CONV, None, None, now).last_activity_at == expected
        assert cache.tally("codex", CONV, None, None, now).last_activity_at is None
        assert cache.tally("shell", CONV, None, None, now).last_activity_at is None
    finally:
        files.reset_caches_for_tests()
