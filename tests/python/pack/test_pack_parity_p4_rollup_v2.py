
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from src.core.db import transaction
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_schema_audit import AUDIT_OK, audit_schema
from src.core.db_steps import STEPS
from src.core.pack.machines import capabilities as caps
from src.core.pack.meshdata import envelope
from src.core.pack.rollup_import import (
    member_pull,
    puller,
    relay_export,
    store,
    v2_export,
    v2_store,
)
from src.core.pack.rollup_import.ddl import (
    ACTIVITY_TABLE,
    CONVERSATIONS_TABLE,
    COVERAGE_TABLE,
    EVENTS_TABLE,
    FLOOR_TABLE,
    MCP_TABLE,
    QUOTA_TABLE,
    STATE_TABLE,
    USAGE_5M_TABLE,
    USAGE_TABLE,
    V2_FLOOR_KEY,
    V2_ORIGIN_TABLES,
    apply_v113,
    delete_origin_rows,
)
from src.core.stats import config as stats_config
from src.core.stats.plugin import live as stats_live, rollup as stats_write
from tests.python.pack.test_rollup_import import _source_totals
from tests.python.pack.test_rollup_relay import CAPS as RELAY_CAPS, Node, _held
from tests.python.pack.test_rollup_signed_relay import Mesh, _noted

V2_CAPS = [*RELAY_CAPS, caps.CAP_MESH, caps.CAP_ROLLUP_V2]
V2_UNSIGNED_CAPS = [*RELAY_CAPS, caps.CAP_ROLLUP_V2]


