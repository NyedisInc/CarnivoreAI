
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement import needs as needs_mod
from src.core.pack.placement.needs import Need
from src.core.pack.placement.workload import Workload

MODE_STATS, MODE_ENHANCED, MODE_FALLBACK, MODE_EXPLICIT = "stats", "enhanced", "fallback", "explicit"
DISK_MARGIN_GB = 5.0
FRESH_SECONDS = 30.0


@dataclass(frozen=True)
class MachineInput:

    install_id: str
    label: str
    snapshot: Optional[Dict[str, Any]]
    usable: bool = True
    is_self: bool = False
    is_home: bool = False
    has_project: bool = True
    live_agents: Optional[int] = None


@dataclass(frozen=True)
class Headroom:

    cpu_cores: Optional[float]
    mem_gb: Optional[float]
    cpu_line: Optional[float]
    mem_line_gb: Optional[float]
    level: str
    cpu_reserve_pct: int
    mem_reserve_pct: int
    load_per_core: Optional[float]


@dataclass
class Decision:

    chosen: Optional[str]
    mode: str
    reason: str
    workload: Dict[str, Any]
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    stayed_home: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"chosen_install_id": self.chosen, "mode": self.mode, "reason": self.reason, "workload": self.workload,
                "candidates": self.candidates}


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def headroom(snapshot: Dict[str, Any]) -> Headroom:
    load = snapshot.get("load") or {}
    reserve = snapshot.get("reserve") or {}
    cpu_pct, mem_pct = int(reserve.get("cpu_pct") or 0), int(reserve.get("mem_pct") or 0)
    cores, load1 = _num(load.get("cores")), _num(load.get("load_1"))
    total, avail = _num(load.get("mem_total_gb")), _num(load.get("mem_available_gb"))
    cpu_line = cores * (1 - cpu_pct / 100) if cores else None
    mem_line = total * (1 - mem_pct / 100) if total else None
    busy_measured = _num(load.get("busy_cores"))
    busy_now = busy_measured if busy_measured is not None else load1
    busy = min(busy_now, cores) if busy_now is not None and cores else None
    held = (snapshot.get("pressure") or {}).get("held") if isinstance(snapshot.get("pressure"), dict) else None
    held = held if isinstance(held, dict) else {}
    held_cpu, held_ram = (max(v, 0.0) if v is not None and math.isfinite(v) else 0.0 for v in (_num(held.get("cpu")), _num(held.get("ram_gb"))))
    cpu_head = cpu_line - busy - held_cpu if cpu_line is not None and busy is not None else None
    mem_head = mem_line - (total - avail) - held_ram if mem_line is not None and avail is not None else None
    return Headroom(cpu_head, mem_head, cpu_line, mem_line, str(reserve.get("level") or "none"), cpu_pct, mem_pct,
                    (busy / cores) if busy is not None and cores else None)


def _pressure_fail(snap: Dict[str, Any]) -> Optional[str]:
    gauge = snap.get("pressure")
    if not isinstance(gauge, dict):
        return None
    if gauge.get("pegged") is True:
        return f"it is pegged: {str(gauge.get('why') or 'past its own reserve line')[:120]}"
    if gauge.get("mem") in ("warn", "critical"):
        return f"it is under memory pressure ({gauge['mem']})"
    return None


def over_reserve(snap: Optional[Dict[str, Any]]) -> bool:
    if snap is None:
        return False
    head = headroom(snap)
    return (_pressure_fail(snap) is not None or (head.cpu_cores is not None and head.cpu_cores < 0)
            or (head.mem_gb is not None and head.mem_gb < 0))


def _as_need(item: Union[Need, str]) -> Need:
    if isinstance(item, Need):
        return item
    try:
        return needs_mod.parse_need(item)
    except ValueError:
        return Need("tool", str(item))


