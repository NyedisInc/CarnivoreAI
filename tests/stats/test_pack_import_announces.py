from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.pack.rollup_import import store as rollup_store
from src.core.stats import changes, pack_scope
from src.core.stats.store import StatsStore

PEER = "install-nostromo"


def _pass(store, before):
    now = pack_scope.rollup_fingerprint(store)
    moved = now is not None and now != before
    return now, changes.summarise(published_sources=0, activity_metrics=(), live_before={}, live_after={},
                                  events_before=0, events_after=0, pack_imported=moved)


def test_an_import_with_no_local_usage_publishes_the_usage_metrics(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    store = StatsStore(tmp_path)
    with closing(connect(db_path_for(tmp_path))) as conn:
        peer_hosts.upsert(conn, install_id=PEER, label="nostromo", grant_id="g1", fid="f1", initiator=False)
        rollup_store.finish(conn, PEER, 1, "d1", 1.0)
    seen, first = _pass(store, None)
    assert first.metrics >= changes.USAGE_METRICS
    seen, quiet = _pass(store, seen)
    assert quiet.empty
    with closing(connect(db_path_for(tmp_path))) as conn:
        rollup_store.finish(conn, PEER, 2, "d1", 2.0)
    _, again = _pass(store, seen)
    assert again.metrics >= changes.USAGE_METRICS
