
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import fire, held, lifecycle, progress, sending, service
from src.cplugs.huddle.nudge import lines, pick, planning, settings
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.huddle.roles import lost as lost_roles, tag_send
from src.cplugs.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

REASON = "nudge"


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


def _store(ctx: CplugContext) -> NudgeStore:
    return NudgeStore(service.store(ctx))


async def _paste(ctx: CplugContext, key: str, name: Optional[str], rows: List[dict], target: str, lead: str) -> Optional[str]:
    try:
        await sending.paste_send(ctx, _run, key, name, rows, target, REASON, aggregate=False, lead=lead)
    except HTTPException as exc:
        return held.refusal_code(exc)
    return None


async def _settle_lost(ctx: CplugContext, key: str, by_owner: Mapping[str, Sequence[int]]) -> int:
    handled = 0
    for holder, item_ids in by_owner.items():
        outcome = await lost_roles.lost_outcome(ctx, holder, wake=True)
        if outcome:
            await tag_send.hand_off(ctx, _run, key, holder, list(item_ids), outcome, set(), owner=True)
            handled += len(item_ids)
    return handled


def _candidates(ctx: CplugContext, key: str, now: float) -> List[planning.Candidate]:
    ages = {k: [line["age_s"] for line in v] for k, v in progress.snapshot(ctx, lambda: now).items()}
    found = _store(ctx).candidates(key)
    owners = _store(ctx).session_keys(key, [row for row, _status, _last, _basis in found])
    out = []
    for row, status, last_activity, basis in found:
        mine = ages.get(str(row["id"]), [])
        out.append(planning.Candidate(row, status, max(last_activity, now - min(mine)) if mine else last_activity, basis,
                                      session_key=owners.get(row["id"], "")))
    return out


def _with_sessions(cands: List[planning.Candidate], rows: List[dict]) -> List[planning.Candidate]:
    by_key = {r["key"]: r for r in rows}
    out = []
    for cand in cands:
        row = by_key.get(cand.session_key) if cand.session_key else None
        out.append(replace(cand, session_state=row["activity_status"], session_last=pick.last_activity_epoch(row["last_activity"])) if row else cand)
    return out


async def _own_rows(ctx: CplugContext, key: str) -> List[dict]:
    return [r for r in await service.candidate_rows(ctx, key) if not r.get("elsewhere")]


async def _wake(ctx: CplugContext, key: str) -> tuple:
    try:
        woken = await session_bring_up.wake_newest(ctx.sessions, int(key))
    except session_bring_up.BringUpFailed as exc:
        logger.info("nudge_wake_failed", list=key, error=str(exc)[:200])
        return [], None
    return (await _own_rows(ctx, key), woken) if woken is not None else ([], None)


async def _send(ctx: CplugContext, key: str, target: str, rows: List[dict], sent: List[planning.Candidate], lead: str, tries: int, now: float) -> int:
    name = await _run(lambda: service.project_names(ctx).get(key))
    refused = await _paste(ctx, key, name, rows, target, lead)
    if refused is not None:
        logger.info("nudge_not_sent", list=key, target=target, code=refused)
        return 0
    done = await _run(lambda: _store(ctx).record_nudges(key, sent, tries, now))
    logger.info("nudged", list=key, target=target, items=len(sent))
    return done


async def sweep_list(ctx: CplugContext, cfg: settings.Settings, key: str, now: float,
                     project_on: bool = True, prefs: Optional[Dict[str, bool]] = None) -> Dict[str, int]:
    result = {"nudged": 0, "stalled": 0}
    prefs = prefs or {}
    interval_s, tries = cfg.minutes * 60.0, cfg.tries
    if held.is_held(key):
        return result
    cands = await _run(lambda: _candidates(ctx, key, now))
    if not cands:
        return result
    rows, woken = await _own_rows(ctx, key), None
    if project_on and await _lost_pass(ctx, cfg, key, now, cands, rows):
        return result
    if not rows:
        first = planning.plan([c for c in cands if not c.session_key], now=now, interval_s=interval_s, tries=tries, session_state=None,
                              list_held=False, position=lifecycle.position)
        if not project_on or not first.nudge:
            return result
        rows, woken = await _wake(ctx, key)
    nudgeable = [r for r in rows if planning.effective(prefs.get(r["key"]), project_on)]
    if not nudgeable:
        return result
    cands = _with_sessions(cands, nudgeable)
    sessions = await _owned_pass(ctx, cfg, key, now, cands, nudgeable, rows)
    result["nudged"], result["stalled"] = sessions
    if not result["nudged"]:
        result["nudged"] = await _pickup(ctx, cfg, key, now, cands, nudgeable, prefs, project_on, woken)
    return result


