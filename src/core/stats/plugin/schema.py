
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

COUNTERS = ("tool_calls", "stop_reasons", "thinking_tokens", "web_searches", "web_fetches",
            "compactions", "turns", "cache_write_5m_tokens", "cache_write_1h_tokens")

MINUTE_RETENTION_SECONDS = 7 * 86400

_USAGE_COLS = ("input INTEGER NOT NULL, cache_write INTEGER NOT NULL, cache_read INTEGER NOT NULL, "
               "output INTEGER NOT NULL, cost_nano INTEGER, messages INTEGER NOT NULL, "
               "priced INTEGER NOT NULL, pv INTEGER")
_ACTIVITY_COLS = ("observed REAL NOT NULL DEFAULT 0, working REAL NOT NULL DEFAULT 0, "
                  "running REAL NOT NULL DEFAULT 0, starts INTEGER NOT NULL DEFAULT 0, "
                  "completions INTEGER NOT NULL DEFAULT 0, waiting REAL NOT NULL DEFAULT 0, "
                  "subagent REAL NOT NULL DEFAULT 0")
_QUOTA_COLS = ("t INTEGER NOT NULL, account_id TEXT NOT NULL, provider TEXT NOT NULL, window TEXT NOT NULL, "
               "reset_at TEXT NOT NULL, utilization REAL, fetched_at TEXT NOT NULL, state TEXT NOT NULL, "
               "PRIMARY KEY(t, account_id, window, reset_at)")

TABLES = f"""
CREATE TABLE IF NOT EXISTS stats_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO stats_meta(key, value) VALUES ('revision', '0');
CREATE TABLE IF NOT EXISTS stats_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
    kind TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{{}}');
CREATE INDEX IF NOT EXISTS stats_events_time ON stats_events(occurred_at);
CREATE TABLE IF NOT EXISTS stats_models_seen (model TEXT PRIMARY KEY, first_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS price_versions (
    version TEXT PRIMARY KEY, source TEXT NOT NULL, source_date TEXT NOT NULL, rates_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stat_retention (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1), minute_floor INTEGER NOT NULL);
INSERT OR IGNORE INTO stat_retention VALUES (1, 0);

CREATE TABLE IF NOT EXISTS dim_source (
    id INTEGER PRIMARY KEY, path_key INTEGER NOT NULL UNIQUE, conversation_id TEXT NOT NULL,
    provider TEXT NOT NULL, agent_kind TEXT NOT NULL, parent_conversation_id TEXT, account_id TEXT,
    subagent_type TEXT, first_minute INTEGER, last_minute INTEGER, cli_version TEXT, branch_hash TEXT);
CREATE TABLE IF NOT EXISTS dim_model (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dim_project (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dim_key (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dim_counter (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dim_price (id INTEGER PRIMARY KEY, version TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dim_live (
    id INTEGER PRIMARY KEY, host TEXT NOT NULL, provider TEXT NOT NULL, conversation_id TEXT NOT NULL,
    project TEXT NOT NULL, model TEXT NOT NULL, agent_kind TEXT NOT NULL,
    UNIQUE(host, provider, conversation_id, project, model, agent_kind));
-- Per-file reading state the next event needs: the running model and the open (still streaming) response for
-- Claude, the cumulative token segment for Codex. One small row per file. Wide rows (a live file, several
-- open responses) are trimmed to one open response once the file has been quiet an hour (ingest.trim_idle).
CREATE TABLE IF NOT EXISTS file_state (src INTEGER PRIMARY KEY, last_t INTEGER NOT NULL, wide INTEGER NOT NULL,
    state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS file_state_wide ON file_state(last_t) WHERE wide = 1;

CREATE TABLE IF NOT EXISTS usage_minute (t INTEGER NOT NULL, src INTEGER NOT NULL, model INTEGER NOT NULL,
    project INTEGER NOT NULL, {_USAGE_COLS}, PRIMARY KEY(t, src, model, project)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS usage_hour (t INTEGER NOT NULL, src INTEGER NOT NULL, model INTEGER NOT NULL,
    project INTEGER NOT NULL, {_USAGE_COLS}, PRIMARY KEY(t, src, model, project)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS counter_minute (t INTEGER NOT NULL, src INTEGER NOT NULL, model INTEGER NOT NULL,
    project INTEGER NOT NULL, counter INTEGER NOT NULL, key INTEGER NOT NULL, value INTEGER NOT NULL,
    PRIMARY KEY(t, src, model, project, counter, key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS counter_hour (t INTEGER NOT NULL, src INTEGER NOT NULL, model INTEGER NOT NULL,
    project INTEGER NOT NULL, counter INTEGER NOT NULL, key INTEGER NOT NULL, value INTEGER NOT NULL,
    PRIMARY KEY(t, src, model, project, counter, key)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS activity_minute (t INTEGER NOT NULL, live INTEGER NOT NULL, {_ACTIVITY_COLS},
    PRIMARY KEY(t, live)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS activity_hour (t INTEGER NOT NULL, live INTEGER NOT NULL, {_ACTIVITY_COLS},
    PRIMARY KEY(t, live)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS coverage_minute (t INTEGER PRIMARY KEY, observed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS coverage_hour (t INTEGER PRIMARY KEY, observed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quota_minute ({_QUOTA_COLS}) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS quota_hour ({_QUOTA_COLS}) WITHOUT ROWID;
"""

