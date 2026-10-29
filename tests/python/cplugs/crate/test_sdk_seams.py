
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.crate_format.canonical import RawText
from src.core.db import connect, db_path_for
from src.core.project_move.plan import PaneListing
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk import exports as sdk_exports
from src.cplugs.sdk.crate_rows import RowQuery, snapshot_rows
from tests.python.inventory.world_build import build_world
from tests.python.session_purge.purge_world import add_session
from tests.python.inventory.world import CONV_A, TMUX_A, UUID_A, UUID_B


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> SimpleNamespace:
    return build_world(tmp_path_factory.mktemp("crate-seams"))


def _main_count(state: Path, table: str) -> int:
    with closing(connect(db_path_for(state))) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_snapshot_is_consistent_across_tables(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    before = _main_count(w.state, "sessions")
    queries = [RowQuery(None, cs.MAIN_STORE, "projects", "1=1"), RowQuery(None, cs.MAIN_STORE, "sessions", "1=1")]
    gen = snapshot_rows(queries, {}, state_dir=w.state)
    store, version, batches = next(gen)
    first = next(batches)
    assert first.table == "projects" and store == cs.MAIN_STORE and version >= 93
    with closing(connect(db_path_for(w.state))) as other:
        add_session(other, "late-row", "carnivore_late", None)
        other.commit()
    rows = [r for b in batches if b.table == "sessions" for r in b.rows]
    assert len(rows) == before and all(r["session_uuid"] != "late-row" for r in rows)
    assert _main_count(w.state, "sessions") == before + 1
    gen.close()


def test_secret_columns_are_absent_and_listed(world: SimpleNamespace) -> None:
    q = [RowQuery(None, cs.MAIN_STORE, "sessions", "session_uuid = ?", (UUID_A,))]
    [(_, _, batches)] = [(s, v, list(b)) for s, v, b in snapshot_rows(q, {(cs.MAIN_STORE, "sessions"): ["title"]},
                                                                       state_dir=world.state)]
    [batch] = batches
    assert batch.omitted == ["title"] and "title" not in batch.columns
    assert len(batch.rows) == 1 and "title" not in batch.rows[0] and batch.rows[0]["session_uuid"] == UUID_A
    assert "__rowid__" not in batch.rows[0] and batch.pk == ["id"] and batch.without_rowid is False


def test_a_row_under_two_queries_comes_once_in_rowid_order(world: SimpleNamespace) -> None:
    queries = [RowQuery(None, cs.MAIN_STORE, "sessions", "session_uuid = ?", (UUID_A,)),
               RowQuery(None, cs.MAIN_STORE, "sessions", "project_id = ?", (world.p1,))]
    rows = [r for _, _, batches in snapshot_rows(queries, {}, state_dir=world.state) for b in batches for r in b.rows]
    ids = [r["id"] for r in rows]
    assert ids == sorted(set(ids)) and world.row_a in ids and world.row_b in ids


def test_absent_side_database_yields_nothing_and_creates_nothing(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.db"
    assert list(snapshot_rows([RowQuery(str(ghost), "ghost.db", "t", "1=1")], {}, state_dir=tmp_path)) == []
    assert not ghost.exists()
    assert list(snapshot_rows([RowQuery(None, cs.MAIN_STORE, "sessions", "1=1")], {}, state_dir=tmp_path)) == []
    assert not db_path_for(tmp_path).exists()


def test_corrupt_database_raises_source_unavailable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite file at all, just bytes" * 200)
    with pytest.raises(cs.SourceUnavailable):
        for _, _, batches in snapshot_rows([RowQuery(str(bad), "bad.db", "t", "1=1")], {}, state_dir=tmp_path):
            list(batches)


def test_missing_table_raises_source_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "side.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE present (a)")
    with pytest.raises(cs.SourceUnavailable):
        for _, _, batches in snapshot_rows([RowQuery(str(path), "side.db", "absent", "1=1")], {}, state_dir=tmp_path):
            list(batches)


def test_without_rowid_is_ordered_by_key_and_bad_text_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "side.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA user_version = 7")
        conn.execute("CREATE TABLE kv (k TEXT, n INTEGER, v BLOB, PRIMARY KEY (k, n)) WITHOUT ROWID")
        conn.executemany("INSERT INTO kv VALUES (?, ?, ?)", [("b", 2, b"\x01"), ("a", 9, None), ("b", 1, None)])
        conn.execute("CREATE TABLE plain (t TEXT, r REAL)")
        conn.execute("INSERT INTO plain VALUES (CAST(X'FF41' AS TEXT), 1e999)")
        conn.execute("INSERT INTO plain VALUES ('ok', 0.5)")
    queries = [RowQuery(str(path), "side.db", "kv", "1=1"), RowQuery(str(path), "side.db", "plain", "1=1")]
    [(store, version, batches)] = [(s, v, list(b)) for s, v, b in snapshot_rows(queries, {}, state_dir=tmp_path)]
    assert store == "side.db" and version == 7
    kv = next(b for b in batches if b.table == "kv")
    assert kv.without_rowid and kv.pk == ["k", "n"] and [(r["k"], r["n"]) for r in kv.rows] == [
        ("a", 9), ("b", 1), ("b", 2)]
    plain = next(b for b in batches if b.table == "plain")
    assert isinstance(plain.rows[0]["t"], RawText) and plain.rows[0]["r"] == float("inf")
    assert plain.decltypes == ["TEXT", "REAL"]


