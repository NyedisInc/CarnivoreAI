
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from src.cplugs.huddle import item_owner
from src.cplugs.sdk import AgentCaller, CplugContext


def owner_labels(infos: Iterable[Any], keys: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for info in infos:
        sid = info.session.id
        label = info.label or info.tmux_session or sid
        out[sid] = label
        out[keys.get(sid) or sid] = label
    return out


async def annotate(ctx: CplugContext, items: List[Dict[str, Any]]) -> None:
    if not any(i.get(item_owner.COLUMN) or i.get(item_owner.TAG_COLUMN) for i in items):
        return
    infos = await ctx.sessions.list()
    labels = owner_labels(infos, await ctx.sessions.durable_keys(infos))
    for item in items:
        for column, field in ((item_owner.COLUMN, item_owner.FIELD), (item_owner.TAG_COLUMN, item_owner.TAGGED_BY)):
            label = labels.get(item.get(column) or "")
            if label:
                item[field] = label


async def annotate_tagged(ctx: CplugContext, items: List[Dict[str, Any]]) -> None:
    if not any(i.get(item_owner.TAG_COLUMN) for i in items):
        return
    infos = await ctx.sessions.list()
    labels = owner_labels(infos, await ctx.sessions.durable_keys(infos))
    for item in items:
        label = labels.get(item.get(item_owner.TAG_COLUMN) or "")
        if label:
            item[item_owner.TAGGED_BY] = label


def held_by(items: Iterable[Dict[str, Any]], caller: AgentCaller, key: Optional[str]) -> Set[int]:
    if caller.external or not caller.current_session_id:
        return set()
    me = {caller.current_session_id, key} - {None, ""}
    return {int(i["id"]) for i in items if i.get(item_owner.COLUMN) in me}
