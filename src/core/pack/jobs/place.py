
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from src.core.pack.jobs import install as install_mod, locality
from src.core.pack.jobs.policy import Policy
from src.core.pack.jobs.types import CAP_JOBS, JobError, PlaceAnswer
from src.core.pack.machines import capabilities
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement import explain, needs as needs_mod, rule, workload as workload_mod
from src.core.pack.placement.needs import Need
from src.core.pack.placement.workload import Workload
from src.core.pack.reserve.holds import HOLDS, Holds

HERE_HOLD_S = 90.0
MIN_OFFLOAD_RUNTIME_S = 8.0
DEFAULT_PEER_OVERHEAD_S = 20.0
BREAKEVEN_UNDER_RESERVE_MIN_S = 15.0
BREAKEVEN_UNDER_RESERVE_MULT = 0.75
BREAKEVEN_PEGGED_MIN_S = 10.0
BREAKEVEN_PEGGED_MULT = 0.35


@dataclass
class PlaceView:

    self_input: rule.MachineInput
    peers: List[rule.MachineInput] = field(default_factory=list)
    caps: Dict[str, List[str]] = field(default_factory=dict)
    master_id: Optional[str] = None
    company_uid: Optional[str] = None
    ssh_hold: Optional[Callable[[str, float, float], None]] = None
    mesh_members: FrozenSet[str] = frozenset()
    member_notes: Dict[str, str] = field(default_factory=dict)
    copy_skips: Dict[str, str] = field(default_factory=dict)
    peer_overheads: Dict[str, float] = field(default_factory=dict)


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
    member = peer.install_id in view.mesh_members
    if member and view.member_notes.get(peer.install_id):
        return view.member_notes[peer.install_id]
    if (view.master_id is not None and view.self_input.install_id != view.master_id and peer.install_id != view.master_id
            and not peer.install_id.startswith("ssh:") and not member):
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
    brought = set(install_mod.covered([n.name for n in union]))
    hard = [n for n in dict.fromkeys([*needs, *filters]) if n not in union and not (n.kind == "tool" and n.name in brought)]
    decision = rule.decide(eligible, work, needs=hard, prefer=prefer, project_uid=project_uid, company_uid=view.company_uid)
    if not decision.chosen:
        return None
    peer = next(p for p in eligible if p.install_id == decision.chosen)
    tools = [next(n.name for n in missing[peer.install_id] if install_mod.ALLOW[n.name] == f) for f in
             install_mod.formulas_of([n.name for n in missing[peer.install_id]])]
    return PlaceAnswer("remote", peer.install_id, peer.label, f"{peer.label} can install {', '.join(tools)} with Homebrew first: {decision.reason}",
                       decision.candidates, install=tools)


def _breakeven_ok(runtime_s: float, overhead_s: float, *, self_can_fit: bool) -> bool:
    if runtime_s < MIN_OFFLOAD_RUNTIME_S:
        return False
    if self_can_fit:
        return runtime_s >= max(BREAKEVEN_UNDER_RESERVE_MIN_S, BREAKEVEN_UNDER_RESERVE_MULT * overhead_s)
    return runtime_s >= max(BREAKEVEN_PEGGED_MIN_S, BREAKEVEN_PEGGED_MULT * overhead_s)


