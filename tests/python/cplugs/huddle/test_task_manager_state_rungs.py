
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List

import pytest

from src.cplugs.huddle import item_owner, lane, lineage, nudges, rules, state_rungs
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS
from src.core.work import tables
from src.core.work.storage import LEGACY_STORAGE
from src.cplugs.sdk import CplugStorage, StorageSpec
from src.core.pack.migrate import task_manager_history, task_manager_names

REAL_DB = Path(os.environ.get("HUDDLE_REAL_DB", "~/Library/Application Support/Carnivore/cplugs/huddle/huddle.db")).expanduser()
OLD_STATES = ("open", "back_burner", "waiting_install", "done_by_claude", "approved", "approved_with_note")
ITEM_INSERT = ("INSERT INTO items (list_key, text, note, position, created_by, state, created_at, updated_at, created_seq, seq) "
               "VALUES ('all', ?, ?, ?, 'joe', ?, 1, 1, 1, 1)")


def walk(path: Path, upto: int, *, backups: bool = False) -> None:
    spec = StorageSpec(db=path.name, migrations=MIGRATIONS[:upto], backup_before=LEGACY_STORAGE.backup_before if backups else None)
    CplugStorage(path.parent, spec).connect(True).close()


def synthetic_v33(folder: Path) -> Path:
    path = folder / "huddle.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        for step in MIGRATIONS[:33]:
            conn.executescript(step)
        for n, state in enumerate(OLD_STATES * 2):
            conn.execute(ITEM_INSERT, (f"{state} {n}", "read me" if n % 2 else "", n, state))
        conn.execute("PRAGMA user_version = 33")
    return path


