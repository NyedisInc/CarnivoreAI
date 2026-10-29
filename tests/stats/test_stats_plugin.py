from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from src.core.db import transaction
from src.core.pipeline import contract as PK
from src.core.pipeline import inherit as inheritance
from src.core.pipeline import plugin_db as host
from src.core.pipeline import registry
from src.core.pipeline.contract import Appended, ConversationRemoved, FileReset
from src.core.stats import config, queries
from src.core.stats.plugin import carry, ingest, rollup
from src.core.stats.plugin.pipeline_plugin import STATS as STATS_PLUGIN
from src.core.stats.pricing import estimate
from src.core.stats.store import StatsStore
from src.core.transcript_contract import parse_range
from src.models.stats import QueryRequest

CONV = "11111111-2222-3333-4444-555555555555"
PARENT = "99999999-2222-3333-4444-555555555555"
T0 = 1772949600
MODEL = "claude-opus-4-7"


def _iso(t: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _assistant(t: int, msg: str, out: int, *, inp: int = 10, session: str = CONV, stop=None, tools=(),
               **extra) -> dict:
    content = [{"type": "tool_use", "id": f"tu-{msg}-{n}", "name": n, "input": {}} for n in tools]
    return {"type": "assistant", "sessionId": session, "timestamp": _iso(t), "cwd": "/work/app", "uuid": f"u-{msg}-{out}",
            "message": {"id": msg, "model": MODEL, "stop_reason": stop, "content": content,
                        "usage": {"input_tokens": inp, "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 5, "output_tokens": out}}, **extra}


def _blob(records) -> bytes:
    return b"".join((json.dumps(r) + "\n").encode() for r in records)


@pytest.fixture
def plugin_db(tmp_path):
    conn = host.open_db(tmp_path, STATS_PLUGIN)
    state = {"offset": 0, "inherit": (PK.INHERIT_HEAD, 0, 0)}

    def deliver(records, *, path=f"/t/{CONV}.jsonl", kind="conversation", family="claude", own=CONV, now=None):
        data = _blob(records)
        rng = parse_range(data, state["offset"], family)
        st, start, end = inheritance.advance(*state["inherit"], rng.lines, own)
        state["inherit"] = (st, start, end)
        event = Appended(own, family, path, kind, state["offset"], rng.complete_end, rng.lines, start, end, None, "test")
        state["offset"] = rng.complete_end
        with transaction(conn):
            ingest.appended(conn, event, now=now)
        return event

    yield conn, deliver, state
    conn.close()


def _q(conn, sql, *args):
    return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def test_minute_and_hour_rollups_are_written_at_ingest_and_a_streamed_response_counts_once(plugin_db):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0 + 5, "msg-a", 1), _assistant(T0 + 6, "msg-a", 7)], now=T0)
    deliver([_assistant(T0 + 7, "msg-a", 20, stop="end_turn"), _assistant(T0 + 125, "msg-b", 3, tools=("Bash",))],
            now=T0)
    minute = _q(conn, "SELECT t, input, cache_read, output, messages FROM usage_minute ORDER BY t")
    assert minute == [(T0, 10, 5, 20, 1), (T0 + 120, 10, 5, 3, 1)]
    assert _q(conn, "SELECT t, input, cache_read, output, messages FROM usage_hour") == [(T0, 20, 10, 23, 2)]
    cost = estimate(MODEL, (10, 0, 5, 20))[0] + estimate(MODEL, (10, 0, 5, 3))[0]
    assert _q(conn, "SELECT cost_nano FROM usage_hour") == [(cost,)]
    counters = _q(conn, "SELECT counter, key, value FROM minute_counters ORDER BY counter")
    assert counters == [("stop_reasons", "end_turn", 1), ("tool_calls", "Bash", 1)]
    view = _q(conn, "SELECT conversation_id, agent_kind, model, SUM(output_tokens) FROM minute_usage GROUP BY 1, 2, 3")
    assert view == [(CONV, "session", MODEL, 23)]


def test_a_fork_copied_head_is_not_counted_and_counting_it_would_be_red(plugin_db, monkeypatch, tmp_path):
    conn, deliver, _ = plugin_db
    copied = [_assistant(T0 + 60 * i, f"parent-{i}", 100, session=PARENT) for i in range(3)]
    own = [_assistant(T0 + 600, "child-1", 4)]
    event = deliver(copied + own, now=T0)
    assert event.inherited_end > event.inherited_start == 0
    assert _q(conn, "SELECT SUM(output_tokens), SUM(usage_count) FROM minute_usage") == [(4, 1)]
    monkeypatch.setattr(Appended, "own_lines", property(lambda self: self.lines))
    fresh = host.open_db(tmp_path, STATS_PLUGIN, path=tmp_path / "red.db")
    with transaction(fresh):
        ingest.appended(fresh, event, now=T0)
    assert _q(fresh, "SELECT SUM(output_tokens) FROM minute_usage") == [(304,)]
    fresh.close()


def test_a_rewrite_drops_what_the_file_gave_and_the_redelivery_counts_once(plugin_db):
    conn, deliver, state = plugin_db
    deliver([_assistant(T0, "msg-a", 50), _assistant(T0 + 60, "msg-b", 60)], now=T0)
    other = f"/t/{PARENT}.jsonl"
    deliver([_assistant(T0, "msg-p", 9, session=PARENT)], path=other, own=PARENT, now=T0)
    with transaction(conn):
        ingest.on_event(conn, FileReset(PK.EV_FILE_REWRITTEN, CONV, "claude", f"/t/{CONV}.jsonl", "conversation", 1, 1))
    assert _q(conn, "SELECT conversation_id, SUM(output_tokens) FROM minute_usage GROUP BY 1") == [(PARENT, 9)]
    assert _q(conn, "SELECT COUNT(*) FROM usage_hour u JOIN dim_source s ON s.id = u.src WHERE s.conversation_id = ?",
              CONV) == [(0,)]
    state.update(offset=0, inherit=(PK.INHERIT_HEAD, 0, 0))
    deliver([_assistant(T0, "msg-a", 50)], now=T0)
    totals = dict(_q(conn, "SELECT conversation_id, SUM(u.output) FROM usage_hour u JOIN dim_source s "
                           "ON s.id = u.src GROUP BY 1"))
    assert totals == {CONV: 50, PARENT: 9}
    with transaction(conn):
        ingest.on_event(conn, ConversationRemoved(PARENT, (other,)))
    assert dict(_q(conn, "SELECT conversation_id, SUM(output_tokens) FROM minute_usage GROUP BY 1")) == {CONV: 50}


def test_minute_detail_is_pruned_after_seven_days_and_hour_totals_answer_instead(plugin_db):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0 + 60 * i, f"m{i}", 10) for i in range(5)], now=T0)
    assert _q(conn, "SELECT COUNT(*) FROM usage_minute") == [(5,)]
    later = T0 + 8 * 86400
    deliver([_assistant(later, "late", 1)], now=later)
    floor = _q(conn, "SELECT minute_floor FROM stat_retention")[0][0]
    assert floor == rollup.hour_of(later - 7 * 86400) and floor > T0
    assert _q(conn, "SELECT t FROM usage_minute") == [(later,)]
    assert _q(conn, "SELECT t, output FROM usage_hour ORDER BY t") == [(T0, 50), (rollup.hour_of(later), 1)]
    assert _q(conn, "SELECT minute_ts, output_tokens FROM minute_usage ORDER BY minute_ts") == [(T0, 50), (later, 1)]


