
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.core.pack.jobs import load_store, metrics, precheck_learn
from src.core.pack.jobs.store import JobStore
from src.core.pack.placement import rule

DAY = 86400.0


def _live_fleet() -> Dict[str, Any]:
    try:
        from src.core.pack.machines import runtime as machines_runtime

        wired = machines_runtime.wiring()
    except Exception:  # noqa: BLE001
        wired = None
    if wired is None:
        return {"machines": [], "aggregate": None}
    rt = wired.runtime
    raw: List[Dict[str, Any]] = [{"install_id": rt.install_id, "label": rt.label, "is_self": True, "state": "self", "snapshot": rt.own_snapshot()}]
    try:
        for peer in wired.peers():
            entry = rt.roster.entries.get(peer.install_id)
            state = rt.roster.peer_state(peer)
            raw.append({
                "install_id": peer.install_id,
                "label": peer.label or (entry.label if entry else ""),
                "is_self": False,
                "state": state,
                "snapshot": entry.snapshot if state == "connected" and entry is not None else None,
            })
    except Exception:  # noqa: BLE001
        pass
    machines: List[Dict[str, Any]] = []
    tot_cores = busy_cores = free_usable_cores = 0.0
    tot_ram = used_ram = free_usable_ram = 0.0
    online_count = active_jobs_total = 0
    for item in raw:
        snap = item["snapshot"]
        if not isinstance(snap, dict):
            machines.append({"install_id": item["install_id"], "label": item["label"], "is_self": item["is_self"],
                             "state": item["state"], "online": False})
            continue
        online_count += 1
        load = snap.get("load") if isinstance(snap.get("load"), dict) else {}
        pressure = snap.get("pressure") if isinstance(snap.get("pressure"), dict) else {}
        jobs_load = snap.get("jobs_load") if isinstance(snap.get("jobs_load"), dict) else {}
        head = rule.headroom(snap)
        cores = float(load.get("cores") or 0)
        busy = load.get("busy_cores_15s") if load.get("busy_cores_15s") is not None else load.get("busy_cores")
        if busy is None:
            busy = load.get("load_1")
        busy_f = min(cores, max(0.0, float(busy))) if (cores > 0 and isinstance(busy, (int, float))) else None
        mem_total = float(load["mem_total_gb"]) if isinstance(load.get("mem_total_gb"), (int, float)) else None
        mem_avail = float(load["mem_available_gb"]) if isinstance(load.get("mem_available_gb"), (int, float)) else None
        mem_used = (mem_total - mem_avail) if (mem_total is not None and mem_avail is not None) else None
        cpu_pct = round(100.0 * busy_f / cores, 1) if (busy_f is not None and cores > 0) else None
        ram_pct = round(100.0 * mem_used / mem_total, 1) if (mem_used is not None and mem_total and mem_total > 0) else None
        active_n = int(jobs_load.get("active_count") or 0)
        active_jobs_total += active_n
        if cores > 0 and busy_f is not None:
            tot_cores += cores
            busy_cores += busy_f
        if head.cpu_cores is not None:
            free_usable_cores += max(0.0, head.cpu_cores)
        if mem_total and mem_used is not None:
            tot_ram += mem_total
            used_ram += mem_used
        if head.mem_gb is not None:
            free_usable_ram += max(0.0, head.mem_gb)
        held = pressure.get("held") if isinstance(pressure.get("held"), dict) else {}
        machines.append({
            "install_id": item["install_id"],
            "label": item["label"],
            "is_self": item["is_self"],
            "state": item["state"],
            "online": True,
            "cores": int(cores) if cores > 0 else None,
            "cpu_pct": cpu_pct,
            "cpu_headroom_cores": round(head.cpu_cores, 2) if head.cpu_cores is not None else None,
            "cpu_reserve_pct": head.cpu_reserve_pct,
            "mem_total_gb": round(mem_total, 1) if mem_total is not None else None,
            "mem_available_gb": round(mem_avail, 1) if mem_avail is not None else None,
            "ram_pct": ram_pct,
            "mem_headroom_gb": round(head.mem_gb, 2) if head.mem_gb is not None else None,
            "mem_reserve_pct": head.mem_reserve_pct,
            "reserve_level": head.level,
            "pegged": bool(pressure.get("pegged")),
            "mem_pressure": pressure.get("mem"),
            "held_cpu": held.get("cpu", 0.0),
            "held_ram_gb": held.get("ram_gb", 0.0),
            "active_jobs": active_n,
        })
    agg = {
        "online_machines": online_count,
        "total_machines": len(machines),
        "total_cores": int(tot_cores),
        "busy_cores": round(busy_cores, 2),
        "fleet_cpu_pct": round(100.0 * busy_cores / tot_cores, 1) if tot_cores > 0 else None,
        "usable_free_cores": round(free_usable_cores, 2),
        "total_ram_gb": round(tot_ram, 1),
        "used_ram_gb": round(used_ram, 1),
        "fleet_ram_pct": round(100.0 * used_ram / tot_ram, 1) if tot_ram > 0 else None,
        "usable_free_ram_gb": round(free_usable_ram, 2),
        "active_jobs": active_jobs_total,
    }
    return {"machines": machines, "aggregate": agg}


