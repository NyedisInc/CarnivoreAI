
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

import structlog
from fastapi import HTTPException

from src.core.automations import attachments, gates, lifecycle, run_sessions, scheduler_log, targets
from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets.recipe import tell_failure
from src.cplugs.sdk.storage import CplugSchemaError

logger = structlog.get_logger()

NOTE_BY: str = "by"

MAX_SLEEP_S = 300.0
MIN_SLEEP_S = 0.05
BOOT_WAIT_S = 60.0

BOOT_ID = uuid.uuid4().hex

MAX_RUNTIME_GRACE_S = 30.0
R_MAX_RUNTIME = "max_runtime"
SCHEDULER_FAILURES = frozenset({m.R_TARGET_MISSING, "dispatch_error", "runner_error", "report_too_large", R_MAX_RUNTIME,
                                m.R_INTERRUPTED})

PASS_ERRORS = (OSError, RuntimeError, sqlite3.Error, CplugSchemaError)


@dataclass
class Context:

    app_state: Any
    store: AutomationStore
    boot_id: str


class Scheduler:

    def __init__(self, app_state: Any, store: AutomationStore, clock: Callable[[], float] = time.time,
                 boot_id: str = BOOT_ID) -> None:
        self._app_state = app_state
        self.store = store
        self._clock = clock
        self._boot_id = boot_id
        self._wake = asyncio.Event()
        self._tasks: Set["asyncio.Task[None]"] = set()
        self._cancelling: Set[str] = set()
        store.on_change = self._nudge_threadsafe

    def _nudge_threadsafe(self) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.nudge)

    _loop: Optional[asyncio.AbstractEventLoop] = None

    def nudge(self) -> None:
        self._wake.set()

    async def _wait_booted(self) -> None:
        task = getattr(getattr(self._app_state, "session_manager", None), "_boot_readopt_task", None)
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), BOOT_WAIT_S)
        except asyncio.TimeoutError:
            logger.warning("automation_boot_wait_timed_out", seconds=BOOT_WAIT_S)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("automation_boot_readopt_failed", error_type=type(exc).__name__)

    async def pass_once(self) -> int:
        claimed = await asyncio.to_thread(self.store.claim_due, self._clock(), self._boot_id)
        try:
            await run_sessions.sweep(self._app_state, self.store, self._clock())
        except (*PASS_ERRORS, HTTPException) as exc:
            logger.error("automation_sweep_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        for run in claimed:
            try:
                await self._dispatch(run)
            except Exception as exc:
                logger.error("automation_dispatch_failed", run_id=run["run_id"], automation_id=run["automation_id"],
                             error_type=type(exc).__name__)
                await asyncio.to_thread(self.store.update_run, run["run_id"], status=m.FAILED, reason="dispatch_error",
                                        ended_at=self._clock(), error=f"{type(exc).__name__}: {exc}")
                await asyncio.to_thread(self._after_end, run["automation_id"], run["run_id"], m.FAILED, "dispatch_error")
        return len(claimed)

    async def _dispatch(self, run: Dict[str, Any], by: Optional[Dict[str, Any]] = None) -> str:
        store = self.store
        automation = await asyncio.to_thread(store.get, run["automation_id"])
        live = await asyncio.to_thread(store.live_runs)
        hint = await self._login_hint(automation["target"])
        verdict, notes = await asyncio.to_thread(gates.evaluate, automation, run, live, hint)
        if by:
            notes = {**notes, NOTE_BY: by}
        if verdict is not None and verdict.status == m.SKIPPED:
            scheduler_log.write("skipped", automation_id=automation["automation_id"], run_id=run["run_id"], reason=verdict.reason)
            skipped = await asyncio.to_thread(store.finish_skip, run["run_id"], verdict.reason)
            if by:
                await asyncio.to_thread(store.update_run, skipped, notes=notes)
            return skipped
        if verdict is not None:
            await asyncio.to_thread(store.update_run, run["run_id"], status=verdict.status, reason=verdict.reason,
                                    ended_at=self._clock(), notes=notes or None)
            await asyncio.to_thread(self._after_end, automation["automation_id"], run["run_id"], verdict.status, verdict.reason)
            return run["run_id"]
        runner = targets.RUNNERS.get(automation["target"]["kind"])
        if runner is None:
            await asyncio.to_thread(store.update_run, run["run_id"], status=m.FAILED, reason=m.R_TARGET_MISSING, ended_at=self._clock(),
                                    notes=notes or None)
            await asyncio.to_thread(self._after_end, automation["automation_id"], run["run_id"], m.FAILED, m.R_TARGET_MISSING)
            return run["run_id"]
        run = await asyncio.to_thread(store.update_run, run["run_id"], status=m.RUNNING, started_at=self._clock(), notes=notes or None)
        scheduler_log.write("started", automation_id=automation["automation_id"], run_id=run["run_id"], trigger=run.get("trigger"),
                            attempt=run.get("attempt"), kind=automation["target"]["kind"])
        task = asyncio.get_running_loop().create_task(self._execute(runner, automation, run), name=f"automation-run-{run['run_id']}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run["run_id"]

    async def _login_hint(self, target: Dict[str, Any]) -> Optional[str]:
        hinter = targets.LOGIN_HINTS.get(target.get("kind") or "")
        if hinter is None:
            return None
        try:
            return await hinter(self._app_state, target)
        except (*PASS_ERRORS, HTTPException, ValueError, LookupError) as exc:
            logger.info("automation_login_hint_unavailable", kind=target.get("kind"), error_type=type(exc).__name__)
            return None

    async def run_now(self, automation_id: str, by: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        run = await asyncio.to_thread(self.store.insert_run, automation_id, self._boot_id, "run_now")
        run_id = await self._dispatch(run, by=by)
        return await asyncio.to_thread(self.store.run, run_id)

    async def cancel_run(self, run_id: str) -> Dict[str, Any]:
        store = self.store
        run = await asyncio.to_thread(store.run, run_id)
        if run["status"] not in m.LIVE_STATUSES:
            raise m.AutomationInvalid("not_live", run_id)
        self._cancelling.add(run_id)
        try:
            task = next((t for t in self._tasks if t.get_name() == f"automation-run-{run_id}"), None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                await asyncio.to_thread(store.update_run, run_id, status=m.CANCELLED, ended_at=self._clock())
        finally:
            self._cancelling.discard(run_id)
        return await asyncio.to_thread(store.run, run_id)

    async def _execute(self, runner: targets.Runner, automation: Dict[str, Any], run: Dict[str, Any]) -> None:
        store = self.store
        fields: Dict[str, Any]
        cap = automation.get("max_runtime_s")
        try:
            work = runner(Context(self._app_state, store, self._boot_id), automation, run)
            outcome = await (asyncio.wait_for(work, float(cap) + MAX_RUNTIME_GRACE_S) if cap else work)
            fields = {"status": outcome.status, "reason": outcome.reason, "report": outcome.report,
                      "cost_usd": outcome.cost_usd, "usage": outcome.usage, "sessions": outcome.sessions, "error": outcome.error}
            fields = {k: v for k, v in fields.items() if v is not None or k == "reason"}
        except asyncio.CancelledError:
            cancelled = run["run_id"] in self._cancelling
            fields = {"status": m.CANCELLED, "reason": None} if cancelled else {"status": m.FAILED, "reason": m.R_INTERRUPTED}
            raise
        except asyncio.TimeoutError:
            logger.warning("automation_max_runtime", run_id=run["run_id"], max_runtime_s=cap)
            fields = {"status": m.FAILED, "reason": R_MAX_RUNTIME}
        except Exception as exc:
            logger.error("automation_runner_failed", run_id=run["run_id"], error_type=type(exc).__name__)
            fields = {"status": m.FAILED, "reason": "runner_error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if fields.get("status") not in m.LIVE_STATUSES:
                fields["ended_at"] = self._clock()
                await asyncio.to_thread(self._collect_attachments, automation, run["run_id"], fields)
            try:
                await asyncio.to_thread(self._finish, automation["automation_id"], run["run_id"], fields)
            except PASS_ERRORS as exc:
                logger.error("automation_run_finish_failed", run_id=run["run_id"], error_type=type(exc).__name__)

    def _collect_attachments(self, automation: Dict[str, Any], run_id: str, fields: Dict[str, Any]) -> None:
        if not attachments.wants(automation["target"]):
            return
        try:
            kept, left = attachments.collect(attachments.folder_for(self.store.attachments_root, run_id))
            if kept:
                fields["attachments"] = kept
            if left:
                notes = (self.store.run(run_id).get("notes") or {})
                fields["notes"] = {**notes, "attachments_left_out": left}
        except (OSError, m.AutomationNotFound) as exc:
            logger.error("automation_attachments_failed", run_id=run_id, error_type=type(exc).__name__)

    def sweep_attachments(self) -> int:
        return attachments.sweep(self.store.attachments_root, self.store.run_ids())

    def _finish(self, automation_id: str, run_id: str, fields: Dict[str, Any]) -> None:
        try:
            self.store.update_run(run_id, **fields)
        except m.ReportTooLarge:
            fields.update(status=m.FAILED, reason="report_too_large", report=None)
            self.store.update_run(run_id, **fields)
        if fields.get("status") not in m.LIVE_STATUSES:
            self._after_end(automation_id, run_id, fields["status"], fields.get("reason"))

    def _after_end(self, automation_id: str, run_id: str, status: str, reason: Optional[str]) -> None:
        event = {m.FAILED: "failed", m.SKIPPED: "skipped"}.get(status, "finished")
        scheduler_log.write(event, automation_id=automation_id, run_id=run_id, status=status, reason=reason)
        try:
            if status != m.SKIPPED:
                self.store.settle_retry(automation_id, status == m.FAILED, self._clock())
            if status == m.FAILED and reason in SCHEDULER_FAILURES:
                tell_failure(self.store.get(automation_id), run_id, self.store)
        except m.AutomationNotFound:
            pass

    def _timeout(self) -> float:
        due = self.store.next_due()
        if due is None:
            return MAX_SLEEP_S
        return min(max(due - self._clock(), MIN_SLEEP_S), MAX_SLEEP_S)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        run_sessions.subscribe(self._app_state, self.store)
        await self._wait_booted()
        try:
            await asyncio.to_thread(self.sweep_attachments)
        except (OSError, sqlite3.Error) as exc:
            logger.error("automation_attachment_sweep_failed", error_type=type(exc).__name__)
        try:
            interrupted = await asyncio.to_thread(lifecycle.reconcile_boot, self.store, self._boot_id)
            for run in interrupted:
                await asyncio.to_thread(self._after_end, run["automation_id"], run["run_id"], m.FAILED, m.R_INTERRUPTED)
        except PASS_ERRORS as exc:
            logger.error("automation_reconcile_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        while True:
            self._wake.clear()
            try:
                await self.pass_once()
                timeout = await asyncio.to_thread(self._timeout)
            except PASS_ERRORS as exc:
                logger.error("automation_pass_failed", error_type=type(exc).__name__, error=str(exc)[:200])
                timeout = MAX_SLEEP_S
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass


_task: Optional["asyncio.Task[None]"] = None
_scheduler: Optional[Scheduler] = None


def start(app_state: Any, state_dir: Path) -> Scheduler:
    global _task, _scheduler
    if _task is not None:
        _task.cancel()
    from src.config import settings  # noqa: PLC0415

    try:
        scheduler_log.start(Path(settings.auth_config_file), settings.get_log_dir())
    except OSError as exc:
        logger.error("automations_log_start_failed", error_type=type(exc).__name__)
    scheduler = _scheduler = Scheduler(app_state, AutomationStore(storage_for(state_dir)))
    app_state.automation_store = scheduler.store
    app_state.automation_scheduler = scheduler
    _task = asyncio.get_running_loop().create_task(scheduler.run(), name="automations-scheduler")
    return scheduler


async def stop() -> None:
    global _task, _scheduler
    scheduler, task, _scheduler, _task = _scheduler, _task, None, None
    run_sessions.unsubscribe()
    pending = [task] if task is not None else []
    if scheduler is not None:
        pending += list(scheduler._tasks)
    for item in pending:
        item.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