_FLOOR = "(SELECT minute_floor FROM stat_retention WHERE singleton = 1)"
FLOOR_SQL = _FLOOR


def _usage_arm(table: str, below: bool) -> str:
    cmp = f"u.t < {_FLOOR}" if below else f"u.t >= {_FLOOR}"
    return (f"SELECT u.t AS minute_ts, 'local' AS host, s.provider AS provider, s.conversation_id AS conversation_id, "
            f"p.name AS project, m.name AS model, s.agent_kind AS agent_kind, u.input AS input_tokens, "
            f"u.cache_write AS cache_write_tokens, u.cache_read AS cache_read_tokens, u.output AS output_tokens, "
            f"u.cost_nano AS estimated_cost_nano_usd, v.version AS price_version, u.messages AS usage_count, "
            f"u.priced AS priced_usage_count, u.messages - u.priced AS unpriced_usage_count, 'ok' AS quality "
            f"FROM {table} u JOIN dim_source s ON s.id = u.src JOIN dim_model m ON m.id = u.model "
            f"JOIN dim_project p ON p.id = u.project LEFT JOIN dim_price v ON v.id = u.pv WHERE {cmp}")


def _counter_arm(table: str, below: bool) -> str:
    cmp = f"c.t < {_FLOOR}" if below else f"c.t >= {_FLOOR}"
    return (f"SELECT c.t AS minute_ts, 'local' AS host, s.provider AS provider, s.conversation_id AS conversation_id, "
            f"p.name AS project, m.name AS model, s.agent_kind AS agent_kind, n.name AS counter, k.name AS key, "
            f"c.value AS value FROM {table} c JOIN dim_source s ON s.id = c.src JOIN dim_model m ON m.id = c.model "
            f"JOIN dim_project p ON p.id = c.project JOIN dim_counter n ON n.id = c.counter "
            f"JOIN dim_key k ON k.id = c.key WHERE {cmp}")


def _activity_arm(table: str, below: bool) -> str:
    cmp = f"a.t < {_FLOOR}" if below else f"a.t >= {_FLOOR}"
    return (f"SELECT a.t AS minute_ts, d.host, d.provider, d.conversation_id, d.project, d.model, d.agent_kind, "
            f"a.observed AS observed_seconds, a.working AS working_seconds, a.running AS running_seconds, "
            f"a.starts, a.completions, a.waiting AS waiting_seconds, a.subagent AS subagent_seconds "
            f"FROM {table} a JOIN dim_live d ON d.id = a.live WHERE {cmp}")


def _quota_arm(table: str, below: bool) -> str:
    cmp = f"t < {_FLOOR}" if below else f"t >= {_FLOOR}"
    return (f"SELECT t AS minute_ts, account_id, provider, window, reset_at, utilization, fetched_at, state "
            f"FROM {table} WHERE {cmp}")


def _coverage_arm(table: str, below: bool) -> str:
    cmp = f"t < {_FLOOR}" if below else f"t >= {_FLOOR}"
    return f"SELECT t AS minute_ts, observed AS observed_seconds FROM {table} WHERE {cmp}"


VIEWS = {
    "minute_usage": (_usage_arm, "usage_minute", "usage_hour"),
    "minute_counters": (_counter_arm, "counter_minute", "counter_hour"),
    "activity_minutes": (_activity_arm, "activity_minute", "activity_hour"),
    "quota_minutes": (_quota_arm, "quota_minute", "quota_hour"),
    "stats_observation_coverage": (_coverage_arm, "coverage_minute", "coverage_hour"),
}

CONVERSATION_META_VIEW = (
    "CREATE VIEW IF NOT EXISTS conversation_meta AS SELECT conversation_id, provider, account_id, "
    "parent_conversation_id, subagent_type, first_minute, last_minute, cli_version, branch_hash FROM dim_source")


def migrate(conn: sqlite3.Connection, from_version: int) -> None:
    if from_version >= SCHEMA_VERSION:
        return
    for statement in TABLES.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.executemany("INSERT OR IGNORE INTO dim_counter (id, name) VALUES (?, ?)",
                     [(i + 1, name) for i, name in enumerate(COUNTERS)])
    for view, (arm, minute, hour) in VIEWS.items():
        conn.execute(f"CREATE VIEW IF NOT EXISTS {view} AS {arm(minute, False)} UNION ALL {arm(hour, True)}")
    conn.execute(CONVERSATION_META_VIEW)
