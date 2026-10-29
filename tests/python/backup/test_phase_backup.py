
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import pytest

from scripts.backup import phase_backup, targets
from scripts.backup.db_snapshot import table_digest
from scripts.backup.errors import BadPhaseId, SetUnreadable, SourceMissing
from scripts.backup.verify_set import verify_set

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def _make_state(tmp_path: Path) -> Tuple[Path, Path]:
    state = tmp_path / "state"
    (state / "cplugs" / "huddle" / "files" / "7").mkdir(parents=True)
    with closing(sqlite3.connect(state / "carnivore.db")) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES ('schema_version', '92');
            CREATE TABLE sessions (id INTEGER PRIMARY KEY, name TEXT, blob BLOB, score REAL);
            CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;
            CREATE TABLE loose (a TEXT, b INTEGER);
        """)
        db.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", [(i, f"s{i}", bytes([i]) * 3, i / 2) for i in range(1, 6)])
        db.executemany("INSERT INTO kv VALUES (?, ?)", [("a", "1"), ("b", "2")])
        db.executemany("INSERT INTO loose VALUES (?, ?)", [("x", 1), ("y", 2)])
        db.commit()
    with closing(sqlite3.connect(state / "cplugs" / "huddle" / "huddle.db")) as db:
        db.executescript("CREATE TABLE items (id INTEGER PRIMARY KEY, text TEXT); PRAGMA user_version = 48;")
        db.executemany("INSERT INTO items VALUES (?, ?)", [(i, f"task {i}") for i in range(1, 4)])
        db.commit()
    (state / "cplugs" / "state.json").write_text(json.dumps({"huddle": {"enabled": True}}))
    (state / "cplugs" / "huddle" / "files" / "7" / "shot.png").write_bytes(b"\x89PNG" + bytes(range(200)))
    dest = tmp_path / "backups"
    dest.mkdir()
    return state, dest


@pytest.fixture()
def rig(tmp_path: Path) -> Tuple[Path, Path, Path]:
    state, dest = _make_state(tmp_path)
    return state, dest, phase_backup.take("P1", state, dest, [], now=NOW)


def _verify(set_dir: Path, state: Path, allow: Tuple[str, ...] = (), live: bool = True):
    return verify_set(set_dir, state if live else None, allow, phase_backup._by_name)


def test_set_is_published_with_manifest_and_verifies(rig) -> None:
    state, _dest, taken = rig
    assert taken.name == "phase-P1-pre-20261016T120000Z"
    manifest = json.loads((taken / "MANIFEST.json").read_text())
    assert manifest["databases"]["carnivore.db"]["tables"]["sessions"]["rows"] == 5
    assert manifest["databases"]["huddle.db"]["user_version"] == 48
    assert manifest["databases"]["carnivore.db"]["schema_version"] == "92"
    assert manifest["trees"]["cplugs/huddle/files"]["files"]["7/shot.png"]["bytes"] == 204
    assert _verify(taken, state).ok
    assert phase_backup.main(["--state-dir", str(state), "--dest", str(taken.parent), "verify", taken.name]) == 0


def test_one_deleted_live_row_goes_red(rig) -> None:
    state, _dest, taken = rig
    with closing(sqlite3.connect(state / "carnivore.db")) as db:
        db.execute("DELETE FROM sessions WHERE id = 3")
        db.commit()
    report = _verify(taken, state)
    assert not report.ok and any(f.startswith("carnivore.db:sessions") for f in report.failures)
    assert phase_backup.main(["--state-dir", str(state), "--dest", str(taken.parent), "verify", taken.name]) == 1


def test_one_changed_live_value_with_same_row_count_goes_red(rig) -> None:
    state, _dest, taken = rig
    with closing(sqlite3.connect(state / "cplugs" / "huddle" / "huddle.db")) as db:
        db.execute("UPDATE items SET text = 'task 2!' WHERE id = 2")
        db.commit()
    assert any(f.startswith("huddle.db:items") for f in _verify(taken, state).failures)


def test_one_changed_attachment_byte_goes_red(rig) -> None:
    state, _dest, taken = rig
    shot = state / "cplugs" / "huddle" / "files" / "7" / "shot.png"
    data = bytearray(shot.read_bytes())
    data[100] ^= 1
    shot.write_bytes(bytes(data))
    assert any("shot.png" in f and "changed" in f for f in _verify(taken, state).failures)


def test_deleted_attachment_goes_red_and_a_new_one_is_only_a_note(rig) -> None:
    state, _dest, taken = rig
    folder = state / "cplugs" / "huddle" / "files" / "7"
    (folder / "new.txt").write_text("hi")
    report = _verify(taken, state)
    assert report.ok and any("new.txt" in n for n in report.notes)
    moved = folder.parent / "moved.png"
    (folder / "shot.png").rename(moved)
    assert any("shot.png" in f and "deleted" in f for f in _verify(taken, state).failures)
    assert moved.exists()


def test_damaged_set_goes_red_even_when_live_is_untouched(rig) -> None:
    state, _dest, taken = rig
    copy = taken / "db" / "carnivore.db"
    with closing(sqlite3.connect(copy)) as db:
        db.execute("DELETE FROM kv WHERE k = 'a'")
        db.commit()
    report = _verify(taken, state, live=False)
    assert any(f.startswith("set carnivore.db:kv") for f in report.failures)
    assert any("sha256 differs" in f for f in report.failures)
    shot = taken / "files" / "cplugs" / "huddle" / "files" / "7" / "shot.png"
    shot.write_bytes(shot.read_bytes()[:-1] + b"Z")
    assert any("shot.png" in f for f in _verify(taken, state, live=False).failures)


def test_allow_changed_covers_exactly_what_it_names(rig) -> None:
    state, _dest, taken = rig
    with closing(sqlite3.connect(state / "carnivore.db")) as db:
        db.execute("INSERT INTO loose VALUES ('z', 3)")
        db.execute("DELETE FROM kv WHERE k = 'b'")
        db.commit()
    report = _verify(taken, state, allow=("carnivore.db:loose",))
    assert [f.split(":")[1] for f in report.failures] == ["kv"]
    assert len(report.allowed) == 1


def test_missing_required_database_and_bad_phase_are_refused(tmp_path: Path) -> None:
    state, dest = _make_state(tmp_path)
    for bad in ("", "../x", "a b", "x" * 40):
        with pytest.raises(BadPhaseId):
            phase_backup.take(bad, state, dest, [], now=NOW)
    (state / "carnivore.db").rename(state / "elsewhere.db")
    with pytest.raises(SourceMissing):
        phase_backup.take("P1", state, dest, [], now=NOW)
    assert not list(dest.iterdir())


def test_take_leaves_the_sources_byte_identical_and_creates_no_file(tmp_path: Path) -> None:
    state, dest = _make_state(tmp_path)
    (state / "cplugs" / "huddle" / "huddle.db").rename(state / "cplugs" / "huddle" / "huddle.db.imported")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in state.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm"))}
    names = {p.name for p in state.rglob("*")}
    taken = phase_backup.take("P2", state, dest, [], now=NOW)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert before == after
    assert {p.name for p in state.rglob("*")} - names <= {"carnivore.db-wal", "carnivore.db-shm"}
    assert "huddle.db" in json.loads((taken / "MANIFEST.json").read_text())["absent"]
    assert not (state / "cplugs" / "huddle" / "huddle.db").exists()


def test_a_second_take_in_the_same_second_is_refused_and_two_sets_list(tmp_path: Path) -> None:
    state, dest = _make_state(tmp_path)
    phase_backup.take("P1", state, dest, [], now=NOW)
    with pytest.raises(phase_backup.PhaseBackupError):
        phase_backup.take("P1", state, dest, [], now=NOW)
    phase_backup.take("P1", state, dest, [], now=datetime(2026, 10, 16, 12, 5, 0, tzinfo=timezone.utc))
    listed = phase_backup.list_sets([dest])
    assert [s["created_utc"] for s in listed] == ["20261016T120500Z", "20261016T120000Z"]
    assert all(s["readable"] and s["rows"] > 0 for s in listed)


def test_unreadable_manifest_is_exit_2_not_a_pass(rig) -> None:
    state, _dest, taken = rig
    (taken / "MANIFEST.json").write_text("{}")
    with pytest.raises(SetUnreadable):
        _verify(taken, state)
    assert phase_backup.main(["--state-dir", str(state), "--dest", str(taken.parent), "verify", taken.name]) == 2
    assert phase_backup.main(["--state-dir", str(state), "--dest", str(taken.parent), "verify", "no-such-set"]) == 2


def test_digest_tells_types_apart() -> None:
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE t (v)")
        digests = []
        for value in (1, 1.0, "1", b"1", None):
            db.execute("DELETE FROM t")
            db.execute("INSERT INTO t VALUES (?)", (value,))
            digests.append(table_digest(db, "t")["sha256"])
    assert len(set(digests)) == 5


def test_legacy_cloude_db_is_found_when_carnivore_db_is_absent(tmp_path: Path) -> None:
    state, dest = _make_state(tmp_path)
    (state / "carnivore.db").rename(state / "cloude.db")
    taken = phase_backup.take("P1", state, dest, [], now=NOW)
    assert "carnivore.db" in json.loads((taken / "MANIFEST.json").read_text())["databases"]
    assert targets.DB_TARGETS[0].required
