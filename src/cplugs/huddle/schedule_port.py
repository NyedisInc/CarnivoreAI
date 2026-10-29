"""
WHICH SESSION A SCHEDULE FIRES INTO is the delivery's own pick, never a second rule: ``fire.deliver`` tells
``fire.pick_target`` over the item's LIST (a project's list: its picked or most recent calling agent session, else its most
recently active one; the shared list and a project with no session of its own have none, because a fire there wakes or starts a
session that does not exist yet). The item's ``owner_session_key`` is NOT consulted by a fire; its TAG is (``tagged_session_key``: the tag, else the project lead, ``roles/tag_send.item_target``).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.cplugs.huddle import fire, item_owner, schedule_wakes, scheduled, service, triggers
from src.cplugs.huddle import lean_read, title as titles
from src.cplugs.huddle.roles import route
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.rules import ALL_LIST
from src.cplugs.sdk import CplugContext, ports
from src.cplugs.sdk.listing import listing_wake

NAME = "session.schedules"
logger = structlog.get_logger()


def entry_of(item: Dict[str, Any]) -> Dict[str, Any]:
    """One scheduled item as core's schedule entry.

    Inputs: item ({id, title, text, start_trigger}). Output: {name, next_fire_at (epoch s | None), enabled, failed, retrying}.
    ``enabled`` is not paused; ``failed`` is a fire that could not be delivered (``last_error``); ``retrying`` is a repeat, which
    carries on to its next occurrence after a failure, while a failed one-shot has no retry.
    Example: entry_of({"id": 1, "title": "x", "text": "", "start_trigger": {"fire_at": 9.0, "paused": True, "repeat": None, "last_error": None}})["enabled"] -> False
    """
    trigger = item[triggers.FIELD]
    return {"name": item.get(titles.FIELD) or lean_read.lead(item.get("text")) or f"item {item['id']}",
            "next_fire_at": trigger.get("fire_at"), "enabled": not trigger.get("paused"),
            "failed": bool(trigger.get("last_error")), "retrying": bool(trigger.get("repeat"))}


class SchedulePort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx
        self._app_state: Any = None
        self._unsubscribe: List[Any] = []
        self._mark: Optional[Tuple[Any, ...]] = None
        self._mark_lock = threading.Lock()

    async def wake_entries(self, asleep: List[Dict[str, Any]], infos: Optional[List[Any]] = None, app_state: Any = None) -> Dict[str, List[Dict[str, Any]]]:
        if app_state is not None:
            self._app_state = app_state
        return {uuid: [entry_of(item) for item in listed] for uuid, listed in (await schedule_wakes.wake_items(self._ctx, asleep, infos)).items()}

    def wake_listing(self) -> None:
        if self._app_state is not None:
            listing_wake(self._app_state)()

    def subscribe(self) -> None:
        if not self._unsubscribe:
            self._unsubscribe = [triggers.subscribe(self.wake_listing), triggers.subscribe_writes(self.wrote)]

    def wrote(self) -> None:
        if self._app_state is None:
            return
        try:
            mark = listing_mark(self._ctx)
        except (sqlite3.Error, OSError) as exc:  # could not
            logger.warning("task_manager_listing_mark_unreadable", error_type=type(exc).__name__, error=str(exc)[:200])
            self.wake_listing()
            return
        with self._mark_lock:
            moved, self._mark = mark != self._mark, mark
        if moved:
            self.wake_listing()

    def unsubscribe(self) -> None:
        for stop in self._unsubscribe:
            stop()
        self._unsubscribe = []

    async def by_session(self, infos: List[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, Any]]]:
        items = await asyncio.to_thread(lambda: service.store(self._ctx).scheduled_items())
        by_list: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            if item["list"] != ALL_LIST and scheduled.state_of(item[triggers.FIELD]) != scheduled.FIRED:
                by_list.setdefault(item["list"], []).append(item)
        if not by_list:
            return {}
        keys = await self._ctx.sessions.durable_keys(infos)
        rows_by_list = {list_key: service.candidates(infos, list_key, keys, await service.agent_session(self._ctx, list_key)) for list_key in by_list}
        defaults, leads = await asyncio.to_thread(_defaults_and_leads, self._ctx, rows_by_list)
        sessions = route.Seen(infos, keys, asleep)
        seen: Dict[tuple, Optional[tuple]] = {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for list_key, listed in by_list.items():
            for item in listed:
                tag = item.get(item_owner.TAG_COLUMN) or ""
                if tag and (list_key, tag) not in seen:
                    seen[(list_key, tag)] = await scheduled.tagged_pings(self._ctx, list_key, tag, leads, sessions)
                tagged = seen[(list_key, tag)] if tag else None
                target = tagged[0] if tagged is not None else defaults[list_key]
                if target is not None:
                    out.setdefault(target, []).append(entry_of(item))
        for entries in out.values():
            entries.sort(key=lambda e: (e["next_fire_at"] is None, e["next_fire_at"] or 0.0))
        return out


def _defaults_and_leads(ctx: CplugContext, rows_by_list: Dict[str, List[dict]]) -> tuple:
    with ctx.storage.read_scope():
        return {key: fire.pick_target(ctx, rows, key) for key, rows in rows_by_list.items()}, scheduled.lead_keys(ctx)


def listing_mark(ctx: CplugContext) -> Tuple[Any, ...]:
    store = service.store(ctx)
    with ctx.storage.read_scope():
        items = store.scheduled_items()
        leads = scheduled.lead_keys(ctx)
        dnd = RoleStore(store).dnd_keys()
    scheduled_rows = sorted((i["id"], i["list"], i.get(item_owner.TAG_COLUMN) or "", entry_of(i)["name"], repr(sorted(i[triggers.FIELD].items())))
                            for i in items)
    return tuple(scheduled_rows), tuple(sorted(leads.items())), tuple(sorted(dnd))


_port: Optional[SchedulePort] = None


def register(ctx: CplugContext) -> None:
    global _port
    _port = SchedulePort(ctx)
    _port.subscribe()
    ports.register(NAME, _port)


def unregister() -> None:
    global _port
    if _port is not None:
        _port.unsubscribe()
    _port = None
    ports.unregister(NAME)