def real_copy(folder: Path, at_most: int = 33) -> Path:
    if not REAL_DB.is_file():
        pytest.skip("no real huddle.db on this machine")
    out = folder / "huddle.db"
    with closing(sqlite3.connect(f"{REAL_DB.as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(out)) as dest:
        source.backup(dest)
    with closing(sqlite3.connect(out)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > at_most:
        out.unlink()
        pytest.skip(f"the real huddle.db is schema {version}, past the schema {at_most} this test walks from")
    return out


def snapshot(path: Path) -> Dict[str, object]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        counts = {r[0]: r[1] for r in conn.execute("SELECT state, COUNT(*) FROM items GROUP BY state")}
        rows = [tuple(None if k == "state" else r[k] for k in r.keys()) for r in conn.execute("SELECT * FROM items ORDER BY id")]
        tables = {r[0]: conn.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0]
                  for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    return {"counts": counts, "rows": rows, "tables": tables}


def expected_counts(before: Dict[str, int], pairs) -> Dict[str, int]:
    after = dict(before)
    for old, new in pairs:
        after[new] = after.get(new, 0) + after.pop(old, 0)
    return {k: v for k, v in after.items() if v}


@pytest.fixture(params=["synthetic", "joe_real"])
def old_file(request, tmp_path: Path) -> Path:
    return synthetic_v33(tmp_path) if request.param == "synthetic" else real_copy(tmp_path)


def _rung_cases() -> List[tuple]:
    return list(state_rungs.RENAME_RUNGS)


@pytest.mark.parametrize("rung,label,pairs", _rung_cases(), ids=[f"rung{n}-{label}" for n, label, _ in _rung_cases()])
def test_each_rename_rung_moves_only_state_loses_no_row_and_keeps_every_note(old_file: Path, rung, label, pairs):
    walk(old_file, rung - 1)
    before = snapshot(old_file)
    walk(old_file, rung)
    after = snapshot(old_file)
    assert after["counts"] == expected_counts(before["counts"], pairs)
    assert sum(after["counts"].values()) == sum(before["counts"].values())
    assert after["rows"] == before["rows"]
    assert after["tables"] == before["tables"]
    assert not {old for old, _ in pairs} & set(after["counts"])


def test_the_whole_walk_takes_one_verified_backup_before_the_first_rename_and_loses_nothing(old_file: Path):
    before = snapshot(old_file)
    CplugStorage(old_file.parent, LEGACY_STORAGE).connect(True).close()
    copies = sorted(p.name for p in old_file.parent.iterdir() if p.name.startswith("huddle.db."))
    assert len(copies) == 1 and re.fullmatch(r"huddle\.db\.pre-[a-z]+-\d{8}T\d{6}Z", copies[0]), copies
    assert snapshot(old_file.parent / copies[0])["counts"] == before["counts"]
    assert sum(snapshot(old_file)["counts"].values()) == sum(before["counts"].values())
    assert set(snapshot(old_file)["counts"]) <= set(rules.STATES)


def test_every_rename_has_a_backup_entry_a_migration_and_an_alias():
    assert dict(LEGACY_STORAGE.backup_before)[23] == "pre-cards"
    for rung, label, pairs in state_rungs.RENAME_RUNGS:
        assert LEGACY_STORAGE.backup_before[rung] == label
        assert MIGRATIONS[rung - 1].count("UPDATE items SET state") >= 1
        for old, new in pairs:
            assert rules.STATE_ALIASES[old] == new
    assert dict(rules.STATE_ALIASES) == dict(state_rungs.RENAMES)
    assert task_manager_names.RETIRED_STATES == dict(state_rungs.RENAMES)
    assert all(new in rules.STATES for _, new in state_rungs.RENAMES) and not set(rules.STATE_ALIASES) & set(rules.STATES)


def test_a_tick_clears_the_owner_on_a_migrated_file_and_on_a_fresh_one(tmp_path: Path):
    for name, builder in (("migrated", synthetic_v33), ("fresh", None)):
        folder = tmp_path / name
        folder.mkdir()
        if builder:
            walk(builder(folder), len(MIGRATIONS))
        else:
            walk(folder / "huddle.db", len(MIGRATIONS))
        with closing(sqlite3.connect(folder / "huddle.db")) as conn, conn:
            conn.execute(ITEM_INSERT, ("owned", "", 99, "open"))
            conn.execute(f"UPDATE items SET {item_owner.COLUMN} = 'sess-a' WHERE text = 'owned'")
            conn.execute("UPDATE items SET state = ? WHERE text = 'owned'", (rules.DONE,))
            assert conn.execute(f"SELECT {item_owner.COLUMN} FROM items WHERE text = 'owned'").fetchone()[0] == "", name


def test_a_fresh_file_and_a_migrated_file_end_with_the_same_schema(tmp_path: Path):
    fresh, migrated = tmp_path / "f", tmp_path / "m"
    fresh.mkdir(), migrated.mkdir()
    walk(fresh / "huddle.db", len(MIGRATIONS))
    walk(synthetic_v33(migrated), len(MIGRATIONS))
    sql = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    with closing(sqlite3.connect(fresh / "huddle.db")) as a, closing(sqlite3.connect(migrated / "huddle.db")) as b:
        norm = lambda rows: [(t, n, " ".join((s or "").split())) for t, n, s in rows]  # noqa: E731
        assert norm(a.execute(sql)) == norm(b.execute(sql))


def test_no_code_writes_items_state_outside_the_known_write_points():
    allowed = {"store.py", "answer_writer.py", "fork.py", "state_rungs.py", "item_owner.py", "ask.py", "closure_undo.py"}
    root = Path(__file__).resolve().parents[4] / "src" / "cplugs" / "huddle"
    pattern = re.compile(r"UPDATE work_items SET[^\"']*\bstate\s*=", re.S)
    writers = {p.name for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))}
    assert writers <= allowed, writers - allowed
    assert {"store.py", "answer_writer.py", "fork.py"} <= writers


def test_core_speaks_the_retired_names_on_the_wire_and_mirrors_the_plugin_rules():
    for current, retired in task_manager_names.WIRE_STATES.items():
        assert rules.STATE_ALIASES[retired] == current
    assert set(task_manager_names.WIRE_STATES) == {new for _, new in state_rungs.RENAMES}
    assert rules.STATE_ALIASES[task_manager_names.DONE_WITH_NOTE] == rules.DONE
    assert task_manager_names.STATE_ARGS == rules.STATE_ARGS
    assert (task_manager_names.SWARM_KEY, task_manager_names.TASK_MANAGER, task_manager_names.SWARM) == (rules.SWARM_KEY, lane.TASK_MANAGER, lane.SWARM)
    assert (task_manager_names.SWARM_ORIGINS, task_manager_names.AGENT_LIST_PREFIX) == (lane.SWARM_ORIGINS, lane.AGENT_LIST_PREFIX)
    assert task_manager_history.IMPORT_BY == lineage.CARNIVORE
    cases = [({"card_origin": "agent:7"}, "16"), ({"card_origin": "spawn:2"}, "16"), ({"card_origin": "owner"}, "16"), ({}, "16"),
             ({"swarm_ref": "trust:1"}, "16"), ({"created_key": "swarm"}, "16"), ({}, "agent:3"), ({"created_key": "owner"}, "16")]
    for item, key in cases:
        assert task_manager_names.lane_of(item, key) == lane.for_new(list_key=key, created_key=item.get("created_key", ""),
                                                               swarm_ref=item.get("swarm_ref", ""), card_origin=item.get("card_origin", "")), item


def legacy_sql(sql: str) -> str:
    names = "|".join(sorted(tables.LEGACY_NAMES, key=len, reverse=True))
    return re.sub(rf"\b({names})\b", lambda m: tables.LEGACY_NAMES[m.group(1)], sql)


def test_a_nudged_item_keeps_its_count_and_stall_across_the_renames(tmp_path: Path):
    path = synthetic_v33(tmp_path)
    with closing(sqlite3.connect(path)) as conn, conn:
        for state in ("waiting_install", "back_burner", "done_by_claude", "approved"):
            conn.execute(ITEM_INSERT, (f"nudged {state}", "", 50, state))
            conn.execute(f"INSERT INTO item_nudges (item_id, basis, count, last_at, stalled_at) SELECT id, {legacy_sql(nudges.BASIS_SQL)}, 7, 5, 9 "
                         "FROM items WHERE text = ?", (f"nudged {state}",))
    walk(path, len(MIGRATIONS))
    with closing(sqlite3.connect(path)) as conn:
        got = conn.execute(f"SELECT text, state, {legacy_sql(nudges.SELECT_COLS)} FROM items WHERE text LIKE 'nudged %' ORDER BY id").fetchall()
    assert [(state, count, last, stalled) for _, state, count, last, stalled in got] == [
        ("waiting", 7, 5.0, 9.0), ("todo", 7, 5.0, 9.0), ("review", 7, 5.0, 9.0), ("done", 7, 5.0, 9.0)]
