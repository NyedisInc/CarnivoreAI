
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.cplugs.huddle import blockers, waits, from_project, inbox, item_owner, nudges, rules, service, store as store_module, store_reads, wire
from src.cplugs.huddle.cards import policy, projection, reads
from src.cplugs.huddle.cards.columns import CARD_COLS
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work import tables
from src.core.work.importer import ready
from src.core.work.ladder import MIGRATIONS
from src.core.work.storage import LEGACY_STORAGE, WorkStorage
from src.cplugs.sdk import CplugSchemaError, CplugStorage, storage_backup

TASKS = [
    ("all", "open plain", "open", 0, "todo"), ("all", "claimed", "open", 1, "in_progress"),
    ("all", "burner", "todo", 0, "todo"), ("all", "reviewing", "review", 0, "review"),
    ("all", "installing", "waiting", 0, "review"), ("all", "ticked", "done", 0, "done"),
    ("all", "ticked note", "done", 0, "done"), ("12", "twelve a", "open", 0, "todo"),
    ("12", "twelve b", "open", 1, "in_progress"), ("12", "twelve c", "review", 0, "review"),
    ("13", "thirteen", "open", 0, "todo"), ("agent:3", "agent card", "open", 0, "todo"),
]
OLD_LANE = "CASE WHEN pack_ref != '' OR created_key IN ('pack', 'swarm') OR list_key LIKE 'agent:%' THEN 'swarm' ELSE 'task_manager' END"
OLD_ITEM_COLS = wire.ITEM_COLS.replace(", review_checks,", ", NULL AS review_checks,").replace(", review_summary", ", NULL AS review_summary").replace(", github_issue", ", NULL AS github_issue").replace(", source_item_id", ", NULL AS source_item_id").replace(", " + item_owner.COLUMN, ", CASE WHEN claude_working = 1 THEN claude_working_by ELSE '' END AS " + item_owner.COLUMN).replace(", " + nudges.SELECT_COLS, "").replace(", " + inbox.SELECT_COLS, "")[: -len(", " + CARD_COLS)].replace(from_project.SELECT_COLS, "NULL AS from_project_id, NULL AS from_project_name").replace("swarm_ref", "pack_ref AS swarm_ref").replace(", lane,", ", " + OLD_LANE + " AS lane,").replace(", perceived_ask,", ", NULL AS perceived_ask,").replace(", " + blockers.SELECT_COL, "").replace(", " + waits.SELECT_COL, "").replace(", " + item_owner.TAG_COLUMN, ", '' AS " + item_owner.TAG_COLUMN)
OLD_MSG_COLS = wire.MSG_COLS[: -len(", category")]


def build_v22(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:22]:
            conn.executescript(step)
        seq = 0
        positions: Dict[str, int] = {}

        def add(list_key: str, text: str, state: str = "open", *, working: int = 0, kind: str = "", swarm_ref: str = "",
                created_key: str = "owner", deleted: int = 0, group: Any = None) -> int:
            nonlocal seq
            seq += 1
            pos = positions[list_key] = positions.get(list_key, -1) + 1
            return conn.execute(
                "INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, kind, "
                "claude_working, claude_working_by, pack_ref, created_key, deleted, group_id) "
                "VALUES (?, ?, ?, 'joe', ?, 100, 100, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (list_key, text, pos, state, seq, seq, kind, working, "sessA" if working else "", swarm_ref, created_key, deleted, group)).lastrowid

        conn.execute("INSERT INTO item_groups (list_key, name, position, created_by, created_at, updated_at, seq) VALUES ('12', 'area', 0, 'joe', 1, 1, 1)")
        ids = {}
        for list_key, text, state, working, _ in TASKS:
            ids[text] = add(list_key, text, state, working=working, group=1 if text == "twelve a" else None)
        add("all", "an info line", kind="info")
        add("all", "a question", kind="question")
        add("12", "trust this folder", swarm_ref="trust:4:ab12", created_key="swarm")
        chat = add("12", "chat", swarm_ref="chat", created_key="swarm")
        add("all", "a tombstone", deleted=1)
        for item, author, kind, text, parts in [
                (ids["open plain"], "joe", "reply", "do it first", ""), (ids["reviewing"], "claude", "attention", "look here", ""),
                (ids["claimed"], "claude", "info", "on it", ""), (chat, "joe", "reply", "hello", ""),
                (chat, "claude", "info", "reported", ""),
                (ids["twelve a"], "claude", "question", "which one?", '{"context": "c", "questions": ["a", "b"]}')]:
            seq += 1
            conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq, parts) VALUES (?, ?, ?, ?, 101, ?, ?)",
                         (item, author, kind, text, seq, parts))
        conn.execute("UPDATE meta SET v = ? WHERE k = 'seq'", (seq,))
        conn.execute("PRAGMA user_version = 22")


