
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Sequence

from src.core.stats.plugin import live
from src.core.stats.plugin.extract import path_key
from src.core.stats.plugin.rollup import dim_id, hour_of
from src.core.stats.plugin.schema import COUNTERS

USAGE = ("minute_ts", "host", "provider", "conversation_id", "project", "model", "agent_kind", "input_tokens",
         "cache_write_tokens", "cache_read_tokens", "output_tokens", "estimated_cost_nano_usd", "price_version",
         "usage_count", "priced_usage_count", "unpriced_usage_count", "quality")
COUNTER = ("minute_ts", "host", "provider", "conversation_id", "project", "model", "agent_kind", "counter", "key",
           "value")
COVERAGE = ("minute_ts", "observed_seconds")
_SQL = re.compile(r"INSERT INTO (\w+)\s*(?:\(([^)]*)\))?\s*VALUES", re.I)


def _source(db, row: Dict[str, Any]) -> int:
    path = f"seed:{row.get('provider', 'claude')}:{row['conversation_id']}:{row.get('agent_kind', 'session')}"
    key = path_key(path)
    db.execute("INSERT OR IGNORE INTO dim_source (path_key, conversation_id, provider, agent_kind) VALUES (?,?,?,?)",
               (key, row["conversation_id"], row.get("provider", "claude"), row.get("agent_kind", "session")))
    return db.execute("SELECT id FROM dim_source WHERE path_key = ?", (key,)).fetchone()[0]


def _usage(db, row: Dict[str, Any]) -> None:
    cache: dict = {}
    src = _source(db, row)
    model, project = dim_id(db, "dim_model", row["model"], cache), dim_id(db, "dim_project", row["project"], cache)
    pv = dim_id(db, "dim_price", row["price_version"], cache) if row.get("price_version") else None
    for table, t in (("usage_minute", row["minute_ts"]), ("usage_hour", hour_of(row["minute_ts"]))):
        db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(t, src, model, project) DO "
                   "UPDATE SET input = input + excluded.input, cache_write = cache_write + excluded.cache_write, "
                   "cache_read = cache_read + excluded.cache_read, output = output + excluded.output, "
                   "cost_nano = CASE WHEN cost_nano IS NULL AND excluded.cost_nano IS NULL THEN NULL ELSE "
                   "COALESCE(cost_nano, 0) + COALESCE(excluded.cost_nano, 0) END, "
                   "messages = messages + excluded.messages, priced = priced + excluded.priced",
                   (t, src, model, project, row["input_tokens"], row["cache_write_tokens"], row["cache_read_tokens"],
                    row["output_tokens"], row["estimated_cost_nano_usd"], row["usage_count"],
                    row["priced_usage_count"], pv))


def _counter(db, row: Dict[str, Any]) -> None:
    cache: dict = {}
    src = _source(db, row)
    ids = (dim_id(db, "dim_model", row["model"], cache), dim_id(db, "dim_project", row["project"], cache),
           COUNTERS.index(row["counter"]) + 1, dim_id(db, "dim_key", row["key"], cache))
    for table, t in (("counter_minute", row["minute_ts"]), ("counter_hour", hour_of(row["minute_ts"]))):
        db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?) ON CONFLICT(t, src, model, project, counter, key) "
                   "DO UPDATE SET value = value + excluded.value", (t, src, *ids, row["value"]))


def _activity(db, row: Dict[str, Any]) -> None:
    dims = tuple(row[k] for k in ("host", "provider", "conversation_id", "project", "model", "agent_kind"))
    live.add_activity(db, row["minute_ts"], dims, (
        row.get("observed_seconds", 0), row.get("working_seconds", 0), row.get("running_seconds", 0),
        row.get("starts", 0), row.get("completions", 0), row.get("waiting_seconds", 0),
        row.get("subagent_seconds", 0)))


def _meta(db, row: Dict[str, Any]) -> None:
    if not db.execute("SELECT 1 FROM dim_source WHERE conversation_id = ?", (row["conversation_id"],)).fetchone():
        _source(db, {"provider": row.get("provider", "claude"), **row})
    sets = {k: v for k, v in row.items() if k not in ("conversation_id", "provider")}
    if sets:
        db.execute(f"UPDATE dim_source SET {', '.join(f'{k} = ?' for k in sets)} WHERE conversation_id = ?",
                   (*sets.values(), row["conversation_id"]))


_WRITERS = {"minute_usage": (USAGE, _usage), "minute_counters": (COUNTER, _counter),
            "activity_minutes": (None, _activity), "conversation_meta": (None, _meta),
            "stats_observation_coverage": (COVERAGE, lambda db, r: live.add_coverage(db, r["minute_ts"],
                                                                                    r["observed_seconds"]))}


def executemany(db, sql: str, rows: Iterable[Sequence[Any]]) -> None:
    match = _SQL.search(sql)
    table, cols = match.group(1), match.group(2)
    default, writer = _WRITERS[table]
    names = [c.strip() for c in cols.split(",")] if cols else list(default)
    for row in rows:
        writer(db, dict(zip(names, row)))


def execute(db, sql: str, row: Sequence[Any]) -> None:
    executemany(db, sql, [row])


def deliver(state_dir, path, *, family: str, conversation_id: str, file_kind: str = "conversation") -> None:
    from pathlib import Path

    from src.core.db import transaction
    from src.core.pipeline import contract as PK
    from src.core.pipeline import inherit as inheritance
    from src.core.pipeline import plugin_db as host
    from src.core.pipeline.contract import Appended
    from src.core.stats.plugin import ingest
    from src.core.stats.plugin.pipeline_plugin import STATS as STATS_PLUGIN
    from src.core.transcript_contract import parse_range

    data = Path(path).read_bytes()
    rng = parse_range(data, 0, family)
    _, start, end = inheritance.advance(PK.INHERIT_HEAD, 0, 0, rng.lines, conversation_id)
    event = Appended(conversation_id, family, str(path), file_kind, 0, rng.complete_end, rng.lines, start, end,
                     None, "test")
    conn = host.open_db(Path(state_dir), STATS_PLUGIN)
    try:
        with transaction(conn):
            ingest.on_event(conn, event)
    finally:
        conn.close()
