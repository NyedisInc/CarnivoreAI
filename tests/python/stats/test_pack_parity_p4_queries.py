from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.mcp_usage_routes import router as mcp_usage_router
from src.api.session_usage_routes import router as session_usage_router
from src.api.stats_event_routes import router as stats_event_router
from src.api.stats_insight_routes import router as stats_insight_router
from src.api.stats_routes import router as stats_router
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation import peer_hosts
from src.core.mcp_usage import report as mcp_report, store as mcp_usage_store
from src.core.pack.rollup_import.ddl import PROJECTS_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.session_usage import rollup as session_usage_rollup
from src.core.stats import config, events, insights, pack_scope, project_groups, queries
from src.core.stats.plugin import live as stats_live
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore
from src.models.stats import AnnotationWrite, QueryRequest, StatsFilters
from tests.stats import seed

HOUR = 3600
FIVE_MIN = 300
BASE = 1_760_000_000 // HOUR * HOUR
NODE_A = "install-aaa"
NODE_B = "install-bbb"
NODE_C = "install-ccc"


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_v113_schema(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({USAGE_TABLE})")}
    if "account_id" not in cols:
        conn.execute(f"ALTER TABLE {USAGE_TABLE} ADD COLUMN account_id TEXT NOT NULL DEFAULT 'unknown'")
    if "subagent_type" not in cols:
        conn.execute(f"ALTER TABLE {USAGE_TABLE} ADD COLUMN subagent_type TEXT NOT NULL DEFAULT 'unknown'")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollups_5m (
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
            PRIMARY KEY (peer_install_id, conversation_id, bucket_5m, model, project, account_id, subagent_type)
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_activity (
            peer_install_id         TEXT NOT NULL,
            conversation_id         TEXT NOT NULL,
            bucket_ts               INTEGER NOT NULL,
            grain                   INTEGER NOT NULL,
            provider                TEXT,
            agent_kind              TEXT,
            model                   TEXT NOT NULL,
            project                 TEXT NOT NULL,
            observed_seconds        REAL NOT NULL DEFAULT 0,
            working_seconds         REAL NOT NULL DEFAULT 0,
            running_seconds         REAL NOT NULL DEFAULT 0,
            starts                  INTEGER NOT NULL DEFAULT 0,
            completions             INTEGER NOT NULL DEFAULT 0,
            waiting_seconds         REAL NOT NULL DEFAULT 0,
            subagent_seconds        REAL NOT NULL DEFAULT 0,
            global_observed_seconds REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (peer_install_id, conversation_id, bucket_ts, grain, model, project)
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_quota (
            peer_install_id TEXT NOT NULL,
            bucket_ts       INTEGER NOT NULL,
            grain           INTEGER NOT NULL,
            provider        TEXT NOT NULL,
            account_id      TEXT NOT NULL,
            window          TEXT NOT NULL,
            utilization     REAL,
            fetched_at      REAL,
            state           TEXT NOT NULL DEFAULT 'ok',
            limit_hit       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (peer_install_id, bucket_ts, grain, provider, account_id, window)
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_conversations (
            peer_install_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            project         TEXT NOT NULL DEFAULT '',
            model           TEXT NOT NULL DEFAULT '',
            provider        TEXT NOT NULL DEFAULT '',
            agent_kind      TEXT NOT NULL DEFAULT '',
            account_id      TEXT NOT NULL DEFAULT 'unknown',
            subagent_type   TEXT NOT NULL DEFAULT 'unknown',
            agent_name      TEXT,
            started_at      INTEGER NOT NULL DEFAULT 0,
            ended_at        INTEGER NOT NULL DEFAULT 0,
            tokens          INTEGER NOT NULL DEFAULT 0,
            cost_nano       INTEGER,
            turns           INTEGER NOT NULL DEFAULT 0,
            impact_score    REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (peer_install_id, conversation_id)
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_events (
            peer_install_id TEXT NOT NULL,
            event_id        INTEGER NOT NULL,
            occurred_at     INTEGER NOT NULL,
            kind            TEXT NOT NULL,
            subject         TEXT NOT NULL,
            data            TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (peer_install_id, event_id)
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_coverage (
            peer_install_id   TEXT PRIMARY KEY,
            earliest_ts       INTEGER,
            latest_ts         INTEGER,
            minute_rows       INTEGER NOT NULL DEFAULT 0,
            unknown_cost_rows INTEGER NOT NULL DEFAULT 0,
            tracked_sources   INTEGER NOT NULL DEFAULT 0,
            db_bytes          INTEGER NOT NULL DEFAULT 0,
            updated_at        REAL NOT NULL DEFAULT 0
        ) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pack_rollup_mcp (
            peer_install_id TEXT NOT NULL,
            hour            INTEGER NOT NULL,
            server          TEXT NOT NULL DEFAULT '',
            tool            TEXT NOT NULL,
            calls           INTEGER NOT NULL DEFAULT 0,
            errors          INTEGER NOT NULL DEFAULT 0,
            total_ms        REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (peer_install_id, hour, server, tool)
        ) WITHOUT ROWID"""
    )
    conn.commit()


def _make_node(tmp_path: Path, name: str, self_id: str, *, v113: bool = True) -> Tuple[Path, StatsStore]:
    state = tmp_path / name
    state.mkdir(parents=True, exist_ok=True)
    store = StatsStore(state)
    store.initialize()
    config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled=1")
    assert ensure_db_migrated(state).status == "ok"
    with closing(connect(db_path_for(state))) as app:
        app.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (META_INSTALL_ID, self_id))
        if v113:
            ensure_v113_schema(app)
        app.commit()
    project_groups.forget()
    pack_scope._cache.clear()
    queries._COV_CACHE.clear()
    queries._DIM_CACHE.clear()
    return state, store


def _register_peer_state(state: Path, peer_id: str, label: str = "peer", rev: int = 1) -> None:
    with closing(connect(db_path_for(state))) as app:
        peer_hosts.upsert(app, install_id=peer_id, label=label, grant_id=f"g-{peer_id}", fid=f"f-{peer_id}", initiator=False)
        app.execute(
            f"INSERT OR REPLACE INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at) "
            "VALUES (?, ?, 'd1', ?, ?)",
            (peer_id, rev, float(BASE + 10 * HOUR), float(BASE + 10 * HOUR)),
        )
        app.commit()


def _query(metric: str, start: int, end: int, *, operation: str = "timeline", resolution: str = "5minute",
           scope: str = "pack", group_by: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> QueryRequest:
    body: Dict[str, Any] = {
        "metric": metric, "from": _iso(start), "to": _iso(end),
        "operation": operation, "resolution": resolution, "scope": scope,
        "filters": filters or {},
    }
    if group_by is not None:
        body["group_by"] = group_by
    return QueryRequest.model_validate(body)


def test_5m_peer_curves_match_across_nodes_and_fallback_to_spread_hours(tmp_path: Path) -> None:
    state_a, store_a = _make_node(tmp_path, "node_a", NODE_A)
    state_b, store_b = _make_node(tmp_path, "node_b", NODE_B)
    _register_peer_state(state_a, NODE_B, "node-b")
    _register_peer_state(state_b, NODE_A, "node-a")
    proj = project_key("/work/shared")

    h_old = BASE + 1 * HOUR
    h_recent = BASE + 30 * HOUR

    with store_a.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (h_recent + 60, "local", "claude", "conv-a", proj, "claude-opus", "session",
                      100, 0, 0, 0, 1000, "v1", 1, 1, 0, "ok"))
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (h_recent + 15 * 60 + 60, "local", "claude", "conv-a", proj, "claude-opus", "session",
                      400, 0, 0, 0, 4000, "v1", 1, 1, 0, "ok"))
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (h_old + 60, "local", "claude", "conv-a-old", proj, "claude-opus", "session",
                      120, 0, 0, 0, 1200, "v1", 1, 1, 0, "ok"))

    with store_b.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (h_recent + 5 * 60 + 60, "local", "claude", "conv-b", proj, "claude-opus", "session",
                      50, 0, 0, 0, 500, "v1", 1, 1, 0, "ok"))
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (h_recent + 20 * 60 + 60, "local", "claude", "conv-b", proj, "claude-opus", "session",
                      250, 0, 0, 0, 2500, "v1", 1, 1, 0, "ok"))

    with closing(connect(db_path_for(state_a))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
            "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
            (NODE_B, "conv-b", h_recent, "claude", "session", "claude-opus", proj, 300, 0, 0, 0, 3000, 2, 2, "acct-b", "main"),
        )
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
            "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
            (NODE_B, "conv-b-old", h_old, "claude", "session", "claude-opus", proj, 240, 0, 0, 0, 2400, 2, 2, "acct-b", "main"),
        )
        app.executemany(
            "INSERT INTO pack_rollups_5m (peer_install_id, conversation_id, bucket_5m, provider, agent_kind, model, project, "
            "account_id, subagent_type, input, cache_write, cache_read, output, cost_nano, messages, priced) "
            "VALUES (?,?,?,?,?,?,?, ?,?, ?,?,?,?,?,?,?)",
            [
                (NODE_B, "conv-b", h_recent + 5 * 60, "claude", "session", "claude-opus", proj, "acct-b", "main", 50, 0, 0, 0, 500, 1, 1),
                (NODE_B, "conv-b", h_recent + 20 * 60, "claude", "session", "claude-opus", proj, "acct-b", "main", 250, 0, 0, 0, 2500, 1, 1),
            ],
        )
        app.commit()

    with closing(connect(db_path_for(state_b))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
            "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
            (NODE_A, "conv-a", h_recent, "claude", "session", "claude-opus", proj, 500, 0, 0, 0, 5000, 2, 2, "acct-a", "main"),
        )
        app.executemany(
            "INSERT INTO pack_rollups_5m (peer_install_id, conversation_id, bucket_5m, provider, agent_kind, model, project, "
            "account_id, subagent_type, input, cache_write, cache_read, output, cost_nano, messages, priced) "
            "VALUES (?,?,?,?,?,?,?, ?,?, ?,?,?,?,?,?,?)",
            [
                (NODE_A, "conv-a", h_recent, "claude", "session", "claude-opus", proj, "acct-a", "main", 100, 0, 0, 0, 1000, 1, 1),
                (NODE_A, "conv-a", h_recent + 15 * 60, "claude", "session", "claude-opus", proj, "acct-a", "main", 400, 0, 0, 0, 4000, 1, 1),
            ],
        )
        app.commit()

    req_5m = _query("total_tokens", h_recent, h_recent + HOUR, resolution="5minute")
    pts_a = {p["time"]: p["value"] for p in queries.execute(store_a, req_5m)["series"][0]["points"] if p["value"] is not None}
    pts_b = {p["time"]: p["value"] for p in queries.execute(store_b, req_5m)["series"][0]["points"] if p["value"] is not None}
    assert pts_a == pts_b
    assert list(pts_a.values()) == [100, 50, 400, 250]
    assert sum(pts_a.values()) == 800

    req_1m = _query("total_tokens", h_recent, h_recent + HOUR, resolution="minute", filters={"host": NODE_B})
    pts_1m = [p["value"] for p in queries.execute(store_a, req_1m)["series"][0]["points"] if p["value"] is not None]
    assert len(pts_1m) == 10
    assert sum(pts_1m) == 300
    assert pts_1m[:5] == [10, 10, 10, 10, 10]
    assert pts_1m[5:] == [50, 50, 50, 50, 50]

    req_old = _query("total_tokens", h_old, h_old + HOUR, resolution="5minute", filters={"host": NODE_B})
    pts_old = [p["value"] for p in queries.execute(store_a, req_old)["series"][0]["points"] if p["value"] is not None]
    assert len(pts_old) == 12
    assert sum(pts_old) == 240
    assert all(v == 20 for v in pts_old)


def test_activity_and_quota_pack_arms_and_quota_dedupe(tmp_path: Path) -> None:
    state, store = _make_node(tmp_path, "node_a", NODE_A)
    _register_peer_state(state, NODE_B, "node-b")
    _register_peer_state(state, NODE_C, "node-c")
    t0 = BASE + 2 * HOUR
    proj = project_key("/work/app")

    with store.connect() as db:
        seed.execute(
            db,
            "INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,"
            "observed_seconds,working_seconds,running_seconds,starts,completions,waiting_seconds,subagent_seconds) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t0 + 60, "local", "claude", "conv-local", proj, "claude-opus", "session", 60, 45, 60, 1, 0, 10, 5),
        )
        seed.execute(db, "INSERT INTO stats_observation_coverage VALUES (?,?)", (t0 + 60, 60))
        stats_live.put_quota(db, {
            "minute_ts": t0, "provider": "claude", "account_id": "acct-shared", "window": "five_hour",
            "reset_at": t0 + 5 * HOUR, "utilization": 40.0, "fetched_at": float(t0 + 10), "state": "ok",
        })
        stats_live.put_quota(db, {
            "minute_ts": t0, "provider": "claude", "account_id": "acct-local", "window": "five_hour",
            "reset_at": t0 + 5 * HOUR, "utilization": 25.0, "fetched_at": float(t0 + 10), "state": "ok",
        })

    with closing(connect(db_path_for(state))) as app:
        app.executemany(
            "INSERT INTO pack_rollup_activity (peer_install_id, conversation_id, bucket_ts, grain, provider, agent_kind, "
            "model, project, observed_seconds, working_seconds, running_seconds, starts, completions, waiting_seconds, "
            "subagent_seconds, global_observed_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (NODE_B, "conv-b", t0 + 300, 300, "claude", "session", "claude-opus", proj, 300, 120, 200, 1, 1, 30, 15, 300),
                (NODE_B, "conv-b", t0, 3600, "claude", "session", "claude-opus", proj, 300, 120, 200, 1, 1, 30, 15, 300),
                (NODE_C, "conv-c", t0, 3600, "claude", "session", "claude-opus", proj, 600, 60, 100, 1, 0, 20, 10, 600),
            ],
        )
        app.executemany(
            "INSERT INTO pack_rollup_quota (peer_install_id, bucket_ts, grain, provider, account_id, window, "
            "utilization, fetched_at, state, limit_hit) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (NODE_B, t0, 300, "claude", "acct-shared", "five_hour", 99.0, float(t0 + 50), "ok", 0),
                (NODE_B, t0, 300, "claude", "acct-peer-only", "five_hour", 70.0, float(t0 + 100), "ok", 0),
                (NODE_C, t0, 300, "claude", "acct-peer-only", "five_hour", 80.0, float(t0 + 200), "ok", 0),
            ],
        )
        app.commit()

    act = queries.execute(store, _query("working_seconds", t0, t0 + HOUR, operation="summary", resolution="5minute"))
    assert act["scope"] == "pack"
    assert act["summary"]["value"] == pytest.approx(45 + 120 + 60)

    swim = queries.execute(store, _query("working_seconds", t0, t0 + HOUR, operation="timeline", resolution="5minute", group_by="conversation_id"))
    assert swim["scope"] == "pack"
    assert {s["filter_value"] for s in swim["series"]} == {"conv-local", "conv-b", "conv-c"}

    runway = queries.execute(
        store,
        _query("quota_utilization", t0, t0 + HOUR, operation="timeline", resolution="5minute",
               group_by="account_id", filters={"window": "five_hour"}),
    )
    assert runway["scope"] == "pack"
    by_acct = {
        s["filter_value"]: [p["value"] for p in s["points"] if p["value"] is not None]
        for s in runway["series"]
    }
    assert set(by_acct) == {"acct-local", "acct-shared", "acct-peer-only"}
    assert by_acct["acct-local"] == [25.0]
    assert by_acct["acct-shared"] == [40.0]
    assert by_acct["acct-peer-only"] == [80.0]


def test_peer_usage_exposes_account_id_and_subagent_type_and_degrades_on_v112(tmp_path: Path) -> None:
    state, store = _make_node(tmp_path, "v113_node", NODE_A, v113=True)
    _register_peer_state(state, NODE_B, "node-b")
    t0 = BASE + 4 * HOUR
    with closing(connect(db_path_for(state))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
            "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
            (NODE_B, "conv-sub", t0, "claude", "subagent", "claude-opus", "p1", 500, 0, 0, 0, 5000, 1, 1, "acct-prod", "research"),
        )
        app.commit()

    by_acct = queries.execute(
        store,
        _query("total_tokens", t0, t0 + HOUR, operation="ranking", resolution="hour", group_by="account_id"),
    )
    assert {r["filter_value"]: r["value"] for r in by_acct["ranking"]} == {"acct-prod": 500}

    by_sub = queries.execute(
        store,
        _query("total_tokens", t0, t0 + HOUR, operation="ranking", resolution="hour", group_by="subagent_type"),
    )
    assert {r["filter_value"]: r["value"] for r in by_sub["ranking"]} == {"research": 500}

    state_old, store_old = _make_node(tmp_path, "v112_node", NODE_A, v113=False)
    _register_peer_state(state_old, NODE_B, "node-b")
    with closing(connect(db_path_for(state_old))) as app:
        for tbl in (
            "pack_rollups_5m", "pack_rollup_activity", "pack_rollup_quota",
            "pack_rollup_conversations", "pack_rollup_events", "pack_rollup_coverage", "pack_rollup_mcp",
        ):
            app.execute(f"DROP TABLE IF EXISTS {tbl}")
        app.execute(f"DROP TABLE IF EXISTS {USAGE_TABLE}")
        app.execute(
            f"""CREATE TABLE {USAGE_TABLE} (
                peer_install_id TEXT NOT NULL, conversation_id TEXT NOT NULL, hour INTEGER NOT NULL,
                provider TEXT, agent_kind TEXT, model TEXT NOT NULL, project TEXT NOT NULL,
                input INTEGER NOT NULL DEFAULT 0, cache_write INTEGER NOT NULL DEFAULT 0,
                cache_read INTEGER NOT NULL DEFAULT 0, output INTEGER NOT NULL DEFAULT 0,
                cost_nano INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0,
                priced INTEGER NOT NULL DEFAULT 0, agent_name TEXT,
                PRIMARY KEY (peer_install_id, conversation_id, hour, model, project)
            ) WITHOUT ROWID"""
        )
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced) "
            "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?)",
            (NODE_B, "conv-old", t0, "claude", "session", "claude-opus", "p1", 300, 0, 0, 0, 3000, 1, 1),
        )
        app.commit()
    old_by_sub = queries.execute(
        store_old,
        _query("total_tokens", t0, t0 + HOUR, operation="ranking", resolution="hour", group_by="subagent_type"),
    )
    assert {r["filter_value"]: r["value"] for r in old_by_sub["ranking"]} == {"unknown": 300}


def test_unhomed_conversation_tie_breaker_is_deterministic_across_nodes(tmp_path: Path) -> None:
    state_a, store_a = _make_node(tmp_path, "tie_a", NODE_A)
    state_b, store_b = _make_node(tmp_path, "tie_b", NODE_B)
    _register_peer_state(state_a, NODE_B, "node-b")
    _register_peer_state(state_b, NODE_A, "node-a")
    t0 = BASE + 5 * HOUR
    proj = project_key("/work/unhomed")

    for store in (store_a, store_b):
        with store.connect() as db:
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (t0 + 60, "local", "claude", "conv-overlap", proj, "claude-opus", "session",
                          77, 0, 0, 0, 770, "v1", 1, 1, 0, "ok"))

    with closing(connect(db_path_for(state_a))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced) VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?)",
            (NODE_B, "conv-overlap", t0, "claude", "session", "claude-opus", proj, 77, 0, 0, 0, 770, 1, 1),
        )
        app.commit()
    with closing(connect(db_path_for(state_b))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced) VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?)",
            (NODE_A, "conv-overlap", t0, "claude", "session", "claude-opus", proj, 77, 0, 0, 0, 770, 1, 1),
        )
        app.commit()

    assert queries.execute(store_a, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour"))["summary"]["value"] == 77
    assert queries.execute(store_a, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_A}))["summary"]["value"] == 77
    assert queries.execute(store_a, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_B}))["summary"]["value"] is None

    assert queries.execute(store_b, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour"))["summary"]["value"] == 77
    assert queries.execute(store_b, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_A}))["summary"]["value"] == 77
    assert queries.execute(store_b, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_B}))["summary"]["value"] is None


def test_explicit_self_install_id_filters_resolve_on_both_nodes(tmp_path: Path) -> None:
    state_a, store_a = _make_node(tmp_path, "self_a", NODE_A)
    state_b, store_b = _make_node(tmp_path, "self_b", NODE_B)
    _register_peer_state(state_a, NODE_B, "node-b")
    _register_peer_state(state_b, NODE_A, "node-a")
    t0 = BASE + 6 * HOUR
    proj = project_key("/work/x")

    with store_a.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (t0 + 60, "local", "claude", "conv-a", proj, "claude-opus", "session",
                      111, 0, 0, 0, 1110, "v1", 1, 1, 0, "ok"))
    with store_b.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (t0 + 60, "local", "claude", "conv-b", proj, "claude-opus", "session",
                      222, 0, 0, 0, 2220, "v1", 1, 1, 0, "ok"))
    with closing(connect(db_path_for(state_a))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced) VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?)",
            (NODE_B, "conv-b", t0, "claude", "session", "claude-opus", proj, 222, 0, 0, 0, 2220, 1, 1),
        )
        app.commit()
    with closing(connect(db_path_for(state_b))) as app:
        app.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced) VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?)",
            (NODE_A, "conv-a", t0, "claude", "session", "claude-opus", proj, 111, 0, 0, 0, 1110, 1, 1),
        )
        app.commit()

    for store in (store_a, store_b):
        assert queries.execute(store, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_A}))["summary"]["value"] == 111
        assert queries.execute(store, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"host": NODE_B}))["summary"]["value"] == 222
        assert queries.execute(store, _query("total_tokens", t0, t0 + HOUR, operation="summary", resolution="hour", filters={"hosts": [NODE_A, NODE_B]}))["summary"]["value"] == 333


def test_pack_arms_for_insights_events_coverage_contributions_dimensions_sessions_and_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, store = _make_node(tmp_path, "full_pack", NODE_A)
    _register_peer_state(state, NODE_B, "node-b")
    t0 = BASE + 10 * HOUR
    day = 86400
    proj_local = project_key("/work/local-proj")
    proj_peer = project_key("/work/peer-proj")

    with store.connect() as db:
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (t0 - 2 * day, "local", "claude", "c-before-local", proj_local, "claude-sonnet", "session",
                      100, 0, 0, 0, 1000, "v1", 1, 1, 0, "ok"))
        seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (t0 + 2 * day, "local", "claude", "c-after-local", proj_local, "claude-opus", "session",
                      500, 0, 0, 0, 5000, "v1", 1, 1, 0, "ok"))
        stats_live.put_quota(db, {
            "minute_ts": t0, "provider": "claude", "account_id": "acct-local", "window": "five_hour",
            "reset_at": t0 + 5 * HOUR, "utilization": 20.0, "fetched_at": float(t0), "state": "ok",
        })
        seed.execute(
            db,
            "INSERT INTO activity_minutes (minute_ts,host,provider,conversation_id,project,model,agent_kind,observed_seconds,working_seconds) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (t0, "local", "claude", "c-after-local", proj_local, "claude-opus", "session", 60, 40),
        )
    events.record("session_created", "ses-local", {"x": 1}, store=store, occurred_at=t0 + 10)
    marker = config.create_annotation(
        store,
        AnnotationWrite(occurred_at=datetime.fromtimestamp(t0, timezone.utc), label="prompt tuned", kind="manual"),
    )["id"]

    with closing(connect(db_path_for(state))) as app:
        app.execute(
            f"INSERT INTO {PROJECTS_TABLE} (peer_install_id, project, name) VALUES (?,?,?)",
            (NODE_B, proj_peer, "PeerApp"),
        )
        for i in range(5):
            app.execute(
                f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
                "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
                (NODE_B, f"c-before-peer-{i}", (t0 - 2 * day) // HOUR * HOUR + i * HOUR, "codex", "agent",
                 "gpt-5-codex", proj_peer, 100 + i, 0, 0, 0, 1100 + i * 10, 1, 1, "acct-peer", "worker"),
            )
            app.execute(
                f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "input, cache_write, cache_read, output, cost_nano, messages, priced, account_id, subagent_type) "
                "VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?)",
                (NODE_B, f"c-after-peer-{i}", (t0 + 2 * day) // HOUR * HOUR + i * HOUR, "codex", "agent",
                 "gpt-5-codex", proj_peer, 600 + i, 0, 0, 0, 6100 + i * 10, 1, 1, "acct-peer", "worker"),
            )
        app.executemany(
            "INSERT INTO pack_rollup_conversations (peer_install_id, conversation_id, project, model, provider, agent_kind, "
            "account_id, subagent_type, started_at, ended_at, tokens, cost_nano, turns, impact_score) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (NODE_B, "c-after-peer-0", proj_peer, "gpt-5-codex", "codex", "agent", "acct-peer", "worker",
                 t0 + 2 * day, t0 + 2 * day + 900, 600, 6100, 4, 1.0),
                (NODE_B, "c-conv-only", proj_peer, "gpt-5-codex", "codex", "agent", "acct-peer", "worker",
                 t0 + 2 * day, t0 + 2 * day + 1200, 999, 9999, 9, 2.0),
            ],
        )
        app.execute(
            "INSERT INTO pack_rollup_quota (peer_install_id, bucket_ts, grain, provider, account_id, window, "
            "utilization, fetched_at, state, limit_hit) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NODE_B, t0, 3600, "codex", "acct-peer-quota", "seven_day", 55.0, float(t0), "ok", 0),
        )
        app.execute(
            "INSERT INTO pack_rollup_events (peer_install_id, event_id, occurred_at, kind, subject, data) "
            "VALUES (?,?,?,?,?,?)",
            (NODE_B, 7, t0 + 20, "model_first_seen", "gpt-5-codex", json.dumps({"model": "gpt-5-codex"})),
        )
        app.execute(
            "INSERT INTO pack_rollup_coverage (peer_install_id, earliest_ts, latest_ts, minute_rows, unknown_cost_rows, "
            "tracked_sources, db_bytes, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (NODE_B, t0 - 5 * day, t0 + 3 * day, 42, 3, 5, 12345, float(t0)),
        )
        app.execute(
            "INSERT INTO sessions (session_uuid, tmux_name, working_dir, origin, created_at, updated_at, claude_session_uuid) "
            "VALUES ('ses-uuid-local', 'carnivore_local', '/work/local-proj', 'created', '2026-01-01', '2026-01-01', 'c-after-local')"
        )
        app.execute(
            "INSERT INTO pack_rollup_activity (peer_install_id, conversation_id, bucket_ts, grain, provider, agent_kind, "
            "model, project, observed_seconds, working_seconds, running_seconds, starts, completions, waiting_seconds, "
            "subagent_seconds, global_observed_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NODE_B, "conv-peer-sess", t0, 3600, "claude", "session", "claude-opus", proj_peer, 300, 180, 200, 1, 1, 0, 0, 300),
        )
        app.execute(
            "INSERT INTO pack_rollup_mcp (peer_install_id, hour, server, tool, calls, errors, total_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (NODE_B, t0, "carnivore", "whoami", 12, 2, 240.0),
        )
        app.commit()

    convs_pack = insights.conversations(store, start=t0 - 3 * day, end=t0 + 3 * day, filters=StatsFilters(), scope="pack")
    conv_map = {item["conversation_id"]: item for item in convs_pack["items"]}
    assert "c-after-local" in conv_map
    assert "c-after-peer-0" in conv_map and conv_map["c-after-peer-0"]["duration_seconds"] == 960
    assert conv_map["c-after-peer-0"]["project"] == "PeerApp"
    assert "c-conv-only" in conv_map and conv_map["c-conv-only"]["cost_nano_usd"] == 9999
    convs_local = insights.conversations(store, start=t0 - 3 * day, end=t0 + 3 * day, filters=StatsFilters(), scope="local")
    assert {item["conversation_id"] for item in convs_local["items"]} == {"c-before-local", "c-after-local"}

    imp_local = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=t0 + 4 * day, scope="local")
    assert imp_local["verdict"] == "insufficient"
    imp_pack = insights.impact(store, annotation_id=marker, metric="estimated_cost_nano_usd", days=7, now=t0 + 4 * day, scope="pack")
    assert imp_pack["before"]["n"] == 6 and imp_pack["after"]["n"] == 7
    assert imp_pack["verdict"] == "higher"

    ev_pack = events.list_events(store, start=t0, end=t0 + 100, kind=None, limit=10, cursor=0, scope="pack")
    assert [e["id"] for e in ev_pack["items"]] == [f"{NODE_B}:7", ev_pack["items"][1]["id"]]
    assert ev_pack["items"][0]["host"] == NODE_B and ev_pack["items"][0]["kind"] == "model_first_seen"
    ev_local = events.list_events(store, start=t0, end=t0 + 100, kind=None, limit=10, cursor=0, scope="local")
    assert len(ev_local["items"]) == 1 and ev_local["items"][0]["subject"] == "ses-local"

    cov = queries.coverage(store)
    assert cov["minute_rows"] == 2 + 42
    assert cov["unknown_cost_rows"] == 3
    assert cov["earliest"] == _iso(t0 - 5 * day)
    assert cov["latest"] == _iso(t0 + 3 * day)
    assert len(cov["peers"]) == 1 and cov["peers"][0]["peer_install_id"] == NODE_B

    contrib_pack = queries.contributions(
        store,
        _query("total_tokens", t0 + 1 * day, t0 + 3 * day, operation="summary", resolution="hour", scope="pack"),
        limit=20, cursor=0,
    )
    contrib_ids = {item["conversation_id"] for item in contrib_pack["items"]}
    assert "c-after-local" in contrib_ids and "c-after-peer-0" in contrib_ids

    for dim, expected_vals in (
        ("provider", {"claude", "codex"}),
        ("model", {"claude-sonnet", "claude-opus", "gpt-5-codex"}),
        ("agent_kind", {"session", "agent"}),
        ("subagent_type", {"unknown", "worker"}),
        ("account_id", {"acct-local", "acct-peer-quota", "acct-peer"}),
        ("window", {"five_hour", "seven_day"}),
    ):
        res = queries.dimensions(store, dimension=dim, filters=StatsFilters(), start=None, end=None, limit=50, cursor=0, scope="pack")
        got = {item["filter_value"] for item in res["items"]}
        assert expected_vals <= got, (dim, got)
    proj_dim = queries.dimensions(store, dimension="project", filters=StatsFilters(), start=None, end=None, limit=50, cursor=0, scope="pack")
    assert "PeerApp" in {item["label"] for item in proj_dim["items"]}

    now_dt = datetime.fromtimestamp(t0 + 3600, timezone.utc)
    su_pack = session_usage_rollup.build(7, now=now_dt, db=db_path_for(state), stats_db=store.db_path, scope="pack")
    assert su_pack["state"] == "ok"
    assert su_pack["by_session"]["ses-uuid-local"]["worked_s"] == 40.0
    assert su_pack["by_session"]["conv-peer-sess"]["worked_s"] == 180.0
    su_local = session_usage_rollup.build(7, now=now_dt, db=db_path_for(state), stats_db=store.db_path, scope="local")
    assert "conv-peer-sess" not in su_local["by_session"]

    usage_db = mcp_usage_store.UsageStore(tmp_path / "mcp_usage.db")
    day_str = datetime.fromtimestamp(t0, timezone.utc).date().isoformat()
    usage_db.replace_from("0000-00-00", [(day_str, "whoami", "pane", "ok", 3)])
    rep_pack = mcp_report.build(30, ["whoami", "sessions_list"], usage_db, now_dt, scope="pack", app_db=db_path_for(state))
    rows_pack = {r["tool"]: r for r in rep_pack["tools"]}
    assert rows_pack["whoami"]["total"] == 15
    assert rows_pack["whoami"]["by_caller_kind"] == {"pane": 3, "pack": 12}
    assert rows_pack["whoami"]["by_outcome"] == {"ok": 13, "error": 2}
    rep_local = mcp_report.build(30, ["whoami", "sessions_list"], usage_db, now_dt, scope="local", app_db=db_path_for(state))
    rows_local = {r["tool"]: r for r in rep_local["tools"]}
    assert rows_local["whoami"]["total"] == 3

    app_api = FastAPI()
    app_api.state.stats_store = store
    for rtr in (stats_router, stats_insight_router, stats_event_router, session_usage_router, mcp_usage_router):
        app_api.include_router(rtr, prefix="/api/v1")
    app_api.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    client = TestClient(app_api)
    assert client.get(
        "/api/v1/stats/conversations",
        params={"from": _iso(t0 - 3 * day), "to": _iso(t0 + 3 * day)},
    ).status_code == 200
    assert client.get(
        "/api/v1/stats/event-log",
        params={"from": _iso(t0), "to": _iso(t0 + 100)},
    ).json()["items"][0]["id"] == f"{NODE_B}:7"
    assert client.get("/api/v1/stats/coverage").json()["peers"][0]["peer_install_id"] == NODE_B
    assert client.get(
        "/api/v1/stats/contributions",
        params={"metric": "total_tokens", "from": _iso(t0 + 1 * day), "to": _iso(t0 + 3 * day)},
    ).status_code == 200
    assert "PeerApp" in {
        i["label"] for i in client.get("/api/v1/stats/dimensions", params={"dimension": "project"}).json()["items"]
    }
