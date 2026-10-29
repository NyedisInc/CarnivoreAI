
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set

from src.cplugs.huddle import item_owner, scheduled, service, triggers, wake_target
from src.cplugs.huddle.rules import ALL_LIST
from src.cplugs.sdk import CplugContext


def _firing(item: Dict[str, Any]) -> Optional[float]:
    trigger = item[triggers.FIELD]
    if item["list"] == ALL_LIST or trigger.get("paused") or scheduled.state_of(trigger) == scheduled.FIRED:
        return None
    return trigger.get("fire_at") or None


class _Reader:

    def __init__(self, ctx: CplugContext, infos: Optional[List[Any]]) -> None:
        self.ctx = ctx
        self._infos = infos
        self._keys: Dict[str, str] = {}
        self._live_keys: Optional[Set[str]] = None
        self._has_own: Dict[str, bool] = {}
        self._leads: Optional[Dict[str, str]] = None

    async def live_keys(self) -> Set[str]:
        if self._live_keys is None:
            if self._infos is None:
                self._infos = await self.ctx.sessions.list()
            self._keys = await self.ctx.sessions.durable_keys(self._infos)
            self._live_keys = set(self._keys.values())
        return self._live_keys

    async def has_own_live(self, list_key: str) -> bool:
        if list_key not in self._has_own:
            await self.live_keys()
            rows = service.candidates(self._infos or [], list_key, self._keys, await service.agent_session(self.ctx, list_key))
            self._has_own[list_key] = any(not r.get("elsewhere") for r in rows)
        return self._has_own[list_key]

    async def lead(self, list_key: str) -> str:
        if not list_key.isdigit():
            return ""
        if self._leads is None:
            self._leads = await asyncio.to_thread(scheduled.lead_keys, self.ctx)
        return self._leads.get(list_key, "")


async def _tagged_target(reader: _Reader, list_key: str, tag: str, asleep_keys: Set[str]) -> Optional[str]:
    for key in (tag, await reader.lead(list_key)):
        if not key:
            continue
        if key in asleep_keys:
            return key
        if key in await reader.live_keys():
            return ""
    return None


async def wake_items(ctx: CplugContext, asleep: List[Dict[str, Any]], infos: Optional[List[Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    asleep_keys = {a["session_uuid"] for a in asleep}
    if not asleep_keys:
        return {}
    items = await asyncio.to_thread(lambda: service.store(ctx).scheduled_items())
    reader = _Reader(ctx, infos)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        if _firing(item) is None:
            continue
        list_key = item["list"]
        tag = item.get(item_owner.TAG_COLUMN) or ""
        target = await _tagged_target(reader, list_key, tag, asleep_keys) if tag else None
        if target is None and list_key.isdigit() and not await reader.has_own_live(list_key):
            target = wake_target.untagged_wake_target(list_key, await reader.lead(list_key), asleep)
        if target:
            out.setdefault(target, []).append(item)
    for listed in out.values():
        listed.sort(key=lambda item: _firing(item) or 0.0)
    return out


async def wake_times(ctx: CplugContext, asleep: List[Dict[str, Any]], infos: Optional[List[Any]] = None) -> Dict[str, float]:
    return {uuid: _firing(listed[0]) for uuid, listed in (await wake_items(ctx, asleep, infos)).items()}
