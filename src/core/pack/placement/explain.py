
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

from src.core.computers import direction
from src.core.db import table_exists
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.placement import enhanced, rule
from src.core.pack.placement.workload import Workload
from src.core.pack.placement.workload import resolve as resolve_workload

logger = structlog.get_logger()

class PlacementUnavailable(RuntimeError):
    pass


@dataclass
class Request:

    workload: Workload
    needs: List[str] = field(default_factory=list)
    project: Optional[str] = None
    machine: Optional[str] = None


@dataclass(frozen=True)
class Presence:

    uid: Optional[str]
    home_install_id: str
    present_on: Optional[Set[str]]


def lookup_project(conn: sqlite3.Connection, project: Optional[str], self_id: str) -> Presence:
    if not project:
        return Presence(None, self_id, None)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
    p2 = {"uid", "home_install_id"} <= cols
    row = conn.execute(f"SELECT {'uid, home_install_id' if p2 else 'NULL, NULL'} FROM projects WHERE display_name = ? OR root = ? LIMIT 1",
                       (project, project)).fetchone()
    if row is None:
        return Presence(None, self_id, {self_id})
    uid, home = row[0], row[1] or self_id
    present = {home, self_id}
    if uid and table_exists(conn, "project_replicas"):
        present |= {r[0] for r in conn.execute("SELECT install_id FROM project_replicas WHERE project_uid = ?", (uid,))}
    return Presence(uid, home, present)


def _inputs(wired: Any, presence: Presence, self_snapshot: Dict[str, Any], live_agents: int, remote: bool) -> List[rule.MachineInput]:
    me = wired.runtime
    out = [rule.MachineInput(me.install_id, me.label, self_snapshot, True, True, presence.home_install_id == me.install_id,
                             presence.present_on is None or me.install_id in presence.present_on, live_agents)]
    if not remote:
        return out
    roster = me.roster
    for peer in wired.peers():
        if direction.contained(peer.install_id):
            continue
        entry = roster.entries.get(peer.install_id)
        live = roster.peer_state(peer) == "connected" and entry is not None
        out.append(rule.MachineInput(peer.install_id, peer.label or (entry.label if entry else ""), entry.snapshot if live else None, live,
                                     False, presence.home_install_id == peer.install_id,
                                     presence.present_on is None or peer.install_id in presence.present_on, None))
    return out


def _gather(wired: Any, request: Request, remote: bool) -> Dict[str, Any]:
    me = wired.runtime
    with closing(wired.open_db()) as conn:
        presence = lookup_project(conn, request.project, me.install_id)
        live = _live_agents(conn)
    return {"settings": me.settings(), "machines": _inputs(wired, presence, me.own_snapshot(), live, remote), "presence": presence}


def _live_agents(conn: sqlite3.Connection) -> int:
    from src.core.swarm import store

    try:
        return store.live_body_count(conn)
    except sqlite3.Error:
        return 0


def _explicit(machines: List[rule.MachineInput], decision: rule.Decision, wanted: str) -> rule.Decision:
    found = next((m for m in machines if wanted in (m.install_id, m.label)), None)
    if found is None:
        raise ValueError(f"no machine in the Pack matches {wanted[:64]}")
    return rule.Decision(found.install_id, rule.MODE_EXPLICIT, f"explicit: {found.label} was chosen by name", decision.workload,
                         decision.candidates)


def record(conn: sqlite3.Connection, decision: rule.Decision, *, agent_id: Optional[int] = None,
           session_id: Optional[int] = None) -> int:
    import json

    with conn:
        cur = conn.execute(
            "INSERT INTO pack_placements (agent_id, session_id, workload_json, chosen_install_id, mode, reason, candidates_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, session_id, json.dumps(decision.workload), decision.chosen, decision.mode, decision.reason[:1000],
             json.dumps(decision.candidates), time.time()))
    return int(cur.lastrowid)


async def place(request: Request, *, wired: Any = None, decide: Optional[enhanced.DecideFn] = None, ref: Any = None,
                timeout: float = enhanced.TIMEOUT_SECONDS, agent_id: Optional[int] = None, record_it: bool = True,
                remote: Optional[bool] = None) -> rule.Decision:
    wired = wired or machines_runtime.wiring()
    if wired is None:
        raise PlacementUnavailable("the Pack machine layer is not running")
    use_remote = remote if remote is not None else bool(request.machine) or wired.runtime.settings().auto_distribute
    got = await asyncio.to_thread(_gather, wired, request, use_remote)
    settings, machines, presence = got["settings"], got["machines"], got["presence"]
    decision = rule.decide(machines, request.workload, auto_distribute=settings.auto_distribute, needs=request.needs,
                           project_uid=presence.uid)
    if request.machine:
        decision = _explicit(machines, decision, request.machine)
    elif settings.placement_mode == "enhanced" and decision.chosen is not None and not decision.stayed_home:
        decision = await _ask_model(decision, settings, machines, presence, decide, ref, timeout)
    if record_it:
        await asyncio.to_thread(_record_with(wired), decision, agent_id)
    return decision


def _record_with(wired: Any) -> Callable[[rule.Decision, Optional[int]], int]:
    def write(decision: rule.Decision, agent_id: Optional[int]) -> int:
        with closing(wired.open_db()) as conn:
            return record(conn, decision, agent_id=agent_id)

    return write


async def _ask_model(decision: rule.Decision, settings: Any, machines: List[rule.MachineInput], presence: Presence,
                     decide: Optional[enhanced.DecideFn], ref: Any, timeout: float) -> rule.Decision:
    rows = [r for r in decision.candidates if r["candidate"]]
    if len(rows) < 2:
        return decision
    try:
        if decide is None:
            from src.core.byoai import gateway

            gw = gateway.get_gateway()
            decide = gw.decide
            ref = enhanced.target_for(gw, settings.placement_model.model_dump() if settings.placement_model else None)
        home = next((m.label for m in machines if m.install_id == presence.home_install_id), None)
        picked = await enhanced.choose(rows, decision.workload, decide=decide, ref=ref, home_label=home, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.info("pack_placement_model_fallback", error=type(exc).__name__)
        why = str(exc) if isinstance(exc, enhanced.Unavailable) else f"model failed ({type(exc).__name__})"
        return rule.Decision(decision.chosen, rule.MODE_FALLBACK, f"{why}; stats rule: {decision.reason}", decision.workload,
                             decision.candidates)
    label = next((r["label"] for r in rows if r["install_id"] == picked), picked)
    return rule.Decision(picked, rule.MODE_ENHANCED, f"model chose {label}; stats rule: {decision.reason}", decision.workload,
                         decision.candidates)


def workload_for(tag: Optional[Dict[str, Any]], task_type: Optional[str]) -> Workload:
    return resolve_workload(tag, task_type)
