
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

import structlog

from src.core import resource_push
from src.core.argent import cost_split, budget, fallback_spend, notices, row_state, timeline, work_items
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unauthorized, error_code
from src.core.argent.fallback_spend import CursorStore
from src.core.argent.runtime import get_runtime
from src.core.budget_hold.store import STORE, HoldStore
from src.core.resource_push import topics
from src.core.session_token_usage.per_request import MAX_LIMIT, read_session_requests
from src.core.session_token_usage.reader import SessionSubject
from src.core.subagents.session import read_session_subagents
from src.models.per_request_usage import RequestUsageRow

logger = structlog.get_logger()

FAST_SECONDS, SLOW_SECONDS = 15.0, 60.0
ACTIVE_SUBAGENT_SECONDS = 3600.0
MAX_ITEMS = 200
LOCAL_PRICING_SHARE = 0.5
UNTETHERED_STATES = ("", "not tethered")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class LiveSession:

    row_id: str
    tmux: str
    working: bool
    subject: SessionSubject


class _State:

    task: Optional["asyncio.Task[None]"] = None
    wake: Optional[asyncio.Event] = None
    transport: Any = None
    snapshot: Dict[str, Any] = {"state": "pending", "as_of": None, "sessions": {}, "items": {}}


_state = _State()


async def live_sessions() -> List[LiveSession]:
    manager = fallback_spend.session_manager()
    if manager is None:
        return []
    found: List[LiveSession] = []
    for info in await manager.list_session_infos():
        session = info.session
        if session is None or str(session.id).startswith("remote:") or info.session_row_id is None or not info.tmux_session:
            continue
        uuid = await asyncio.to_thread(manager.claude_uuid_for_tmux_name, info.tmux_session)
        found.append(LiveSession(str(info.session_row_id), info.tmux_session, info.activity_status in ("working", "working_subagent"),
                                 SessionSubject(agent_family=info.agent_family, conversation_uuid=uuid, working_dir=session.working_dir)))
    return found


def active_items(declared: List[Dict[str, str]], now: float) -> Set[str]:
    out: Set[str] = set()
    for row in declared:
        if row["sub_agent_id"] == "":
            out.add(row["work_item_id"])
            continue
        try:
            at = datetime.strptime(row["ts"], _TS_FORMAT).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if now - at <= ACTIVE_SUBAGENT_SECONDS:
            out.add(row["work_item_id"])
    return out


def _local_requests(subject: SessionSubject, since: Optional[str]) -> Optional[List[RequestUsageRow]]:
    usage = read_session_requests(subject, since=since, limit=MAX_LIMIT)
    if usage.state == "unchecked":
        return None
    return list(usage.requests) if usage.state == "ok" else []


async def local_extra(tenant: str, wanted: Set[str], sessions: Mapping[str, Tuple[LiveSession, List[Dict[str, str]]]], price_table: Mapping[str, Any],
                      cursors: CursorStore, read: Callable[[SessionSubject, Optional[str]], Optional[List[RequestUsageRow]]]) -> Dict[str, Optional[int]]:
    extra: Dict[str, Optional[int]] = {item: 0 for item in wanted}
    for row_id, (session, declared) in sessions.items():
        if not ({d["work_item_id"] for d in declared} & wanted):
            continue
        tether = await asyncio.to_thread(row_state.lookup, tenant, session.tmux)
        if tether["state"] not in UNTETHERED_STATES:
            continue
        since = await asyncio.to_thread(cursors.get, tenant, row_id)
        rows = await asyncio.to_thread(read, session.subject, since)
        if rows is None:
            for item in {d["work_item_id"] for d in declared} & wanted:
                extra[item] = None
            continue
        for row in rows:
            item = timeline.effective(declared, row.agent_id)
            if item not in wanted:
                continue
            price = budget.price_micros(price_table, row.model or "", row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_creation_tokens)
            extra[item] = None if price is None or extra[item] is None else (extra[item] or 0) + price
    return extra


