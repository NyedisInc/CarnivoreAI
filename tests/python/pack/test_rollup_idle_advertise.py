from __future__ import annotations

from pathlib import Path

from src.core.stats import rollup, wiring
from src.core.stats.plugin import revision
from src.core.stats.store import StatsStore
from tests.python.pack.test_rollup_import import (  # noqa: F401
    PEER, Clock, Peer, _conversation, _importer, _run, _source_totals, _totals, b_state)


def _pre_k1b_store(state: Path) -> StatsStore:
    store = StatsStore(state)
    store.state_dir.mkdir(parents=True, exist_ok=True)
    from src.core.pipeline import plugin_db
    from src.core.stats.plugin.pipeline_plugin import STATS

    conn = plugin_db.open_db(state, STATS)
    try:
        for i in range(4):
            _conversation(conn, f"idle-{i}", f"proj{i % 2}", list(range(3)), seed=i)
        for table in (revision.TABLE_REV, revision.TABLE_META):
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    finally:
        conn.close()
    return store


def test_history_without_a_new_flush_is_advertised_and_pulled(tmp_path, b_state, monkeypatch):
    monkeypatch.delenv("CLOUDE_TEST_MODE", raising=False)
    store = _pre_k1b_store(tmp_path / "idle")
    with store.connect(readonly=True) as conn:
        assert not revision.exists(conn), "the fixture must be a pre-K1b file"
        assert conn.execute("SELECT COUNT(*) FROM usage_hour").fetchone()[0] > 0, "population: the file holds history"
    wiring.initialize(store)
    advertised = rollup.advertised_revisions(store)
    assert advertised.get("stats", 0) > 0, "history that exists is advertised at start"

    peer, clock = Peer(tmp_path), Clock()
    peer.conn = store.connect()
    try:
        _run(_importer(b_state, peer, clock).maybe_pull(PEER, {"install_id": PEER, "pipeline_rev": advertised}))
        assert peer.requests, "the advertisement made the peer pull"
        stored = _totals(b_state)
        assert stored[0] > 0 and stored == _source_totals(peer.conn), "the pull imported the whole pre-K1b history"
    finally:
        peer.conn.close()
