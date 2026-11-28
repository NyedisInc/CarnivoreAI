
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import machine_stats_routes, provider_ledger_routes
from src.api.auth import require_auth
from src.core.computers import direction
from src.core.deepsearch import peer_air_gap
from src.core.pack.globalsync import mesh_telemetry
from src.core.pack.machines import capabilities as caps, exchange, roster as roster_mod, settings_doc
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, kinds, telemetry_kind, wire, withhold
from src.core.pack.meshdata.store import RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.stats import config as stats_config, live_view, rollup
from src.core.stats.store import StatsStore
from src.core.stats_feed import peers as feed_peers
from src.core.stats_feed.model import WINDOWS, Classes
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow
from tests.stats import seed as stats_seed

CERT = base64.b64encode(b"x" * 40).decode()
NOW_S = 1_800_000_000.0
NOW_MS = int(NOW_S * 1000)


class TelemetryWorld:

    def __init__(self, tmp: Path, *names: str, one_way: tuple[str, ...] = ()) -> None:
        self.keys = {n: DeviceKey.from_seed(bytes([i + 11]) * 32) for i, n in enumerate(names)}
        self.listed = list(names)
        self.one_way = set(one_way)
        self.now_ms = NOW_MS
        self.signing = {n: self._signing(n) for n in names}
        self.stores = {
            n: RecordStore(tmp / f"{n}.db", f"iid-{n}", wall=lambda: self.now_ms, signing=self.signing[n])
            for n in names
        }

    def _signing(self, name: str) -> Signing:
        return Signing(install_id=f"iid-{name}", load_key=lambda: self.keys[name], pinned_key=lambda _iid: None)

    def lst(self) -> RosterV2:
        rows = [
            RosterComputerV2(
                install_id=f"iid-{n}",
                label=n,
                fed_public_key=b64url(self.keys[n].raw_pub),
                cert=CERT,
                mesh=True,
                one_way=n in self.one_way,
            )
            for n in self.listed
        ]
        return RosterV2(generation=1, alpha=rows[0].install_id, home=rows[0].install_id, issued_at=1, computers=rows)

    def sync(self, src: str, dst: str) -> tuple[str, int]:
        lst = self.lst()

        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), f"iid-{src}", lst, self.now_ms)
            return json.loads(json.dumps(answer))

        return asyncio.run(wire.run_sync(self.stores[src], call, lst, f"iid-{dst}", lambda: self.now_ms))


def _make_stats_store(tmp_path: Path) -> StatsStore:
    store = StatsStore(tmp_path)
    store.initialize()
    stats_config.ensure_schema(store)
    with store.connect() as db:
        db.execute("UPDATE stats_settings SET enabled = 1")
    return store


def _insert_minute(
    store: StatsStore,
    minute_ts: int,
    conv: str,
    *,
    provider: str = "claude",
    project: str = "a" * 24,
    model: str = "claude-opus-4-6",
    inp: int = 100,
    cw: int = 50,
    cr: int = 200,
    out: int = 50,
    cost: Optional[int] = 1_000_000_000,
) -> None:
    with store.connect() as db:
        stats_seed.execute(
            db,
            "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                minute_ts, "local", provider, conv, project, model, "main",
                inp, cw, cr, out, cost, "v1" if cost is not None else None,
                1, 1 if cost is not None else 0, 0 if cost is not None else 1, "ok",
            ),
        )


