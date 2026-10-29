
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from src.core.pipeline import contract as C
from src.core.pipeline import deliver, plugin_db
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 40


def make_plugin() -> C.Plugin:
    def migrate(conn, _from):
        conn.execute("CREATE TABLE IF NOT EXISTS seen (n INTEGER)")

    def on_events(conn, events):
        conn.execute("INSERT INTO seen VALUES (?)", (len(events),))

    return C.Plugin(id="probe", db_name="probe.db", schema_version=1, migrate=migrate, on_events=on_events)


def make_delivery(tmp_path, plugin):
    run = deliver.PluginRun(plugin)
    delivery = SimpleNamespace(state_dir=tmp_path, clock=lambda: 1.0, timer=lambda: 0.0)
    return delivery, run


def test_deliveries_reuse_one_connection_and_a_replaced_file_is_reopened(tmp_path, monkeypatch):
    plugin = make_plugin()
    delivery, run = make_delivery(tmp_path, plugin)
    opened = count_connects(monkeypatch)
    for i in range(N):
        cursor = plugin_db.Cursor(f"/t/{i}.jsonl", f"c{i}", "claude", "conversation", offset=1)
        assert deliver._apply(delivery, run, None, object(), cursor)
    path = plugin_db.db_path(tmp_path, plugin)
    print(f"\nindexer: {N} applied events, {opens_of(opened, 'probe.db')} connects (before: {N})")
    assert opens_of(opened, "probe.db") == 1
    with sqlite3.connect(str(path)) as outside:
        assert outside.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == N
        outside.execute("INSERT INTO seen VALUES (99)")
    assert plugin_db.pooled_db(tmp_path, plugin).execute("SELECT COUNT(*) FROM seen").fetchone()[0] == N + 1

    path.unlink()
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    cursor = plugin_db.Cursor("/t/after.jsonl", "c", "claude", "conversation", offset=1)
    assert deliver._apply(delivery, run, None, object(), cursor)
    assert plugin_db.pooled_db(tmp_path, plugin).execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 1
    assert opens_of(opened, "probe.db") == 3
