
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import gone, service as roles_service
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.sdk import CplugContext, ports
from src.cplugs.sdk.listing import listing_wake

NAME = "session.roles"
logger = structlog.get_logger()


class RolesPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx
        self._app_state: Any = None

    async def read(self, app_state: Any, infos: List[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, bool]]:
        self._app_state = app_state
        roster = await roles_service.measure(self._ctx, infos, asleep)
        if await self.check_gone(roster=roster):
            roster = await roles_service.measure(self._ctx, infos, asleep)
        store = RoleStore(service.store(self._ctx))
        seats, dnd = await asyncio.to_thread(_seats_and_dnd, store, roster, False)
        keys = roster.keys
        holders = {list_key: roles_service.holder_of(seat, roster)[0] for list_key, seat in seats.items()}
        out: Dict[str, Dict[str, bool]] = {}
        for info in infos:
            key = keys.get(info.session.id) or info.session.id
            project = getattr(info, "project_id", None)
            out[info.session.id] = {"lead": project is not None and holders.get(str(project)) == key, "dnd": key in dnd}
        return out

    async def settle(self) -> None:
        await settle(self._ctx)

    async def check_gone(self, app_state: Any = None, roster: Optional[roles_service.Roster] = None) -> bool:
        if app_state is not None:
            self._app_state = app_state
        try:
            return bool(await gone.check(self._ctx, roster))
        except (roles_service.RolesUnmeasured, OSError, RuntimeError, ValueError, LookupError, sqlite3.Error, TaskManagerError) as exc:
            logger.warning("task_manager_lead_gone_check_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return False

    def wake(self) -> None:
        if self._app_state is not None:
            listing_wake(self._app_state)()


def _seats_and_dnd(store: RoleStore, roster: roles_service.Roster, write_pick: bool) -> Tuple[Dict[str, Any], FrozenSet[str]]:
    with store.read_scope():
        return roles_service.evaluate(store, roster, write_pick=write_pick), store.dnd_keys()


_port: Optional[RolesPort] = None


def register(ctx: CplugContext) -> RolesPort:
    global _port
    if _port is None:
        _port = RolesPort(ctx)
    ports.register(NAME, _port)
    return _port


def unregister() -> None:
    global _port
    _port = None
    ports.unregister(NAME)


async def settle(ctx: CplugContext) -> None:
    try:
        roster = await roles_service.measure(session_ctx(ctx))
        store = RoleStore(service.store(ctx))
        await asyncio.to_thread(roles_service.evaluate, store, roster)
    except (roles_service.RolesUnmeasured, OSError, RuntimeError, ValueError, LookupError, sqlite3.Error, TaskManagerError) as exc:
        logger.warning("task_manager_lead_settle_failed", error_type=type(exc).__name__, error=str(exc)[:200])


def wake() -> None:
    if _port is not None:
        _port.wake()


def announce(ctx: CplugContext) -> None:
    roles_service.notify_prefs(ctx)
    wake()


def session_ctx(fallback: CplugContext) -> CplugContext:
    return _port._ctx if _port is not None else fallback