async def _lost_pass(ctx: CplugContext, cfg: settings.Settings, key: str, now: float, cands: List[planning.Candidate], rows: List[dict]) -> int:
    lost = planning.plan_lost(cands, live_keys={r["key"] for r in rows}, now=now, interval_s=cfg.minutes * 60.0, list_held=False,
                              position=lifecycle.position)
    if not lost:
        return 0
    handled = await _settle_lost(ctx, key, lost)
    logger.info("nudge_lost_settled", list=key, owners=len(lost), items=handled)
    return handled


async def _owned_pass(ctx: CplugContext, cfg: settings.Settings, key: str, now: float,
                      cands: List[planning.Candidate], nudgeable: List[dict], rows: List[dict]) -> Tuple[int, int]:
    interval_s, nudged, raised = cfg.minutes * 60.0, 0, 0
    live = {r["key"]: r for r in nudgeable}
    for owner in sorted({c.session_key for c in cands if c.session_key} & set(live)):
        mine = [c for c in cands if c.session_key == owner]
        plan = planning.plan(mine, now=now, interval_s=interval_s, tries=cfg.tries, session_state=None, list_held=False, position=lifecycle.position)
        if plan.stall:
            label = live[owner]["label"]
            contexts = {c.id: lines.stall_line(label, now - max(c.last_activity, c.session_last or 0.0), cfg.tries) for c in plan.stall}
            raised += len(await _run(lambda: _store(ctx).raise_stall(key, plan.stall, now, contexts)))
        if plan.nudge:
            nudged += await _send(ctx, key, live[owner]["id"], rows, plan.nudge,
                                  lines.claimed_line(plan.nudge, now, cfg.texts, cfg.max_items), cfg.tries, now)
    return nudged, raised


async def _pickup(ctx: CplugContext, cfg: settings.Settings, key: str, now: float, cands: List[planning.Candidate], nudgeable: List[dict],
                  prefs: Dict[str, bool], project_on: bool, woken: Optional[str]) -> tuple:
    idle = pick.idle_rows(nudgeable, cands, prefs, project_on, woken)
    if not idle:
        return 0
    target = await _run(lambda: fire.pick_target(ctx, idle, key))
    row = next(r for r in idle if r["id"] == target)
    top = pick.next_open([c for c in cands if not c.session_key], row["activity_status"], lifecycle.position)
    if top is None:
        return 0
    interval_s = cfg.minutes * 60.0
    top = pick.with_session_quiet(top, pick.last_activity_epoch(row["last_activity"]), now, interval_s)
    plan = planning.plan([top], now=now, interval_s=interval_s, tries=cfg.tries, session_state=row["activity_status"], list_held=False,
                         position=lifecycle.position)
    if not plan.nudge:
        return 0
    line = lines.pickup_line(top, now, cfg.texts) if top.pickup else lines.unclaimed_line(top, now, cfg.texts)
    return await _send(ctx, key, target, idle, plan.nudge, line, cfg.tries, now)


async def _session_lists(ctx: CplugContext, on_keys: Set[str]) -> Set[str]:
    if not on_keys:
        return set()
    infos = await ctx.sessions.list()
    keys = await ctx.sessions.durable_keys(infos)
    return {str(i.project_id) for i in infos if service.is_agent(i) and getattr(i, "project_id", None) is not None
            and (keys.get(i.session.id) or i.session.id) in on_keys}


async def sweep(ctx: CplugContext, clock: Callable[[], float] = time.time) -> float:
    cfg = settings.read(ctx.settings_now())
    if not cfg.enabled:
        return cfg.minutes
    project_on = set(await _run(_store(ctx).nudge_lists))
    prefs = await _run(_store(ctx).session_prefs)
    try:
        lists = project_on | await _session_lists(ctx, {k for k, on in prefs.items() if on})
    except (OSError, RuntimeError, AttributeError) as exc:
        logger.warning("nudge_session_lists_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        lists = project_on
    for key in sorted(lists):
        if not key.isdigit():
            continue
        try:
            await sweep_list(ctx, cfg, key, clock(), key in project_on, prefs)
        except (OSError, RuntimeError, ValueError, LookupError, AttributeError, sqlite3.Error) as exc:
            logger.error("nudge_list_failed", list=key, error_type=type(exc).__name__, error=str(exc)[:200])
    return cfg.minutes
