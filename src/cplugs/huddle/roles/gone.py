
from __future__ import annotations

import asyncio
import json
import weakref
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.cplugs.huddle import rules, service
from src.cplugs.huddle.roles import ask, lead, service as roles_service, set_lead
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

KEEP = "keep"
CARRIER_TITLE = "pick a new lead"
MAX_SESSIONS = 11


def option_id(session_key: str) -> str:
    return session_key.replace("-", "").lower()[:32]


LATER = "later"
_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    if loop not in _LOCKS:
        _LOCKS[loop] = asyncio.Lock()
    return _LOCKS[loop]


def _open_questions(store: Any, list_key: Optional[str] = None) -> Dict[str, List[Tuple[int, Dict[str, Any]]]]:
    where, args = ("AND i.list_key = ? ", (ask.LEAD_GONE, list_key)) if list_key is not None else ("", (ask.LEAD_GONE,))
    with closing(store._read_connection()) as conn:
        rows = conn.execute("SELECT i.list_key, m.item_id, m.parts FROM work_messages m JOIN work_items i ON i.id = m.item_id WHERE m.kind = 'question' "
                            f"AND m.answered = 0 AND m.category = ? AND i.deleted = 0 {where}ORDER BY m.id", args).fetchall()
    out: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for r in rows:
        out.setdefault(str(r[0]), []).append((int(r[1]), json.loads(r[2]) if r[2] else {}))
    return out


def _session_options(roster: roles_service.Roster, list_key: str) -> Dict[str, str]:
    return {option_id(k): roster.labels.get(k, k) for k in roster.live_keys(list_key) | roster.asleep_keys(list_key)}


def _chosen(sessions: Mapping[str, str]) -> List[str]:
    return sorted(sessions, key=lambda o: (sessions[o].lower(), o))[:MAX_SESSIONS]


def _ask(store: Any, item_id: int, context: str, sessions: Mapping[str, str], keep_label: str) -> None:
    chosen = _chosen(sessions)
    options, labels = chosen + [KEEP], {**{o: sessions[o] for o in chosen}, KEEP: keep_label}
    if len(options) < 2:
        options.append(LATER)
        labels[LATER] = "decide later"
    ask.carnivore_ask(store, item_id, category=ask.LEAD_GONE, context=context, options=options, labels=labels)


def _raise_question(store: Any, list_key: str, roster: roles_service.Roster, moved_to: str) -> Optional[int]:
    if _open_questions(store, list_key):
        return None
    carrier = store.add(list_key, "the lead of this project is gone", actor=rules.CLAUDE, created_key=rules.CARNIVORE_KEY, state=rules.TODO, title=CARRIER_TITLE)
    context = f"the lead of this project was archived or deleted; its seat moved up to {moved_to}" if moved_to else "the lead of this project was archived or deleted"
    _ask(store, int(carrier["id"]), context, _session_options(roster, list_key), f"keep {moved_to}" if moved_to else "leave it empty")
    return int(carrier["id"])


def _refresh(store: Any, projects: Mapping[str, str], roster: roles_service.Roster) -> None:
    for list_key, open_now in _open_questions(store).items():
        if list_key in projects:
            _refresh_one(store, list_key, open_now, roster)


def _refresh_one(store: Any, list_key: str, open_now: List[Tuple[int, Dict[str, Any]]], roster: roles_service.Roster) -> None:
    for extra, _parts in open_now[1:]:
        store.mark_answered(extra, actor=rules.CLAUDE)
        logger.info("task_manager_lead_gone_duplicate_withdrawn", list=list_key, item=extra)
    item_id, parts = open_now[0]
    offered = {o["id"]: o["label"] for q in parts.get("questions", [])[:1] for o in q.get("options", [])}
    sessions = {o: label for o, label in offered.items() if o not in (KEEP, LATER)}
    wanted = {**_session_options(roster, list_key), **sessions}
    if set(_chosen(wanted)) != set(sessions):
        _ask(store, item_id, str(parts.get("context") or "the lead of this project was archived or deleted"), wanted, offered.get(KEEP, "keep"))
        logger.info("task_manager_lead_gone_options_refreshed", list=list_key, item=item_id, sessions=len(wanted))