def _by_id(body: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    items = body.get("items")
    return {r["id"]: dict(r) for r in items if isinstance(r, dict) and isinstance(r.get("id"), str)} if isinstance(items, list) else {}


async def _item_name(tenant: str, item_id: str) -> str:
    row = await asyncio.to_thread(work_items.resolve, tenant, item_id)
    return str(row.get("title") or item_id) if row else item_id


def _viewer_name() -> str:
    row = get_runtime().store.get_login()
    return str(row.get("display_name") or "") if row else ""


async def _notify(tenant: str, item_id: str, level: Optional[str], standing: budget.Standing, extra: Optional[int]) -> None:
    if level is None:
        return
    moved = await asyncio.to_thread(budget.move_level, tenant, item_id, level)
    if moved == "same":
        return
    name = await _item_name(tenant, item_id)
    spent = budget.money(None if standing.spent_micros is None else standing.spent_micros + (extra or 0))
    cap = budget.money(standing.cap_micros)
    if moved == "rose" and level == budget.WARN:
        notices.budget_warn(item_id, name, spent, cap)
    elif moved == "rose" and level == budget.HOLD:
        notices.budget_hold(item_id, name, standing.owner_name or standing.governing_item_title, spent, cap)


def _client(server_url: str, ca_path: str, token: Optional[str]) -> ArgentClient:
    store = get_runtime().store

    def expired() -> None:
        store.mark_login_expired()
        resource_push.notify(topics.ARGENT_STATUS)

    return ArgentClient(server_url, lambda: token, ca_path=ca_path, transport=_state.transport, on_unauthorized=expired)


async def _get(client: ArgentClient, path: str, params: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return dict((await client.get(path, params=params)).body)
    except Unauthorized:
        raise
    except ArgentError as exc:
        logger.info("argent_cost_call_failed", path=path, status=exc.status, code=exc.code)
        return None


_NO_BUDGET: Dict[str, Any] = {"state": "ok", "_no_budget": True}


async def _status(client: ArgentClient, item: str) -> Optional[Dict[str, Any]]:
    try:
        return dict((await client.get("/v1/my/budgets/status", params={"work_item_id": item})).body)
    except NotFound as exc:
        if error_code(exc.body) == "not_found":
            return dict(_NO_BUDGET)
        logger.info("argent_cost_call_failed", path="/v1/my/budgets/status", status=exc.status, code=exc.code)
        return None
    except Unauthorized:
        raise
    except ArgentError as exc:
        logger.info("argent_cost_call_failed", path="/v1/my/budgets/status", status=exc.status, code=exc.code)
        return None


async def poll_once(client: ArgentClient, tenant: str, sessions: List[LiveSession], *, holds: HoldStore = STORE, cursors: Optional[CursorStore] = None,
                    read: Callable[[SessionSubject, Optional[str]], Optional[List[RequestUsageRow]]] = _local_requests,
                    clock: Callable[[], float] = time.time) -> float:
    now = clock()
    cursors = cursors or CursorStore()
    watched: Dict[str, Tuple[LiveSession, List[Dict[str, str]]]] = {}
    refs: Dict[str, str] = {}
    for session in sessions:
        ref = (await asyncio.to_thread(row_state.lookup, tenant, session.tmux))["ref"]
        declared = await asyncio.to_thread(timeline.current, tenant, ref)
        if declared:
            watched[session.row_id], refs[session.row_id] = (session, declared), ref
    members: Dict[str, Set[str]] = {}
    for row_id, (_session, declared) in watched.items():
        for item in active_items(declared, now):
            members.setdefault(item, set()).add(row_id)
    held_before = {h["item_id"]: h for h in holds.snapshot()}
    items = sorted(set(members) | set(held_before))[:MAX_ITEMS]
    cost_sessions = await _get(client, "/v1/my/cost", {"by": "session"})
    cost_items = await _get(client, "/v1/my/cost", {"by": "work_item"})
    agents = await _agent_rows(client, tenant, watched, refs, now)
    prices = (cost_sessions or cost_items or {}).get("price_per_mtok")
    standings: Dict[str, Optional[budget.Standing]] = {}
    no_budget: Set[str] = set()
    viewer = await asyncio.to_thread(_viewer_name)
    for item in items:
        body = await _status(client, item)
        if body is not None and body.pop("_no_budget", False):
            no_budget.add(item)
        standings[item] = budget.parse_standing(body) if body is not None else None
    wanted = {i for i, st in standings.items() if st and st.known and st.state != "paused" and st.cap_micros and st.spent_micros is not None
              and st.spent_micros >= st.cap_micros * LOCAL_PRICING_SHARE}
    extras = await local_extra(tenant, wanted, watched, prices if isinstance(prices, dict) else {}, cursors, read) if wanted else {}
    entries: Dict[str, Dict[str, Any]] = {}
    for item in items:
        standing = standings[item]
        if standing is None:
            entries[item] = {"name": await _item_name(tenant, item), "budget": None, "held": item in held_before}
            continue
        if item in no_budget:
            if item in held_before:
                await asyncio.to_thread(holds.clear_hold, item)
                notices.service.resolve(notices.BUDGET_HOLD_PREFIX + item)
            await asyncio.to_thread(budget.move_level, tenant, item, budget.OK)
            entries[item] = {"name": await _item_name(tenant, item), "budget": None, "held": False}
            continue
        extra = extras.get(item, 0)
        decision = budget.decide(standing, extra)
        await _apply(holds, tenant, item, decision, held_before.get(item), members.get(item, set()))
        await _notify(tenant, item, decision.level, standing, extra)
        entries[item] = {"name": await _item_name(tenant, item), "held": bool(decision.held) if decision.held is not None else item in held_before,
                         "budget": {"state": standing.state, "spent_micros": standing.spent_micros, "cap_micros": standing.cap_micros,
                                    "owner_name": standing.owner_name, "resets_at": standing.resets_at,
                                    "viewer_is_owner": budget.viewer_is_owner(standing.owner_name, viewer),
                                    "governing_item_id": standing.governing_item_id, "governing_item_title": standing.governing_item_title,
                                    "effective_spent_micros": None if standing.spent_micros is None or extra is None else standing.spent_micros + extra}}
    _publish(watched, refs, entries, cost_sessions, cost_items, agents)
    near = any(e["budget"] and budget.near_cap(budget.parse_standing(e["budget"])) for e in entries.values())
    working = any(session.working for row_id, (session, _d) in watched.items() if any(row_id in members.get(i, ()) for i in items))
    return FAST_SECONDS if near or working else SLOW_SECONDS


async def _agent_rows(client: ArgentClient, tenant: str, watched: Mapping[str, Tuple[LiveSession, List[Dict[str, str]]]], refs: Mapping[str, str],
                      now: float) -> Dict[str, Optional[List[Dict[str, Any]]]]:
    out: Dict[str, Optional[List[Dict[str, Any]]]] = {}
    for row_id in sorted(cost_split.watched_rows(now) & set(watched)):
        session, declared = watched[row_id]
        body = await _get(client, "/v1/my/cost", {"by": "sub_agent", "id": refs[row_id]})
        if body is None:
            out[row_id] = None
            continue
        listed = await asyncio.to_thread(read_session_subagents, session.subject)
        names = {s.id: s.description for s in listed.subagents if s.description}
        out[row_id] = cost_split.rows(body, declared, names)
    return out


async def _apply(holds: HoldStore, tenant: str, item: str, decision: budget.Decision, before: Optional[Dict[str, Any]], members: Set[str]) -> None:
    if decision.held is True:
        keys = sorted(members)
        if keys and (before is None or sorted(before["session_keys"]) != keys):
            name = await _item_name(tenant, item)
            await asyncio.to_thread(holds.set_hold, item, name, keys, tenant)
    elif decision.held is False and before is not None:
        await asyncio.to_thread(holds.clear_hold, item)
        notices.hold_lifted(item, await _item_name(tenant, item))


def _publish(watched: Mapping[str, Tuple[LiveSession, List[Dict[str, str]]]], refs: Mapping[str, str], entries: Dict[str, Dict[str, Any]],
             cost_sessions: Optional[Dict[str, Any]], cost_items: Optional[Dict[str, Any]], agents: Mapping[str, Optional[List[Dict[str, Any]]]]) -> None:
    previous = _state.snapshot
    by_session = _by_id(cost_sessions) if cost_sessions is not None else None
    by_item = _by_id(cost_items) if cost_items is not None else None
    session_rows: Dict[str, Any] = {}
    for row_id, (_session, declared) in watched.items():
        ref = refs[row_id]
        old = previous["sessions"].get(row_id, {}).get("cost")
        session_rows[row_id] = {"ref": ref, "items": sorted({d["work_item_id"] for d in declared}),
                                "cost": (by_session.get(ref) if by_session is not None else old)}
        if row_id in agents:
            split = agents[row_id]
            session_rows[row_id]["agents"] = split if split is not None else previous["sessions"].get(row_id, {}).get("agents")
    for item, entry in entries.items():
        old = previous["items"].get(item, {}).get("cost")
        entry["cost"] = by_item.get(item) if by_item is not None else old
    as_of = (cost_sessions or cost_items or {}).get("as_of") or previous.get("as_of")
    fresh = {"state": "ok", "as_of": as_of, "sessions": session_rows, "items": entries}
    changed = fresh != {k: previous.get(k) for k in fresh}
    _state.snapshot = fresh
    if changed:
        resource_push.notify(topics.ARGENT_COST)


def snapshot() -> Dict[str, Any]:
    return _state.snapshot


async def pass_once() -> float:
    cfg = await asyncio.to_thread(settings_module.read)
    if not cfg.enabled:
        return SLOW_SECONDS
    try:
        client, tenant = await work_items.client_for_call()
    except Unauthorized:
        return SLOW_SECONDS
    runtime = get_runtime()
    if await asyncio.to_thread(runtime.store.login_expired):
        return SLOW_SECONDS
    try:
        return await poll_once(client, tenant, await live_sessions())
    except Unauthorized:
        return SLOW_SECONDS
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_cost_pass_failed", error_type=type(exc).__name__)
        return SLOW_SECONDS


async def _run() -> None:
    assert _state.wake is not None
    while True:
        try:
            wait = await pass_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("argent_cost_pass_crashed", error_type=type(exc).__name__)
            wait = SLOW_SECONDS
        try:
            await asyncio.wait_for(_state.wake.wait(), wait)
        except asyncio.TimeoutError:
            pass
        _state.wake.clear()


def start() -> None:
    if is_running():
        return
    _state.wake = asyncio.Event()
    _state.task = asyncio.get_running_loop().create_task(_run())


async def stop() -> None:
    task, _state.task = _state.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _state.snapshot = {"state": "pending", "as_of": None, "sessions": {}, "items": {}}
    cost_split.clear()


def is_running() -> bool:
    return _state.task is not None and not _state.task.done()


def poke() -> None:
    if _state.wake is not None:
        _state.wake.set()
