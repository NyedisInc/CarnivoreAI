
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import lead, service as roles_service
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.swarm import SwarmError

logger = structlog.get_logger()

PROMOTE, SKIPPED, ALREADY_AGENT, NO_LEAD, BAD_PICK, CLEAR_SEAT = "promote", "skipped", "already_agent", "no_lead", "bad_pick", "clear_seat"
PROMOTE_COMPANY = "promote_company"
PINNED_SEAT = "pinned_seat"
DONE, REFUSED, CLEARED = "promoted", "refused", "cleared"


def _resolve_pick(wanted: str, roster: roles_service.Roster, list_key: str) -> Optional[str]:
    pool = roster.live_keys(list_key) | roster.asleep_keys(list_key)
    if wanted in pool:
        return wanted
    named = [k for k in pool if roster.labels.get(k) == wanted]
    return named[0] if len(named) == 1 else None


def _current_lead(seats: Mapping[str, lead.Seat], roster: roles_service.Roster, list_key: str) -> Tuple[Optional[str], str]:
    holder = roles_service.holder_of(seats.get(list_key, lead.Seat(list_key)), roster)[0]
    if holder is not None:
        return holder, "its current lead"
    pool = roster.live_keys(list_key) | roster.asleep_keys(list_key)
    return (next(iter(pool)), "its only session") if len(pool) == 1 else (None, "")


async def plan(ctx: CplugContext, skip: Sequence[str] = (), picks: Optional[Mapping[str, str]] = None) -> List[Dict[str, Any]]:
    picks = dict(picks or {})
    roster = await roles_service.measure(ctx)
    store = RoleStore(service.store(ctx))
    seats = await asyncio.to_thread(store.seats)
    rows: List[Dict[str, Any]] = []
    names = await asyncio.to_thread(service.project_names, ctx)
    swarm = service.swarm_of(ctx)
    for list_key, name in sorted(names.items()):
        if not list_key.isdigit():
            continue
        row: Dict[str, Any] = {"list": list_key, "project": name}
        pick = picks.get(list_key) or picks.get(name)
        seat = seats.get(list_key, lead.Seat(list_key))
        if list_key in skip or name in skip:
            rows.append({**row, "action": SKIPPED, "reason": "on the skip list"})
        elif not pick and lead.is_pinned(seat, roster.project_agents.get(list_key)) and \
                roles_service.holder_of(seat, roster)[0] == seat.lead_key:
            rows.append({**row, "action": PINNED_SEAT, "session": seat.lead_key, "session_name": roster.labels.get(seat.lead_key, seat.lead_key),
                         "reason": "the owner pinned the Task Manager seat to this session; it is not promoted"})
        elif list_key in roster.project_agents:
            rows.append({**row, "action": ALREADY_AGENT, "reason": "the project already has a Swarm project agent"})
        elif not pick and (inherited := roster.inherited_agent(list_key)) is not None and \
                roles_service.holder_of(seat, roster)[0] == inherited:
            rows.append({**row, "action": ALREADY_AGENT, "reason": "an enclosing project's Swarm project agent already leads it"})
        else:
            key, why = (_resolve_pick(pick, roster, list_key), "the owner's pick") if pick else _current_lead(seats, roster, list_key)
            if pick and key is None:
                rows.append({**row, "action": BAD_PICK, "reason": f"{pick!r} is not one session of this project (live or asleep)"})
            elif key is None or lead.fallback_agent_id(key) is not None:
                rows.append({**row, "action": NO_LEAD, "reason": "the project has no lead session to promote"})
            else:
                hq = swarm is not None and await asyncio.to_thread(swarm.company_hq, list_key) is not None
                rows.append({**row, "action": PROMOTE_COMPANY if hq else PROMOTE, "session": key, "session_name": roster.labels.get(key, key),
                             "state": "live" if key in roster.live_keys(list_key) else "asleep",
                             "reason": why})
    live = set(names)
    for list_key, seat in sorted(seats.items()):
        if list_key.isdigit() and list_key not in live and seat.lead_key:
            rows.append({"list": list_key, "project": f"project {list_key} (archived or gone)", "action": CLEAR_SEAT,
                         "session": seat.lead_key, "session_name": roster.labels.get(seat.lead_key, seat.lead_key),
                         "reason": "the seat is kept for a project that is no longer live"})
    return rows


async def run(ctx: CplugContext, skip: Sequence[str] = (), picks: Optional[Mapping[str, str]] = None, dry_run: bool = True) -> Dict[str, Any]:
    rows = await plan(ctx, skip, picks)
    swarm = service.swarm_of(ctx)
    if not dry_run:
        if swarm is None:
            raise SwarmError("the Swarm is not available here")
        roles = RoleStore(service.store(ctx))
        for row in rows:
            if row["action"] == CLEAR_SEAT:
                await asyncio.to_thread(roles.set_lead, row["list"], "", "")
                row["outcome"] = CLEARED
            if row["action"] not in (PROMOTE, PROMOTE_COMPANY):
                continue
            try:
                await swarm.promote_session(row["session"], row["list"])
                row["outcome"] = DONE
            except SwarmError as exc:
                row["outcome"], row["detail"] = REFUSED, str(exc)
                logger.warning("task_manager_retrofit_refused", list=row["list"], error=str(exc)[:200])
        roster = await roles_service.measure(ctx)
        await asyncio.to_thread(roles_service.evaluate, RoleStore(service.store(ctx)), roster)
    return {"dry_run": dry_run, "plan": rows, "promoted": sum(r.get("outcome") == DONE for r in rows), "cleared": sum(r.get("outcome") == CLEARED for r in rows),
            "refused": sum(r.get("outcome") == REFUSED for r in rows)}