def _fail(machine: MachineInput, work: Workload, *, needs: List[Need], project_uid: Optional[str], company_uid: Optional[str],
          head: Optional[Headroom]) -> Optional[str]:
    snap = machine.snapshot
    if not machine.usable or snap is None:
        return "its link is down or its figures are older than 30 s"
    broken = restrictions_mod.check(restrictions_mod.from_dict(snap.get("restrictions")), restrictions_mod.ACTION_HOST_AGENTS,
                                    project_uid=project_uid, company_uid=company_uid, live_agents=machine.live_agents or 0)
    if broken:
        return f"its own restriction {broken} refuses it"
    if not machine.has_project:
        return "the project is not on this machine"
    unmet = [r for r in (needs_mod.unmet_reason(snap, n) for n in needs) if r]
    if unmet:
        return f"it {'; '.join(unmet)}"
    pressed = _pressure_fail(snap) if (work.heavy or not machine.is_self) else None
    if pressed:
        return pressed
    if work.heavy and (snap.get("battery") or {}).get("on_battery"):
        return "it is on battery and heavy work stays off battery"
    if head is not None:
        if head.mem_gb is not None and work.est_ram_gb > head.mem_gb:
            return f"{max(head.mem_gb, 0):.1f} GB free after its reserve, the job needs {work.est_ram_gb:g}"
        if head.cpu_cores is not None and work.est_cpu_cores > head.cpu_cores:
            return f"{max(head.cpu_cores, 0):.1f} cores free after its reserve, the job needs {work.est_cpu_cores:g}"
    free = _num((snap.get("load") or {}).get("disk_free_gb"))
    if free is not None and free < work.est_disk_gb + DISK_MARGIN_GB:
        return f"{free:.0f} GB of disk free, the job needs {work.est_disk_gb:g} plus {DISK_MARGIN_GB:g}"
    return None


def describe(label: str, head: Headroom) -> str:
    cores = "unknown cores" if head.cpu_cores is None else f"{max(head.cpu_cores, 0):.1f} cores"
    mem = "unknown memory" if head.mem_gb is None else f"{max(head.mem_gb, 0):.1f} GB"
    return f"{label}: {cores} and {mem} free after its {head.cpu_reserve_pct}% {head.level.replace('_', ' ')} reserve"


def _score(head: Headroom, work: Workload) -> float:
    cpu = (head.cpu_cores if head.cpu_cores is not None else 1e6) / max(work.est_cpu_cores, 0.5)
    mem = (head.mem_gb if head.mem_gb is not None else 1e6) / max(work.est_ram_gb, 0.5)
    return min(cpu, mem)


def decide(machines: List[MachineInput], work: Workload, *, auto_distribute: bool = False,
           needs: Optional[Sequence[Union[Need, str]]] = None, project_uid: Optional[str] = None, company_uid: Optional[str] = None,
           prefer: Optional[Sequence[Need]] = None) -> Decision:
    need_list = [_as_need(n) for n in needs or []]
    wants = list(prefer or [])
    rows: List[Dict[str, Any]] = []
    scored = []
    sentences = []
    for m in machines:
        head = headroom(m.snapshot) if m.snapshot is not None and m.usable else None
        why_not = _fail(m, work, needs=need_list, project_uid=project_uid, company_uid=company_uid, head=head)
        rows.append({"install_id": m.install_id, "label": m.label, "candidate": why_not is None, "filter": why_not,
                     "is_home": m.is_home,
                     "needs_unmet": [r for r in (needs_mod.unmet_reason(m.snapshot, n) for n in need_list) if r] if m.snapshot is not None else [],
                     "prefer_met": sum(1 for n in wants if needs_mod.meets(m.snapshot, n) is True),
                     "cpu_headroom": None if head is None or head.cpu_cores is None else round(head.cpu_cores, 2),
                     "mem_headroom_gb": None if head is None or head.mem_gb is None else round(head.mem_gb, 2),
                     "reserve": None if head is None else {"level": head.level, "cpu_pct": head.cpu_reserve_pct,
                                                           "mem_pct": head.mem_reserve_pct}})
        if head is not None:
            sentences.append(describe(m.label + (" (this computer)" if m.is_self else ""), head))
        if why_not is None and head is not None:
            scored.append((m, head, rows[-1]["prefer_met"]))
    if not scored:
        refused = "; ".join(f"{r['label']}: {r['filter']}" for r in rows if r["filter"]) or "no machine is in the Pack"
        return Decision(None, MODE_STATS, f"no machine can take this job now ({refused})", work.as_dict(), rows)
    home = next(((m, h) for m, h, _p in scored if m.is_home), None)
    if home is not None and not work.heavy and not auto_distribute:
        chosen, head = home
        why = f"light work stays on its home; {describe(chosen.label, head)}"
        return Decision(chosen.install_id, MODE_STATS, why, work.as_dict(), rows, stayed_home=True)
    else:
        chosen, head, _met = min(scored, key=lambda mhp: (-mhp[2], -round(_score(mhp[1], work), 3), not mhp[0].is_home,
                                                          mhp[1].load_per_core if mhp[1].load_per_core is not None else 0.0))
        others = [s for s in sentences if not s.startswith(chosen.label)]
        why = "; ".join([describe(chosen.label, head)] + others)
    return Decision(chosen.install_id, MODE_STATS, why, work.as_dict(), rows)