def _utilization_history(store: JobStore, days: int, now: float) -> Dict[str, Any]:
    since_hour = int(now // 3600) - (days * 24 - 1)
    rows = load_store.machine_hours_since(store, since_hour)
    by_machine: Dict[str, Dict[str, Any]] = {}
    total_pegged = 0.0
    total_idle_waste = 0.0
    for r in rows:
        iid = r["install_id"]
        acc = by_machine.setdefault(iid, {
            "install_id": iid, "label": r["label"], "cores": r["cores"], "mem_total_gb": r["mem_total_gb"],
            "cpu_sum": 0.0, "cpu_n": 0, "max_cpu_pct": None, "ram_sum": 0.0, "ram_n": 0, "max_ram_pct": None,
            "pegged_minutes": 0.0, "mem_warn_minutes": 0.0, "idle_while_pegged_minutes": 0.0, "hours": 0,
        })
        if r["label"]:
            acc["label"] = r["label"]
        acc["hours"] += 1
        if r["avg_cpu_pct"] is not None:
            acc["cpu_sum"] += r["avg_cpu_pct"]
            acc["cpu_n"] += 1
        if r["max_cpu_pct"] is not None:
            acc["max_cpu_pct"] = r["max_cpu_pct"] if acc["max_cpu_pct"] is None else max(acc["max_cpu_pct"], r["max_cpu_pct"])
        if r["avg_ram_pct"] is not None:
            acc["ram_sum"] += r["avg_ram_pct"]
            acc["ram_n"] += 1
        if r["max_ram_pct"] is not None:
            acc["max_ram_pct"] = r["max_ram_pct"] if acc["max_ram_pct"] is None else max(acc["max_ram_pct"], r["max_ram_pct"])
        acc["pegged_minutes"] = round(acc["pegged_minutes"] + r["pegged_minutes"], 1)
        acc["mem_warn_minutes"] = round(acc["mem_warn_minutes"] + r["mem_warn_minutes"], 1)
        acc["idle_while_pegged_minutes"] = round(acc["idle_while_pegged_minutes"] + r["idle_while_pegged_minutes"], 1)
        total_pegged += r["pegged_minutes"]
        total_idle_waste += r["idle_while_pegged_minutes"]
    summary = [{
        "install_id": a["install_id"],
        "label": a["label"],
        "cores": a["cores"],
        "mem_total_gb": a["mem_total_gb"],
        "avg_cpu_pct": round(a["cpu_sum"] / a["cpu_n"], 1) if a["cpu_n"] else None,
        "max_cpu_pct": a["max_cpu_pct"],
        "avg_ram_pct": round(a["ram_sum"] / a["ram_n"], 1) if a["ram_n"] else None,
        "max_ram_pct": a["max_ram_pct"],
        "pegged_minutes": a["pegged_minutes"],
        "mem_warn_minutes": a["mem_warn_minutes"],
        "idle_while_pegged_minutes": a["idle_while_pegged_minutes"],
        "hours_measured": a["hours"],
    } for a in by_machine.values()]
    return {
        "window_days": days,
        "pegged_minutes_total": round(total_pegged, 1),
        "idle_while_peer_pegged_minutes": round(total_idle_waste, 1),
        "by_machine": summary,
        "hours": rows[-168:],
    }


def _efficiency(store: JobStore, days: int, now: float) -> Dict[str, Any]:
    cutoff = now - days * DAY
    with store._borrow() as conn:  # noqa: SLF001
        jobs = conn.execute(
            "SELECT id, project_uid, project_name, peer_install_id, peer_label, state, body, created_at, started_at, ended_at "
            "FROM jobs WHERE created_at>=?", (cutoff,)
        ).fetchall()
        done_ids = [r["id"] for r in jobs if r["state"] == "done" and r["peer_install_id"]]
        ev_by_job: Dict[str, Dict[str, float]] = {}
        if done_ids:
            marks = ",".join("?" for _ in done_ids)
            for er in conn.execute(f"SELECT job_id, state, at FROM job_events WHERE job_id IN ({marks}) ORDER BY id", done_ids):
                ev_by_job.setdefault(str(er["job_id"]), {}).setdefault(str(er["state"]), float(er["at"]))
    overheads: List[float] = []
    runs: List[float] = []
    by_proj: Dict[str, Dict[str, Any]] = {}
    state_counts: Dict[str, int] = {}
    for j in jobs:
        st = str(j["state"])
        state_counts[st] = state_counts.get(st, 0) + 1
        if st != "done" or not j["peer_install_id"]:
            continue
        em = ev_by_job.get(str(j["id"]), {})
        t_mir, t_st, t_run, t_col = em.get("mirroring"), em.get("starting"), em.get("running"), em.get("collecting")
        t_dn = em.get("done") or j["ended_at"]
        if t_mir is not None and t_st is not None and t_col is not None and t_dn is not None:
            ov = max(0.0, (t_st - t_mir) + ((t_run - t_st) if t_run is not None else 0.0) + (t_dn - t_col))
            rn = max(0.0, t_col - (t_run if t_run is not None else t_st))
            overheads.append(ov)
            runs.append(rn)
            pname = str(j["project_name"] or j["project_uid"])
            acc = by_proj.setdefault(pname, {"project": pname, "project_uid": j["project_uid"], "overheads": [], "runs": []})
            acc["overheads"].append(ov)
            acc["runs"].append(rn)

    def _p50(vals: List[float]) -> Optional[float]:
        if not vals:
            return None
        s = sorted(vals)
        return round(s[len(s) // 2], 1)

    total_ov = sum(overheads)
    total_run = sum(runs)
    proj_rows = [{
        "project": a["project"],
        "project_uid": a["project_uid"],
        "remote_done": len(a["runs"]),
        "p50_overhead_s": _p50(a["overheads"]),
        "p50_run_s": _p50(a["runs"]),
        "overhead_ratio": round(sum(a["overheads"]) / (sum(a["overheads"]) + sum(a["runs"])), 3) if (sum(a["overheads"]) + sum(a["runs"])) > 0 else None,
    } for a in sorted(by_proj.values(), key=lambda x: -len(x["runs"]))]
    return {
        "window_days": days,
        "state_counts": state_counts,
        "p50_overhead_s": _p50(overheads),
        "p50_run_s": _p50(runs),
        "overhead_ratio": round(total_ov / (total_ov + total_run), 3) if (total_ov + total_run) > 0 else None,
        "peer_overheads": load_store.overhead_rows(store, now=now),
        "by_project": proj_rows,
    }


def _guard_health(store: JobStore, days: int, now: float) -> Dict[str, Any]:
    cutoff = now - days * DAY
    with store._borrow() as conn:  # noqa: SLF001
        top_gw = [dict(r) for r in conn.execute(
            "SELECT shape, COUNT(*) AS count FROM guard_giveways WHERE at>=? GROUP BY shape ORDER BY count DESC LIMIT 10",
            (cutoff,),
        ).fetchall()]
    return {
        "window_days": days,
        "funnel": load_store.guard_funnel(store, days, now=now),
        "top_giveways": top_gw,
    }


def _learned_profiles(store: JobStore, now: float, *, limit: int = 30) -> List[Dict[str, Any]]:
    with store._borrow() as conn:  # noqa: SLF001
        pairs = conn.execute(
            "SELECT project_uid, shape, COUNT(*) AS n, MAX(at) AS last_at FROM command_runs "
            "GROUP BY project_uid, shape ORDER BY n DESC, last_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in pairs:
        uid, sh = str(r["project_uid"]), str(r["shape"])
        prof = precheck_learn.profile(store, uid, sh, now=now)
        if prof is None:
            continue
        out.append({
            "project_uid": uid,
            "shape": sh,
            "runs": prof.runs,
            "p50_wall_s": prof.p50_wall_s,
            "p75_cpu_cores": prof.p75_cpu_cores,
            "p75_ram_gb": prof.p75_ram_gb,
            "heavy": precheck_learn.learned_heavy(store, uid, sh, now=now),
            "override": load_store.shape_override_get(store, uid, sh),
        })
    return out


def build(store: JobStore, days: int = 7, *, now: Optional[float] = None) -> Dict[str, Any]:
    at = time.time() if now is None else float(now)
    days = max(1, min(metrics.KEEP_DAYS, int(days)))
    return {
        "days": days,
        "fleet_now": _live_fleet(),
        "utilization_history": _utilization_history(store, days, at),
        "efficiency": _efficiency(store, days, at),
        "guard_health": _guard_health(store, days, at),
        "learned_profiles": _learned_profiles(store, at),
        "summary": metrics.report(store, days, now=at),
    }
