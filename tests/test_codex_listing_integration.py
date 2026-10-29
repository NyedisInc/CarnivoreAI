from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core import attention_reader as reader_module
from src.core.attention import codex_stores
from src.core.attention.display import to_display, status_source_for
from src.core.attention.ledger import AttentionLedger
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.watcher import AttentionWatcher, WatchTarget
from src.core.attention_reader import AttentionEvidenceReader
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_ORIGIN_CREATED, SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP
from src.core.session_identity import record_instance
from src.core.session_status_map import StatusMap
from src.core.session_instance_index import InstanceIndex

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
THREAD = "3fce7313-a048-4034-8b0d-72deecec7e53"
CWD = "/Users/x/proj"
SESSION_ID = "ses_1"
TMUX = "cloude_proj"
EPOCH = 1788463220
RESTING_PANE = "some scrollback\n› Ask Codex to do anything\n"

def _make_home(
    tmp_path,
    *,
    turns,
    projection_offset=10_000_000,
    rollout_tail=None,
    cwd=CWD,
    lock=False,
    thread_name=None,
):
    home = tmp_path / ".codex"
    (home / "sessions" / "2026" / "09" / "12").mkdir(parents=True)
    (home / "thread-writer-locks").mkdir(parents=True)

    hist = home / "thread_history_1.sqlite"
    con = sqlite3.connect(str(hist))
    con.execute(
        "CREATE TABLE thread_turns (thread_id TEXT NOT NULL, turn_id TEXT "
        "NOT NULL, rollout_ordinal INTEGER NOT NULL, status TEXT NOT NULL, "
        "error_json TEXT, PRIMARY KEY (thread_id, turn_id))"
    )
    con.execute(
        "CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY "
        "KEY, next_rollout_byte_offset INTEGER NOT NULL, next_rollout_ordinal "
        "INTEGER NOT NULL)"
    )
    for i, (status, err) in enumerate(turns):
        con.execute(
            "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, "
            "status, error_json) VALUES (?, ?, ?, ?, ?)",
            (THREAD, "turn_%d" % i, i, status, err),
        )
    con.execute(
        "INSERT INTO thread_history_projection_state VALUES (?, ?, ?)",
        (THREAD, projection_offset, len(turns)),
    )
    con.commit()
    con.close()

    rollout = (
        home / "sessions" / "2026" / "09" / "12"
        / ("rollout-2026-09-12T10-48-49-%s.jsonl" % THREAD)
    )
    tail = rollout_tail or (
        '{"timestamp":"%s","ordinal":0,"type":"event_msg",'
        '"payload":{"type":"task_complete","turn_id":"turn_0"}}\n'
        % NOW.isoformat()
    )
    rollout.write_text(tail, encoding="utf-8")

    state = home / "state_5.sqlite"
    con = sqlite3.connect(str(state))
    con.execute(
        "CREATE TABLE threads (id TEXT, rollout_path TEXT, cwd TEXT, "
        "thread_source TEXT, name TEXT, recency_at INTEGER, archived INTEGER)"
    )
    con.execute(
        "INSERT INTO threads VALUES (?, ?, ?, 'user', ?, 0, 0)",
        (THREAD, str(rollout), cwd, thread_name),
    )
    con.commit()
    con.close()

    if lock:
        (home / "thread-writer-locks" / ("%s.lock" % THREAD)).write_text("")
    return home


def _live_lock(monkeypatch):
    monkeypatch.setattr(
        codex_stores, "_lsof_holders", lambda path: {os.getpid()}
    )


def test_symlinked_codex_home_matches_physical_writer_lock(tmp_path, monkeypatch):
    physical = _make_home(tmp_path, turns=[("completed", None)], lock=True)
    link = tmp_path / "linked-codex-home"
    link.symlink_to(physical, target_is_directory=True)
    lock = physical / "thread-writer-locks" / f"{THREAD}.lock"

    def lsof(argv, **kwargs):
        assert argv[:3] == ["lsof", "-a", "-p"]
        return subprocess.CompletedProcess(argv, 0, stdout=f"n{lock}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", lsof)
    picked = codex_stores.resolve_primary_uuid(
        str(link), pane_current_path=CWD, pane_title="", pane_pid=os.getpid(),
        process_parents={},
    )
    assert picked == THREAD


