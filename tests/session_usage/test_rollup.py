
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from src.core.lineage import ddl, graph
from src.core.session_usage import rollup
from src.core.stats import config
from src.core.stats.store import StatsStore
from tests.python.bookmarks import fixtures
from tests.stats import seed

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
OLD = "conv-old"
SQL = ("INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,"
       "observed_seconds,working_seconds) VALUES (?,?,?,?,?,?,?,?,?)")


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _datastore(tmp_path):
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    with closing(sqlite3.connect(db)) as conn:
        for stmt in ddl.DDL_V49:
            conn.execute(stmt)
        graph.add_edge(conn, "conversation", OLD, "session", "row-uuid-1", "clear")
        conn.commit()
    return db


def test_two_conversations_of_one_session_sum_to_its_worked_seconds(tmp_path):
    db = _datastore(tmp_path)
    store = StatsStore(tmp_path / "stats-state")
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as conn:
        for minute, conv, working in (("2026-10-13T10:00:00Z", OLD, 40), ("2026-10-13T10:01:00Z", OLD, 20),
                                      ("2026-10-14T09:00:00Z", fixtures.SOURCE, 50),
                                      ("2026-10-14T09:01:00Z", fixtures.SOURCE, 0),
                                      ("2026-10-14T09:00:00Z", "someone-else", 60),
                                      ("2026-08-01T09:00:00Z", fixtures.SOURCE, 999)):
            seed.execute(conn, SQL, (_ts(minute), "local", "claude", conv, "p", "opus", "session", 60, working))
    answer = rollup.build(30, now=NOW, db=db, stats_db=store.db_path)
    assert answer["state"] == "ok"
    assert set(answer["by_session"]) == {"row-uuid-1"}
    mine = answer["by_session"]["row-uuid-1"]
    assert mine["worked_s"] == 110 and mine["active_days"] >= 2
    assert mine["last_worked_at"] == "2026-10-14T09:00:00Z"


def test_an_absent_stats_store_answers_no_stats_not_zero(tmp_path):
    answer = rollup.build(30, now=NOW, db=_datastore(tmp_path), stats_db=tmp_path / "nope" / "stats.db")
    assert answer["state"] == "no_stats" and answer["by_session"] == {} and answer["measured_since"] is None
