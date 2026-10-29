
from __future__ import annotations

from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.cplugs.huddle import item_owner, service
from src.cplugs.huddle.roles import ask, lost, route, tags
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]
_CATEGORY = {route.GONE: ask.SESSION_GONE, route.WAKE_FAILED: ask.WAKE_FAILED}
OWNER_CATEGORY = {route.GONE: ask.OWNER_GONE, route.WAKE_FAILED: ask.OWNER_WAKE_FAILED}
_CONTEXT = {ask.SESSION_GONE: "the agent tagged on this task is gone", ask.WAKE_FAILED: "the agent tagged on this task would not wake",
            ask.OWNER_GONE: "the session working on this task is gone", ask.OWNER_WAKE_FAILED: "the session working on this task would not wake"}


def candidate_of(info: Any, key: str) -> Dict[str, Any]:
    return {"id": info.session.id, "key": key, "label": info.label or info.tmux_session or info.session.id,
            "tmux_session": info.tmux_session, "project": info.project_name, "activity_status": info.activity_status,
            "elsewhere": False, "last_activity": None}


def _untold_tags(store: Any, list_key: str) -> Dict[str, List[int]]:
    with closing(store._read_connection()) as conn:
        found = item_owner.untold_rows(conn, list_key)
    out: Dict[str, List[int]] = {}
    for item_id, tag, _owner in found:
        if tag:
            out.setdefault(tag, []).append(item_id)
    return out


def _untold_owners(store: Any, list_key: str) -> Dict[str, List[int]]:
    with closing(store._read_connection()) as conn:
        found = item_owner.untold_rows(conn, list_key)
    out: Dict[str, List[int]] = {}
    for item_id, tag, owner in found:
        if owner and not tag:
            out.setdefault(owner, []).append(item_id)
    return out


def _ask_for_gone(store: Any, item_ids: List[int], category: str) -> List[int]:
    raised: List[int] = []
    for item_id in item_ids:
        with closing(store._read_connection()) as conn:
            if ask.has_open(conn, item_id, category):
                continue
        ask.carnivore_ask(store, item_id, category=category, context=_CONTEXT[category], options=ask.STALL_OPTIONS)
        raised.append(item_id)
    return raised


async def _lead_row(ctx: CplugContext, run: Runner, list_key: str, have: set) -> List[Dict[str, Any]]:
    holder = await run(lambda: RoleStore(service.store(ctx)).seat(list_key).lead_key) if list_key.isdigit() else ""
    if not holder or holder in have:
        return []
    found = await route.resolve(ctx, holder)
    return [candidate_of(found.info, holder)] if found.ready else []


async def settle_tag(ctx: CplugContext, run: Runner, list_key: str, tag: str, item_ids: List[int], have: set) -> List[Dict[str, Any]]:
    found = await route.resolve(ctx, tag)
    if found.ready:
        return [candidate_of(found.info, tag)]
    return await hand_off(ctx, run, list_key, tag, item_ids, found.outcome, have)


async def hand_off(ctx: CplugContext, run: Runner, list_key: str, lost_key: str, item_ids: List[int], outcome: str, have: set,
                   *, owner: bool = False) -> List[Dict[str, Any]]:
    store = service.store(ctx)
    kind = "owner" if owner else "tag"
    holder = await run(lambda: RoleStore(store).seat(list_key).lead_key) if list_key.isdigit() else ""
    if holder and holder != lost_key:
        moved = await run(lambda: [i for i in item_ids if tags.take_over(store, i, holder, lost=lost_key if owner else "")])
        logger.info("task_manager_lost_to_lead", kind=kind, list=list_key, items=moved, reason=outcome)
        return await _lead_row(ctx, run, list_key, have)
    category = (OWNER_CATEGORY if owner else _CATEGORY)[outcome]
    raised = await run(lambda: _ask_for_gone(store, item_ids, category))
    logger.info("task_manager_lost_asked", kind=kind, list=list_key, items=raised, reason=outcome)
    return []


async def settle_owner(ctx: CplugContext, run: Runner, list_key: str, owner: str, item_ids: List[int], have: set) -> List[Dict[str, Any]]:
    outcome = await lost.lost_outcome(ctx, owner, wake=False)
    return await hand_off(ctx, run, list_key, owner, item_ids, outcome, have, owner=True) if outcome else []


async def extra_rows(ctx: CplugContext, run: Runner, list_key: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tagged = await run(lambda: _untold_tags(service.store(ctx), list_key))
    have = {r["key"] for r in rows}
    extra: List[Dict[str, Any]] = []
    for tag, item_ids in tagged.items():
        if tag in have:
            continue
        extra.extend(await settle_tag(ctx, run, list_key, tag, item_ids, have | {r["key"] for r in extra}))
    owned = await run(lambda: _untold_owners(service.store(ctx), list_key))
    for owner, item_ids in owned.items():
        if owner not in have | {r["key"] for r in extra}:
            extra.extend(await settle_owner(ctx, run, list_key, owner, item_ids, have | {r["key"] for r in extra}))
    return extra


async def item_target(ctx: CplugContext, run: Runner, list_key: str, item_id: int, rows: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    store = service.store(ctx)
    tag = (await run(lambda: store.item(item_id)))[item_owner.TAG_COLUMN]
    if not tag:
        return None, []
    have = {r["key"] for r in rows}
    extra = [] if tag in have else await settle_tag(ctx, run, list_key, tag, [item_id], have)
    now = await run(lambda: store.item(item_id))
    key = now[item_owner.TAG_COLUMN] or now[item_owner.COLUMN]
    row = next((r for r in rows + extra if key and r["key"] == key), None)
    return (row["id"] if row else None), extra