def copy_of(base: Path, name: str) -> Path:
    folder = base / name
    folder.mkdir()
    shutil.copy2(base / "v22.db", folder / "huddle.db")
    return folder


class _V22Renamed(CplugStorage):

    def __init__(self, folder: Path) -> None:
        super().__init__(folder, None)
        self._file = folder / "renamed.db"
        shutil.copy2(folder / "huddle.db", self._file)
        with closing(sqlite3.connect(self._file)) as conn, conn:
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
                new = next((n for n, old in tables.LEGACY_NAMES.items() if old == name), None)
                if new is not None:
                    conn.execute(f'ALTER TABLE "{name}" RENAME TO "{new}"')

    @property
    def db_path(self) -> Path:
        return self._file

    def _open(self, write: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(self._file)
        conn.row_factory = sqlite3.Row
        return conn


def rows(path: Path, sql: str) -> List[tuple]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        return [tuple(r) for r in conn.execute(sql)]


@pytest.fixture()
def fixture_dir(tmp_path: Path) -> Path:
    build_v22(tmp_path / "v22.db")
    return tmp_path


def lists_of(store: TaskManagerStore) -> Dict[str, Any]:
    return {key: store.list_items(key) for key in ("all", "12", "13", "agent:3")}


def test_the_walk_backs_up_first_converts_in_place_and_changes_nothing_a_reader_sees(fixture_dir: Path, monkeypatch):
    policy.drain_kicks()
    source = fixture_dir / "v22.db"
    counts_v22 = {t: rows(source, f"SELECT COUNT(*) FROM {t}")[0][0] for (t,) in rows(source, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    task_cols = "SELECT id, list_key, position, state, claude_working, claude_working_by, group_id FROM items ORDER BY id"
    message_cols = "SELECT id, item_id, author, author_key, kind, text, answered, created_at, seq, seen, parts FROM messages ORDER BY id"
    before_tasks, before_messages, before_seq = rows(source, task_cols), rows(source, message_cols), rows(source, "SELECT v FROM meta WHERE k = 'seq'")

    for module in (store_module, store_reads):
        monkeypatch.setattr(module, "ITEM_COLS", OLD_ITEM_COLS)
        monkeypatch.setattr(module, "MSG_COLS", OLD_MSG_COLS)
    monkeypatch.setattr(store_reads.inbox_store, "open_entries_in", lambda conn, list_key: [])
    before = lists_of(TaskManagerStore(_V22Renamed(copy_of(fixture_dir, "old")), notify=lambda key: None))
    monkeypatch.undo()
    assert before["all"]["items"] and before["12"]["groups"]

    heard: List[Any] = []
    swarm = SimpleNamespace(thread_changed=lambda key: heard.append(("thread_changed", key)),
                           deal_requested=lambda key: heard.append(("deal", key)))
    folder = copy_of(fixture_dir, "new")
    ctx = SimpleNamespace(storage=WorkStorage(folder), settings={"view": "area"}, swarm=swarm,
                          notify=lambda name, key=None: heard.append(("notify", name, key)), has=lambda perm: True)
    after = lists_of(service.store(ctx))
    db = folder / "huddle.db"

    assert after == before
    assert heard == [] and policy.KICKS == set()
    assert rows(db, "SELECT COUNT(*) FROM card_events")[0][0] == 0 and rows(db, "SELECT COUNT(*) FROM card_deals")[0][0] == 0
    assert rows(db, "PRAGMA user_version")[0][0] == len(MIGRATIONS)
    assert rows(db, task_cols) == before_tasks and rows(db, message_cols) == before_messages
    assert rows(db, "SELECT v FROM meta WHERE k = 'seq'") == before_seq

    backups = sorted(p for p in folder.iterdir() if ".pre-cards-" in p.name)
    assert [p.name.split(".pre-cards-")[0] for p in backups] == ["huddle.db"] and backups[0].name.endswith("Z")
    assert rows(backups[0], "PRAGMA user_version")[0][0] == 22
    assert rows(backups[0], "PRAGMA integrity_check") == [("ok",)]
    assert {t: rows(backups[0], f"SELECT COUNT(*) FROM {t}")[0][0] for t in counts_v22} == counts_v22
    assert rows(backups[0], task_cols) == before_tasks
    assert WorkStorage(folder).size_bytes() >= db.stat().st_size + backups[0].stat().st_size

    store = TaskManagerStore(WorkStorage(folder), notify=lambda key: None)
    with closing(store._connect(False)) as conn:
        by_text = {r["text"]: r["col"] for r in conn.execute(f"SELECT text, {projection.COLUMN_SQL} AS col FROM work_items")}
        cards = {c["text"]: c for key in ("all", "12", "13", "agent:3") for c in reads.many(conn, [key])}
    assert {t[1]: by_text[t[1]] for t in TASKS} == {t[1]: t[4] for t in TASKS}
    assert {text: card["column"] for text, card in cards.items()} == {t[1]: t[4] for t in TASKS}
    assert cards["claimed"]["legacy_claim"] == "sessA" and cards["claimed"]["holder"] is None
    assert cards["open plain"]["queue_index"] == 1 and cards["burner"]["queue_index"] == 2 and cards["reviewing"]["queue_index"] is None
    assert cards["open plain"]["origin"] == {"kind": "owner", "ref": ""}
    assert all(card["parent"] is None and card["pin"] == {"agent_id": None, "place": False} for card in cards.values())


def test_a_forced_verify_failure_leaves_the_file_at_v22_and_the_next_open_retries(fixture_dir: Path, monkeypatch):
    folder = copy_of(fixture_dir, "failing")

    def refuse(copy: Path, **kwargs: Any) -> None:
        raise storage_backup.BackupFailed("forced")

    monkeypatch.setattr(storage_backup, "verify", refuse)
    with pytest.raises(CplugSchemaError, match="backup before rung 23 failed"):
        WorkStorage(folder).connect(True)
    assert rows(folder / "huddle.db", "PRAGMA user_version")[0][0] == 22
    assert not [p for p in folder.iterdir() if "pre-cards" in p.name]
    assert "card_events" not in {r[0] for r in rows(folder / "huddle.db", "SELECT name FROM sqlite_master")}
    monkeypatch.undo()
    ready.forget(WorkStorage(folder).db_path)
    WorkStorage(folder).connect(True).close()
    assert rows(folder / "huddle.db", "PRAGMA user_version")[0][0] == len(MIGRATIONS)
    assert len([p for p in folder.iterdir() if ".pre-cards-" in p.name]) == 1


def test_a_backup_is_refused_over_an_existing_name_and_a_changed_row_count(fixture_dir: Path):
    from datetime import datetime, timezone

    folder = copy_of(fixture_dir, "twice")
    when = datetime(2026, 10, 8, 3, 15, 0, tzinfo=timezone.utc)
    with closing(sqlite3.connect(folder / "huddle.db")) as conn:
        first = storage_backup.take(conn, folder / "huddle.db", "pre-cards", expect_version=22, now=when)
        assert first.name == "huddle.db.pre-cards-20261008T031500Z"
        with pytest.raises(storage_backup.BackupFailed, match="already exists"):
            storage_backup.take(conn, folder / "huddle.db", "pre-cards", expect_version=22, now=when)
        with pytest.raises(storage_backup.BackupFailed, match="schema 22, expected 21"):
            storage_backup.take(conn, folder / "huddle.db", "pre-cards", expect_version=21, now=when.replace(second=1))
    with closing(sqlite3.connect(first)) as copy:
        counts = {**storage_backup._counts(copy)}
    counts["items"] += 1
    with pytest.raises(storage_backup.BackupFailed, match="row counts differ in items"):
        storage_backup.verify(first, expect_version=22, expect_counts=counts)
    assert sorted(p.name for p in folder.iterdir()) == ["huddle.db", first.name]


def test_a_fresh_file_and_a_file_already_at_23_take_no_backup(tmp_path: Path):
    folder = tmp_path / "fresh"
    CplugStorage(folder, LEGACY_STORAGE).connect(True).close()
    CplugStorage(folder, LEGACY_STORAGE).connect(True).close()
    assert sorted(p.name for p in folder.iterdir()) == ["huddle.db"]


def test_the_sql_projection_equals_the_python_one_on_the_whole_grid(tmp_path: Path):
    store = TaskManagerStore(WorkStorage(tmp_path / "grid"), notify=lambda key: None)
    seen = 0
    with closing(store._connect(True)) as conn, conn:
        for state in rules.STATES:
            for holder in (None, 7):
                for working in (0, 1):
                    for parent, accepted in ((None, None), (5, None), (None, 9.0), (5, 9.0)):
                        seen += 1
                        conn.execute(
                            "INSERT INTO work_items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, "
                            "claude_working, card_holder, card_parent, card_accepted_at) VALUES ('1', 'x', ?, 'joe', ?, 1, 1, 1, 1, ?, ?, ?, ?)",
                            (seen, state, working, holder, parent, accepted))
        graded = conn.execute(f"SELECT {wire.ITEM_COLS}, {projection.COLUMN_SQL} AS sql_col FROM work_items").fetchall()
    assert seen == len(graded) == len(rules.STATES) * 2 * 2 * 4
    assert all(projection.column(r) == r["sql_col"] for r in graded)
    assert {r["sql_col"] for r in graded} == {"todo", "in_progress", "review", "done"}
    assert any(projection.column(r) == "done" and r["state"] == "review" for r in graded)
