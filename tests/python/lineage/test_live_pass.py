
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from scripts.lineage import backfill_disk
from src.core.db import db_path_for, transaction
from src.core.lineage import constants as K
from src.core.lineage import events, live, milestones
from tests.s7_helpers import migrated_connection

COMPACT = {"type": "system", "subtype": "compact_boundary", "uuid": "rec-1", "timestamp": "2026-10-09T12:00:00Z",
           "compactMetadata": {"trigger": "manual", "preTokens": 90000}}


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    folder = tmp_path / "projects" / "-proj"
    folder.mkdir(parents=True)
    return {"state": state, "db": db_path_for(state), "root": tmp_path / "projects", "folder": folder}


def _transcript(folder, conversation, records):
    path = folder / f"{conversation}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _rows(db, sql):
    with closing(sqlite3.connect(db)) as raw:
        return raw.execute(sql).fetchall()


def test_a_compact_in_a_new_transcript_becomes_a_milestone_with_its_line_and_offset(world):
    _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "cli", "timestamp": "2026-10-09T11:00:00Z"},
                                            COMPACT])
    report = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert report.counts["compacts"] == 1 and report.counts["nodes"] == 1
    [(kind, source, line, offset, detail)] = _rows(
        world["db"], "SELECT kind, source, jsonl_line, jsonl_offset, detail_json FROM conversation_milestones")
    assert (kind, source, line) == ("compact", "jsonl_scan", 2) and offset > 0
    assert json.loads(detail) == {"pre_tokens": 90000, "record_uuid": "rec-1", "trigger": "manual"}
    assert _rows(world["db"], "SELECT level FROM lineage_nodes WHERE node_id = 'conv-a'") == [("human",)]


def test_the_cursor_makes_a_quiet_pass_read_nothing_and_a_rerun_adds_nothing(world):
    path = _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "cli"}, COMPACT])
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    quiet = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert quiet.examined == 0 and quiet.unchanged == 1
    (world["state"] / live.CURSOR_FILENAME).unlink()
    again = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert again.examined == 1 and again.counts["compacts"] == 0 and again.counts["nodes"] == 0
    assert _rows(world["db"], "SELECT COUNT(*) FROM conversation_milestones") == [(1,)]
    path.write_text(path.read_text() + json.dumps({**COMPACT, "uuid": "rec-2", "timestamp": "2026-10-10T01:00:00Z"}) + "\n")
    grown = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert grown.counts["compacts"] == 1


def test_a_compact_the_archive_already_stored_is_not_added_again(world):
    conn = migrated_connection(world["state"])
    with transaction(conn):
        milestones.add_milestone(conn, "conv-a", "compact", K.SOURCE_ARCHIVE, at_ts=COMPACT["timestamp"], jsonl_line=7)
    conn.close()
    _transcript(world["folder"], "conv-a", [{"type": "user"}, COMPACT])
    assert live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False).counts["compacts"] == 0


def test_a_dry_run_writes_nothing_and_counts_what_a_run_would_add(world):
    _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "sdk-cli"}, COMPACT])
    (world["folder"] / "conv-a" / "subagents").mkdir(parents=True)
    (world["folder"] / "conv-a" / "subagents" / "agent-1.jsonl").write_text("{}\n")
    dry = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False, apply=False)
    assert dry.dry_run and dry.counts["compacts"] == 1 and dry.counts["nodes"] == 1 and dry.counts["subagents"] == 1
    assert _rows(world["db"], "SELECT COUNT(*) FROM conversation_milestones") == [(0,)]
    assert _rows(world["db"], "SELECT COUNT(*) FROM lineage_nodes") == [(0,)]
    assert not (world["state"] / live.CURSOR_FILENAME).exists()
    real = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert (real.counts["compacts"], real.counts["nodes"], real.counts["subagents"]) == (1, 1, 1)
    assert _rows(world["db"], "SELECT level FROM lineage_nodes") == [("subsession",)]


def test_a_fork_pointer_and_a_pending_switch_are_both_settled_by_the_pass(world):
    conn = migrated_connection(world["state"])
    with transaction(conn):
        events.record_flip_edges(conn, "old", "sess-1", "switch", child_conversation_id="new")
    conn.close()
    _transcript(world["folder"], "new", [{"type": "user", "forkedFrom": {"sessionId": "old", "messageUuid": "m5"}}])
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    edges = _rows(world["db"], "SELECT child_type, edge_kind, json_extract(detail_json, '$.forked_from_message_uuid') "
                               "FROM lineage_edges ORDER BY child_type")
    assert edges == [("conversation", "fork", "m5"), ("session", "fork", "m5")]


