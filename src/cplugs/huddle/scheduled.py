
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import fire, item_owner, lean_read, service, title as titles, triggers, wake_target
from src.cplugs.huddle.roles import route
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.rules import ALL_LIST, check_list_key
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

PENDING, FAILED, PAUSED, FIRED = "pending", "failed", "paused", "fired"
_RANK = {PENDING: 0, FAILED: 0, PAUSED: 1, FIRED: 2}


def state_of(trigger: Dict[str, Any]) -> str:
    if trigger.get("repeat"):
        return PAUSED if trigger.get("paused") else FAILED if trigger.get("last_error") else PENDING
    if trigger.get("last_error"):
        return FAILED
    return FIRED if trigger.get("fired_at") is not None else PENDING


def _sort_key(item: Dict[str, Any]) -> tuple:
    trigger = item[triggers.FIELD]
    return (_RANK[state_of(trigger)], trigger.get("fire_at") or 0.0)


def _wanted(item: Dict[str, Any], paused: Optional[bool]) -> bool:
    trigger = item.get(triggers.FIELD)
    if not trigger or trigger.get("fire_at") is None and not trigger.get("repeat"):
        return False
    return paused is None or bool(trigger.get("paused")) == paused


def lead_keys(ctx: CplugContext) -> Dict[str, str]:
    return {key: seat.lead_key for key, seat in RoleStore(service.store(ctx)).seats().items()}


async def _pings(ctx: CplugContext, key: str, leads: Optional[Dict[str, str]] = None) -> tuple:
    if key == ALL_LIST:
        return None, None
    rows = await service.candidate_rows(ctx, key)
    target = await asyncio.to_thread(fire.pick_target, ctx, rows, key)
    if target is None and key.isdigit():
        lead = leads.get(key, "") if leads is not None else await asyncio.to_thread(lambda: RoleStore(service.store(ctx)).seat(key).lead_key)
        try:
            sleepers = await ctx.sessions.asleep_read()
        except HTTPException as exc:  # could not be read
            logger.warning("task_manager_schedules_asleep_unreadable", list=key, status=exc.status_code)
            return None, None
        if sleepers is None:
            return None, None
        return None, wake_target.untagged_wake_target(key, lead, sleepers)
    return target, next((r["key"] for r in rows if r["id"] == target), None)


async def tagged_pings(ctx: CplugContext, list_key: str, tag: str, leads: Optional[Dict[str, str]] = None,
                       seen: Optional[route.Seen] = None) -> Optional[tuple]:
    if not list_key.isdigit():
        lead = ""
    elif leads is not None:
        lead = leads.get(list_key, "")
    else:
        lead = await asyncio.to_thread(lambda: RoleStore(service.store(ctx)).seat(list_key).lead_key)
    for key in (tag, lead if lead != tag else ""):
        if not key:
            continue
        found = await route.peek(ctx, key, seen)
        if found.outcome == route.LIVE:
            return found.info.session.id, key
        if found.outcome == route.ASLEEP:
            return None, key
    return None


async def _item_pings(ctx: CplugContext, group: Dict[str, Any], item: Dict[str, Any], default: tuple, leads: Dict[str, str],
                      seen: Dict[tuple, Optional[tuple]]) -> tuple:
    tag = item.get(item_owner.TAG_COLUMN) or ""
    if tag and group["list"] != ALL_LIST:
        found = (group["list"], tag)
        if found not in seen:
            seen[found] = await tagged_pings(ctx, group["list"], tag, leads)
        return seen[found] or default
    return default


def _entry(group: Dict[str, Any], item: Dict[str, Any], session: Optional[str], session_key: Optional[str] = None) -> Dict[str, Any]:
    trigger = item[triggers.FIELD]
    state = state_of(trigger)
    return {"list": group["list"], "list_name": group["name"] or ("shared" if group["list"] == ALL_LIST else group["list"]),
            "item": item["id"], "title": item.get(titles.FIELD) or lean_read.lead(item.get("text")),
            "next_fire": None if state == FIRED else trigger.get("fire_at_iso"), "repeat": trigger.get("repeat"),
            "paused": bool(trigger.get("paused")), "state": state, "last_error": trigger.get("last_error"),
            "pings": {"project_id": group["project_id"], "project": group["name"], "session": session, "session_key": session_key}}


async def build(ctx: CplugContext, list_key: Optional[str] = None, paused: Optional[bool] = None) -> Dict[str, Any]:
    wanted = check_list_key(list_key) if list_key is not None else None
    body = await asyncio.to_thread(service.store(ctx).aggregate)
    names = await asyncio.to_thread(service.project_names, ctx)
    groups: List[Dict[str, Any]] = []
    rows: List[tuple] = []
    leads = await asyncio.to_thread(lead_keys, ctx)
    seen: Dict[tuple, Optional[tuple]] = {}
    for group in service.aggregate_groups(body, names):
        if wanted is not None and group["list"] != wanted:
            continue
        items = sorted((i for i in group["items"] if _wanted(i, paused)), key=_sort_key)
        if not items:
            continue
        groups.append({**group, "items": items})
        default = await _pings(ctx, group["list"], leads)
        for i in items:
            session, session_key = await _item_pings(ctx, group, i, default, leads, seen)
            rows.append((_sort_key(i), _entry(group, i, session, session_key)))
    rows.sort(key=lambda r: r[0])
    return {"cursor": body["cursor"], "groups": groups, "schedules": [r[1] for r in rows]}
