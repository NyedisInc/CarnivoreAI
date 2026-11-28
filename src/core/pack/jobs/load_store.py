
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.core.pack.jobs.store import JobStore


class LoadStoreError(ValueError):
    pass


OVERHEAD_ALPHA = 0.35
OVERHEAD_STALE_S = 7 * 86400.0
KEEP_DAYS = 30
TICK_MINUTES = 10.0 / 60.0
VALID_OVERRIDE_MODES = frozenset({"local_only", "always_offload"})


def record_overhead(store: JobStore, project_uid: str, peer_install_id: str, overhead_s: float, *,
                    mirror_s: float = 0.0, bundle_bytes: int = 0, now: Optional[float] = None) -> None:
    if not project_uid or not peer_install_id or overhead_s < 0:
        return
    at = time.time() if now is None else float(now)
    val = min(float(overhead_s), 3600.0)
    with store._tx() as conn:  # noqa: SLF001
        row = conn.execute("SELECT ewma_s, samples, updated_at FROM peer_overhead WHERE project_uid=? AND peer_install_id=?",
                           (project_uid, peer_install_id)).fetchone()
        if row is None or at - float(row["updated_at"]) > OVERHEAD_STALE_S:
            ewma, samples = val, 1
        else:
            ewma = round(OVERHEAD_ALPHA * val + (1.0 - OVERHEAD_ALPHA) * float(row["ewma_s"]), 2)
            samples = int(row["samples"]) + 1
        conn.execute(
            "INSERT INTO peer_overhead (project_uid, peer_install_id, ewma_s, samples, last_mirror_s, last_bundle_bytes, updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_uid, peer_install_id) DO UPDATE SET "
            "ewma_s=excluded.ewma_s, samples=excluded.samples, last_mirror_s=excluded.last_mirror_s, "
            "last_bundle_bytes=excluded.last_bundle_bytes, updated_at=excluded.updated_at",
            (project_uid, peer_install_id, ewma, samples, float(mirror_s), int(bundle_bytes), at),
        )


def peer_overheads(store: JobStore, project_uid: str, *, now: Optional[float] = None) -> Dict[str, float]:
    if not project_uid:
        return {}
    cutoff = (time.time() if now is None else float(now)) - OVERHEAD_STALE_S
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT peer_install_id, ewma_s FROM peer_overhead WHERE project_uid=? AND updated_at>=?",
                            (project_uid, cutoff)).fetchall()
    return {str(r["peer_install_id"]): float(r["ewma_s"]) for r in rows}