def test_codex_cumulative_totals_count_as_deltas(plugin_db):
    conn, deliver, _ = plugin_db

    def tc(t, inp, out):
        return {"type": "event_msg", "timestamp": _iso(t), "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": inp, "cached_input_tokens": 0, "output_tokens": out}}}}
    records = [{"type": "session_meta", "timestamp": _iso(T0), "payload": {"cwd": "/w", "cli_version": "0.115.0"}},
               {"type": "turn_context", "timestamp": _iso(T0), "payload": {"model": "gpt-5"}},
               tc(T0 + 1, 100, 10), tc(T0 + 61, 150, 30), tc(T0 + 62, 150, 30)]
    deliver(records, path="/c/rollout.jsonl", family="codex", own="cx-1", now=T0)
    assert _q(conn, "SELECT t, input, output, messages FROM usage_minute ORDER BY t") == [(T0, 100, 10, 1),
                                                                                         (T0 + 60, 50, 20, 1)]
    assert _q(conn, "SELECT provider, cli_version FROM dim_source") == [("codex", "0.115.0")]


def test_disabled_span_lines_are_skipped(plugin_db):
    conn, deliver, _ = plugin_db
    conn.execute("CREATE TABLE stats_disabled_spans (start_ts INTEGER PRIMARY KEY, end_ts INTEGER)")
    conn.execute("INSERT INTO stats_disabled_spans VALUES (?, ?)", (T0 + 60, T0 + 120))
    deliver([_assistant(T0, "a", 1), _assistant(T0 + 60, "b", 2), _assistant(T0 + 120, "c", 4)], now=T0)
    assert _q(conn, "SELECT SUM(output) FROM usage_minute") == [(5,)]


def test_the_plugin_is_registered_and_its_db_is_the_stats_store(tmp_path):
    assert registry.find("stats") is STATS_PLUGIN
    store = StatsStore(tmp_path)
    store.initialize()
    assert store.db_path == tmp_path / PK.PLUGIN_DIR / "stats.db"
    assert not (tmp_path / "cloude-stats.db").exists()


