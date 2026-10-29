
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts.time_machine_retire import retire

SEARCH_DDL = (
    "CREATE TABLE session_search_rows (id INTEGER PRIMARY KEY, doc_id INTEGER)",
    "CREATE TABLE session_search_docs (id INTEGER PRIMARY KEY, conversation_id TEXT)",
    "CREATE TABLE session_search_live (id INTEGER PRIMARY KEY, conversation_id TEXT)",
    "CREATE VIRTUAL TABLE session_search_fts USING fts5(body, content='', contentless_delete=1)",
    "CREATE TABLE conversation_index (id INTEGER PRIMARY KEY, conversation_id TEXT)",
    "CREATE TABLE pipeline_jobs (id INTEGER PRIMARY KEY, event TEXT, state TEXT, created_at TEXT)",
    "CREATE TABLE pipeline_stage_runs (job_id INTEGER, stage TEXT, PRIMARY KEY (job_id, stage))",
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)",
)


def build(tmp_path: Path, cache: str = "ready", open_job: bool = False) -> Path:
    state = tmp_path / "state"
    (state / "time-machine" / "a").mkdir(parents=True)
    (state / "time-machine" / "a" / "p.bin").write_bytes(b"x" * 100)
    for name in retire.RUNNER_FILES:
        (state / name).write_text("{}")
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        for ddl in SEARCH_DDL:
            c.execute(ddl)
        c.execute("INSERT INTO meta VALUES ('schema_version', '88')")
        c.executemany("INSERT INTO session_search_rows VALUES (?, 1)", [(1,), (2,)])
        c.execute("INSERT INTO session_search_docs VALUES (1, 'c1')")
        c.execute("INSERT INTO session_search_live VALUES (1, 'c1')")
        c.execute("INSERT INTO session_search_fts(rowid, body) VALUES (1, 'hello')")
        c.execute("INSERT INTO conversation_index VALUES (1, 'c1')")
        c.executemany("INSERT INTO pipeline_jobs VALUES (?, ?, 'done', '2026-10-01T00:00:00+00:00')",
                      [(1, "backfill"), (2, "kill")])
        c.executemany("INSERT INTO pipeline_stage_runs VALUES (?, ?)",
                      [(1, "milestones"), (1, "capture"), (2, "capture"), (2, "milestones"), (2, "plugins")])
        if open_job:
            c.execute("INSERT INTO pipeline_jobs VALUES (3, 'live', 'queued', '2026-10-01T00:00:00+00:00')")
        c.commit()
    with closing(sqlite3.connect(state / "deepsearch.db")) as c:
        c.execute("CREATE TABLE cache_meta (id INTEGER PRIMARY KEY, state TEXT NOT NULL, built_at TEXT)")
        c.execute("INSERT INTO cache_meta VALUES (1, ?, NULL)", (cache,))
        c.commit()
    (state / "config.json").write_text(json.dumps(
        {"save_pipeline": {"capture_scope": "x"}, "byoai": {"features": {"pipeline.summary": {}, "keep.me": {}}}}))
    return state


def counts(state: Path) -> dict:
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        tables = ("session_search_rows", "session_search_docs", "session_search_live", "conversation_index",
                  "pipeline_jobs", "pipeline_stage_runs")
        out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        out["fts"] = c.execute("SELECT COUNT(*) FROM session_search_fts_docsize").fetchone()[0]
        return out


def test_dry_run_changes_nothing(tmp_path, capsys):
    state = build(tmp_path)
    before = counts(state)
    assert retire.run(state, state / "config.json", apply=False) == retire.EXIT_OK
    assert counts(state) == before
    assert (state / "time-machine").is_dir() and (state / retire.RUNNER_FILES[0]).exists()
    assert "rows pipeline_stage_runs: 3" in capsys.readouterr().out
    assert "save_pipeline" in (state / "config.json").read_text()


def test_apply_empties_exactly_the_named_rows(tmp_path):
    state = build(tmp_path)
    assert retire.run(state, state / "config.json", apply=True) == retire.EXIT_OK
    got = counts(state)
    assert got == {"session_search_rows": 0, "session_search_docs": 0, "session_search_live": 0, "fts": 0,
                   "conversation_index": 1, "pipeline_jobs": 1, "pipeline_stage_runs": 2}
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        assert sorted(c.execute("SELECT job_id, stage FROM pipeline_stage_runs")) == [(2, "milestones"), (2, "plugins")]
    assert not (state / "time-machine").exists() and not (state / retire.RUNNER_FILES[1]).exists()
    assert list(state.glob("carnivore.db.bak-*")), "a verified backup file is kept"
    cfg = json.loads((state / "config.json").read_text())
    assert "save_pipeline" not in cfg and cfg["byoai"]["features"] == {"keep.me": {}}


@pytest.mark.parametrize("kwargs", [{"cache": "building"}, {"open_job": True}])
def test_gates_refuse_and_change_nothing(tmp_path, kwargs):
    state = build(tmp_path, **kwargs)
    before = counts(state)
    assert retire.run(state, state / "config.json", apply=True) == retire.EXIT_REFUSED
    assert counts(state) == before and (state / "time-machine").is_dir()


def test_no_verified_backup_means_no_dml(tmp_path, monkeypatch):
    state = build(tmp_path)
    before = counts(state)
    monkeypatch.setattr(retire.db_backup, "take_backup",
                        lambda *a, **k: retire.db_backup.BackupResult(taken=True, verified=False, reason="bad"))
    assert retire.run(state, state / "config.json", apply=True) == retire.EXIT_NO_BACKUP
    assert counts(state) == before and (state / "time-machine").is_dir()