def overhead_rows(store: JobStore, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
    cutoff = (time.time() if now is None else float(now)) - OVERHEAD_STALE_S
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT project_uid, peer_install_id, ewma_s, samples, last_mirror_s, last_bundle_bytes, updated_at "
            "FROM peer_overhead WHERE updated_at>=? ORDER BY samples DESC, updated_at DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _snap_cpu_pct(snap: Dict[str, Any]) -> Optional[float]:
    load = snap.get("load") if isinstance(snap.get("load"), dict) else {}
    cores = load.get("cores")
    busy = load.get("busy_cores_15s") if load.get("busy_cores_15s") is not None else load.get("busy_cores")
    if busy is None:
        busy = load.get("load_1")
    if not isinstance(cores, (int, float)) or cores <= 0 or not isinstance(busy, (int, float)):
        return None
    return round(min(100.0, max(0.0, 100.0 * float(busy) / float(cores))), 1)


def _snap_ram(snap: Dict[str, Any]) -> tuple:
    load = snap.get("load") if isinstance(snap.get("load"), dict) else {}
    total = load.get("mem_total_gb")
    avail = load.get("mem_available_gb")
    pct = load.get("memory_percent")
    if pct is None and isinstance(total, (int, float)) and total > 0 and isinstance(avail, (int, float)):
        pct = round(100.0 * (float(total) - float(avail)) / float(total), 1)
    return (float(total) if isinstance(total, (int, float)) else None,
            float(avail) if isinstance(avail, (int, float)) else None,
            float(pct) if isinstance(pct, (int, float)) else None)


def record_fleet_sample(store: JobStore, machines: Sequence[Dict[str, Any]], *, now: Optional[float] = None) -> None:
    if not machines:
        return
    at = time.time() if now is None else float(now)
    hour = int(at // 3600)
    keep_since = hour - KEEP_DAYS * 24
    parsed = []
    any_pegged = False
    for m in machines:
        snap = m.get("snapshot")
        if not isinstance(snap, dict):
            continue
        pressure = snap.get("pressure") if isinstance(snap.get("pressure"), dict) else {}
        pegged = bool(pressure.get("pegged"))
        if pegged:
            any_pegged = True
        cpu_pct = _snap_cpu_pct(snap)
        total_gb, avail_gb, ram_pct = _snap_ram(snap)
        cores = (snap.get("load") or {}).get("cores") if isinstance(snap.get("load"), dict) else None
        jobs_load = snap.get("jobs_load") if isinstance(snap.get("jobs_load"), dict) else {}
        parsed.append({
            "install_id": str(m.get("install_id") or snap.get("install_id") or ""),
            "label": str(m.get("label") or snap.get("label") or ""),
            "cores": int(cores) if isinstance(cores, (int, float)) and cores > 0 else None,
            "mem_total_gb": total_gb,
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
            "avail_gb": avail_gb,
            "pegged": pegged,
            "mem_warn": pressure.get("mem") in ("warn", "critical"),
            "active_jobs": int(jobs_load.get("active_count") or 0),
        })
    if not parsed:
        return
    with store._tx() as conn:  # noqa: SLF001
        for item in parsed:
            if not item["install_id"]:
                continue
            idle_waste = 1 if (any_pegged and not item["pegged"]
                               and item["cpu_pct"] is not None and item["cpu_pct"] <= 70.0
                               and (item["avail_gb"] is None or item["avail_gb"] >= 2.0)) else 0
            cpu_val = item["cpu_pct"]
            ram_val = item["ram_pct"]
            avail_val = item["avail_gb"]
            conn.execute(
                "INSERT INTO machine_load_hours (install_id, hour, label, cores, mem_total_gb, busy_cpu_sum, busy_cpu_n, busy_cpu_max, "
                "used_ram_sum, used_ram_n, used_ram_max, avail_ram_sum, pegged_ticks, mem_warn_ticks, idle_while_pegged_ticks, jobs_hosted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(install_id, hour) DO UPDATE SET "
                "label=excluded.label, cores=COALESCE(excluded.cores, machine_load_hours.cores), "
                "mem_total_gb=COALESCE(excluded.mem_total_gb, machine_load_hours.mem_total_gb), "
                "busy_cpu_sum=machine_load_hours.busy_cpu_sum + excluded.busy_cpu_sum, "
                "busy_cpu_n=machine_load_hours.busy_cpu_n + excluded.busy_cpu_n, "
                "busy_cpu_max=CASE WHEN excluded.busy_cpu_max IS NULL THEN machine_load_hours.busy_cpu_max "
                "  WHEN machine_load_hours.busy_cpu_max IS NULL THEN excluded.busy_cpu_max "
                "  ELSE MAX(machine_load_hours.busy_cpu_max, excluded.busy_cpu_max) END, "
                "used_ram_sum=machine_load_hours.used_ram_sum + excluded.used_ram_sum, "
                "used_ram_n=machine_load_hours.used_ram_n + excluded.used_ram_n, "
                "used_ram_max=CASE WHEN excluded.used_ram_max IS NULL THEN machine_load_hours.used_ram_max "
                "  WHEN machine_load_hours.used_ram_max IS NULL THEN excluded.used_ram_max "
                "  ELSE MAX(machine_load_hours.used_ram_max, excluded.used_ram_max) END, "
                "avail_ram_sum=machine_load_hours.avail_ram_sum + excluded.avail_ram_sum, "
                "pegged_ticks=machine_load_hours.pegged_ticks + excluded.pegged_ticks, "
                "mem_warn_ticks=machine_load_hours.mem_warn_ticks + excluded.mem_warn_ticks, "
                "idle_while_pegged_ticks=machine_load_hours.idle_while_pegged_ticks + excluded.idle_while_pegged_ticks, "
                "jobs_hosted=MAX(machine_load_hours.jobs_hosted, excluded.jobs_hosted)",
                (
                    item["install_id"], hour, item["label"], item["cores"], item["mem_total_gb"],
                    cpu_val or 0.0, 1 if cpu_val is not None else 0, cpu_val,
                    ram_val or 0.0, 1 if ram_val is not None else 0, ram_val,
                    avail_val or 0.0, 1 if item["pegged"] else 0, 1 if item["mem_warn"] else 0,
                    idle_waste, item["active_jobs"],
                ),
            )
        conn.execute("DELETE FROM machine_load_hours WHERE hour<?", (keep_since,))


def machine_hours_since(store: JobStore, since_hour: int) -> List[Dict[str, Any]]:
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT * FROM machine_load_hours WHERE hour>=? ORDER BY hour, install_id", (int(since_hour),)).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        cn, rn = int(r["busy_cpu_n"]), int(r["used_ram_n"])
        out.append({
            "install_id": r["install_id"],
            "label": r["label"],
            "hour": int(r["hour"]),
            "cores": r["cores"],
            "mem_total_gb": r["mem_total_gb"],
            "avg_cpu_pct": round(float(r["busy_cpu_sum"]) / cn, 1) if cn else None,
            "max_cpu_pct": round(float(r["busy_cpu_max"]), 1) if r["busy_cpu_max"] is not None else None,
            "avg_ram_pct": round(float(r["used_ram_sum"]) / rn, 1) if rn else None,
            "max_ram_pct": round(float(r["used_ram_max"]), 1) if r["used_ram_max"] is not None else None,
            "avg_avail_ram_gb": round(float(r["avail_ram_sum"]) / rn, 1) if rn else None,
            "pegged_minutes": round(int(r["pegged_ticks"]) * TICK_MINUTES, 1),
            "mem_warn_minutes": round(int(r["mem_warn_ticks"]) * TICK_MINUTES, 1),
            "idle_while_pegged_minutes": round(int(r["idle_while_pegged_ticks"]) * TICK_MINUTES, 1),
            "peak_hosted_jobs": int(r["jobs_hosted"]),
            "samples": max(cn, rn),
        })
    return out


def record_guard_event(store: JobStore, outcome: str, *, now: Optional[float] = None) -> None:
    if not outcome:
        return
    at = time.time() if now is None else float(now)
    day = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d")
    keep_day = datetime.fromtimestamp(at - KEEP_DAYS * 86400.0, timezone.utc).strftime("%Y-%m-%d")
    with store._tx() as conn:  # noqa: SLF001
        conn.execute(
            "INSERT INTO guard_events (day, outcome, count) VALUES (?,?,1) "
            "ON CONFLICT(day, outcome) DO UPDATE SET count=guard_events.count + 1",
            (day, outcome[:48]),
        )
        conn.execute("DELETE FROM guard_events WHERE day<?", (keep_day,))


def guard_funnel(store: JobStore, days: int = 7, *, now: Optional[float] = None) -> Dict[str, int]:
    at = time.time() if now is None else float(now)
    since_day = datetime.fromtimestamp(at - max(1, days) * 86400.0, timezone.utc).strftime("%Y-%m-%d")
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT outcome, SUM(count) AS total FROM guard_events WHERE day>=? GROUP BY outcome", (since_day,)).fetchall()
    return {str(r["outcome"]): int(r["total"]) for r in rows}


def shape_override_get(store: JobStore, project_uid: str, shape: str) -> Optional[str]:
    if not project_uid or not shape:
        return None
    with store._borrow() as conn:  # noqa: SLF001
        row = conn.execute("SELECT mode FROM shape_overrides WHERE project_uid=? AND shape=?", (project_uid, shape)).fetchone()
    return str(row["mode"]) if row else None


def shape_override_set(store: JobStore, project_uid: str, shape: str, mode: Optional[str], *, now: Optional[float] = None) -> None:
    with store._tx() as conn:  # noqa: SLF001
        if mode is None:
            conn.execute("DELETE FROM shape_overrides WHERE project_uid=? AND shape=?", (project_uid, shape))
            return
        if mode not in VALID_OVERRIDE_MODES:
            raise LoadStoreError(f"mode must be one of {', '.join(sorted(VALID_OVERRIDE_MODES))}")
        conn.execute(
            "INSERT INTO shape_overrides (project_uid, shape, mode, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(project_uid, shape) DO UPDATE SET mode=excluded.mode, updated_at=excluded.updated_at",
            (project_uid, shape[:120], mode, time.time() if now is None else float(now)),
        )


def shape_overrides_list(store: JobStore, project_uid: Optional[str] = None) -> List[Dict[str, Any]]:
    with store._borrow() as conn:  # noqa: SLF001
        if project_uid:
            rows = conn.execute("SELECT project_uid, shape, mode, updated_at FROM shape_overrides WHERE project_uid=? ORDER BY shape",
                                (project_uid,)).fetchall()
        else:
            rows = conn.execute("SELECT project_uid, shape, mode, updated_at FROM shape_overrides ORDER BY project_uid, shape").fetchall()
    return [dict(r) for r in rows]


def reset_shape_runs(store: JobStore, project_uid: str, shape: Optional[str] = None) -> int:
    with store._tx() as conn:  # noqa: SLF001
        if shape:
            return int(conn.execute("DELETE FROM command_runs WHERE project_uid=? AND shape=?", (project_uid, shape)).rowcount)
        return int(conn.execute("DELETE FROM command_runs WHERE project_uid=?", (project_uid,)).rowcount)
