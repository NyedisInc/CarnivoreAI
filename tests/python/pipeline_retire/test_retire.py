
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.pipeline_retire import retire

JOBS = "CREATE TABLE pipeline_jobs (id INTEGER PRIMARY KEY, event TEXT, state TEXT)"
STAGES = "CREATE TABLE pipeline_stage_runs (job_id INTEGER, stage TEXT, PRIMARY KEY (job_id, stage))"
GOVERNANCE = ("addons.json", "stats.health.json", "deepsearch.slow.json")
KEPT = ("stats.db", "stats.db-wal", "stats.db-shm", "notes.json", "addons.json.bak")


def build(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    folder = state / "pipeline-plugins"
    folder.mkdir(parents=True)
    for name in (*GOVERNANCE, *KEPT):
        (folder / name).write_text("x" * 10)
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO meta VALUES ('schema_version', '89')")
        c.execute(JOBS)
        c.execute(STAGES)
        c.execute("CREATE TABLE conversation_index (id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO conversation_index VALUES (1)")
        c.executemany("INSERT INTO pipeline_jobs VALUES (?, 'kill', ?)", [(1, "done"), (2, "dead"), (3, "queued")])
        c.executemany("INSERT INTO pipeline_stage_runs VALUES (?, ?)", [(1, "plugins"), (1, "capture"), (3, "plugins")])
        c.commit()
    return state


def counts(state: Path) -> dict:
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("pipeline_jobs", "pipeline_stage_runs", "conversation_index")}


def present(state: Path) -> set:
    return {p.name for p in (state / "pipeline-plugins").iterdir()}


def test_dry_run_changes_nothing(tmp_path, capsys):
    state = build(tmp_path)
    before_files = present(state)
    assert retire.run(state, apply=False) == retire.EXIT_OK
    assert counts(state) == {"pipeline_jobs": 3, "pipeline_stage_runs": 3, "conversation_index": 1}
    assert present(state) == before_files
    assert not list(state.glob("carnivore.db.bak-*")), "a dry run takes no backup"
    out = capsys.readouterr().out
    assert "rows pipeline_jobs: 3" in out and "files to delete: 3" in out


def test_apply_empties_the_two_tables_keeps_the_schema_and_deletes_only_governance_files(tmp_path):
    state = build(tmp_path)
    assert retire.run(state, apply=True) == retire.EXIT_OK
    assert counts(state) == {"pipeline_jobs": 0, "pipeline_stage_runs": 0, "conversation_index": 1}
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"pipeline_jobs", "pipeline_stage_runs"} <= names, "the tables stay as dormant schema"
    assert present(state) == set(KEPT), "plugin databases and unrelated files stay"
    assert list(state.glob("carnivore.db.bak-*")), "a verified backup is kept"


def test_the_population_is_non_empty_so_a_green_run_looked_at_something(tmp_path):
    state = build(tmp_path)
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        assert sum(retire.count_rows(c).values()) == 6
    assert [p.name for p in retire.retire_files(state)] == sorted(GOVERNANCE)


def test_no_verified_backup_means_no_change(tmp_path, monkeypatch):
    state = build(tmp_path)
    monkeypatch.setattr(retire.db_backup, "take_backup",
                        lambda *a, **k: retire.db_backup.BackupResult(taken=True, verified=False, reason="bad"))
    assert retire.run(state, apply=True) == retire.EXIT_NO_BACKUP
    assert counts(state)["pipeline_jobs"] == 3 and present(state) == set(GOVERNANCE) | set(KEPT)


def test_a_state_dir_without_the_tables_is_refused(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    with closing(sqlite3.connect(state / "carnivore.db")) as c:
        c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        c.commit()
    assert retire.run(state, apply=True) == retire.EXIT_REFUSED
