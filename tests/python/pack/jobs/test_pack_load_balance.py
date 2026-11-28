
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.api import pack_jobs_metrics_routes as routes
from src.core import host_metrics
from src.core.machine_stats.cpu_busy import CpuMeter
from src.core.mcp import pack_jobs_metrics_tools as mcp_tools
from src.core.pack.jobs import (
    boot,
    ddl,
    load_report,
    load_store,
    locality,
    place,
    policy as policy_mod,
    precheck,
    precheck_hook,
    precheck_learn,
    runner,
)
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobRecord, JobState
from src.core.pack.placement import needs as needs_mod, rule, workload
from src.core.pack.reserve.holds import Holds
from src.core.swarm import admission

NOW = 1_800_000_000.0
UID = "p1abc123"


def _snap(
    iid: str,
    label: str,
    *,
    cores: int = 10,
    busy_15s: float = 1.0,
    busy_1m: float = 1.0,
    mem_total: float = 16.0,
    mem_avail: float = 10.0,
    cpu_reserve_pct: int = 10,
    mem_reserve_pct: int = 10,
    pegged: bool = False,
    pageouts: float = 0.0,
    held_cpu: float = 0.0,
    held_ram: float = 0.0,
    warm_projects: List[str] | None = None,
    active_jobs: int = 0,
) -> Dict[str, Any]:
    return {
        "install_id": iid,
        "label": label,
        "load": {
            "cores": cores,
            "busy_cores_15s": busy_15s,
            "busy_cores": busy_1m,
            "load_1": busy_1m,
            "mem_total_gb": mem_total,
            "mem_available_gb": mem_avail,
            "memory_percent": round(100.0 * (mem_total - mem_avail) / mem_total, 1),
            "pageouts_per_s": pageouts,
        },
        "pressure": {
            "pegged": pegged,
            "mem": "ok",
            "held": {"cpu": held_cpu, "ram_gb": held_ram, "n": 1 if (held_cpu or held_ram) else 0},
        },
        "reserve": {"cpu_pct": cpu_reserve_pct, "mem_pct": mem_reserve_pct, "level": "idle"},
        "jobs_load": {
            "active_count": active_jobs,
            "held_cpu": held_cpu,
            "held_ram_gb": held_ram,
            "held_n": 1 if (held_cpu or held_ram) else 0,
            "warm_projects": list(warm_projects or []),
        },
        "projects": [{"uid": UID, "root": f"/work/{label}"}],
        "tools": {"pytest": "8.0", "npm": "10.0", "git": "2.44"},
        "harnesses": [{"name": "claude", "usable": True}],
        "restrictions": {"never_use": False, "restricted_now": False},
    }




def test_cpu_meter_15s_window_reacts_faster_than_1m() -> None:
    ticks = {0.0: (0, 1000), 30.0: (100, 2000), 50.0: (100, 3000), 60.0: (900, 4000)}
    now = [0.0]
    meter = CpuMeter(read=lambda: ticks[now[0]], clock=lambda: now[0])
    meter.sample()
    now[0] = 30.0
    meter.sample()
    now[0] = 50.0
    meter.sample()
    now[0] = 60.0
    res = meter.busy_cores(10)
    assert res["busy_15s"] is not None and res["busy_1"] is not None
    assert res["busy_15s"] == 8.0
    assert res["busy_1"] < res["busy_15s"]


def test_darwin_mach_memory_and_unified_admission() -> None:
    if sys.platform != "darwin":
        pytest.skip("Darwin-only Mach host_statistics64 check")
    mem = host_metrics._mach_vm_memory()
    assert mem is not None
    assert mem["total_bytes"] > 0 and 0 < mem["available_bytes"] <= mem["total_bytes"]
    assert "compressed_bytes" in mem and "wired_bytes" in mem
    pct = admission.available_memory_pct()
    assert pct is not None and 0.0 < pct <= 100.0


def test_dynamic_hold_decay_prevents_double_counting() -> None:
    now = [100.0]
    h = Holds(clock=lambda: now[0])
    assert h.try_hold("j1", "o", 3.0, 2.0, 60.0, lambda c, r: c <= 10.0 and r <= 10.0)
    assert h.total() == (3.0, 2.0, 1)
    h.set_measured("j1", cpu=2.2, ram_gb=1.5)
    assert h.total() == (0.8, 0.5, 1)
    h.set_measured("j1", cpu=4.0, ram_gb=3.0)
    assert h.total() == (0.0, 0.0, 1)
    h.drop("j1")
    assert h.total() == (0.0, 0.0, 0)




