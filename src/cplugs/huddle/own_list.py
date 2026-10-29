"""Own-list guard: an agent writes to ITS project's Task Manager list; another project's list needs ``cross_project`` (#1510).

**ONE GUARD, EVERY WRITE.** :func:`guard` wraps the inner handler of each Task Manager write tool (add, update, reply, ask, move,
mark_answered, delete, fork, progress, group create and update, focus), and the batch ops run those same handlers, so a batch
op is judged on its own and a refused op fails alone (``batch.py`` reports per op). It compares the calling session's project
(the one ``list: mine`` resolves to) with the project of every list the call touches: the ``list`` argument, and the list of
each ``item`` / ``items`` / group the call names. Differing and no ``cross_project: true``: a :class:`ToolError` warning.

**Not guarded:** reads, an external token or an unbound caller (no session), and a list that is not a project's (``all``,
``agent:<id>``). **Unknown never blocks:** a session with no project is allowed and the answer carries
``warning: "could not tell your project"``.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.cplugs.huddle import actor_log, flags, service
from src.cplugs.huddle.roles import dnd_gate
from src.cplugs.huddle.rules import ALL_LIST, TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

logger = structlog.get_logger()

FIELD = "cross_project"
WARNING_FIELD = "warning"
UNKNOWN_WARNING = "could not tell your project"
ANSWER_FIELDS = (FIELD, WARNING_FIELD)
SCHEMA = {FIELD: {"type": "boolean", "description": "Write to ANOTHER project's list (default refused); the owner sees it as cross-project."}}

Target = Tuple[str, str]


@dataclass(frozen=True)
class Verdict:

    extra: Dict[str, Any]
    crossing: Optional[Tuple[str, str]] = None
    # own project
    source: Optional[Tuple[str, str]] = None


def refusal(subject: str, mine: str, other: str) -> str:
    return (f"{subject} is on the {other} list, not your project {mine}. Write to your own list (list: mine). "
            f"If this really belongs on {other}'s list, repeat the call with cross_project: true.")


async def own_project(ctx: CplugContext, caller: AgentCaller) -> Optional[str]:
    """The calling session's project id as a list key (what ``list: mine`` resolves to), or None when it has none.

    Inputs: ctx; caller. Output: str | None. An external token has no session: None.
    """
    if caller.external or not caller.current_session_id:
        return None
    own = next((i for i in await ctx.sessions.list() if i.session.id == caller.current_session_id), None)
    project = getattr(own, "project_id", None) if own else None
    return None if project is None else str(project)


def _is_project_key(key: str) -> bool:
    return key not in (ALL_LIST, "mine") and not key.startswith("agent:")


async def targets(ctx: CplugContext, args: dict, *, group_is_id: bool = False) -> List[Target]:
    found: List[Target] = []
    value = args.get("list", args.get("list_id"))
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, str) and _is_project_key(value):
        found.append(("this write", value))
    item_ids = [args["item"]] if "item" in args else list(args.get("items") or []) if isinstance(args.get("items"), list) else []
    if isinstance(args.get("open"), int):
        item_ids.append(args["open"])
    store = service.store(ctx)
    for item_id in item_ids:
        try:
            found.append((f"item {item_id}", (await asyncio.to_thread(store.item, item_id))["list"]))
        except (TaskManagerError, TypeError):
            continue
    if group_is_id and isinstance(args.get("group"), int):
        try:
            found.append((f"group {args['group']}", await asyncio.to_thread(service.groups(ctx).list_of, args["group"])))
        except TaskManagerError:
            pass
    return [t for t in found if _is_project_key(t[1])]


async def judge(ctx: CplugContext, caller: AgentCaller, found: List[Target], cross: bool) -> Verdict:
    if caller.external or not caller.current_session_id or not found:
        return Verdict({})
    mine = await own_project(ctx, caller)
    if mine is None:
        return Verdict({WARNING_FIELD: UNKNOWN_WARNING})
    differing = [t for t in found if t[1] != mine]
    if not differing:
        return Verdict({})
    names = await asyncio.to_thread(service.project_names, ctx)
    subject, other_key = differing[0]
    mine_name, other_name = names.get(mine, mine), names.get(other_key, other_key)
    if not cross:
        logger.info("task_manager_cross_project_refused", session=caller.current_session_id, mine=mine, other=other_key)
        raise ToolError(refusal(subject, mine_name, other_name))
    logger.info("task_manager_cross_project_allowed", session=caller.current_session_id, mine=mine, other=other_key)
    return Verdict({FIELD: {"from": mine_name, "to": other_name}}, (mine_name, other_name), (mine, mine_name))


_CROSSING: "contextvars.ContextVar[bool]" = contextvars.ContextVar("task_manager_cross_project", default=False)


def crossing() -> bool:
    return _CROSSING.get()


def _item_ids(args: dict, result: Any, creates: bool) -> List[int]:
    ids: List[int] = [args["item"]] if isinstance(args.get("item"), int) else []
    if isinstance(result, dict):
        if creates and isinstance(result.get("id"), int):
            ids.append(result["id"])
        if isinstance(result.get("fork"), dict) and isinstance(result["fork"].get("id"), int):
            ids.append(result["fork"]["id"])
    return list(dict.fromkeys(ids))


def _tag_source(store: Any, item_id: int, source: Optional[Tuple[str, str]]) -> None:
    if source is None:
        return
    if store.item(item_id)["list"] != source[0]:
        store.stamp_from_project(item_id, source[0], source[1])


def guard(fn: Callable[[CplugContext, AgentCaller, dict], Awaitable[Any]], *, creates: bool = False, records: bool = True,
          group_is_id: bool = False, dnd: bool = False) -> Callable[[CplugContext, AgentCaller, dict], Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(ctx: CplugContext, caller: AgentCaller, args: dict) -> Any:
        """Judge, run, annotate. Raises ToolError for a refused crossing."""
        clean = {k: v for k, v in args.items() if k != FIELD and not (dnd and k == dnd_gate.FIELD)}
        verdict = await judge(ctx, caller, await targets(ctx, clean, group_is_id=group_is_id), flags.flag(args, FIELD, False))
        if dnd:
            await dnd_gate.check(ctx, caller, clean, args.get(dnd_gate.FIELD))
        token = actor_log.set_acting_key(await actor_log.caller_key(ctx, caller) or "")
        crossed = _CROSSING.set(bool(verdict.crossing))
        try:
            result = await fn(ctx, caller, clean)
        finally:
            _CROSSING.reset(crossed)
            actor_log.reset_acting_key(token)
        touched = _item_ids(clean, result, creates)
        await actor_log.record(ctx, caller, service.store(ctx), fn.__name__.lstrip("_"), touched, cross=bool(verdict.crossing),
                               own_list_key=verdict.source[0] if verdict.source else None)
        if verdict.crossing and records:
            note = f"written from another project: {verdict.crossing[0]}"
            store = service.store(ctx)
            for item_id in _item_ids(clean, result, creates):
                await asyncio.to_thread(store.note_system, item_id, note)
                await asyncio.to_thread(_tag_source, store, item_id, verdict.source)
        return {**result, **verdict.extra} if verdict.extra and isinstance(result, dict) else result

    return wrapper


def guarded(**options: bool) -> Callable[[Callable[[CplugContext, AgentCaller, dict], Awaitable[Any]]], Callable[[CplugContext, AgentCaller, dict], Awaitable[Any]]]:
    return lambda fn: guard(fn, **options)