def test_empty_match_still_yields_one_batch(world: SimpleNamespace) -> None:
    q = [RowQuery(None, cs.MAIN_STORE, "sessions", "session_uuid = ?", ("nobody",))]
    [(_, _, batches)] = [(s, v, list(b)) for s, v, b in snapshot_rows(q, {}, state_dir=world.state)]
    assert len(batches) == 1 and batches[0].rows == [] and "session_uuid" in batches[0].columns


def test_resolve_maps_its_errors(world: SimpleNamespace, tmp_path: Path) -> None:
    collected: list = []
    found = cs.resolve(cs.SCOPE_SESSION, UUID_A, world.locations, related_blockers=collected)
    assert found.session.session_uuid == UUID_A and collected == []
    assert cs.resolve(cs.SCOPE_PROJECT, str(world.p1), world.locations).project.project_id == world.p1
    with pytest.raises(cs.CrateTargetError) as missing:
        cs.resolve(cs.SCOPE_SESSION, "no-such-session", world.locations)
    assert missing.value.code == "target_not_found"
    with pytest.raises(cs.CrateTargetError) as missing_project:
        cs.resolve(cs.SCOPE_PROJECT, "no-such-project", world.locations)
    assert missing_project.value.code == "target_not_found"
    with pytest.raises(ValueError):
        cs.resolve("galaxy", UUID_A, world.locations)
    w = build_world(tmp_path)
    with closing(connect(db_path_for(w.state))) as conn:
        add_session(conn, "dup", TMUX_A, None)
        conn.commit()
    with pytest.raises(cs.CrateTargetError) as ambiguous:
        cs.resolve(cs.SCOPE_SESSION, TMUX_A, w.locations)
    assert ambiguous.value.code == "target_ambiguous" and set(ambiguous.value.candidates) >= {UUID_A, "dup"}
    with pytest.raises(cs.SourceUnavailable):
        cs.resolve(cs.SCOPE_SESSION, UUID_A, cs.Locations(state_dir=tmp_path / "none", config_path=tmp_path / "c"))


def test_live_panes_is_patchable_and_feeds_live_blocker(world: SimpleNamespace, monkeypatch) -> None:
    import src.api.project_move_routes as routes

    monkeypatch.setattr(routes, "read_live_panes", lambda: PaneListing(ok=True, panes=((TMUX_A, None, "/x"),)))
    listing = cs.live_panes()
    ident = cs.resolve(cs.SCOPE_SESSION, UUID_A, world.locations).session
    assert listing.ok and cs.live_blocker(ident, listing)
    assert cs.live_blocker(ident, PaneListing(ok=True, panes=())) is None
    assert cs.live_blocker(ident, PaneListing(ok=False, reason="no answer"))
    assert cs.is_local_host(None) and cs.is_local_host("local") and not cs.is_local_host("peer-1")


def test_with_main_db_round_trip(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    new = sdk_exports.Bundle(bundle_id="crate-test-0001", sha256="a" * 64, scope="session", created_at=1792267200.0,
                             session_uuid=UUID_A, locations=(sdk_exports.Location("/x/crate-test-0001.crate", 1.0),))
    sdk_exports.with_main_db(lambda conn: sdk_exports.record_bundle(
        conn, new, [sdk_exports.Pointer(CONV_A, "claude", "crate-test-0001", 1.0, "t")]), state=w.state)
    listed = sdk_exports.with_main_db(sdk_exports.list_bundles, state=w.state)
    assert "crate-test-0001" in [b.bundle_id for b in listed]
    assert CONV_A in sdk_exports.with_main_db(lambda c: sdk_exports.pointers_for(c, [CONV_A]), state=w.state)


def test_small_reads(world: SimpleNamespace) -> None:
    assert cs.fork_relatives([world.row_b], state_dir=world.state) == [(UUID_B, UUID_A)]
    assert cs.fork_relatives([world.row_a, world.row_b], state_dir=world.state) == []
    assert cs.fork_relatives([], state_dir=world.state) == []
    assert cs.project_air_gapped(world.p1, state_dir=world.state) in (False, None)
    install_id, host = cs.install_identity(state_dir=world.state)
    assert host and not host.endswith(".local")
    assert len(cs.detectors_digest()) == 64 and cs.detectors_digest() == cs.detectors_digest()
    assert cs.app_version()
    journal = cs.journal_entries(world.state, {UUID_A}, {world.row_a})
    assert journal is not None and set(journal) == {"sessions", "declined"}


def test_scan_counts_and_redact_keep_values_out() -> None:
    token = "ghp_" + "Ab1" * 12
    counts = cs.scan_counts(f"key {token} end")
    assert sum(counts.values()) >= 1 and all(isinstance(k, str) for k in counts)
    starred = cs.redact(f"key {token} end")
    assert token not in starred and len(starred) == len(f"key {token} end")
    assert cs.scan_counts("nothing secret here") == {}
