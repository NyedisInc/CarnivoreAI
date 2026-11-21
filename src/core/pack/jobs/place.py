
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.core.pack.jobs import install as install_mod
from src.core.pack.jobs.policy import Policy
from src.core.pack.jobs.types import CAP_JOBS, JobError, PlaceAnswer
from src.core.pack.machines import capabilities
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement import explain, needs as needs_mod, rule
from src.core.pack.placement.needs import Need
from src.core.pack.placement.workload import Workload
from src.core.pack.reserve.holds import HOLDS, Holds

HERE_HOLD_S = 90.0


@dataclass
class PlaceView:

    self_input: rule.MachineInput
    peers: List[rule.MachineInput] = field(default_factory=list)
    caps: Dict[str, List[str]] = field(default_factory=dict)
    master_id: Optional[str] = None
    company_uid: Optional[str] = None
    ssh_hold: Optional[Callable[[str, float, float], None]] = None


def _company_uid(conn: sqlite3.Connection, project_uid: str) -> Optional[str]:
    try:
        row = conn.execute("SELECT c.uid FROM projects p JOIN companies c ON c.id = p.company_id WHERE p.uid = ?",
                           (project_uid,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def live_view(project_root: str, project_uid: str) -> PlaceView:
    from src.core.pack.machines import runtime as machines_runtime

    wired = machines_runtime.wiring()
    if wired is None:
        raise JobError("pack_not_running", "the Pack is not running on this computer", 503)
    me = wired.runtime
    with closing(wired.open_db()) as conn:
        presence = explain.lookup_project(conn, project_root, me.install_id)
        company = _company_uid(conn, project_uid)
    machines = explain.machine_inputs(wired, presence, me.own_snapshot(), 0, True)
    caps = {p.install_id: list(p.capabilities) for p in wired.peers()}
    from src.core.pack.jobs.ssh import view as ssh_view

    return ssh_view.extend_live(PlaceView(machines[0], machines[1:], caps, me.content_alpha(), company))


def drop_reason(peer: rule.MachineInput, policy: Policy, view: PlaceView) -> Optional[str]:
    if not capabilities.has(view.caps.get(peer.install_id), CAP_JOBS):
        return "runs an older carnivore"
    if peer.install_id in policy.never_use or peer.label in policy.never_use:
        return "is on the never use list"
    return unfit_reason(peer, view, policy.project_uid)


def unfit_reason(peer: rule.MachineInput, view: PlaceView, project_uid: str) -> Optional[str]:
    if (view.master_id is not None and view.self_input.install_id != view.master_id and peer.install_id != view.master_id
            and not peer.install_id.startswith("ssh:")):
        return "is not the master and this computer is not either"
    if peer.snapshot is not None:
        broken = restrictions_mod.check(restrictions_mod.from_dict(peer.snapshot.get("restrictions")), restrictions_mod.ACTION_HOST_AGENTS,
                                        project_uid=project_uid, company_uid=view.company_uid, live_agents=0)
        if broken:
            return f"its own restriction {broken} refuses it"
    return None


def _own_snapshot(me: rule.MachineInput, holds: Holds) -> Optional[Dict[str, Any]]:
    if me.snapshot is None:
        return None
    snap = {k: v for k, v in me.snapshot.items() if k != "restrictions"}
    cpu, ram, count = holds.total()
    gauge = dict(snap["pressure"]) if isinstance(snap.get("pressure"), dict) else {}
    gauge["held"] = {"cpu": cpu, "ram_gb": ram, "n": count}
    snap["pressure"] = gauge
    return snap


def _unmet(snapshot: Optional[Dict[str, Any]], wants: Sequence[Need]) -> List[str]:
    return [r for r in (needs_mod.unmet_reason(snapshot, n) for n in wants) if r]


def _refuse(me: rule.MachineInput, own_snap: Optional[Dict[str, Any]], strict: Sequence[Need], view: PlaceView, policy: Policy,
            decision: Optional[rule.Decision]) -> PlaceAnswer:
    words = ", ".join(n.text for n in strict)
    rows = {r["install_id"]: r for r in (decision.candidates if decision is not None else [])}
    full: List[str] = []
    named: List[str] = [f"{me.label} (this computer) {'; '.join(_unmet(own_snap, strict))}"]
    for peer in view.peers:
        dropped = drop_reason(peer, policy, view)
        lacking = _unmet(peer.snapshot, strict)
        if lacking:
            named.append(f"{peer.label} {'; '.join(lacking)}")
        elif dropped:
            named.append(f"{peer.label} would meet it but {dropped}")
        else:
            why = (rows.get(peer.install_id) or {}).get("filter") or "has no room for it"
            if not peer.usable or peer.snapshot is None:
                named.append(f"{peer.label} would meet it but is not connected")
            else:
                full.append(peer.label)
                named.append(f"{peer.label} has it but is full: {why}")
    if full:
        return PlaceAnswer("refused", None, None, f"{', '.join(full)} has {words} but is full now: " + "; ".join(named), code="requirement_busy")
    return PlaceAnswer("refused", None, None, f"no computer can run this job, it needs {words}: " + "; ".join(named), code="requirement_unmet")


def _can_install(peer: rule.MachineInput, view: PlaceView) -> bool:
    snap = peer.snapshot
    can = snap.get("can") if snap is not None else None
    if not (peer.usable and isinstance(can, dict) and can.get("brew") is True):
        return False
    if restrictions_mod.check(restrictions_mod.from_dict(snap.get("restrictions")), restrictions_mod.ACTION_INSTALL_TOOLS) is not None:
        return False
    return capabilities.has(view.caps.get(peer.install_id), install_mod.CAP_INSTALL)


def install_candidates(work: Workload, project_uid: str, policy: Policy, view: PlaceView, *, needs: Sequence[Need] = (),
                       filters: Sequence[Need] = (), prefer: Sequence[Need] = ()) -> Optional[PlaceAnswer]:
    missing: Dict[str, List[Need]] = {}
    for peer in view.peers:
        if drop_reason(peer, policy, view) is not None or not _can_install(peer, view):
            continue
        lacking = [n for n in needs if needs_mod.unmet_reason(peer.snapshot, n)]
        if lacking and all(n.kind == "tool" and n.name in install_mod.ALLOW for n in lacking):
            missing[peer.install_id] = lacking
    if not missing:
        return None
    union = {n for lacking in missing.values() for n in lacking}
    eligible = [p for p in view.peers if p.install_id in missing]
    hard = [n for n in dict.fromkeys([*needs, *filters]) if n not in union]
    decision = rule.decide(eligible, work, needs=hard, prefer=prefer, project_uid=project_uid, company_uid=view.company_uid)
    if not decision.chosen:
        return None
    peer = next(p for p in eligible if p.install_id == decision.chosen)
    tools = [next(n.name for n in missing[peer.install_id] if install_mod.ALLOW[n.name] == f) for f in
             install_mod.formulas_of([n.name for n in missing[peer.install_id]])]
    return PlaceAnswer("remote", peer.install_id, peer.label, f"{peer.label} can install {', '.join(tools)} with Homebrew first: {decision.reason}",
                       decision.candidates, install=tools)


def place(work: Workload, project_uid: str, policy: Policy, view: PlaceView, *, needs: Sequence[Need] = (), prefer: Sequence[Need] = (),
          filters: Sequence[Need] = (), holds: Holds = HOLDS) -> PlaceAnswer:
    if not policy.auto_delegate:
        return PlaceAnswer("here", None, None, "project is set to this computer only")
    me = view.self_input
    own_snap = _own_snapshot(me, holds)
    own_meets = not _unmet(own_snap, needs)
    own = rule.decide([replace(me, snapshot=own_snap)], work, needs=needs) if own_meets else None
    if own is not None and own.chosen == me.install_id and own_snap is not None and (work.heavy or not rule.over_reserve(own_snap)):
        if work.heavy:
            holds.try_hold(f"here-{uuid.uuid4().hex[:12]}", me.install_id, work.est_cpu_cores, work.est_ram_gb, HERE_HOLD_S, lambda _c, _r: True)
        return PlaceAnswer("here", None, None, f"this computer has room: {rule.describe(me.label, rule.headroom(own_snap))}", own.candidates)
    reasons: List[str] = []
    kept: List[rule.MachineInput] = []
    for peer in view.peers:
        why = drop_reason(peer, policy, view)
        if why:
            reasons.append(f"{peer.label} {why}")
        else:
            kept.append(peer)
    hard = list(dict.fromkeys([*needs, *filters]))
    decision = rule.decide(kept, work, needs=hard, prefer=prefer, project_uid=project_uid, company_uid=view.company_uid) if kept else None
    if decision is not None and decision.chosen:
        peer = next(p for p in kept if p.install_id == decision.chosen)
        if view.ssh_hold is not None and peer.install_id.startswith("ssh:"):
            view.ssh_hold(peer.install_id, work.est_cpu_cores, work.est_ram_gb)
        return PlaceAnswer("remote", peer.install_id, peer.label, decision.reason, decision.candidates)
    if not own_meets:
        refused = _refuse(me, own_snap, needs, view, policy, decision)
        if refused.code == "requirement_unmet":
            return install_candidates(work, project_uid, policy, view, needs=needs, filters=filters, prefer=prefer) or refused
        return refused
    if decision is not None:
        reasons += [f"{r['label']}: {r['filter']}" for r in decision.candidates if r["filter"]]
    return PlaceAnswer("here", None, None, f"no other computer can take it now ({'; '.join(reasons) or 'none is paired'})",
                       decision.candidates if decision is not None else [])