def test_telemetry_kind_registration_and_schema_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    assert telemetry_kind.KIND in kinds.KINDS
    assert kinds.KINDS[telemetry_kind.KIND].key_is_origin is True
    assert kinds.KINDS[telemetry_kind.KIND].cap == 64
    assert envelope.KIND_TELEMETRY in envelope.KINDS

    good = {
        "ts": NOW_S,
        "label": "alpha",
        "app_version": "1.25.0",
        "vitals_15m": {
            "tpm_5m": 120.5,
            "tpm_15m": 90.0,
            "tpm_60m": 45.0,
            "usd_hr_5m": 2.4,
            "cache_read_15m": 500,
            "cache_denom_15m": 1000,
            "active_models_15m": ["claude-opus-4-6"],
            "feed_rate": {"span_seconds": 300.0, "fresh": 1.0, "cache_write": 0.5, "cache_read": 2.0, "out": 0.5},
            "feed_buckets_1m": [[int(NOW_S // 60) * 60, 100, 50, 200, 50]],
        },
        "hot_15m": [{"conversation_id": "c1", "provider": "claude", "project": "cloudecode", "model": "claude-opus-4-6", "tokens": 400, "cost_nano": 1000}],
        "agents_5m": [{"conversation_id": "c1", "name": "worker", "tokens": 400, "tokens_per_minute": 80.0}],
        "machine": {"cpu_percent": 33.2, "cpu_count": 10, "memory_percent": 50.0, "memory_used_bytes": 8_000_000_000, "memory_total_bytes": 16_000_000_000, "disk_percent": 40.0, "disk_free_bytes": 100_000_000_000, "disk_total_bytes": 200_000_000_000, "load_1": 1.25, "load_5": 1.1, "load_15": 0.9, "uptime_seconds": 3600, "live_agents": 3},
        "ledger": [{"account_key": "k1", "id": "a1", "name": "Pro", "provider": "claude", "plan": "max", "five_hour_pct": 25.0, "seven_day_pct": 10.0, "five_hour_resets_at": "2026-11-27T00:00:00+00:00", "credential_state": "ok"}],
    }
    assert telemetry_kind.valid(good) is True

    assert telemetry_kind.valid({"label": "alpha"}) is False
    assert telemetry_kind.valid({"ts": float("nan")}) is False
    assert telemetry_kind.valid({"ts": 0}) is False

    assert telemetry_kind.valid({**good, "api_key": "sk-123"}) is False
    assert telemetry_kind.valid({**good, "ledger": [{**good["ledger"][0], "access_token": "tok"}]}) is False
    assert telemetry_kind.valid({**good, "machine": {**good["machine"], "password": "secret"}}) is False

    assert telemetry_kind.valid({**good, "hot_15m": [{**good["hot_15m"][0], "project": "/Users/demo/secret"}]}) is False
    assert telemetry_kind.valid({**good, "label": "C:\\Users\\demo\\secret"}) is False

    huge = {
        "ts": NOW_S,
        "ledger": [
            {"account_key": "k" * 120, "id": f"id{i}", "name": "n" * 90, "provider": "claude", "plan": "p" * 60, "five_hour_resets_at": "2026-11-27T00:00:00+00:00", "seven_day_resets_at": "2026-12-01T00:00:00+00:00"}
            for i in range(8)
        ],
        "agents_5m": [{"conversation_id": f"conv-{i}-" + "x" * 100, "name": "m" * 90, "tokens": 10, "tokens_per_minute": 2.0} for i in range(10)],
        "hot_15m": [{"conversation_id": f"hot-{i}-" + "x" * 100, "provider": "claude", "project": "p" * 100, "model": "m" * 80, "tokens": 100, "cost_nano": 5} for i in range(5)],
    }
    assert len(json.dumps(huge, sort_keys=True, separators=(",", ":"))) > telemetry_kind.MAX_VALUE_BYTES
    assert telemetry_kind.valid(huge) is False


def test_mesh_telemetry_2hop_relay_withhold_one_way_and_ttl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda _iid: False)

    w = TelemetryWorld(tmp_path, "a", "b", "c", "d", one_way=("d",))
    lst = w.lst()

    p_d = mesh_telemetry.collect(None, None, self_id="iid-d", label="d", machine={"cpu_percent": 10.0}, now=NOW_S)
    assert mesh_telemetry.publish_now(w.stores["d"], lst, w.signing["d"], p_d) is False
    assert telemetry_kind.origin_ok(lst, "iid-d") is False
    assert telemetry_kind.serve_ok(lst, "iid-d") is False

    p_b = mesh_telemetry.collect(None, None, self_id="iid-b", label="beta", app_version="1.25.0", machine={"cpu_percent": 42.0, "live_agents": 4}, now=NOW_S)
    assert mesh_telemetry.publish_now(w.stores["b"], lst, w.signing["b"], p_b) is True
    w.sync("b", "a")
    w.sync("a", "c")

    peers_c = mesh_telemetry.fresh_peers(w.stores["c"], lst, "iid-c", now=NOW_S + 30.0)
    assert "iid-b" in peers_c
    assert peers_c["iid-b"]["machine"]["cpu_percent"] == 42.0

    assert mesh_telemetry.fresh_peers(w.stores["c"], lst, "iid-c", now=NOW_S + 91.0) == {}

    assert w.stores["b"].put_own(withhold.KIND, "iid-b", withhold.build(["iid-c"]), w.signing["b"], force=True) is True
    w.sync("b", "a")
    assert "telemetry:iid-b" not in w.stores["a"].servable(lst, for_peer="iid-c")
    w.stores["c"].offer_batch({f"{withhold.KIND}:iid-b": w.stores["b"].servable(lst)[f"{withhold.KIND}:iid-b"]}, "iid-a", lst, NOW_MS)
    assert "iid-b" not in mesh_telemetry.fresh_peers(w.stores["c"], lst, "iid-c", now=NOW_S + 10.0)


def test_collect_enforces_air_gap_and_4kib_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_stats_store(tmp_path)
    now_min = int(NOW_S // 60) * 60
    _insert_minute(store, now_min, "conv-ok", project="ok_proj_key", inp=100, cw=0, cr=100, out=50)
    _insert_minute(store, now_min, "conv-secret", project="secret_proj_key", inp=900, cw=0, cr=0, out=100)

    monkeypatch.setattr(rollup, "allowed_projects", lambda _s: frozenset({"ok_proj_key"}))
    payload = mesh_telemetry.collect(None, store, self_id="iid-a", label="alpha/box", machine={"cpu_percent": 15.0}, now=NOW_S)
    assert telemetry_kind.valid(payload) is True
    assert "/" not in payload["label"]
    assert [h["conversation_id"] for h in payload.get("hot_15m", [])] == ["conv-ok"]
    assert [a["conversation_id"] for a in payload.get("agents_5m", [])] == ["conv-ok"]

    def _raise_unreadable(_s: Any) -> Any:
        raise peer_air_gap.AirGapUnreadable("unreadable")

    monkeypatch.setattr(rollup, "allowed_projects", _raise_unreadable)
    blocked = mesh_telemetry.collect(None, store, self_id="iid-a", label="alpha", machine={"cpu_percent": 15.0}, now=NOW_S)
    assert telemetry_kind.valid(blocked) is True
    assert "hot_15m" not in blocked and "agents_5m" not in blocked and "vitals_15m" not in blocked

    monkeypatch.setattr(rollup, "allowed_projects", lambda _s: None)
    oversized_ledger = [
        {"account_key": "k" * 120, "id": f"acct-{i}", "name": "n" * 90, "provider": "claude", "plan": "p" * 60, "five_hour_resets_at": "2026-11-27T00:00:00+00:00", "seven_day_resets_at": "2026-12-01T00:00:00+00:00"}
        for i in range(8)
    ]
    oversized_buckets = [[now_min - i * 60, 1000000 + i, 2000000 + i, 3000000 + i, 4000000 + i] for i in range(15)]
    for i in range(10):
        _insert_minute(store, now_min, f"conv-big-{i}-" + "z" * 80, project="ok_proj_key", inp=500 + i)
    trimmed = mesh_telemetry.collect(
        None,
        store,
        self_id="iid-a",
        label="alpha",
        machine={"cpu_percent": 12.0},
        ledger_accounts=oversized_ledger,
        feed_snapshot={"feed_buckets_1m": oversized_buckets},
        now=NOW_S,
    )
    assert telemetry_kind.valid(trimmed) is True
    assert len(json.dumps(trimmed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)) <= 4096


def test_live_v2_merges_peer_telemetry_and_invalidates_cache(tmp_path: Path) -> None:
    store = _make_stats_store(tmp_path)
    now_min = int(NOW_S // 60) * 60
    _insert_minute(store, now_min, "local-conv", model="m-local", inp=100, cw=0, cr=300, out=100, cost=1_000_000_000)

    local_only = live_view.live_v2(store, NOW_S)
    peer_tel = {
        "iid-b": {
            "ts": NOW_S,
            "label": "beta",
            "vitals_15m": {
                "tpm_5m": 200.0,
                "tpm_15m": 100.0,
                "tpm_60m": 50.0,
                "usd_hr_5m": 6.0,
                "cache_read_15m": 600,
                "cache_denom_15m": 1000,
                "active_models_15m": ["m-peer"],
                "model_tokens_15m": {"m-peer": 1000},
            },
            "hot_15m": [
                {"conversation_id": "peer-conv", "provider": "claude", "project": "proj-b", "model": "m-peer", "tokens": 1000, "cost_nano": 2_000_000_000},
            ],
            "agents_5m": [
                {"conversation_id": "peer-conv", "name": "peer-agent", "tokens": 1000, "tokens_per_minute": 200.0},
            ],
        },
    }

    merged = live_view.live_v2(store, NOW_S, peer_telemetry=peer_tel, scope="pack")
    assert merged["burn"]["5m"]["tokens_per_minute"] == pytest.approx(local_only["burn"]["5m"]["tokens_per_minute"] + 200.0)
    assert merged["burn"]["5m"]["estimated_usd_per_hour"] == pytest.approx(local_only["burn"]["5m"]["estimated_usd_per_hour"] + 6.0)
    assert merged["cache_hit_ratio_15m"] == pytest.approx((300 + 600) / (400 + 1000))
    assert [c["conversation_id"] for c in merged["top_conversations_15m"]] == ["peer-conv", "local-conv"]
    assert [a["conversation_id"] for a in merged["agents_5m"]] == ["peer-conv", "local-conv"]
    assert merged["active_models_15m"] == ["m-peer", "m-local"]

    assert live_view.live_v2(store, NOW_S, peer_telemetry=peer_tel, scope="local") == local_only

    c1 = live_view.live_v2_cached(store, NOW_S, peer_telemetry=peer_tel, scope="pack")
    peer_tel_2 = {"iid-b": {**peer_tel["iid-b"], "vitals_15m": {**peer_tel["iid-b"]["vitals_15m"], "tpm_5m": 400.0}}}
    c2 = live_view.live_v2_cached(store, NOW_S, peer_telemetry=peer_tel_2, scope="pack")
    assert c2["burn"]["5m"]["tokens_per_minute"] == pytest.approx(c1["burn"]["5m"]["tokens_per_minute"] + 200.0)


def test_stats_feed_overlay_folds_indirect_mesh_telemetry_without_double_counting() -> None:
    spec = WINDOWS["1h"]
    last_min = int(NOW_S // 60) * 60
    own_bars = [Classes(0, 0, 0, 0) for _ in range(spec.buckets)]
    own_bars[-1] = Classes(10, 0, 0, 5)
    own_rate = {"span_seconds": 300.0, "fresh": 1.0, "cache_write": 0.0, "cache_read": 0.0, "out": 0.5}

    direct_answer = feed_peers.PeerAnswer(
        v=1,
        install_id="iid-b",
        rev=1,
        now=NOW_S,
        state="ok",
        rate=feed_peers.RateWire(span_seconds=300.0, fresh=2.0, cache_write=0.0, cache_read=0.0, out=1.0),
        windows={"1h": [(last_min, 20, 0, 0, 10)]},
    )
    book = feed_peers.PeerBook(
        items={
            "peer-b": feed_peers.Imported(key="peer-b", label="beta", answer=direct_answer, good_mono=100.0, good_wall=NOW_S, state="ok"),
        }
    )
    peer_tel = {
        "iid-b": {
            "ts": NOW_S,
            "label": "beta",
            "vitals_15m": {
                "feed_buckets_1m": [[last_min, 20, 0, 0, 10]],
                "feed_rate": {"span_seconds": 300.0, "fresh": 2.0, "cache_write": 0.0, "cache_read": 0.0, "out": 1.0},
            },
        },
        "iid-c": {
            "ts": NOW_S,
            "label": "gamma",
            "vitals_15m": {
                "feed_buckets_1m": [[last_min, 30, 0, 0, 15]],
                "feed_rate": {"span_seconds": 300.0, "fresh": 3.0, "cache_write": 0.0, "cache_read": 0.0, "out": 1.5},
            },
        },
    }

    merged = feed_peers.overlay(book, spec, NOW_S, 102.0, own_bars, own_rate, "ok", peer_telemetry=peer_tel)
    assert merged.bars[-1] == Classes(60, 0, 0, 30)
    assert merged.rate["fresh"] == pytest.approx(6.0)
    assert merged.rate["out"] == pytest.approx(3.0)
    mesh_sources = [s for s in merged.sources if s.get("via_mesh")]
    assert len(mesh_sources) == 1 and mesh_sources[0]["label"] == "gamma" and mesh_sources[0]["state"] == "ok"


def test_roster_view_enriches_indirect_machine_from_telemetry() -> None:
    r = roster_mod.Roster(clock=lambda: NOW_S)
    r.record(
        "iid-a",
        label="alpha",
        snapshot={
            "install_id": "iid-a",
            "members": [{"install_id": "iid-c", "label": "gamma", "state": "connected"}],
            "capabilities": ["pack.machine"],
        },
        holds_master="iid-a",
    )
    peer_tel = {
        "iid-c": {
            "ts": NOW_S - 12.0,
            "label": "gamma",
            "app_version": "1.25.0",
            "machine": {
                "cpu_percent": 55.5,
                "memory_percent": 60.0,
                "memory_used_bytes": 12_000_000_000,
                "memory_total_bytes": 20_000_000_000,
                "disk_free_bytes": 50_000_000_000,
                "disk_total_bytes": 100_000_000_000,
                "load_1": 2.1,
                "uptime_seconds": 7200,
                "live_agents": 6,
            },
        },
    }
    view = r.view(
        self_snapshot={"install_id": "iid-b"},
        self_id="iid-b",
        self_label="beta",
        peers=[roster_mod.PeerInfo("iid-a", "alpha", "peer-a", "connected", ["pack.machine"])],
        settings=settings_doc.PackSettings(rev=(1, "iid-a"), master_install_id="iid-a"),
        peer_telemetry=peer_tel,
    )
    by_id = {m["install_id"]: m for m in view["machines"]}
    assert "iid-c" in by_id
    gamma = by_id["iid-c"]
    assert gamma["paired"] is False
    assert gamma["age_seconds"] == 12
    assert gamma["snapshot"] is not None
    assert gamma["snapshot"]["via_telemetry"] is True
    assert gamma["snapshot"]["cpu_percent"] == 55.5
    assert gamma["snapshot"]["live_agents"] == 6


def test_provider_ledger_folds_mesh_telemetry_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.pack.relay import ledger_sync_store, ledger_sync_view
    from src.core.provider_ledger import relay_accounts

    monkeypatch.setattr(ledger_sync_store, "statuses_by_profile", lambda: {})
    monkeypatch.setattr(relay_accounts, "all_relay_rows", lambda **_k: [])
    monkeypatch.setattr(ledger_sync_view, "decorate_local", lambda rows: list(rows))

    local_acct = AccountUsage(
        id="acct-local",
        name="Local Max",
        provider="claude",
        identity="same@example.com",
        credential_state="ok",
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=20.0, window_seconds=18000)],
    )
    snap = LedgerSnapshot(
        accounts=[local_acct],
        total=LedgerTotal(accounts=1, windows=[]),
        loop=LoopStatus(alive=True),
    )
    from src.core.federation.peer_ledger import identity_key

    dup_key = identity_key("claude", "same@example.com")
    peer_tel = {
        "iid-b": {
            "ts": NOW_S,
            "label": "beta",
            "ledger": [
                {"account_key": dup_key, "id": "dup-id", "name": "Dup Max", "provider": "claude", "five_hour_pct": 99.0, "credential_state": "ok"},
                {"account_key": "remote-unique-key", "id": "acct-remote", "name": "Remote Max", "provider": "claude", "plan": "max", "five_hour_pct": 60.0, "seven_day_pct": 30.0, "five_hour_resets_at": "2026-11-27T01:00:00+00:00", "credential_state": "ok"},
            ],
        },
    }

    assembled = provider_ledger_routes._assemble_ledger_snapshot(snap, peer_telemetry=peer_tel)
    assert len(assembled.accounts) == 2
    assert assembled.total.accounts == 2
    five_h = next(w for w in assembled.total.windows if w.kind == "five_hour")
    assert five_h.accounts == 2
    assert five_h.used_pct == pytest.approx(40.0)


def test_machine_stats_endpoint_pack_ordering_and_aggregate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    peer_tel = {
        "iid-z": {
            "ts": NOW_S,
            "label": "Zulu",
            "machine": {
                "cpu_percent": 60.0, "cpu_count": 12, "memory_percent": 75.0,
                "memory_used_bytes": 15_000_000_000, "memory_total_bytes": 20_000_000_000,
                "disk_percent": 50.0, "disk_free_bytes": 100_000_000_000, "disk_total_bytes": 200_000_000_000,
                "load_1": 3.0, "load_5": 2.0, "load_15": 1.0, "uptime_seconds": 50000, "live_agents": 4,
            },
        },
        "iid-a": {
            "ts": NOW_S,
            "label": "alpha",
            "machine": {
                "cpu_percent": 20.0, "cpu_count": 8, "memory_percent": 50.0,
                "memory_used_bytes": 10_000_000_000, "memory_total_bytes": 20_000_000_000,
                "disk_percent": 25.0, "disk_free_bytes": 150_000_000_000, "disk_total_bytes": 200_000_000_000,
                "load_1": 1.0, "load_5": 1.0, "load_15": 1.0, "uptime_seconds": 20000, "live_agents": 2,
            },
        },
    }
    monkeypatch.setattr(mesh_telemetry, "active_peers", lambda **_k: peer_tel)

    class _FakeRuntime:
        install_id = "iid-m"
        label = "middle"

    monkeypatch.setattr(exchange, "RUNTIME", _FakeRuntime())

    app = FastAPI()
    app.include_router(machine_stats_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}

    class _FakeSampler:
        def read(self, _max_age: float = 2.0) -> Dict[str, Any]:
            return {
                "cpu_percent": 40.0, "cpu_count": 4, "memory_percent": 50.0,
                "memory_used_bytes": 5_000_000_000, "memory_total_bytes": 10_000_000_000,
                "disk_percent": 50.0, "disk_free_bytes": 50_000_000_000, "disk_total_bytes": 100_000_000_000,
                "load_1": 2.0, "load_5": 1.5, "load_15": 1.0, "uptime_seconds": 10000,
            }

    from src.core.machine_stats import MachineStatsWatch

    app.state.machine_stats_watch = MachineStatsWatch(_FakeSampler())
    with TestClient(app) as http:
        body = http.get("/api/v1/machine-stats").json()

    assert body["cpu_percent"] == 40.0
    assert [m["install_id"] for m in body["machines"]] == ["iid-a", "iid-m", "iid-z"]
    agg = body["pack_aggregate"]
    assert agg["machine_count"] == 3
    assert agg["cpu_percent"] == pytest.approx(40.0)
    assert agg["cpu_count"] == 24
    assert agg["memory_used_bytes"] == 30_000_000_000
    assert agg["memory_total_bytes"] == 50_000_000_000
    assert agg["memory_percent"] == pytest.approx(60.0)
    assert agg["disk_free_bytes"] == 300_000_000_000
    assert agg["disk_total_bytes"] == 500_000_000_000
    assert agg["disk_percent"] == pytest.approx(40.0)
    assert agg["load_1"] == pytest.approx(6.0)
    assert agg["uptime_seconds"] == 50000
    assert agg["live_agents"] == 6