def test_a_fresh_install_without_the_lineage_tables_is_refused_by_name(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = db_path_for(state)
    with closing(sqlite3.connect(db)) as raw:
        raw.execute("CREATE TABLE sessions (id INTEGER)")
    with pytest.raises(live.LineageLiveError):
        live.sweep(db, state, roots=[tmp_path])


def test_the_script_is_a_dry_run_unless_told_and_idempotent_when_applied(world, capsys):
    _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "cli"}, COMPACT])
    base = ["--db", str(world["db"]), "--state-dir", str(world["state"]), "--corpus", str(world["root"])]
    assert backfill_disk.main(base) == 0
    assert "dry run: nothing written" in capsys.readouterr().out
    assert _rows(world["db"], "SELECT COUNT(*) FROM conversation_milestones") == [(0,)]
    assert backfill_disk.main(base + ["--apply"]) == 0
    assert backfill_disk.main(base + ["--apply"]) == 0
    assert _rows(world["db"], "SELECT COUNT(*) FROM conversation_milestones") == [(1,)]
    (world["state"] / live.CURSOR_FILENAME).unlink()
    assert backfill_disk.main(base + ["--apply"]) == 0
    assert _rows(world["db"], "SELECT COUNT(*) FROM conversation_milestones") == [(1,)]



CODEX_PARENT = "01a06e76-0273-75b2-ac59-5838bf03fa3b"
CODEX_FORK = "01a06e77-0000-75b2-ac59-000000000001"
CODEX_SUB = "01a06e78-0000-75b2-ac59-000000000002"


def _rollout(root, conversation, payload):
    folder = root / "2026" / "10" / "10"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"rollout-2026-10-10T10-00-00-{conversation}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": conversation, "cwd": "/x", **payload}}) + "\n"
        + json.dumps({"type": "turn_context", "payload": {}}) + "\n")


def test_codex_fork_and_subagent_pointers_become_edges_and_old_rollouts_only_a_node(world, tmp_path):
    codex_root = tmp_path / "codex-sessions"
    _rollout(codex_root, CODEX_PARENT, {"source": "vscode"})
    _rollout(codex_root, CODEX_FORK, {"source": "cli", "forked_from_id": CODEX_PARENT})
    _rollout(codex_root, CODEX_SUB, {"source": {"subagent": {"thread_spawn": {"parent_thread_id": CODEX_PARENT, "depth": 1}}}})
    report = live.sweep(world["db"], world["state"], roots=[world["root"]], codex_root=codex_root)
    assert report.counts["nodes"] == 3 and report.counts["codex_fork_edges"] == 1 and report.counts["codex_spawn_edges"] == 1
    edges = _rows(world["db"], "SELECT parent_id, child_id, edge_kind, link_basis FROM lineage_edges ORDER BY edge_kind")
    assert edges == [(CODEX_PARENT, CODEX_FORK, "fork", "recorded"), (CODEX_PARENT, CODEX_SUB, "spawned_by", "recorded")]
    levels = dict(_rows(world["db"], "SELECT node_id, level FROM lineage_nodes"))
    assert levels == {CODEX_PARENT: "human", CODEX_FORK: "human", CODEX_SUB: "subsession"}
    assert live.sweep(world["db"], world["state"], roots=[world["root"]], codex_root=codex_root).examined == 0


def test_a_rollout_without_a_meta_line_is_skipped_without_a_guess(world, tmp_path):
    codex_root = tmp_path / "codex-sessions"
    folder = codex_root / "2026" / "10" / "10"
    folder.mkdir(parents=True)
    (folder / f"rollout-2026-10-10T10-00-00-{CODEX_PARENT}.jsonl").write_text("not json\n")
    report = live.sweep(world["db"], world["state"], roots=[world["root"]], codex_root=codex_root)
    assert report.counts["nodes"] == 0 and _rows(world["db"], "SELECT COUNT(*) FROM lineage_edges") == [(0,)]


def test_a_newly_recorded_compact_is_announced_to_bookmark_panels_once(world, monkeypatch):
    from src.core.bookmarks import compactions

    told = []
    monkeypatch.setattr(compactions, "announce", lambda session_uuid: told.append(session_uuid))
    _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "cli", "timestamp": "2026-10-09T11:00:00Z"},
                                            COMPACT])
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert len(told) == 1