async def check(ctx: CplugContext, roster: Optional[roles_service.Roster] = None) -> List[Dict[str, Any]]:
    async with _lock():
        return await _check(ctx, roster)


async def _check(ctx: CplugContext, roster: Optional[roles_service.Roster]) -> List[Dict[str, Any]]:
    swarm = service.swarm_of(ctx)
    projects = await asyncio.to_thread(service.project_names, ctx)
    roster = roster or await roles_service.measure(ctx)
    retired = [a for a in roster.agents if a.rank == "project" and a.body_gone and a.project_key in projects]
    for agent in retired:
        await swarm.retire_dead_project_agent(agent.agent_id)
    if retired:
        roster = await roles_service.measure(ctx)
    store = RoleStore(service.store(ctx))
    seats = await asyncio.to_thread(roles_service.evaluate, store, roster)
    acted: List[Dict[str, Any]] = []
    for list_key, seat in seats.items():
        if list_key not in projects or not seat.ever_led or roles_service.holder_of(seat, roster)[1] != lead.VACANT_GONE:
            continue
        fallback = await asyncio.to_thread(swarm.fallback_agent, list_key) if swarm is not None else None
        if fallback is not None:
            await asyncio.to_thread(store.set_lead, list_key, lead.fallback_key(fallback.agent_id), lead.BY_FALLBACK)
        else:
            await asyncio.to_thread(store.set_lead, list_key, "", lead.BY_OWNER)
        asked = await asyncio.to_thread(_raise_question, service.store(ctx), list_key, roster, fallback.display_name if fallback else "")
        logger.info("task_manager_lead_gone", list=list_key, moved_to=fallback.agent_id if fallback else None, asked=asked)
        acted.append({"list": list_key, "moved_to": fallback.display_name if fallback else "", "asked": asked})
    await asyncio.to_thread(_refresh, service.store(ctx), projects, roster)
    return acted


async def apply_answer(ctx: CplugContext, posted: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    outcome = posted.get("carnivore")
    if not outcome or outcome["category"] != ask.LEAD_GONE:
        return None
    list_key, carrier = posted["item"]["list"], int(posted["item"]["id"])
    store = service.store(ctx)
    if outcome["choice"] in (KEEP, LATER):
        await asyncio.to_thread(_clear_carriers, store, list_key)
        return None
    roster = await roles_service.measure(ctx)
    key = next((k for k in roster.live_keys(list_key) | roster.asleep_keys(list_key) if option_id(k) == outcome["choice"]), None)
    try:
        if key is None:
            raise set_lead.LeadRefused("that session is no longer a live or asleep session of this project")
        done = await set_lead.set_lead(ctx, list_key, key)
    except set_lead.LeadRefused as exc:
        logger.warning("task_manager_lead_pick_refused", list=list_key, error=str(exc)[:200])
        await asyncio.to_thread(_ask, store, carrier, f"that pick did not take ({exc}). pick again", _session_options(roster, list_key),
                                await asyncio.to_thread(_keep_label, store, list_key, roster))
        return None
    await asyncio.to_thread(_clear_carriers, store, list_key)
    return done


def _clear_carriers(store: Any, list_key: str) -> None:
    with closing(store._read_connection()) as conn:
        spent = [int(r[0]) for r in conn.execute(
            "SELECT i.id FROM work_items i WHERE i.list_key = ? AND i.deleted = 0 AND i.title = ? AND i.created_key = ? AND NOT EXISTS "
            "(SELECT 1 FROM work_messages m WHERE m.item_id = i.id AND m.kind = 'question' AND m.answered = 0)",
            (list_key, CARRIER_TITLE, rules.CARNIVORE_KEY)).fetchall()]
    for item_id in spent:
        store.delete(item_id, actor=rules.JOE)


def _keep_label(store: Any, list_key: str, roster: roles_service.Roster) -> str:
    holder = roles_service.holder_of(RoleStore(store).seat(list_key), roster)[0]
    return f"keep {roster.labels.get(holder, holder)}" if holder else "leave it empty"
