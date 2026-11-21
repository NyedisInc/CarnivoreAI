from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set

import pytest

from src.core.automations import models as automation_models
from src.core.automations.store import AutomationStore
from src.core.automations.target_projects import KINDS_WITH_PROJECT_ID
from src.core.automations.store_schema import storage_for
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.library_cleanup import project_dependents as deps
from src.core.library_cleanup import projects as projects_module
from src.core.library_cleanup.errors import CleanupNotFound, CleanupRefused
from src.core.library_cleanup.projects import merge_projects
from src.core.work.storage import FOLDER_NAME, PLUGINS_FOLDER, WorkStorage

NOW = "2026-11-11T00:00:00Z"
SOURCE, TARGET = 1, 2
SOURCE_UID, TARGET_UID = "uid-source", "uid-target"


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    ensure_db_migrated(tmp_path, 4, "test")
    WorkStorage(tmp_path / PLUGINS_FOLDER / FOLDER_NAME, tmp_path).ensure_ready()
    return tmp_path


@pytest.fixture()
def conn(state: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(db_path_for(state), create=False)) as c:
        for pid, name, uid in ((SOURCE, "old", SOURCE_UID), (TARGET, "new", TARGET_UID)):
            c.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at, uid) "
                      "VALUES (?, ?, ?, ?, 'test', ?, ?, ?)", (pid, f"/p/{name}", f"/p/{name}", name, NOW, NOW, uid))
        yield c


def _archive(c: sqlite3.Connection, project_id: int) -> int:
    return c.execute("INSERT INTO transcript_archives (archive_uuid, kind, source_path, content_gzip, content_sha256, "
                     "raw_byte_length, compressed_byte_length, line_ending, has_trailing_newline, ingested_at, project_id) "
                     "VALUES ('a1', 'session', '/x', x'00', 'h', 1, 1, 'LF', 1, ?, ?)", (NOW, project_id)).lastrowid


def _insert_row(c: sqlite3.Connection, table: str, given: Dict[str, object]) -> None:
    c.execute("PRAGMA foreign_keys = OFF")
    values = dict(given)
    for _cid, name, ctype, notnull, default, pk in c.execute(f'PRAGMA table_info("{table}")').fetchall():
        if name not in values and notnull and default is None and not pk:
            values[name] = 1 if "INT" in ctype.upper() or "REAL" in ctype.upper() else "x"
    c.execute(f'INSERT INTO "{table}" ({", ".join(values)}) VALUES ({", ".join("?" * len(values))})', tuple(values.values()))
    c.execute("PRAGMA foreign_keys = ON")


def _snapshot(c: sqlite3.Connection) -> Dict[str, List[tuple]]:
    return {t: [tuple(r) for r in c.execute(q)] for t, q in {
        "projects": "SELECT id FROM projects ORDER BY id",
        "index": "SELECT conversation_id, project_id, project_name FROM conversation_index ORDER BY 1",
        "archive": "SELECT id, project_id FROM transcript_archives ORDER BY 1"}.items()}


def _seed_movable(c: sqlite3.Connection) -> None:
    c.execute("INSERT INTO conversation_index (conversation_id, project_id, project_name, captured_at, updated_at) "
              "VALUES ('c1', ?, 'old', ?, ?)", (SOURCE, NOW, NOW))
    _archive(c, SOURCE)


def test_transcript_archive_rows_follow_the_merge(conn: sqlite3.Connection) -> None:
    archive_id = _archive(conn, SOURCE)
    conn.execute("INSERT INTO transcript_root_decisions (archive_id, decided_at, decided_by, action, project_id) "
                 "VALUES (?, ?, 'test', 'rooted', ?)", (archive_id, NOW, SOURCE))
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert conn.execute("SELECT project_id FROM transcript_archives").fetchone()[0] == TARGET
    assert conn.execute("SELECT project_id FROM transcript_root_decisions").fetchone()[0] == TARGET


