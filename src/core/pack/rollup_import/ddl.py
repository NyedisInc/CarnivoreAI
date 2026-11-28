
from __future__ import annotations

import sqlite3
import time
from typing import Tuple

USAGE_TABLE = "pack_rollups"
COUNTER_TABLE = "pack_rollup_counters"
STATE_TABLE = "pack_rollup_state"
REV_TABLE = "pack_rollup_rev"
META_TABLE = "pack_rollup_meta"
PROJECTS_TABLE = "pack_rollup_projects"
RELAY_STATE_TABLE = "pack_rollup_relay_state"
OFFERS_TABLE = "pack_rollup_offers"
FLOOR_TABLE = "pack_rollup_floor"
USAGE_5M_TABLE = "pack_rollups_5m"
ACTIVITY_TABLE = "pack_rollup_activity"
QUOTA_TABLE = "pack_rollup_quota"
CONVERSATIONS_TABLE = "pack_rollup_conversations"
EVENTS_TABLE = "pack_rollup_events"
COVERAGE_TABLE = "pack_rollup_coverage"
MCP_TABLE = "pack_rollup_mcp"
NAMES_FLOOR_KEY = "\0names"
EPOCH_FLOOR_KEY = "\0epoch"
V2_FLOOR_KEY = "\0v2"
RELAY_REV_KEY = "relay_rev"

DDL_V89: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {USAGE_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        provider        TEXT,
        agent_kind      TEXT,
        model           TEXT NOT NULL,
        project         TEXT NOT NULL,
        input           INTEGER NOT NULL DEFAULT 0,
        cache_write     INTEGER NOT NULL DEFAULT 0,
        cache_read      INTEGER NOT NULL DEFAULT 0,
        output          INTEGER NOT NULL DEFAULT 0,
        cost_nano       INTEGER NOT NULL DEFAULT 0,
        messages        INTEGER NOT NULL DEFAULT 0,
        priced          INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, conversation_id, hour, model, project)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {USAGE_TABLE}_hour ON {USAGE_TABLE}(hour)",
    f"""CREATE TABLE IF NOT EXISTS {COUNTER_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        provider        TEXT,
        agent_kind      TEXT,
        model           TEXT NOT NULL,
        project         TEXT NOT NULL,
        counter         TEXT NOT NULL,
        key             TEXT NOT NULL,
        value           INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, conversation_id, hour, model, project, counter, key)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {COUNTER_TABLE}_hour ON {COUNTER_TABLE}(hour)",
    f"""CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
        peer_install_id TEXT PRIMARY KEY,
        revision        INTEGER NOT NULL DEFAULT 0,
        scope_digest    TEXT NOT NULL DEFAULT '',
        pulled_at       REAL NOT NULL DEFAULT 0,
        updated_at      REAL NOT NULL DEFAULT 0
    ) WITHOUT ROWID""",
)


V103_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (USAGE_TABLE, "agent_name", f"ALTER TABLE {USAGE_TABLE} ADD COLUMN agent_name TEXT"),
)


def apply_v103(conn: sqlite3.Connection) -> None:
    for table, column, statement in V103_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


def apply_v89(conn: sqlite3.Connection) -> None:
    for statement in DDL_V89:
        conn.execute(statement)


DDL_V107: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {REV_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        rev             INTEGER NOT NULL,
        PRIMARY KEY (peer_install_id, conversation_id, hour)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {REV_TABLE}_rev ON {REV_TABLE}(rev, hour, conversation_id, peer_install_id)",
    f"CREATE TABLE IF NOT EXISTS {META_TABLE} (k TEXT PRIMARY KEY, v INTEGER) WITHOUT ROWID",
    f"""CREATE TABLE IF NOT EXISTS {PROJECTS_TABLE} (
        peer_install_id TEXT NOT NULL,
        project         TEXT NOT NULL,
        name            TEXT NOT NULL,
        home_install_id TEXT,
        PRIMARY KEY (peer_install_id, project)
    ) WITHOUT ROWID""",
    f"""CREATE TABLE IF NOT EXISTS {RELAY_STATE_TABLE} (
        forwarder_install_id TEXT PRIMARY KEY,
        revision             INTEGER NOT NULL DEFAULT 0,
        scope_digest         TEXT NOT NULL DEFAULT '',
        pulled_at            REAL,
        updated_at           REAL
    ) WITHOUT ROWID""",
    f"""CREATE TABLE IF NOT EXISTS {OFFERS_TABLE} (
        forwarder_install_id TEXT NOT NULL,
        origin_install_id    TEXT NOT NULL,
        hops                 INTEGER,
        updated_at           REAL,
        PRIMARY KEY (forwarder_install_id, origin_install_id)
    ) WITHOUT ROWID""",
)

V107_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (STATE_TABLE, "via", f"ALTER TABLE {STATE_TABLE} ADD COLUMN via TEXT NOT NULL DEFAULT ''"),
    (STATE_TABLE, "hops", f"ALTER TABLE {STATE_TABLE} ADD COLUMN hops INTEGER NOT NULL DEFAULT 1"),
    (STATE_TABLE, "label", f"ALTER TABLE {STATE_TABLE} ADD COLUMN label TEXT"),
    (STATE_TABLE, "one_way", f"ALTER TABLE {STATE_TABLE} ADD COLUMN one_way TEXT NOT NULL DEFAULT '[]'"),
    (STATE_TABLE, "origin_pulled_at", f"ALTER TABLE {STATE_TABLE} ADD COLUMN origin_pulled_at REAL NOT NULL DEFAULT 0"),
)


def apply_v107(conn: sqlite3.Connection) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({STATE_TABLE})")}
    for table, column, statement in V107_COLUMNS:
        if present and column not in present:
            conn.execute(statement)
    for statement in DDL_V107:
        conn.execute(statement)
    seed = int(time.time() * 1000)
    conn.execute(f"INSERT OR IGNORE INTO {META_TABLE} (k, v) VALUES (?, ?)", (RELAY_REV_KEY, seed))
    held = int(conn.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (RELAY_REV_KEY,)).fetchone()[0])
    for table in (USAGE_TABLE, COUNTER_TABLE):
        conn.execute(f"INSERT OR IGNORE INTO {REV_TABLE} (peer_install_id, conversation_id, hour, rev) "
                     f"SELECT DISTINCT peer_install_id, conversation_id, hour, ? FROM {table}", (held,))


DDL_V108: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {FLOOR_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        floor           INTEGER NOT NULL,
        PRIMARY KEY (peer_install_id, conversation_id, hour)
    ) WITHOUT ROWID""",
)