def _seed_rich_stats(node: Node, now_ts: int, proj_ok: str, proj_secret: Optional[str] = None) -> None:
    hour_now = (now_ts // 3600) * 3600
    bucket_5m = (now_ts // 300) * 300
    old_hour = hour_now - 48 * 3600

    node.stats.execute(
        "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, account_id, subagent_type, first_minute, last_minute) "
        "VALUES (1001, 'conv-main', 'claude', 'session', 'acct-pro', 'primary', ?, ?)",
        (old_hour, bucket_5m),
    )
    src_main = node.stats.execute("SELECT id FROM dim_source WHERE conversation_id = 'conv-main'").fetchone()[0]
    batch = stats_write.Batch(src_main)
    batch.add_usage(bucket_5m + 60, "claude-opus", proj_ok, "v1", (100, 10, 50, 25), 5000, 1)
    batch.add_usage(old_hour + 60, "claude-opus", proj_ok, "v1", (200, 20, 60, 40), 9000, 1)
    batch.add_counter(bucket_5m + 60, "claude-opus", proj_ok, "turns", "total", 3)
    batch.flush(node.stats, {})

    if proj_secret:
        node.stats.execute(
            "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, account_id, subagent_type, first_minute, last_minute) "
            "VALUES (1002, 'conv-secret', 'claude', 'session', 'acct-secret', 'subagent', ?, ?)",
            (bucket_5m, bucket_5m),
        )
        src_sec = node.stats.execute("SELECT id FROM dim_source WHERE conversation_id = 'conv-secret'").fetchone()[0]
        sb = stats_write.Batch(src_sec)
        sb.add_usage(bucket_5m + 60, "claude-opus", proj_secret, "v1", (999, 0, 0, 1), 100, 1)
        sb.flush(node.stats, {})

    stats_live.add_activity(
        node.stats, bucket_5m, ("local", "claude", "conv-main", proj_ok, "claude-opus", "session"),
        (60.0, 45.0, 60.0, 1, 0, 5.0, 10.0),
    )
    stats_live.add_coverage(node.stats, bucket_5m, 60.0)
    stats_live.add_activity(
        node.stats, old_hour, ("local", "claude", "conv-main", proj_ok, "claude-opus", "session"),
        (300.0, 180.0, 300.0, 1, 1, 15.0, 0.0),
    )
    stats_live.add_coverage(node.stats, old_hour, 600.0)
    if proj_secret:
        stats_live.add_activity(
            node.stats, bucket_5m, ("local", "claude", "conv-secret", proj_secret, "claude-opus", "session"),
            (30.0, 30.0, 30.0, 1, 0, 0.0, 0.0),
        )

    stats_live.put_quota(node.stats, {
        "minute_ts": bucket_5m, "account_id": "acct-pro", "provider": "claude",
        "window": "5h", "reset_at": "2026-11-27T00:00:00+00:00",
        "utilization": 100.0, "fetched_at": "2026-11-26T22:00:00+00:00", "state": "ok",
    })
    stats_live.put_quota(node.stats, {
        "minute_ts": old_hour, "account_id": "acct-pro", "provider": "claude",
        "window": "7d", "reset_at": "2026-11-30T00:00:00+00:00",
        "utilization": 42.5, "fetched_at": "2026-11-24T22:00:00+00:00", "state": "ok",
    })

    node.stats.execute(
        "INSERT INTO stats_events (occurred_at, kind, subject, data) VALUES (?, 'model_first_seen', 'claude-opus', ?)",
        (bucket_5m, json.dumps({"model": "claude-opus"})),
    )
    node.stats.execute("UPDATE stats_meta SET value = '5' WHERE key = 'revision'")
    node.stats.commit()

    with closing(node.open_db()) as app_conn, transaction(app_conn):
        app_conn.execute(
            "INSERT INTO mcp_events (call_id, started_at, tool, caller_kind, outcome, duration_ms) VALUES "
            "('c1', ?, 'sessions_list', 'pane', 'ok', 120), "
            "('c2', ?, 'sessions_list', 'pane', 'error', 80), "
            "('c3', ?, 'mcp__github__list_issues', 'external', 'ok', 250)",
            (float(hour_now + 10), float(hour_now + 20), float(hour_now + 30)),
        )


def _v2_post(mesh: Mesh, caller: Node, target: Node):
    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        inc_v2 = q.get("v2") in ("1", "true", "True")
        page = relay_export.serve_stream(
            target, target.open_db, caller=caller.iid, stream=q.get("stream"),
            since_revision=int(q["since_rev"]),
            until_revision=int(q["until_rev"]) if "until_rev" in q else None,
            cursor=q.get("cursor"), max_bytes=int(q["max_bytes"]),
            signing=target.signing if caps.mesh_on() else None,
            include_v2=inc_v2,
        )
        return 200, json.loads(json.dumps(page))
    return post


def _wire_v2(mesh: Mesh, name: str, node_caps: List[str] = V2_CAPS) -> Node:
    node = mesh.nodes[name]
    node.importer = puller.RollupImporter(
        node.open_db,
        lambda iid, n=node: _v2_post(mesh, n, mesh.by_iid(iid)),
        lambda iid: node_caps,
        node.clock,
        self_id=node.iid,
        held_list=mesh.roster,
    )
    return node


def test_schema_v112_to_v113_migration_idempotent_and_delete_origin_rows(tmp_path: Path) -> None:
    assert CURRENT_SCHEMA_VERSION == 113
    db_file = tmp_path / "mig.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("BEGIN")
        for version in range(0, 112):
            STEPS[version](conn)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '112')")
        conn.commit()

        conn.execute("BEGIN")
        STEPS[112](conn)
        apply_v113(conn)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '113')")
        conn.commit()

        assert audit_schema(conn, 113).status == AUDIT_OK
        usage_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({USAGE_TABLE})")}
        state_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({STATE_TABLE})")}
        assert {"account_id", "subagent_type"}.issubset(usage_cols)
        assert {"v2_rev", "v2_epoch", "v2_sig", "v2_blob"}.issubset(state_cols)

        origin = "iid-origin"
        conn.execute("BEGIN")
        conn.execute(
            f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at, v2_rev, v2_epoch, v2_sig, v2_blob) "
            "VALUES (?, 1, 'd', 1.0, 1.0, 10, 2, 'sig', '{}')",
            (origin,),
        )
        conn.execute(f"INSERT INTO {USAGE_5M_TABLE} (peer_install_id, conversation_id, bucket_5m, model, project) VALUES (?, 'c1', 300, 'm', 'p')", (origin,))
        conn.execute(f"INSERT INTO {ACTIVITY_TABLE} (peer_install_id, conversation_id, bucket_ts, grain, project) VALUES (?, 'c1', 300, 300, 'p')", (origin,))
        conn.execute(f"INSERT INTO {QUOTA_TABLE} (peer_install_id, bucket_ts, grain, provider, account_id, window) VALUES (?, 300, 300, 'claude', 'a1', '5h')", (origin,))
        conn.execute(f"INSERT INTO {CONVERSATIONS_TABLE} (peer_install_id, conversation_id) VALUES (?, 'c1')", (origin,))
        conn.execute(f"INSERT INTO {EVENTS_TABLE} (peer_install_id, event_id, occurred_at, kind) VALUES (?, 'e1', 300, 'k')", (origin,))
        conn.execute(f"INSERT INTO {COVERAGE_TABLE} (peer_install_id, minute_rows) VALUES (?, 5)", (origin,))
        conn.execute(f"INSERT INTO {MCP_TABLE} (peer_install_id, hour, server, tool, calls) VALUES (?, 3600, 'carnivore', 't', 1)", (origin,))
        delete_origin_rows(conn, origin)
        conn.commit()

        for table in V2_ORIGIN_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE peer_install_id = ?", (origin,)).fetchone()[0] == 0
        row = conn.execute(f"SELECT v2_rev, v2_epoch, v2_sig, v2_blob FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
        assert row == (None, None, None, None)
    finally:
        conn.close()


def test_v2_export_and_store_round_trip_and_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": True})
    now_ts = int(time.time())
    a = Node(tmp_path, "a")
    b = Node(tmp_path, "b")
    proj = "a" * 24
    _seed_rich_stats(a, now_ts, proj)

    payload = v2_export.build_v2(a, a.open_db, now=float(now_ts))
    assert payload["conv_meta"]["conv-main"] == ["acct-pro", "primary"]
    assert len(payload["usage_5m"]) == 1
    assert any(r[2] == 300 and r[14] == 60 for r in payload["activity"])
    assert any(r[2] == 3600 and r[14] == 600 for r in payload["activity"])
    assert any(r[1] == 300 and r[8] == 1 for r in payload["quota"])
    assert any(r[1] == 3600 and r[8] == 0 for r in payload["quota"])
    assert len(payload["conversations"]) == 1 and payload["conversations"][0][12] == 3
    assert len(payload["events"]) == 1
    assert payload["coverage"]["tracked_sources"] >= 1
    assert {(r[1], r[2], r[3], r[4]) for r in payload["mcp"]} == {
        ("carnivore", "sessions_list", 2, 1),
        ("github", "list_issues", 1, 0),
    }

    with closing(b.open_db()) as conn, transaction(conn):
        conn.execute(
            f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at) "
            "VALUES (?, 1, 'd', 1.0, 1.0)",
            (a.iid,),
        )
        conn.execute(
            f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, model, project, input) "
            "VALUES (?, 'conv-main', 3600, 'claude-opus', ?, 100)",
            (a.iid, proj),
        )
        assert v2_store.apply_v2(conn, a.iid, payload, rev=7, now=float(now_ts)) is True

    with closing(b.open_db()) as conn:
        acct, stype = conn.execute(
            f"SELECT account_id, subagent_type FROM {USAGE_TABLE} WHERE peer_install_id = ? AND conversation_id = 'conv-main'",
            (a.iid,),
        ).fetchone()
        assert (acct, stype) == ("acct-pro", "primary")
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {ACTIVITY_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] >= 2
        assert conn.execute(f"SELECT COUNT(*) FROM {QUOTA_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] >= 2
        assert conn.execute(f"SELECT COUNT(*) FROM {CONVERSATIONS_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {EVENTS_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {COVERAGE_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {MCP_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 2


def test_v2_26h_pruning_drops_stale_5m_keeps_hourly(tmp_path: Path) -> None:
    b = Node(tmp_path, "b")
    now_ts = 1_760_100_000
    stale_5m = now_ts - 27 * 3600
    fresh_5m = now_ts - 1 * 3600
    old_hr = now_ts - 72 * 3600
    payload = {
        "conv_meta": {},
        "usage_5m": [
            ["c1", stale_5m, "claude", "session", "m", "p", "a", "s", 1, 0, 0, 1, 0, 1, 1, None],
            ["c1", fresh_5m, "claude", "session", "m", "p", "a", "s", 2, 0, 0, 2, 0, 1, 1, None],
        ],
        "activity": [
            ["c1", stale_5m, 300, "claude", "session", "m", "p", 60, 30, 60, 0, 0, 0, 0, 60],
            ["c1", fresh_5m, 300, "claude", "session", "m", "p", 60, 30, 60, 0, 0, 0, 0, 60],
            ["c1", old_hr, 3600, "claude", "session", "m", "p", 600, 300, 600, 1, 1, 0, 0, 600],
        ],
        "quota": [
            [stale_5m, 300, "claude", "a1", "5h", 10.0, stale_5m, "ok", 0],
            [fresh_5m, 300, "claude", "a1", "5h", 20.0, fresh_5m, "ok", 0],
            [old_hr, 3600, "claude", "a1", "7d", 30.0, old_hr, "ok", 0],
        ],
        "conversations": [],
        "events": [],
        "coverage": None,
        "mcp": [],
    }
    with closing(b.open_db()) as conn, transaction(conn):
        conn.execute(f"INSERT INTO {STATE_TABLE} (peer_install_id) VALUES ('iid-a')")
        assert v2_store.apply_v2(conn, "iid-a", payload, rev=1, now=float(now_ts)) is True

    with closing(b.open_db()) as conn:
        assert [r[0] for r in conn.execute(f"SELECT bucket_5m FROM {USAGE_5M_TABLE}")] == [fresh_5m]
        assert sorted(tuple(r) for r in conn.execute(f"SELECT grain, bucket_ts FROM {ACTIVITY_TABLE}")) == [(300, fresh_5m), (3600, old_hr)]
        assert sorted(tuple(r) for r in conn.execute(f"SELECT grain, bucket_ts FROM {QUOTA_TABLE}")) == [(300, fresh_5m), (3600, old_hr)]


def test_air_gap_allowlist_and_relay_denial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": True})
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    now_ts = int(time.time())
    proj_ok, proj_secret = "a" * 24, "b" * 24

    mesh = Mesh(tmp_path, "a", "b", "c")
    for name in ("a", "b", "c"):
        _wire_v2(mesh, name)
    a, b, c = mesh.nodes["a"], mesh.nodes["b"], mesh.nodes["c"]
    _seed_rich_stats(a, now_ts, proj_ok, proj_secret)

    filtered = v2_export.build_v2(a, a.open_db, allow_projects=frozenset({proj_ok}), now=float(now_ts))
    assert proj_secret not in v2_store.v2_projects(filtered)
    assert "conv-secret" not in filtered["conv_meta"]
    assert "conv-main" in filtered["conv_meta"]

    b.pair(a)
    c.pair(b)
    b.clock.now = float(now_ts)
    c.clock.now = float(now_ts)
    b.pull(a)
    with closing(b.open_db()) as conn:
        assert v2_store.relay_v2_for(conn, a.iid, frozenset({proj_secret}), signed_form=True) is None
        assert v2_store.relay_v2_for(conn, a.iid, frozenset(), signed_form=True) is not None
        unsigned = v2_store.relay_v2_for(conn, a.iid, frozenset({proj_secret}), signed_form=False)
        assert unsigned is not None
        assert proj_secret not in v2_store.v2_projects(unsigned["v2"])
        assert "conv-secret" not in unsigned["v2"]["conv_meta"]


def test_signed_v2_end_to_end_multi_hop_tamper_replay_and_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": True})
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    now_ts = int(time.time())
    proj = "c" * 24

    mesh = Mesh(tmp_path, "a", "b", "c", "d")
    for name in ("a", "b", "c", "d"):
        _wire_v2(mesh, name)
    a, b, c, d = mesh.nodes["a"], mesh.nodes["b"], mesh.nodes["c"], mesh.nodes["d"]
    b.pair(a)
    c.pair(b)
    d.pair(b)
    for node in (a, b, c, d):
        node.clock.now = float(now_ts)

    _seed_rich_stats(a, now_ts, proj)
    b.pull(a)
    with closing(b.open_db()) as conn:
        st = store.get_state(conn, a.iid)
        assert st is not None and st.v2_rev is not None
        assert tuple(conn.execute(f"SELECT v2_sig IS NOT NULL, v2_blob IS NOT NULL FROM {STATE_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()) == (1, 1)
        assert conn.execute(f"SELECT account_id FROM {USAGE_TABLE} WHERE peer_install_id = ? AND conversation_id = 'conv-main'", (a.iid,)).fetchone()[0] == "acct-pro"

    c.pull(b)
    assert _held(c, a.iid) == _source_totals(a.stats)
    with closing(c.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {QUOTA_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] >= 2
        assert conn.execute(f"SELECT COUNT(*) FROM {MCP_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 2
        assert conn.execute(f"SELECT account_id FROM {USAGE_TABLE} WHERE peer_install_id = ? AND conversation_id = 'conv-main'", (a.iid,)).fetchone()[0] == "acct-pro"

    with closing(b.open_db()) as conn, transaction(conn):
        raw_blob = conn.execute(f"SELECT v2_blob FROM {STATE_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0]
        tampered = json.loads(raw_blob)
        tampered["coverage"]["db_bytes"] = 999999999
        conn.execute(f"UPDATE {STATE_TABLE} SET v2_blob = ? WHERE peer_install_id = ?", (json.dumps(tampered), a.iid))
    d.pull(b)
    assert _noted(d, "relay_forged")
    with closing(d.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {COVERAGE_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 0

    with closing(c.open_db()) as conn:
        v2_rev, v2_epoch, v2_sig, v2_blob = conn.execute(
            f"SELECT v2_rev, v2_epoch, v2_sig, v2_blob FROM {STATE_TABLE} WHERE peer_install_id = ?", (a.iid,)
        ).fetchone()
        held_payload = json.loads(v2_blob)
        floor = conn.execute(
            f"SELECT floor FROM {FLOOR_TABLE} WHERE peer_install_id = ? AND conversation_id = ? AND hour = 0",
            (a.iid, V2_FLOOR_KEY),
        ).fetchone()[0]
        assert floor == v2_rev
        with transaction(conn):
            assert v2_store.apply_v2_signed(conn, a.iid, held_payload, v2_rev - 1, v2_sig, v2_epoch, now=float(now_ts)) is False
            assert v2_store.apply_v2_signed(conn, a.iid, held_payload, v2_rev + 1, v2_sig, v2_epoch - 1, now=float(now_ts)) is False
            empty_v2 = {
                "conv_meta": {}, "usage_5m": [], "activity": [], "quota": [],
                "conversations": [], "events": [], "coverage": None, "mcp": [],
            }
            signed_new = v2_export.sign_v2(empty_v2, v2_rev + 5, a.signing, v2_epoch + 1)
            assert signed_new is not None
            verified = v2_export.verify_v2(
                a.iid, signed_new["v2"], signed_new["v2_rev"], signed_new["v2_sig"], mesh.roster(), signed_new["v2_epoch"]
            )
            assert verified is not None
            assert v2_store.apply_v2_signed(conn, a.iid, signed_new["v2"], *verified, now=float(now_ts)) is True
        assert conn.execute(f"SELECT COUNT(*) FROM {MCP_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 0


def test_backward_compat_and_v1_to_v2_upgrade_hydration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": True})
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    now_ts = int(time.time())
    proj = "d" * 24

    mesh = Mesh(tmp_path, "a", "b")
    a, b = mesh.nodes["a"], mesh.nodes["b"]
    b.pair(a)
    b.clock.now = float(now_ts)
    _seed_rich_stats(a, now_ts, proj)

    peer_caps = [*RELAY_CAPS, caps.CAP_MESH]
    b.importer = puller.RollupImporter(
        b.open_db, lambda iid: _v2_post(mesh, b, a), lambda iid: peer_caps, b.clock,
        self_id=b.iid, held_list=mesh.roster,
    )
    v1_page = relay_export.serve_stream(a, a.open_db, caller=b.iid, stream="own", since_revision=0, signing=a.signing, include_v2=False)
    assert not any(k in v1_page for k in ("v2", "v2_rev", "v2_epoch", "v2_sig"))

    b.pull(a)
    with closing(b.open_db()) as conn:
        st = store.get_state(conn, a.iid)
        assert st is not None and st.v2_rev is None
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 0

    peer_caps.append(caps.CAP_ROLLUP_V2)
    b.clock.now += puller.MIN_INTERVAL_SECONDS + 1
    asyncio.run(b.importer.maybe_pull(a.iid, a.snapshot()))
    with closing(b.open_db()) as conn:
        st = store.get_state(conn, a.iid)
        assert st is not None and st.v2_rev is not None
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == 1


def test_v2_payload_bounding_and_cadence_constants() -> None:
    assert puller.MIN_INTERVAL_SECONDS == 15.0
    assert member_pull.MEMBER_PULL_INTERVAL_SECONDS == 30.0
    assert envelope.KIND_ROLLUP_V2 in envelope.KINDS
    assert caps.CAP_ROLLUP_V2 == "pack.rollup_v2"

    huge = {
        "conv_meta": {f"c-{i}": ["acct", "primary"] for i in range(200)},
        "usage_5m": [
            [f"c-{i}", 1_760_000_000 + i * 300, "claude", "session", "claude-opus", "p" * 24, "acct", "primary", 10, 0, 0, 5, 100, 1, 1, None]
            for i in range(400)
        ],
        "activity": [], "quota": [], "conversations": [], "events": [], "coverage": None, "mcp": [],
    }
    bounded = v2_export._bound_payload(huge, max_bytes=8192)
    assert len(json.dumps(bounded, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")) <= 8192
    assert len(bounded["usage_5m"]) < len(huge["usage_5m"])
