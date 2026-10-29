
from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import time
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import blockers, kinds, lineage, rules, service, wait_checks, wait_copy, waits
from src.cplugs.huddle.roles import ask, unstick
from src.cplugs.huddle.rules import TaskManagerError, TaskManagerStale
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

PASS_LIMIT, CONCURRENCY = 20, 4
CHECK_TIMEOUT_S = 15.0
RUN_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError, subprocess.SubprocessError, HTTPException)
EXPIRED_DETAIL, CLEARED_DETAIL, FAILED_DETAIL = "wait_expired", "wait_cleared", "wait_failed"
CHILDREN_DONE_DETAIL = "children_done"
CHILDREN_DONE_WHAT = "its forked tasks are done"

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


def hand_back(store: Any, item_id: int, text: str, detail: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
    store.update(item_id, actor=rules.JOE, expected_revision=expected_revision, state=rules.OPEN, decided=lineage.Decided(lineage.CARNIVORE, detail))
    return store.post(item_id, text, actor=rules.CLAUDE, kind=kinds.INFO, author_key=rules.CARNIVORE_KEY)["item"]


async def _after_hold(ctx: CplugContext, cleared: Mapping[str, Any], text: str, detail: str, told_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if cleared["state"] != rules.WAITING:
        return None
    store = service.store(ctx)
    try:
        item = await _run(lambda: hand_back(store, cleared["item_id"], text, detail, cleared["revision"]))
    except TaskManagerStale:
        logger.info("task_manager_hold_parent_moved", item=cleared["item_id"])
        return None
    if told_key is not None:
        await send_parker(ctx, {"set_by": told_key}, item["list"], cleared["item_id"])
    return item


async def finish_hold(ctx: CplugContext, item_id: int, by: str, text: str, detail: str, *, tell: bool) -> Optional[Dict[str, Any]]:
    store = service.store(ctx)
    cleared = await _run(lambda: blockers.BlockerStore(store).clear_hold(item_id, by))
    if cleared is None:
        return None
    logger.info("task_manager_hold_cleared", item=item_id, by_owner=by == rules.OWNER_KEY)
    item = await _after_hold(ctx, cleared, text, detail, "" if tell else None)
    return item if item is not None else await _run(lambda: store.item(item_id))


async def send_parker(ctx: CplugContext, wait: Mapping[str, Any], list_key: str, item_id: int) -> None:
    store = service.store(ctx)
    try:
        key = await _run(lambda: unstick.tag_key(store, item_id)) or wait.get("set_by") or await _run(lambda: unstick.owning_key(store, item_id))
        told = await unstick.send_session(ctx, _run, key, list_key)
        logger.info("task_manager_wait_told", item=item_id, list=list_key, status=told.get("status"))
    except RUN_ERRORS as exc:
        logger.warning("task_manager_wait_tell_failed", item=item_id, error_type=type(exc).__name__, error=str(exc)[:200])


async def finish(ctx: CplugContext, wait: Mapping[str, Any], status: str, text: str, detail: str) -> Optional[Dict[str, Any]]:
    store = service.store(ctx)
    if not await _run(lambda: waits.WaitStore(store).claim_end(wait["id"], status, text)):
        return None
    item = await _run(lambda: hand_back(store, wait["item_id"], text, detail))
    logger.info("task_manager_wait_ended", item=wait["item_id"], wait=wait["id"], status=status)
    await send_parker(ctx, wait, item["list"], wait["item_id"])
    return item


class WaitRunner:

    def __init__(self, ctx: CplugContext, clock: Callable[[], float] = time.time) -> None:
        self._ctx = ctx
        self._clock = clock

    def _store(self) -> Any:
        return service.store(self._ctx)

    def next_due(self, include_checks: bool = True) -> Optional[float]:
        return waits.WaitStore(self._store()).next_due(include_checks)

    async def expire_due(self) -> int:
        store = self._store()
        now = self._clock()
        due = await _run(lambda: waits.WaitStore(store).due_expiries(now))
        acted = 0
        for wait in due:
            if wait["status"] == waits.ESCALATED:
                acted += await self._backstop(wait, now)
                continue
            taken = await _run(lambda w=wait: waits.WaitStore(store).claim_expiry(w, now))
            if not taken:
                continue
            acted += 1
            try:
                if taken == waits.EXPIRED:
                    await self._first_expiry(wait)
                else:
                    await self._escalate(wait)
            except TaskManagerError as exc:
                logger.warning("task_manager_wait_expiry_failed", item=wait["item_id"], wait=wait["id"], error=str(exc)[:200])
        return acted

    async def _backstop(self, wait: Mapping[str, Any], now: float) -> int:
        store = self._store()
        if not await _run(lambda: waits.WaitStore(store).claim_backstop(wait, now)):
            return 0
        if not await _run(lambda: waits.WaitStore(store).has_open_question(wait["item_id"])):
            try:
                await self._escalate(wait)
            except TaskManagerError as exc:
                logger.warning("task_manager_wait_reask_failed", item=wait["item_id"], wait=wait["id"], error=str(exc)[:200])
        return 1

    async def _first_expiry(self, wait: Mapping[str, Any]) -> None:
        store = self._store()
        item = await _run(lambda: hand_back(store, wait["item_id"], wait_copy.challenge(wait["waiting_on"], wait["expect_by"]), EXPIRED_DETAIL))
        logger.info("task_manager_wait_expired", item=wait["item_id"], wait=wait["id"], extended=bool(wait["extended"]))
        await send_parker(self._ctx, wait, item["list"], wait["item_id"])

    async def _escalate(self, wait: Mapping[str, Any]) -> None:
        store = self._store()
        await _run(lambda: ask.carnivore_ask(store, wait["item_id"], category=ask.WAIT_STUCK, context=wait_copy.escalation(wait["waiting_on"], wait["expect_by"]),
                                             options=ask.WAIT_OPTIONS, labels=ask.WAIT_LABELS))
        logger.info("task_manager_wait_escalated", item=wait["item_id"], wait=wait["id"])

    def _hosts(self) -> List[str]:
        return [h.strip() for h in str(self._ctx.settings_now().get("waitCheckHosts", "")).split(",") if h.strip()]

    async def run_checks(self) -> int:
        store = self._store()
        claimed = await _run(lambda: waits.WaitStore(store).claim_due_checks(self._clock(), PASS_LIMIT))
        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(wait: Dict[str, Any]) -> None:
            async with gate:
                await self._run_one(wait)

        await asyncio.gather(*(one(w) for w in claimed))
        return len(claimed)

    async def _run_one(self, wait: Dict[str, Any]) -> None:
        store = self._store()
        try:
            check = wait_checks.parse(json.loads(wait["check_json"]))
            verdict = await asyncio.wait_for(wait_checks.run(check, ops=self._ctx.sessions, extra_hosts=self._hosts()), CHECK_TIMEOUT_S)
        except asyncio.TimeoutError:
            verdict = wait_checks.Verdict(wait_checks.UNKNOWN, f"check timed out after {CHECK_TIMEOUT_S:.0f}s")
        except (TaskManagerError, ValueError) as exc:
            verdict = wait_checks.Verdict(wait_checks.UNKNOWN, f"check unreadable: {type(exc).__name__}")
        except RUN_ERRORS as exc:
            verdict = wait_checks.Verdict(wait_checks.UNKNOWN, f"check failed to run: {type(exc).__name__}")
        logger.info("task_manager_wait_check_run", item=wait["item_id"], wait=wait["id"], check=wait["check_kind"], runs=wait["check_runs"], result=verdict.status)
        await _run(lambda: waits.WaitStore(store).record_result(wait["id"], verdict.status))
        if verdict.status == wait_checks.PASS:
            await self._clear(wait, verdict.what)

    async def _clear(self, wait: Mapping[str, Any], what: str) -> None:
        try:
            await finish(self._ctx, wait, waits.CLEARED, wait_copy.cleared(what), CLEARED_DETAIL)
        except TaskManagerError as exc:
            logger.warning("task_manager_wait_clear_failed", item=wait["item_id"], wait=wait["id"], error=str(exc)[:200])

    async def run_checks_safe(self) -> int:
        try:
            return await self.run_checks()
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            logger.error("task_manager_wait_checks_failed", error_type=type(exc).__name__, error=str(exc)[:200])
            return 0

    async def release_holds(self) -> int:
        store = self._store()
        released = 0
        for hold in await _run(lambda: blockers.BlockerStore(store).releasable()):
            cleared = await _run(lambda h=hold: blockers.BlockerStore(store).claim_release(h["id"]))
            if cleared is None:
                continue
            released += 1
            logger.info("task_manager_hold_released", item=hold["item_id"], blocker=hold["id"], state=cleared["state"])
            try:
                await _after_hold(self._ctx, cleared, wait_copy.cleared(CHILDREN_DONE_WHAT), CHILDREN_DONE_DETAIL, hold["created_by"])
            except TaskManagerError as exc:
                logger.warning("task_manager_hold_release_failed", item=hold["item_id"], error=str(exc)[:200])
        return released

    async def run_events(self) -> int:
        store = self._store()
        cleared = await self.release_holds()
        for wait in await _run(lambda: waits.WaitStore(store).event_watchers()):
            try:
                check = wait_checks.parse(json.loads(wait["check_json"]))
            except (TaskManagerError, ValueError):
                continue
            state = await _run(lambda c=check: waits.WaitStore(store).item_state(c.item))
            if state == check.state:
                logger.info("task_manager_wait_check_run", item=wait["item_id"], wait=wait["id"], check=wait["check_kind"], runs=wait["check_runs"], result=wait_checks.PASS)
                await self._clear(wait, wait_checks.describe(check))
                cleared += 1
        return cleared

    async def run_pass(self, *, events: bool = True, checks: bool = True) -> int:
        return await self.expire_due() + (await self.run_checks() if checks else 0) + (await self.run_events() if events else 0)