V108_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (REV_TABLE, "origin_rev", f"ALTER TABLE {REV_TABLE} ADD COLUMN origin_rev INTEGER"),
    (REV_TABLE, "epoch", f"ALTER TABLE {REV_TABLE} ADD COLUMN epoch INTEGER"),
    (REV_TABLE, "sig", f"ALTER TABLE {REV_TABLE} ADD COLUMN sig TEXT"),
    (STATE_TABLE, "names_rev", f"ALTER TABLE {STATE_TABLE} ADD COLUMN names_rev INTEGER"),
    (STATE_TABLE, "names_sig", f"ALTER TABLE {STATE_TABLE} ADD COLUMN names_sig TEXT"),
    (STATE_TABLE, "names_epoch", f"ALTER TABLE {STATE_TABLE} ADD COLUMN names_epoch INTEGER"),
)


def apply_v108(conn: sqlite3.Connection) -> None:
    for statement in DDL_V108:
        conn.execute(statement)
    present: dict = {}
    for table, column, statement in V108_COLUMNS:
        if table not in present:
            present[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present[table] and column not in present[table]:
            conn.execute(statement)


DDL_V113: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {USAGE_5M_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        bucket_5m       INTEGER NOT NULL,
        provider        TEXT,
        agent_kind      TEXT,
        model           TEXT NOT NULL,
        project         TEXT NOT NULL,
        account_id      TEXT NOT NULL DEFAULT 'unknown',
        subagent_type   TEXT NOT NULL DEFAULT 'unknown',
        input           INTEGER NOT NULL DEFAULT 0,
        cache_write     INTEGER NOT NULL DEFAULT 0,
        cache_read      INTEGER NOT NULL DEFAULT 0,
        output          INTEGER NOT NULL DEFAULT 0,
        cost_nano       INTEGER NOT NULL DEFAULT 0,
        messages        INTEGER NOT NULL DEFAULT 0,
        priced          INTEGER NOT NULL DEFAULT 0,
        agent_name      TEXT,
        PRIMARY KEY (peer_install_id, conversation_id, bucket_5m, model, project)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {USAGE_5M_TABLE}_bucket ON {USAGE_5M_TABLE}(bucket_5m)",
    f"""CREATE TABLE IF NOT EXISTS {ACTIVITY_TABLE} (
        peer_install_id         TEXT NOT NULL,
        conversation_id         TEXT NOT NULL,
        bucket_ts               INTEGER NOT NULL,
        grain                   INTEGER NOT NULL,
        provider                TEXT,
        agent_kind              TEXT,
        model                   TEXT NOT NULL DEFAULT '',
        project                 TEXT NOT NULL,
        observed_seconds        INTEGER NOT NULL DEFAULT 0,
        working_seconds         INTEGER NOT NULL DEFAULT 0,
        running_seconds         INTEGER NOT NULL DEFAULT 0,
        starts                  INTEGER NOT NULL DEFAULT 0,
        completions             INTEGER NOT NULL DEFAULT 0,
        waiting_seconds         INTEGER NOT NULL DEFAULT 0,
        subagent_seconds        INTEGER NOT NULL DEFAULT 0,
        global_observed_seconds INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, conversation_id, grain, bucket_ts, project)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {ACTIVITY_TABLE}_bucket ON {ACTIVITY_TABLE}(grain, bucket_ts)",
    f"""CREATE TABLE IF NOT EXISTS {QUOTA_TABLE} (
        peer_install_id TEXT NOT NULL,
        bucket_ts       INTEGER NOT NULL,
        grain           INTEGER NOT NULL,
        provider        TEXT NOT NULL,
        account_id      TEXT NOT NULL,
        window          TEXT NOT NULL,
        utilization     REAL,
        fetched_at      INTEGER,
        state           TEXT NOT NULL DEFAULT 'ok',
        limit_hit       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, grain, bucket_ts, provider, account_id, window)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {QUOTA_TABLE}_bucket ON {QUOTA_TABLE}(grain, bucket_ts)",
    f"""CREATE TABLE IF NOT EXISTS {CONVERSATIONS_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        project         TEXT NOT NULL DEFAULT '',
        model           TEXT NOT NULL DEFAULT '',
        provider        TEXT,
        agent_kind      TEXT,
        account_id      TEXT NOT NULL DEFAULT 'unknown',
        subagent_type   TEXT NOT NULL DEFAULT 'unknown',
        agent_name      TEXT,
        started_at      INTEGER NOT NULL DEFAULT 0,
        ended_at        INTEGER NOT NULL DEFAULT 0,
        tokens          INTEGER NOT NULL DEFAULT 0,
        cost_nano       INTEGER,
        turns           INTEGER NOT NULL DEFAULT 0,
        impact_score    REAL,
        PRIMARY KEY (peer_install_id, conversation_id)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {CONVERSATIONS_TABLE}_ended ON {CONVERSATIONS_TABLE}(ended_at)",
    f"""CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
        peer_install_id TEXT NOT NULL,
        event_id        TEXT NOT NULL,
        occurred_at     INTEGER NOT NULL,
        kind            TEXT NOT NULL,
        subject         TEXT NOT NULL DEFAULT '',
        data            TEXT NOT NULL DEFAULT '{{}}',
        PRIMARY KEY (peer_install_id, event_id)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {EVENTS_TABLE}_ts ON {EVENTS_TABLE}(occurred_at)",
    f"""CREATE TABLE IF NOT EXISTS {COVERAGE_TABLE} (
        peer_install_id   TEXT PRIMARY KEY,
        earliest_ts       INTEGER,
        latest_ts         INTEGER,
        minute_rows       INTEGER NOT NULL DEFAULT 0,
        unknown_cost_rows INTEGER NOT NULL DEFAULT 0,
        tracked_sources   INTEGER NOT NULL DEFAULT 0,
        db_bytes          INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL NOT NULL DEFAULT 0
    ) WITHOUT ROWID""",
    f"""CREATE TABLE IF NOT EXISTS {MCP_TABLE} (
        peer_install_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        server          TEXT NOT NULL,
        tool            TEXT NOT NULL,
        calls           INTEGER NOT NULL DEFAULT 0,
        errors          INTEGER NOT NULL DEFAULT 0,
        total_ms        INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, hour, server, tool)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {MCP_TABLE}_hour ON {MCP_TABLE}(hour)",
)

V113_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (USAGE_TABLE, "account_id", f"ALTER TABLE {USAGE_TABLE} ADD COLUMN account_id TEXT NOT NULL DEFAULT 'unknown'"),
    (USAGE_TABLE, "subagent_type", f"ALTER TABLE {USAGE_TABLE} ADD COLUMN subagent_type TEXT NOT NULL DEFAULT 'unknown'"),
    (STATE_TABLE, "v2_rev", f"ALTER TABLE {STATE_TABLE} ADD COLUMN v2_rev INTEGER"),
    (STATE_TABLE, "v2_epoch", f"ALTER TABLE {STATE_TABLE} ADD COLUMN v2_epoch INTEGER"),
    (STATE_TABLE, "v2_sig", f"ALTER TABLE {STATE_TABLE} ADD COLUMN v2_sig TEXT"),
    (STATE_TABLE, "v2_blob", f"ALTER TABLE {STATE_TABLE} ADD COLUMN v2_blob TEXT"),
)

V2_ORIGIN_TABLES: Tuple[str, ...] = (
    USAGE_5M_TABLE,
    ACTIVITY_TABLE,
    QUOTA_TABLE,
    CONVERSATIONS_TABLE,
    EVENTS_TABLE,
    COVERAGE_TABLE,
    MCP_TABLE,
)


def apply_v113(conn: sqlite3.Connection) -> None:
    for statement in DDL_V113:
        conn.execute(statement)
    present: dict[str, set[str]] = {}
    for table, column, statement in V113_COLUMNS:
        if table not in present:
            present[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present[table] and column not in present[table]:
            conn.execute(statement)


def delete_origin_rows(conn: sqlite3.Connection, origin: str) -> None:
    for table in (USAGE_TABLE, COUNTER_TABLE, PROJECTS_TABLE):
        conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ?", (origin,))
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in V2_ORIGIN_TABLES:
        if table in existing:
            conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ?", (origin,))
    state_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({STATE_TABLE})")}
    if "v2_rev" in state_cols:
        conn.execute(
            f"UPDATE {STATE_TABLE} SET names_rev = NULL, names_sig = NULL, names_epoch = NULL, "
            "v2_rev = NULL, v2_epoch = NULL, v2_sig = NULL, v2_blob = NULL WHERE peer_install_id = ?",
            (origin,),
        )
    else:
        conn.execute(
            f"UPDATE {STATE_TABLE} SET names_rev = NULL, names_sig = NULL, names_epoch = NULL WHERE peer_install_id = ?",
            (origin,),
        )


def supplied_through(conn: sqlite3.Connection, forwarder: str) -> list:
    return [r[0] for r in conn.execute(f"SELECT peer_install_id FROM {STATE_TABLE} WHERE via = ?", (forwarder,))]


def purge_rows(conn: sqlite3.Connection, peer_install_id: str, *, keep_state: bool = False, keep_floor: bool = False) -> None:
    changed = False
    released = supplied_through(conn, peer_install_id)
    for origin in [peer_install_id, *released]:
        delete_origin_rows(conn, origin)
        if origin != peer_install_id or not keep_state:
            for table in (REV_TABLE, STATE_TABLE):
                changed = conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ?", (origin,)).rowcount > 0 or changed
    conn.execute(f"DELETE FROM {OFFERS_TABLE} WHERE origin_install_id = ?", (peer_install_id,))
    if not keep_floor:
        conn.execute(f"DELETE FROM {FLOOR_TABLE} WHERE peer_install_id = ?", (peer_install_id,))
    for origin in released:
        conn.execute(f"UPDATE {RELAY_STATE_TABLE} SET revision = 0 WHERE forwarder_install_id != ? AND forwarder_install_id IN "
                     f"(SELECT forwarder_install_id FROM {OFFERS_TABLE} WHERE origin_install_id = ?)", (peer_install_id, origin))
    if changed:
        conn.execute(f"UPDATE {META_TABLE} SET v = v + 1 WHERE k = ?", (RELAY_REV_KEY,))
    conn.execute(f"DELETE FROM {OFFERS_TABLE} WHERE forwarder_install_id = ?", (peer_install_id,))
    conn.execute(f"DELETE FROM {RELAY_STATE_TABLE} WHERE forwarder_install_id = ?", (peer_install_id,))