def test_p45_poisoned_shapes_and_single_outlier_cannot_graduate(tmp_path) -> None:
    store = JobStore(tmp_path)
    assert precheck_hook.is_exempt("cat foo.log | cut -c1-400 | tr -d '\\r' | head -20")
    assert precheck_learn.shape("pytest -q | cut -c1-400") == "pytest -q"
    assert precheck_learn.shape("timeout 580 pytest -q") == "pytest -q"
    assert precheck_learn.shape("timeout 580 pytest -q /work/tests/x.py") == "pytest <path> -q"
    assert precheck_learn.shape("python3 - <<'EOF'\nprint(1)\nEOF") is None
    assert precheck_learn.shape("python3 -c 'print(1)'") is None
    assert precheck_learn.shape("node -e 'console.log(1)'") is None
    precheck_learn.record(store, UID, "deploy.sh N", 180.0, now=NOW)
    assert not precheck_learn.learned_heavy(store, UID, "deploy.sh N", now=NOW + 10)
    precheck_learn.record(store, UID, "wait.sh", 120.0, now=NOW, cpu_s=2.0, peak_ram_gb=0.1)
    precheck_learn.record(store, UID, "wait.sh", 130.0, now=NOW + 5, cpu_s=3.0, peak_ram_gb=0.1)
    assert not precheck_learn.learned_heavy(store, UID, "wait.sh", now=NOW + 10)
    precheck_learn.record(store, UID, "compile.sh", 80.0, now=NOW, cpu_s=95.0, peak_ram_gb=1.8)
    assert precheck_learn.learned_heavy(store, UID, "compile.sh", now=NOW + 10)
    precheck_learn.record(store, UID, "compile.sh", 90.0, now=NOW + 10, cpu_s=180.0, peak_ram_gb=2.4)
    prof = precheck_learn.profile(store, UID, "compile.sh", now=NOW + 20)
    assert prof is not None and prof.runs == 2 and prof.p50_wall_s >= 80.0
    assert prof.p75_ram_gb is not None and prof.p75_ram_gb >= 1.8
    with store._tx() as conn:
        conn.execute("DELETE FROM schema_marks WHERE name=?", ("wipe_poisoned_shapes_2026_11_23",))
        conn.execute("INSERT INTO command_runs (project_uid, shape, seconds, at) VALUES (?,?,?,?)", (UID, "cut -c1-400", 200.0, NOW))
        conn.execute("INSERT INTO command_runs (project_uid, shape, seconds, at) VALUES (?,?,?,?)", (UID, "timeout N", 300.0, NOW))
        conn.execute("INSERT INTO command_runs (project_uid, shape, seconds, at) VALUES (?,?,?,?)", (UID, "python3 -", 150.0, NOW))
        conn.execute("INSERT INTO command_runs (project_uid, shape, seconds, at) VALUES (?,?,?,?)", (UID, "keep.sh", 90.0, NOW))
        ddl.migrate(conn)
        shapes = [r[0] for r in conn.execute("SELECT shape FROM command_runs WHERE shape IN ('cut -c1-400','timeout N','python3 -','keep.sh')")]
    assert shapes == ["keep.sh"]