def _pipeline(tmp_path, monkeypatch, home, *, pane=RESTING_PANE):
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            record_instance(conn, socket="cloude", name=TMUX, epoch=EPOCH,
                            origin=SESSION_ORIGIN_CREATED, working_dir=CWD)

    def row(*args, **kwargs):
        with closing(connect(db_path_for(state))) as conn:
            return dict(conn.execute("SELECT * FROM sessions WHERE tmux_name = ?", (TMUX,)).fetchone())

    manager = SimpleNamespace(
        _registry=SimpleNamespace(
            backends={SESSION_ID: SimpleNamespace(socket_name="cloude")},
            sessions={SESSION_ID: SimpleNamespace(agent_type="codex", working_dir=CWD)},
        ),
        _build_tmux_status_map=lambda: StatusMap(
            {TMUX: {"status": "running", "created_at_epoch": EPOCH, "pid": os.getpid()}},
            complete=True, socket="cloude"),
        _identity_for_instance=lambda *args: {"agent_type": "codex"},
        _instance_index_for_listing=lambda *, socket, names: InstanceIndex(),
        _writable_datastore_connection=lambda: connect(db_path_for(state)),
        _tmux_socket_name=lambda: "cloude",
    )
    monkeypatch.setattr(reader_module, "DEFAULT_CODEX_HOME", str(home))
    monkeypatch.setattr(reader_module, "read_instance_row", row)
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda *args: pane))
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    _live_lock(monkeypatch)
    monkeypatch.setattr(codex_stores, "_owned_writer_uuids", lambda home, pids: {THREAD})
    target = WatchTarget(SESSION_ID, "instance")
    reader = AttentionEvidenceReader(manager, lambda sid: (TMUX, EPOCH))
    effects = AttentionSideEffects(manager)

    def apply(target, observation):
        effects._bind_codex(target.session_id, TMUX, observation.evidence.codex_bind_uuid, EPOCH)

    clock = [NOW]
    watcher = AttentionWatcher(
        list_targets=lambda: [target], read_evidence=reader,
        raise_toast=lambda *args: None, set_unread=lambda *args: None,
        on_busy_edge=lambda *args: None, on_observation=apply,
        ledger=AttentionLedger(), now=lambda: clock[0],
    )
    return watcher, clock, row


def _tick(watcher, clock, seconds=0):
    clock[0] = NOW + timedelta(seconds=seconds)
    asyncio.run(watcher.tick_once())
    observation = watcher.observation_for(SESSION_ID, clock[0])
    return to_display(observation.verdict, unread=False, tmux_status="running"), status_source_for(observation.verdict)


def test_codex_row_binds_uuid_once_and_paints_a_real_rest_status(tmp_path, monkeypatch):
    home = _make_home(tmp_path, turns=[("completed", None)], lock=True)
    watcher, clock, row = _pipeline(tmp_path, monkeypatch, home)
    assert _tick(watcher, clock) == ("idle", "registry")
    first = row()
    assert first["claude_session_uuid"] == THREAD
    assert first["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP
    assert _tick(watcher, clock, 2) == ("idle", "registry")
    assert row()["updated_at"] == first["updated_at"]


def test_codex_busy_over_a_resting_pane_is_vetoed_not_green(tmp_path, monkeypatch):
    home = _make_home(tmp_path, turns=[("completed", None), ("inProgress", None)], lock=True)
    watcher, clock, row = _pipeline(tmp_path, monkeypatch, home)
    assert _tick(watcher, clock) == ("working", "registry")
    _tick(watcher, clock, 2)
    assert _tick(watcher, clock, 4) == ("unknown", "pane")


def test_codex_row_with_no_resolvable_thread_stays_unknown(tmp_path, monkeypatch):
    home = _make_home(tmp_path, turns=[("completed", None)], cwd="/elsewhere")
    watcher, clock, row = _pipeline(tmp_path, monkeypatch, home, pane="")
    assert _tick(watcher, clock) == ("unknown", "none")
    assert row()["claude_session_uuid"] is None


def test_resolve_primary_uuid_picks_the_user_thread_at_the_cwd(tmp_path):
    home = _make_home(tmp_path, turns=[("completed", None)])
    assert codex_stores.resolve_primary_uuid(str(home), pane_current_path=CWD, pane_title="") == THREAD


def test_resolve_primary_uuid_is_none_when_no_user_thread_matches(tmp_path):
    home = _make_home(tmp_path, turns=[("completed", None)], cwd="/other")
    assert codex_stores.resolve_primary_uuid(str(home), pane_current_path=CWD, pane_title="") is None