def place(work: Workload, project_uid: str, policy: Policy, view: PlaceView, *, needs: Sequence[Need] = (), prefer: Sequence[Need] = (),
          filters: Sequence[Need] = (), holds: Holds = HOLDS, est_runtime_s: Optional[float] = None,
          active_balance: bool = True) -> PlaceAnswer:
    if not policy.auto_delegate:
        return PlaceAnswer("here", None, None, "project is set to this computer only")
    me = view.self_input
    own_snap = _own_snapshot(me, holds)
    pinned_here, effective_needs = locality.split_self_local_needs(needs)
    own_meets = not _unmet(own_snap, effective_needs)
    if pinned_here:
        if own_meets:
            if work.heavy:
                holds.try_hold(f"here-{uuid.uuid4().hex[:12]}", me.install_id, work.est_cpu_cores, work.est_ram_gb, HERE_HOLD_S, lambda _c, _r: True)
            return PlaceAnswer("here", None, None, f"pinned to this computer: {me.label}")
        return _refuse(me, own_snap, effective_needs, view, policy, None)
    self_input = replace(me, snapshot=own_snap)
    own = rule.decide([self_input], work, needs=effective_needs, project_uid=project_uid) if own_meets else None
    own_fits = bool(own is not None and own.chosen == me.install_id and own_snap is not None and (work.heavy or not rule.over_reserve(own_snap)))
    runtime_s = float(est_runtime_s) if est_runtime_s is not None else workload_mod.est_runtime_s(work.kind)
    if own_meets and own_fits and runtime_s < MIN_OFFLOAD_RUNTIME_S:
        return PlaceAnswer("here", None, None, f"command is too short ({runtime_s:.0f} s) to justify remote transfer", own.candidates if own else [])
    reasons: List[str] = []
    kept: List[rule.MachineInput] = []
    ov_map: Dict[str, float] = {}
    for peer in view.peers:
        why = drop_reason(peer, policy, view)
        if why:
            reasons.append(f"{peer.label} {why}")
            continue
        has_measured_ov = peer.install_id in view.peer_overheads
        ov_s = float(view.peer_overheads.get(peer.install_id, DEFAULT_PEER_OVERHEAD_S))
        check_be = (
            own_meets
            and peer.usable
            and peer.snapshot is not None
            and peer.has_project
            and (own_fits or work.heavy or est_runtime_s is not None or has_measured_ov)
        )
        if check_be and not _breakeven_ok(runtime_s, ov_s, self_can_fit=own_fits):
            reasons.append(f"{peer.label} skipped (transfer overhead {ov_s:.0f} s exceeds job runtime {runtime_s:.0f} s)")
            continue
        ov_map[peer.install_id] = ov_s
        kept.append(peer)
    hard = list(dict.fromkeys([*effective_needs, *filters]))
    if active_balance and work.heavy and own_fits and kept:
        peer_dec = rule.decide(kept, work, needs=hard, prefer=prefer, project_uid=project_uid, company_uid=view.company_uid,
                               overheads=ov_map, est_runtime_s=runtime_s)
        if peer_dec.chosen:
            best_peer = next(p for p in kept if p.install_id == peer_dec.chosen)
            combined = rule.decide([self_input, best_peer], work, auto_distribute=True, needs=effective_needs, prefer=(),
                                   project_uid=project_uid, company_uid=view.company_uid, overheads=ov_map, est_runtime_s=runtime_s)
            if combined.chosen and combined.chosen != me.install_id:
                if view.ssh_hold is not None and best_peer.install_id.startswith("ssh:"):
                    view.ssh_hold(best_peer.install_id, work.est_cpu_cores, work.est_ram_gb)
                return PlaceAnswer("remote", best_peer.install_id, best_peer.label, combined.reason, combined.candidates)
            if work.heavy:
                holds.try_hold(f"here-{uuid.uuid4().hex[:12]}", me.install_id, work.est_cpu_cores, work.est_ram_gb, HERE_HOLD_S, lambda _c, _r: True)
            return PlaceAnswer("here", None, None, f"this computer has room: {rule.describe(me.label, rule.headroom(own_snap))}", combined.candidates)
    if own_fits:
        if work.heavy:
            holds.try_hold(f"here-{uuid.uuid4().hex[:12]}", me.install_id, work.est_cpu_cores, work.est_ram_gb, HERE_HOLD_S, lambda _c, _r: True)
        return PlaceAnswer("here", None, None, f"this computer has room: {rule.describe(me.label, rule.headroom(own_snap))}", own.candidates if own else [])
    decision = rule.decide(kept, work, needs=hard, prefer=prefer, project_uid=project_uid, company_uid=view.company_uid,
                           overheads=ov_map, est_runtime_s=runtime_s) if kept else None
    if decision is not None and decision.chosen:
        peer = next(p for p in kept if p.install_id == decision.chosen)
        if view.ssh_hold is not None and peer.install_id.startswith("ssh:"):
            view.ssh_hold(peer.install_id, work.est_cpu_cores, work.est_ram_gb)
        return PlaceAnswer("remote", peer.install_id, peer.label, decision.reason, decision.candidates)
    if not own_meets:
        refused = _refuse(me, own_snap, effective_needs, view, policy, decision)
        if refused.code == "requirement_unmet":
            return install_candidates(work, project_uid, policy, view, needs=effective_needs, filters=filters, prefer=prefer) or refused
        return refused
    if decision is not None:
        reasons += [f"{r['label']}: {r['filter']}" for r in decision.candidates if r["filter"]]
    return PlaceAnswer("here", None, None, f"no other computer can take it now ({'; '.join(reasons) or 'none is paired'})",
                       decision.candidates if decision is not None else [])