def test_overhead_ewma_fleet_history_and_guard_funnel(tmp_path) -> None:
    store = JobStore(tmp_path)
    load_store.record_overhead(store, UID, "peer-a", 80.0, mirror_s=70.0, bundle_bytes=5_000_000, now=NOW)
    load_store.record_overhead(store, UID, "peer-a", 20.0, mirror_s=12.0, bundle_bytes=200_000, now=NOW + 60)
    ov = load_store.peer_overheads(store, UID, now=NOW + 120)
    assert 50.0 < ov["peer-a"] < 65.0
    s_host_a = _snap("id-a", "host-a", cores=14, busy_15s=13.0, mem_total=64.0, mem_avail=32.0, pegged=True)
    s_host_c = _snap("id-c", "host-c", cores=10, busy_15s=0.4, mem_total=16.0, mem_avail=7.0, pegged=False)
    for step in range(6):
        load_store.record_fleet_sample(
            store,
            [{"install_id": "id-a", "label": "host-a", "snapshot": s_host_a},
             {"install_id": "id-c", "label": "host-c", "snapshot": s_host_c}],
            now=NOW + step * 10,
        )
    hours = {r["install_id"]: r for r in load_store.machine_hours_since(store, int(NOW // 3600) - 1)}
    assert hours["id-a"]["pegged_minutes"] == 1.0 and hours["id-a"]["idle_while_pegged_minutes"] == 0.0
    assert hours["id-c"]["idle_while_pegged_minutes"] == 1.0
    load_store.record_guard_event(store, "blocked_remote", now=NOW)
    load_store.record_guard_event(store, "blocked_remote", now=NOW + 1)
    load_store.record_guard_event(store, "local_only", now=NOW + 2)
    assert load_store.guard_funnel(store, 7, now=NOW + 5) == {"blocked_remote": 2, "local_only": 1}




def _mi(iid: str, label: str, snap: Dict[str, Any], *, is_self: bool = False) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snap, True, is_self, is_self, True, None)


def test_p46_locality_self_pins_and_local_only_commands() -> None:
    from src.core.pack.jobs.types import CAP_JOBS

    pinned, rem = locality.split_self_local_needs([needs_mod.Need("label", "this-mac"), needs_mod.Need("tool", "pytest")])
    assert pinned is True and rem == [needs_mod.Need("tool", "pytest")]
    s_host_a = _snap("id-a", "host-a")
    assert needs_mod.meets(s_host_a, needs_mod.Need("label", "host-a")) is True
    assert needs_mod.meets(s_host_a, needs_mod.Need("label", "host-b")) is not True
    assert locality.local_only_reason("pytest /Users/demo/outside-project/check.py", "/work/app", "/work/app") is not None
    assert locality.local_only_reason("tmux -L cloude list-sessions", "/work/app", "/work/app") is not None
    assert locality.local_only_reason("scripts/refresh-local-install.sh", "/work/app", "/work/app") is not None
    assert locality.local_only_reason("scripts/custom-local.sh", "/work/app", "/work/app", local_only_globs=["scripts/custom-*.sh"]) is not None
    assert locality.local_only_reason("pytest -q tests/unit/test_ok.py", "/work/app", "/work/app") is None
    pol = policy_mod.Policy(project_uid=UID, auto_delegate=True)
    view = place.PlaceView(self_input=_mi("id-a", "host-a", s_host_a, is_self=True), peers=[], caps={"id-a": [CAP_JOBS]}, master_id="id-a")
    ans = place.place(workload.resolve({"kind": "suite"}), UID, pol, view, needs=[needs_mod.Need("label", "this-mac")], holds=Holds())
    assert ans.decision == "here"


def test_p47_p16_sizing_break_even_and_active_fleet_balancing() -> None:
    from src.core.pack.jobs.types import CAP_JOBS

    suite = workload.resolve({"kind": "suite"})
    agent_w = workload.resolve({"kind": "agent"})
    small = workload.resolve({"kind": "test_small"})
    assert (suite.est_cpu_cores, suite.est_ram_gb) == (3.0, 2.0)
    assert (agent_w.est_cpu_cores, agent_w.est_ram_gb) == (1.0, 1.5)
    assert workload.classify_command("pytest -q tests/x.py") == "test_small"
    assert workload.classify_command("pytest -q") == "suite"

    pol = policy_mod.Policy(project_uid=UID, auto_delegate=True)
    s_host_a_busy = _snap("id-a", "host-a", cores=14, busy_15s=6.5, busy_1m=6.5, mem_total=64.0, mem_avail=28.0,
                          cpu_reserve_pct=30, mem_reserve_pct=20)
    s_host_c_idle = _snap("id-c", "host-c", cores=10, busy_15s=0.4, busy_1m=0.4, mem_total=16.0, mem_avail=6.5,
                          cpu_reserve_pct=10, mem_reserve_pct=10)
    s_host_b_idle = _snap("id-b", "host-b", cores=10, busy_15s=1.0, busy_1m=1.0, mem_total=16.0, mem_avail=7.0,
                          cpu_reserve_pct=10, mem_reserve_pct=10)
    peers = [_mi("id-c", "host-c", s_host_c_idle), _mi("id-b", "host-b", s_host_b_idle)]
    caps = {"id-c": [CAP_JOBS], "id-b": [CAP_JOBS]}
    view = place.PlaceView(_mi("id-a", "host-a", s_host_a_busy, is_self=True), peers, caps, "id-a",
                           peer_overheads={"id-c": 12.0, "id-b": 12.0})
    ans = place.place(suite, UID, pol, view, est_runtime_s=60.0, holds=Holds())
    assert ans.decision == "remote" and ans.peer_install_id in ("id-c", "id-b")
    assert all("score" in c for c in ans.why)

    slow_view = place.PlaceView(_mi("id-a", "host-a", s_host_a_busy, is_self=True), peers, caps, "id-a",
                                peer_overheads={"id-c": 80.0, "id-b": 80.0})
    ans_short = place.place(small, UID, pol, slow_view, est_runtime_s=5.0, holds=Holds())
    assert ans_short.decision == "here"

    s_host_a_idle = _snap("id-a", "host-a", cores=14, busy_15s=0.5, busy_1m=0.5, mem_total=64.0, mem_avail=40.0,
                          cpu_reserve_pct=30, mem_reserve_pct=20)
    idle_view = place.PlaceView(_mi("id-a", "host-a", s_host_a_idle, is_self=True), peers, caps, "id-a",
                                peer_overheads={"id-c": 15.0, "id-b": 15.0})
    ans_idle = place.place(suite, UID, pol, idle_view, est_runtime_s=60.0, holds=Holds())
    assert ans_idle.decision == "here"

    ram_heavy = workload.Workload(kind="render", est_cpu_cores=3.0, est_ram_gb=8.0)
    ans_ram = place.place(ram_heavy, UID, pol, view, est_runtime_s=120.0, holds=Holds())
    assert ans_ram.decision == "here"


def test_q6_runner_uses_zsh_no_nomatch() -> None:
    assert 'zsh) "$RUN_SHELL" -l -o no_nomatch' in runner._RUN_SH




def test_load_report_route_owner_only_profiles_and_mcp(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(boot, "engine", lambda: SimpleNamespace(store=store))
    load_store.record_overhead(store, UID, "id-c", 14.0, mirror_s=10.0, bundle_bytes=12345, now=NOW)
    load_store.record_guard_event(store, "blocked_remote", now=NOW)
    precheck_learn.record(store, UID, "make build", 95.0, now=NOW, cpu_s=120.0, peak_ram_gb=2.1)
    rep = load_report.build(store, 7, now=NOW + 10)
    assert set(rep) == {"days", "fleet_now", "utilization_history", "efficiency", "guard_health", "learned_profiles", "summary"}
    assert rep["guard_health"]["funnel"]["blocked_remote"] == 1
    assert any(p["shape"] == "make build" for p in rep["learned_profiles"])

    load_spec = [s for s in mcp_tools.SPECS if s.name == "pack_load_get"][0]
    seen: Dict[str, Any] = {}
    load_spec.invoke(SimpleNamespace(route=lambda days: seen.setdefault("days", days), args={"days": 14}))
    assert seen == {"days": 14}

    monkeypatch.setattr(routes, "is_api_key", lambda token: token == "sk-api-key")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.put_load_profiles(
            "demo",
            routes.LoadProfilesBody(reset_all=True),
            credentials=SimpleNamespace(credentials="sk-api-key"),
        ))
    assert exc.value.status_code == 403 and exc.value.detail["code"] == "mark_owner_only"

    monkeypatch.setattr(routes.projects_service, "open_db_or_503", lambda _s: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(routes.projects_service, "resolve_target", lambda _c, name: {"uid": UID, "display_name": name})
    out = routes._put_load_profiles(
        "demo",
        routes.LoadProfilesBody(
            reset_shape="make build",
            shape_overrides={"./local.sh": "local_only"},
            local_only=["scripts/local-*.sh"],
        ),
    )
    assert out["cleared_runs"] == 1
    assert out["local_only"] == ["scripts/local-*.sh"]
    assert out["overrides"][0]["shape"] == "./local.sh" and out["overrides"][0]["mode"] == "local_only"
    assert load_store.shape_override_get(store, UID, "./local.sh") == "local_only"
