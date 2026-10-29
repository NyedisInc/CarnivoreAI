
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.inventory import coverage, registry, registry_side
from src.core.inventory.claims import ClaimBook, Exclusion
from src.core.inventory.model import MAIN_STORE
from tests.python.inventory import schemas


@pytest.fixture(scope="module")
def built(tmp_path_factory: Any) -> Dict[str, Path]:
    state = tmp_path_factory.mktemp("coverage-state")
    return {MAIN_STORE: schemas.build_main(state), **schemas.build_side(state)}


def audit_all(book: ClaimBook, built: Dict[str, Path]) -> List[str]:
    problems: List[str] = []
    for store, path in built.items():
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            problems += coverage.audit(book, store, conn)
    return problems


def without(book: ClaimBook, store: str, table: str) -> ClaimBook:
    return ClaimBook([c for c in book.claims if (c.store, c.table) != (store, table)],
                     [e for e in book.exclusions if (e.store, e.table) != (store, table)], book.stores)


def test_every_table_is_claimed_or_excluded(built: Dict[str, Path]) -> None:
    assert audit_all(registry.book(), built) == []


def test_every_side_database_is_built_and_registered(built: Dict[str, Path]) -> None:
    assert set(built) == {MAIN_STORE, *registry_side.SIDE_DBS}
    stray = [s.store for s in registry_side.excluded_stores() if s.store in registry_side.SIDE_DBS]
    assert stray == [], "a database cannot be both opened and excluded"


def test_the_main_database_carries_every_table_a_live_install_has(built: Dict[str, Path]) -> None:
    with closing(sqlite3.connect(f"file:{built[MAIN_STORE]}?mode=ro", uri=True)) as conn:
        tables = set(coverage.read_tables(conn))
    assert {"message_bodies", "session_search_live", "transcript_archives", "spectator_links", "session_conversations",
            "swarm_agents", "lineage_edges", "crosstalk_messages"} <= tables



@pytest.mark.parametrize("store, table", [
    (MAIN_STORE, "lineage_edges"), (MAIN_STORE, "crosstalk_messages"), (MAIN_STORE, "projects"), (MAIN_STORE, "app_alerts"),
    (MAIN_STORE, "work_items"), (MAIN_STORE, "work_write_actors"), (registry_side.STATS, "usage_minute"),
    (registry_side.DEEPSEARCH, "session_search_live"),
])
def test_dropping_a_claim_or_exclusion_fails_the_audit(built: Dict[str, Path], store: str, table: str) -> None:
    problems = audit_all(without(registry.book(), store, table), built)
    assert any(f"{store}.{table}: neither claimed nor excluded" in p for p in problems), problems


def test_a_new_key_column_on_a_claimed_table_fails_the_audit(built: Dict[str, Path]) -> None:
    with closing(sqlite3.connect(f"file:{built[MAIN_STORE]}?mode=ro", uri=True)) as source, closing(sqlite3.connect(":memory:")) as copy:
        source.backup(copy)
        copy.execute("ALTER TABLE session_notes ADD COLUMN owner_session_uuid TEXT")
        copy.execute("ALTER TABLE layouts ADD COLUMN home_path TEXT")
        problems = coverage.audit(registry.book(), MAIN_STORE, copy)
    assert any("session_notes" in p and "owner_session_uuid" in p for p in problems), problems
    assert any("layouts" in p and "home_path" in p for p in problems), problems


@pytest.mark.parametrize("column", ["owner_uuid", "parent_id", "item_id", "uid", "tmux_name", "thread_id", "card_ref", "working_directory",
                                    "companion_of", "project_uid", "host_key"])
def test_the_detector_sees_every_common_shape_of_a_key_column(built: Dict[str, Path], column: str) -> None:
    assert coverage.identity_columns(("id", column)) == [column]


@pytest.mark.parametrize("column", ["agent_kind", "agent_family", "created_at", "updated_by", "record_type", "display_name", "id"])
def test_the_detector_leaves_labels_and_bookkeeping_alone(built: Dict[str, Path], column: str) -> None:
    assert coverage.identity_columns(("id", column)) == []


@pytest.mark.parametrize("table, kind", [("hosts", "global"), ("lineage_sources", "derived"), ("message_corpora", "dormant"),
                                         ("pack_blobs", "transient"), ("meta", "global")])
def test_any_exclusion_kind_that_gains_a_key_column_fails_the_audit(built: Dict[str, Path], table: str, kind: str) -> None:
    with closing(sqlite3.connect(f"file:{built[MAIN_STORE]}?mode=ro", uri=True)) as source, closing(sqlite3.connect(":memory:")) as copy:
        source.backup(copy)
        copy.execute(f"ALTER TABLE {table} ADD COLUMN owner_project_id INTEGER")
        problems = coverage.audit(registry.book(), MAIN_STORE, copy)
    assert any(f"{table}:" in p and "owner_project_id" in p and kind in p for p in problems), problems


def test_an_exclusion_that_ignores_a_column_the_table_lacks_fails_the_audit(built: Dict[str, Path]) -> None:
    book = registry.book()
    wrong = ClaimBook(book.claims, [*(e for e in book.exclusions if (e.store, e.table) != (MAIN_STORE, "app_alerts")),
                                    Exclusion(MAIN_STORE, "app_alerts", "unkeyed", "x", ignored=("no_such_column",))], book.stores)
    assert any("app_alerts" in p and "no_such_column" in p for p in audit_all(wrong, built))


def test_an_unkeyed_exclusion_that_gains_a_key_column_fails_the_audit(built: Dict[str, Path]) -> None:
    with closing(sqlite3.connect(f"file:{built[MAIN_STORE]}?mode=ro", uri=True)) as source, closing(sqlite3.connect(":memory:")) as copy:
        source.backup(copy)
        copy.execute("ALTER TABLE browser_sessions ADD COLUMN project_id INTEGER")
        problems = coverage.audit(registry.book(), MAIN_STORE, copy)
    assert any("browser_sessions" in p and "unkeyed" in p for p in problems), problems


def test_a_table_both_claimed_and_excluded_fails_the_audit(built: Dict[str, Path]) -> None:
    book = registry.book()
    both = ClaimBook(book.claims, [*book.exclusions, Exclusion(MAIN_STORE, "projects", "global", "x")], book.stores)
    assert any("both claimed and excluded" in p for p in audit_all(both, built))


def test_a_stale_registry_entry_fails_the_audit(built: Dict[str, Path]) -> None:
    book = registry.book()
    stale = ClaimBook(book.claims, [*book.exclusions, Exclusion(MAIN_STORE, "no_such_table", "global", "x")], book.stores)
    assert any("no_such_table: registered but not in the schema" in p for p in audit_all(stale, built))
