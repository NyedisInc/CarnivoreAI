
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, TypeVar

from src.core.swarm import activity, alerts, body, owner_wait, settings as swarm_settings, store, thread_port
from src.core.swarm.names import shown_name

T = TypeVar("T")

_SUMMARY_COLS = ("id", "slug", "display_name", "rank", "state", "parent_id", "job", "repo_dir", "effort", "harness",
                 "thread_key",
                 "project_id", "company_id", "persona")


class AgentMissing(LookupError):
    pass


async def _bodies(manager: Any) -> Dict[int, Any]:
    infos = await manager.list_session_infos()
    return {int(i.session_row_id): i for i in infos
            if getattr(i, "session_row_id", None) is not None and getattr(i, "host_key", None) in (None, "local")}


async def _uuids(agents: List[Dict[str, Any]]) -> Dict[int, str]:
    ids = sorted({a["session_row_id"] for a in agents if a.get("session_row_id") is not None})
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = await body.run_db(lambda c: c.execute(
        f"SELECT id, session_uuid FROM sessions WHERE id IN ({marks}) AND session_uuid IS NOT NULL", ids).fetchall())
    return {int(r[0]): str(r[1]) for r in rows}


async def _host_labels(agents: List[Dict[str, Any]]) -> Dict[str, str]:
    keys = sorted({a.get("host_key") or "local" for a in agents} - {"local"})
    if not keys:
        return {}
    marks = ",".join("?" for _ in keys)
    rows = await body.run_db(lambda c: c.execute(f"SELECT key, label FROM hosts WHERE kind = 'peer' AND key IN ({marks})", keys).fetchall())
    return {str(r[0]): str(r[1]) for r in rows if r[1]}


async def _placement_reasons(agents: List[Dict[str, Any]]) -> Dict[int, str]:
    ids = sorted({a["id"] for a in agents})
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = await body.run_db(lambda c: c.execute(
        f"SELECT agent_id, reason FROM pack_placements WHERE agent_id IN ({marks}) AND chosen_install_id IS NOT NULL "
        "ORDER BY id", ids).fetchall())
    return {int(r[0]): str(r[1]) for r in rows if r[1]}


def summarize(agent: Dict[str, Any], bodies: Dict[int, Any], uuids: Optional[Dict[int, str]] = None,
              labels: Optional[Dict[str, str]] = None, reasons: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    out = {k: agent[k] for k in _SUMMARY_COLS}
    pass
    out["display_name"] = shown_name(agent)
    out["specialty"] = agent.get("specialty") if agent["rank"] == "feature" else None
    out["session_row_id"] = agent["session_row_id"]
    out["session_uuid"] = (uuids or {}).get(agent["session_row_id"]) if agent["session_row_id"] is not None else None
    info = bodies.get(agent["session_row_id"]) if agent["session_row_id"] is not None else None
    out["session_id"] = info.session.id if info is not None else None
    out["tmux_session"] = (str(info.tmux_session) if info.tmux_session else None) if info is not None else None
    slot = agent.get("color_slot")
    seed = agent.get("character_seed")
    out["character_seed"] = seed if seed is not None else _stable_seed(agent["id"], slot)
    out["color_slot"] = slot if slot is not None else out["character_seed"] % 8 + 1
    out["color_chosen"] = bool(agent.get("color_chosen"))
    out["shape"] = agent.get("shape")
    out["tile_bg"] = agent.get("tile_bg")
    host = agent.get("host_key") or "local"
    out["host_key"] = host
    out["host_label"] = None if host == "local" else (labels or {}).get(host) or host
    out["placement_reason"] = (reasons or {}).get(agent["id"])
    return out


def _stable_seed(agent_id: int, slot: Optional[int]) -> int:
    return (agent_id * 2654435761 + (slot or 0)) % 2**31 or 1


async def _live_fields(agents: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    live = await body.run_db(owner_wait.live_questions)
    rungs = await alerts.roster_alerts(agents, live)
    waiting = owner_wait.asking_agents(live)
    return {a["id"]: {**rungs[a["id"]], **activity.current(a["id"]), "question_waiting": a["id"] in waiting} for a in agents}


async def roster(manager: Any) -> Dict[str, Any]:
    def read(conn: sqlite3.Connection) -> tuple:
        return store.list_agents(conn), store.live_body_count(conn)

    agents, live = await body.run_db(read)
    cfg = swarm_settings.read_current()
    bodies = await _bodies(manager)
    fields = await _live_fields(agents)
    uuids = await _uuids(agents)
    labels = await _host_labels(agents)
    reasons = await _placement_reasons(agents)
    return {"agents": [{**summarize(a, bodies, uuids, labels, reasons), **fields[a["id"]]} for a in agents],
            "threads_ready": thread_port.get() is not None,
            "limits": {"max_children_per_parent": cfg.max_children_per_parent, "max_live_bodies": cfg.max_live_bodies,
                       "live_bodies": live}}


async def detail(manager: Any, agent_id: int) -> Dict[str, Any]:
    def read(conn: sqlite3.Connection) -> Optional[tuple]:
        agent = store.get_agent(conn, agent_id)
        if agent is None:
            return None
        kids = [k["id"] for k in store.list_agents(conn, parent_id=agent_id)]
        return agent, kids, store.get_open_wake(conn, agent_id)

    found = await body.run_db(read)
    if found is None:
        raise AgentMissing(str(agent_id))
    agent, kids, wake = found
    out = summarize(agent, await _bodies(manager), await _uuids([agent]), await _host_labels([agent]),
                    await _placement_reasons([agent]))
    out.update((await _live_fields([agent]))[agent["id"]])
    out.update(goal=agent["goal"], effort_reason=agent["effort_reason"], launch_profile=agent["launch_profile"],
               memory_scope=agent["memory_scope"], children=kids,
               open_wake={k: wake[k] for k in ("id", "started_at", "reason", "mode")} if wake else None)
    return out


async def get_agent_row(agent_id: int) -> Dict[str, Any]:
    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None:
        raise AgentMissing(str(agent_id))
    return agent