def test_the_old_database_is_retired_and_only_its_settings_come_across(tmp_path):
    legacy = tmp_path / "cloude-stats.db"
    with closing(sqlite3.connect(legacy)) as old:
        old.executescript("""
            CREATE TABLE stats_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO stats_meta VALUES ('revision', '41');
            CREATE TABLE stats_charts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, config_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            INSERT INTO stats_charts VALUES ('chart-1', 3, '{}', 1, 2);
            CREATE TABLE minute_usage (minute_ts INTEGER, output_tokens INTEGER);
            INSERT INTO minute_usage VALUES (60, 999);""")
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    retired = list(tmp_path.glob("cloude-stats.db.retired-*"))
    assert len(retired) == 1 and not legacy.exists()
    with store.connect(readonly=True) as db:
        assert db.execute("SELECT id, revision FROM stats_charts").fetchall()[0][:] == ("chart-1", 3)
        assert db.execute("SELECT COUNT(*) FROM minute_usage").fetchone()[0] == 0
    assert store.revision() == 41
    store.initialize()
    assert len(list(tmp_path.glob("cloude-stats.db.retired-*"))) == 1


def test_carry_over_keeps_settings_and_live_signals_but_not_transcript_numbers(plugin_db, tmp_path):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0, "a", 5)], now=T0)
    from src.core.stats.plugin import live
    with transaction(conn):
        live.add_activity(conn, T0, ("local", "claude", CONV, "p", MODEL, "session"), (30, 20, 30, 1, 0, 0, 0))
    fresh = host.open_db(tmp_path, STATS_PLUGIN, path=tmp_path / "fresh.db")
    with transaction(fresh):
        carry.carry_over(conn, fresh)
    assert _q(fresh, "SELECT SUM(working_seconds) FROM activity_minutes") == [(20.0,)]
    assert _q(fresh, "SELECT COUNT(*) FROM usage_minute") == [(0,)]
    fresh.close()


def test_a_reader_query_reads_the_plugin_rows(plugin_db, tmp_path):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0 + 5, "a", 7), _assistant(T0 + 3700, "b", 3)], now=T0)
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled = 1")
    request = QueryRequest.model_validate({"metric": "output_tokens", "from": _iso(T0), "to": _iso(T0 + 7200),
                                           "resolution": "hour", "group_by": "model"})
    out = queries.execute(store, request)
    assert [p["value"] for p in out["series"][0]["points"]] == [7, 3]


def test_a_response_whose_lines_interleave_with_another_counts_once(plugin_db):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0, "a", 2), _assistant(T0 + 1, "b", 5), _assistant(T0 + 2, "a", 9)], now=T0)
    assert _q(conn, "SELECT SUM(output), SUM(messages) FROM usage_minute") == [(14, 2)]


def test_a_quiet_file_keeps_one_open_response(plugin_db):
    conn, deliver, _ = plugin_db
    deliver([_assistant(T0, "a", 2), _assistant(T0 + 1, "b", 5)], now=T0 + 10)
    assert _q(conn, "SELECT wide FROM file_state") == [(1,)]
    other = f"/t/{PARENT}.jsonl"
    deliver([_assistant(T0 + 7200, "p", 1, session=PARENT)], path=other, own=PARENT, now=T0 + 7200)
    widths = sorted(len(json.loads(r[0])["open"]) for r in conn.execute("SELECT state FROM file_state"))
    assert widths == [1, 1] and _q(conn, "SELECT SUM(wide) FROM file_state") == [(0,)]


def _open_backfills(store):
    with store.connect(readonly=True) as db:
        return db.execute("SELECT COUNT(*) FROM stats_backfill WHERE state IN ('requested', 'running')").fetchone()[0]


def test_retirement_does_not_carry_an_open_backfill_request(tmp_path):
    legacy = tmp_path / "cloude-stats.db"
    with closing(sqlite3.connect(legacy)) as old:
        old.executescript("""
            CREATE TABLE stats_backfill (idempotency_key TEXT PRIMARY KEY, state TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            INSERT INTO stats_backfill VALUES ('k1', 'running', 1, 1), ('k2', 'requested', 1, 1),
                ('k3', 'complete', 1, 1);""")
    store = StatsStore(tmp_path)
    store.initialize()
    assert _open_backfills(store) == 0
    with store.connect(readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM stats_backfill").fetchone()[0] == 3


def test_carry_over_leaves_no_open_backfill_request(tmp_path):
    old_store = StatsStore(tmp_path / "a")
    old_store.initialize()
    config.ensure_schema(old_store)
    with old_store.connect() as db:
        db.execute("INSERT INTO stats_backfill (idempotency_key, state, requested_at, updated_at) VALUES ('k1', 'running', 1, 1)")
    fresh = host.open_db(tmp_path, STATS_PLUGIN, path=tmp_path / "fresh.db")
    with closing(sqlite3.connect(old_store.db_path)) as old, transaction(fresh):
        carry.carry_over(old, fresh)
    assert fresh.execute("SELECT state FROM stats_backfill WHERE idempotency_key = 'k1'").fetchone()[0] == "complete"
    fresh.close()


def test_startup_repairs_an_install_already_carrying_a_stale_request(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("INSERT INTO stats_backfill (idempotency_key, state, requested_at, updated_at) VALUES ('stale', 'running', 1, 1)")
    assert _open_backfills(store) == 1
    store.initialize()
    assert _open_backfills(store) == 0