def test_merge_succeeds_when_the_retired_archive_table_is_absent(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE transcript_root_decisions")
    conn.execute("DROP TABLE transcript_archives")
    conn.execute("PRAGMA foreign_keys = ON")
    _insert_row(conn, "companies", {"name": "acme", "hq_project_id": SOURCE})
    conn.execute("INSERT INTO project_storage (project_id, state, updated_at) VALUES (?, 'live', ?)", (SOURCE, NOW))
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert conn.execute("SELECT hq_project_id FROM companies").fetchone()[0] == TARGET
    assert [r[0] for r in conn.execute("SELECT project_id FROM project_storage")] == [TARGET]


def test_index_rows_take_the_target_name(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO conversation_index (conversation_id, project_id, project_name, captured_at, updated_at) "
                 "VALUES ('c1', ?, 'old', ?, ?)", (SOURCE, NOW, NOW))
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert tuple(conn.execute("SELECT project_id, project_name FROM conversation_index").fetchone()) == (TARGET, "new")


def test_storage_record_moves_when_target_has_none(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO project_storage (project_id, state, updated_at) VALUES (?, 'live', ?)", (SOURCE, NOW))
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert [r[0] for r in conn.execute("SELECT project_id FROM project_storage")] == [TARGET]


def test_storage_conflict_refuses_before_any_write(conn: sqlite3.Connection) -> None:
    for pid in (SOURCE, TARGET):
        conn.execute("INSERT INTO project_storage (project_id, state, updated_at) VALUES (?, 'live', ?)", (pid, NOW))
    _seed_movable(conn)
    before = _snapshot(conn)
    with pytest.raises(CleanupRefused) as refused:
        merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert refused.value.code == deps.REFUSE_STORAGE_CONFLICT
    assert _snapshot(conn) == before


def test_company_hq_pointer_follows_the_merge(conn: sqlite3.Connection) -> None:
    _insert_row(conn, "companies", {"name": "acme", "hq_project_id": SOURCE})
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert conn.execute("SELECT hq_project_id FROM companies").fetchone()[0] == TARGET


def test_task_manager_from_tag_follows_the_merge(conn: sqlite3.Connection) -> None:
    _insert_row(conn, "work_items", {"from_project_id": str(SOURCE), "from_project_name": "old"})
    merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert tuple(conn.execute("SELECT from_project_id, from_project_name FROM work_items").fetchone()) == (str(TARGET), "new")


def _automation(state: Path, project_id: Optional[int], target: Optional[Dict[str, object]] = None,
                automation_id: str = "aut_1") -> AutomationStore:
    store = AutomationStore(storage_for(state), notify=lambda _topic: None)
    with closing(storage_for(state).connect(True)) as db:
        db.execute("INSERT INTO automations (automation_id, name, name_key, enabled, cron, target, delivery, revision, "
                   "created_by, created_at, updated_at, project_id) VALUES (?, ?, ?, 1, '0 7 * * 1', ?, '{}', 1, "
                   "'app', 0, 0, ?)", (automation_id, automation_id, automation_id, json.dumps(target or {}), project_id))
        db.commit()
    return store


def test_automations_follow_the_merge_through_their_store(state: Path, conn: sqlite3.Connection) -> None:
    store = _automation(state, SOURCE)
    result = merge_projects(conn, SOURCE, TARGET, allow_different_folder=True, repoint_automations=store.repoint_project)
    assert result["automations_moved"] == 1
    assert store.get("aut_1")["project_id"] == TARGET
    assert store.repoint_project(SOURCE, TARGET) == 0


TARGETS = {
    "swarm_card": {"kind": "swarm_card", "project_id": SOURCE, "title": "t", "summary": "s"},
    "session_message": {"kind": "session_message", "if_gone": "start", "project_id": SOURCE},
    "command": {"kind": "command", "command": "ls", "project_id": SOURCE},
    "sequence": {"kind": "sequence", "steps": [{"kind": "command", "command": "ls", "project_id": SOURCE},
                                               {"kind": "session_message", "if_gone": "start", "project_id": SOURCE}]},
}


@pytest.mark.parametrize("kind", sorted(TARGETS))
def test_project_id_inside_the_target_json_follows_the_merge(state: Path, kind: str) -> None:
    store = _automation(state, None, TARGETS[kind])
    assert store.repoint_project(SOURCE, TARGET) == 1
    stored = store.get("aut_1")["target"]
    ids = [stored["project_id"]] if kind != "sequence" else [step["project_id"] for step in stored["steps"]]
    assert ids and set(ids) == {TARGET}
    assert store.repoint_project(SOURCE, TARGET) == 0


def test_every_target_kind_with_a_project_id_is_listed() -> None:
    carrying = {kind for kind, model in automation_models._TARGET_MODELS.items() if "project_id" in model.model_fields}
    assert carrying == KINDS_WITH_PROJECT_ID


def _hook_before_transaction(monkeypatch: pytest.MonkeyPatch, interfere: Callable[[], None]) -> None:
    real = projects_module.transaction
    fired: List[bool] = []

    def hooked(c: sqlite3.Connection):
        if not fired:
            fired.append(True)
            interfere()
        return real(c)

    monkeypatch.setattr(projects_module, "transaction", hooked)


def test_a_refused_merge_moves_no_automation_when_a_lane_row_lands_in_the_race_window(
        state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _automation(state, SOURCE)

    def land_swarm_row() -> None:
        with closing(connect(db_path_for(state), create=False)) as other:
            _insert_row(other, "swarm_project_settings", {"project_id": SOURCE})

    _hook_before_transaction(monkeypatch, land_swarm_row)
    with pytest.raises(CleanupRefused):
        merge_projects(conn, SOURCE, TARGET, allow_different_folder=True, repoint_automations=store.repoint_project)
    assert store.get("aut_1")["project_id"] == SOURCE


def test_a_concurrent_merge_of_the_target_never_strands_automations_on_a_deleted_project(
        state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_row(conn, "projects", {"id": 3, "root": "/p/third", "raw_path": "/p/third", "display_name": "third", "source": "test",
                                   "created_at": NOW, "updated_at": NOW, "uid": "uid-third"})
    store = _automation(state, SOURCE, automation_id="a1")
    _automation(state, TARGET, automation_id="a2")

    def merge_two_into_three() -> None:
        with closing(connect(db_path_for(state), create=False)) as other:
            merge_projects(other, TARGET, 3, allow_different_folder=True, repoint_automations=store.repoint_project)

    _hook_before_transaction(monkeypatch, merge_two_into_three)
    with pytest.raises(CleanupNotFound):
        merge_projects(conn, SOURCE, TARGET, allow_different_folder=True, repoint_automations=store.repoint_project)
    live = {r[0] for r in conn.execute("SELECT id FROM projects")}
    assert {store.get(a)["project_id"] for a in ("a1", "a2")} <= live
    assert store.get("a1")["project_id"] == SOURCE and store.get("a2")["project_id"] == 3


LANE_ROWS = [
    ("swarm_agents", "project_id", "id", {"rank": "project", "memory_scope": "project", "effort": "low"}),
    ("swarm_promotions", "project_id", "id", {"from_rank": "task", "to_rank": "feature"}),
    ("swarm_project_settings", "project_id", "id", {}),
    ("swarm_suggestions", "made_project_id", "id", {"kind": "project"}),
    ("project_replicas", "project_uid", "uid", {"install_id": "peer"}),
    ("pack_bundle_tips", "project_uid", "uid", {"install_id": "peer"}),
    ("pack_carried_trust", "project_uid", "uid", {}),
    ("export_bundles", "project_uid", "uid", {"sha256": "0" * 64, "scope": "project"}),
    ("swarm_remote_bodies", "project_uid", "uid", {}),
]


@pytest.mark.parametrize("table,column,kind,extra", LANE_ROWS)
def test_swarm_or_pack_data_refuses_before_any_write(conn: sqlite3.Connection, state: Path, table: str, column: str,
                                                      kind: str, extra: Dict[str, object]) -> None:
    _seed_movable(conn)
    store = _automation(state, SOURCE)
    _insert_row(conn, table, {column: SOURCE if kind == "id" else SOURCE_UID, **extra})
    before = _snapshot(conn)
    with pytest.raises(CleanupRefused) as refused:
        merge_projects(conn, SOURCE, TARGET, allow_different_folder=True, repoint_automations=store.repoint_project)
    assert refused.value.code == deps.REFUSE_SWARM_OR_PACK and f"{table}=1" in refused.value.detail
    assert _snapshot(conn) == before
    assert store.get("aut_1")["project_id"] == SOURCE


def _project_keyed(c: sqlite3.Connection) -> Set[str]:
    found: Set[str] = set()
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        cols = [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]
        fks = [r for r in c.execute(f'PRAGMA foreign_key_list("{table}")') if r[2] == "projects"]
        if fks or any("project" in col or col in deps.TASK_MANAGER_KEY_COLUMNS for col in cols):
            found.add(table)
    return found


TASK_MANAGER_ROWS = [("work_items", "list_key", {"text": "t"}), ("work_project_roles", "list_key", {}),
                     ("work_card_deals", "project_key", {"state": "waiting", "requested_at": 0}),
                     ("work_inbox", "list_key", {})]


@pytest.mark.parametrize("table,column,extra", TASK_MANAGER_ROWS)
def test_task_manager_rows_on_the_source_refuse_before_any_write(conn: sqlite3.Connection, table: str, column: str,
                                                                  extra: Dict[str, object]) -> None:
    _seed_movable(conn)
    _insert_row(conn, table, {column: str(SOURCE), **extra})
    before = _snapshot(conn)
    with pytest.raises(CleanupRefused) as refused:
        merge_projects(conn, SOURCE, TARGET, allow_different_folder=True)
    assert refused.value.code == deps.REFUSE_TASK_MANAGER and f"{table}=1" in refused.value.detail
    assert _snapshot(conn) == before


class _MemoryStore:

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def connect(self) -> sqlite3.Connection:
        return self._db


def _stats_and_message_stores() -> Iterator[sqlite3.Connection]:
    from src.core import message_host_ddl as host, message_model_ddl as model
    from src.core.stats import rules as git_rules
    from src.core.stats.plugin import schema as stats

    db = sqlite3.connect(":memory:")
    stats.migrate(db, 0)
    git_rules.initialize(_MemoryStore(db))
    yield db
    db = sqlite3.connect(":memory:")
    for ddl in (model.DDL_MESSAGE_TRANSCRIPTS, host.DDL_MESSAGE_HOSTS, host.DDL_MESSAGE_CORPORA, host.DDL_MESSAGE_PROJECTS):
        db.execute(ddl)
    for alter in host.ALTER_TRANSCRIPTS:
        db.execute(alter)
    yield db


def test_every_project_keyed_table_is_moved_refused_or_left_alone(state: Path, conn: sqlite3.Connection) -> None:
    handled = {*deps.MOVED_BY_MERGE, *(t for t, _ in deps.MOVED_COLUMNS), *(t for t, _ in deps.REFUSED_WHEN_PRESENT),
               *deps.LEFT_ALONE, *deps.task_manager_tables(conn)}
    assert _project_keyed(conn) - handled == set()
    assert deps.task_manager_tables(conn).keys() >= {"work_items", "work_project_roles", "work_card_deals"}
    for store in _stats_and_message_stores():
        assert _project_keyed(store) - handled == set()
    with closing(storage_for(state).connect(True)) as db:
        assert _project_keyed(db) == {"automations"}
