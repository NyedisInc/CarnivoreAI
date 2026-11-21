
from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.account_switch.auto_restart import SessionEvidence, at_rest
from src.core.argent import health, outage, row_state, rollout_store as store
from src.core.argent import settings as settings_module
from src.core.argent.rebuild import CannotRebuild
from src.core.argent.runtime import get_runtime
from src.core.attention.codex_pane_home import codex_home_for_row
from src.core.auto_sleep import live_work
from src.core.budget_hold.store import STORE
from src.core.hosts.identity import is_remote_info
from src.core.resource_push import topics
from src.core.session_instance_rekey import IDENTITY_CANNOT_DETERMINE
from src.core.session_respawn import LIVE_RESTART_REASON_ARGENT_ROLLOUT
from src.core.session_resume_target import CONVERSATION_RESUMED
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT, family_conversation_presence
from src.plugins.sdk import ports

logger = structlog.get_logger()

PASS_SECONDS = 15.0
MAX_ROWS_PER_PASS = 3
QUIET_SECONDS = 120.0
PARK_AFTER_SECONDS = 24 * 3600
CAP_SHARE = health.CAP_SHARE
HOLD_PREFIX = "rollout:"
FAMILIES = ("claude", "codex")
PORT_NAME = "argent"

PERMANENT_REASONS = ("settings override", "upstream on a private network", "codex headers unsupported", "cannot rebuild launch command",
                     "gateway unreachable from")
BUSY, STARTUP, NO_CONVERSATION, TOO_LARGE, DOWN = "busy", "startup dialog", "no conversation yet", "too large for gateway cap", "argent down at launch"
NOT_RESUMED = "conversation not resumed"
COOLING = "re-tether cooldown"

IDLE, RAN, CANCELLED_BY_SWITCH, FEATURE_OFF = "idle", "ran", "cancelled", "feature_off"


def _notify() -> None:
    resource_push.notify(topics.ARGENT_ROLLOUT)


def tenant_id() -> str:
    login = get_runtime().store.get_login()
    return str(login["tenant_id"]) if login else ""


def need(direction: str, tether: Dict[str, str]) -> Tuple[str, str]:
    state, reason = tether["state"], tether["reason"]
    if direction == "off":
        return ("restart", "") if state in (row_state.PENDING, "tethered") else ("done", "direct")
    if state in (row_state.PENDING, "tethered"):
        return "done", "pending first traffic" if state == row_state.PENDING else "tethered"
    if state == row_state.NOT_TETHERED and reason.startswith(PERMANENT_REASONS):
        return "exclude", reason
    return "restart", ""


def gate_reason(report: health.HealthReport, now: float) -> str:
    if now - report.checked_at > health.FRESH_SECONDS or report.state not in (health.UP, health.CAP_TOO_LOW) or report.mints_accepted is not True:
        return DOWN
    return TOO_LARGE if report.state == health.CAP_TOO_LOW else ""


class RolloutEngine:

    def __init__(self, manager: Any, *, evidence: Any = None, clock: Callable[[], float] = time.time,
                 probe: Callable[[], Any] = health.probe_now) -> None:
        self._manager, self._clock, self._probe = manager, clock, probe
        self._evidence = evidence or SessionEvidence(manager)
        self._lock = asyncio.Lock()

    async def run_pass(self) -> str:
        async with self._lock:
            return await self._pass()

    async def _release_stale_holds(self) -> None:
        if STORE.any_hold():
            for hold in STORE.snapshot():
                if hold["item_id"].startswith(HOLD_PREFIX):
                    await asyncio.to_thread(STORE.clear_hold, hold["item_id"])

    async def _pass(self) -> str:
        await self._release_stale_holds()
        if ports.get(PORT_NAME) is None:
            return FEATURE_OFF
        tenant = await asyncio.to_thread(tenant_id)
        roll = await asyncio.to_thread(store.current, tenant)
        if roll is None or roll["state"] != store.RUNNING:
            return IDLE
        epoch, direction = int(roll["epoch"]), roll["direction"]
        cfg = await asyncio.to_thread(settings_module.read)
        if cfg.enabled != (direction == "on"):
            await self._set_state(tenant, epoch, store.CANCELLED, "switch changed")
            return CANCELLED_BY_SWITCH
        known = {r["tmux_name"]: r for r in await asyncio.to_thread(store.rows, tenant, epoch)}
        candidates = await self._observe(tenant, epoch, direction, known)
        gate, cap = "", None
        if direction == "on" and candidates:
            report = health.latest()
            if self._clock() - report.checked_at > health.FRESH_SECONDS:
                report = await self._probe()
            gate, cap = gate_reason(report, self._clock()), report.body_cap_bytes
        restarted = 0
        for info in candidates:
            name = info.tmux_session
            entry = known.get(name) or {"state": store.PENDING, "first_seen": self._clock()}
            if entry["state"] == store.PARKED or restarted >= MAX_ROWS_PER_PASS:
                continue
            why = gate or await self._cooling(tenant, direction, info) or await self._refusal(info, cap if direction == "on" else None)
            if why is not None:
                await self._wait(tenant, epoch, name, why, self._clock() - float(entry["first_seen"]))
                continue
            restarted += await self._restart(tenant, epoch, direction, info)
        await self._finish_if_done(tenant, epoch)
        return RAN

    async def _observe(self, tenant: str, epoch: int, direction: str, known: Dict[str, Dict[str, Any]]) -> List[Any]:
        infos = await self._manager.list_session_infos()
        candidates, live = [], set()
        expiring = await asyncio.to_thread(outage.expiring_refs, tenant, self._clock()) if direction == "on" else set()
        for info in infos:
            name = info.tmux_session
            if info.agent_family not in FAMILIES or not name or info.session is None or is_remote_info(info):
                continue
            live.add(name)
            tether = await asyncio.to_thread(row_state.lookup, tenant, name)
            verdict, reason = need(direction, tether)
            if verdict == "done" and tether["ref"] in expiring:
                verdict = "restart"
            if name not in known:
                await asyncio.to_thread(store.ensure_row, tenant, epoch, name, clock=self._clock)
            state = known.get(name, {}).get("state", store.PENDING)
            if state in (store.RESTARTED, store.FAILED, store.EXCLUDED):
                continue
            if verdict == "restart":
                candidates.append(info)
            elif state in (store.PENDING, store.PARKED):
                await self._set_row(tenant, epoch, name, store.EXCLUDED if verdict == "exclude" else store.RESTARTED, reason)
        for name, entry in known.items():
            if name not in live and entry["state"] in (store.PENDING, store.PARKED):
                await self._set_row(tenant, epoch, name, store.FAILED, "session ended")
        candidates.sort(key=lambda i: float(known.get(i.tmux_session, {}).get("first_seen", self._clock())))
        return candidates

    async def _refusal(self, info: Any, cap: Optional[int], owner: bool = False) -> Optional[str]:
        if info.activity_status != "dead" and not owner:
            if info.startup_gate not in (None, "ready"):
                return STARTUP
            if not at_rest(info) or info.subagents_running != 0 or info.background_open != 0:
                return BUSY
            watcher = getattr(self._manager, "_attention_watcher", None)
            observation = watcher.observation_for(str(info.session.id)) if watcher is not None else None
            if observation is None or getattr(observation, "stale", True) or live_work.hold_for(getattr(observation, "evidence", None), require_measured=True):
                return BUSY
            quiet = await self._evidence.quiet_seconds(info.tmux_session)
            if quiet is None or quiet < QUIET_SECONDS:
                return BUSY
        target = await asyncio.to_thread(self._manager._resume_target_for_tmux_name, info.tmux_session, self._manager.tmux_socket_name())
        if target.outcome != CONVERSATION_RESUMED or not target.claude_session_uuid:
            return NO_CONVERSATION
        presence = await asyncio.to_thread(
            family_conversation_presence, info.agent_family, target.claude_session_uuid,
            working_dir=getattr(info.session, "working_dir", None),
            codex_home=codex_home_for_row(info.agent_family, self._manager.tmux_socket_name(), info.tmux_session))
        if presence.outcome not in (CONVERSATION_PRESENT, CONVERSATION_ABSENT):
            return NO_CONVERSATION
        size = _size(presence.path) if presence.outcome == CONVERSATION_PRESENT else 0
        if size <= 0:
            return NOT_RESUMED
        return TOO_LARGE if cap is not None and size > CAP_SHARE * cap else None

    async def _cooling(self, tenant: str, direction: str, info: Any) -> Optional[str]:
        if direction != "on":
            return None
        ref = (await asyncio.to_thread(row_state.lookup, tenant, info.tmux_session))["ref"]
        return COOLING if await asyncio.to_thread(outage.retether_blocked, tenant, ref, self._clock()) else None

    async def _wait(self, tenant: str, epoch: int, name: str, why: str, age: float) -> None:
        if why == NOT_RESUMED:
            await self._set_row(tenant, epoch, name, store.FAILED, NOT_RESUMED)
        elif why == BUSY and age > PARK_AFTER_SECONDS:
            await self._set_row(tenant, epoch, name, store.PARKED, BUSY)
        else:
            await self._set_row(tenant, epoch, name, store.PENDING, why)

    async def restart_now(self, name: str) -> str:
        async with self._lock:
            tenant = await asyncio.to_thread(tenant_id)
            roll = await asyncio.to_thread(store.current, tenant)
            if roll is None:
                return "no_rollout"
            epoch = int(roll["epoch"])
            row = next((r for r in await asyncio.to_thread(store.rows, tenant, epoch) if r["tmux_name"] == name), None)
            if row is None or row["state"] not in (store.PENDING, store.PARKED):
                return "not_open"
            info = next((i for i in await self._manager.list_session_infos()
                         if i.tmux_session == name and i.agent_family in FAMILIES and i.session is not None and not is_remote_info(i)), None)
            if info is None:
                return "not_found"
            await self._restart(tenant, epoch, roll["direction"], info, owner=True)
            after = next((r for r in await asyncio.to_thread(store.rows, tenant, epoch) if r["tmux_name"] == name), None)
            return "ok" if after is not None and after["state"] == store.RESTARTED else "refused"

    async def _restart(self, tenant: str, epoch: int, direction: str, info: Any, owner: bool = False) -> int:
        name, row_id = info.tmux_session, info.session_row_id
        hold = f"{HOLD_PREFIX}{row_id}" if row_id is not None else None
        if hold:
            await asyncio.to_thread(STORE.set_hold, hold, "the gateway rollout", [str(row_id)], tenant)
        try:
            fresh = await self._manager.get_session_info(info.session.id)
            cap = health.latest().body_cap_bytes if direction == "on" else None
            if fresh is None or fresh.tmux_session != name:
                return 0
            why = (None if owner else await self._cooling(tenant, direction, fresh)) or await self._refusal(fresh, cap, owner)
            if why is not None:
                await self._wait(tenant, epoch, name, why, 0.0)
                return 0
            dead = fresh.activity_status == "dead"
            try:
                result = await self._manager.respawn_session(
                    name, live_restart_confirmed=not dead, require_agent_resume=True, argent_rebuild=direction == "on",
                    live_restart_reason=None if dead else LIVE_RESTART_REASON_ARGENT_ROLLOUT)
            except CannotRebuild as exc:
                await self._set_row(tenant, epoch, name, store.EXCLUDED, f"cannot rebuild launch command: {exc.cause}")
                return 1
            except (ValueError, LookupError, RuntimeError, OSError) as exc:
                logger.info("argent_rollout_restart_refused", tmux_session=name, error_type=type(exc).__name__)
                await self._set_row(tenant, epoch, name, store.FAILED, f"restart refused: {type(exc).__name__}")
                return 1
            await self._verify(tenant, epoch, direction, name, result)
            return 1
        finally:
            if hold:
                await asyncio.to_thread(STORE.clear_hold, hold)

    async def _verify(self, tenant: str, epoch: int, direction: str, name: str, result: Any) -> None:
        ok = (isinstance(result, dict) and result.get("ok") is True and result.get("kind") == "agent"
              and result.get("conversation") == CONVERSATION_RESUMED and result.get("identity_status") != IDENTITY_CANNOT_DETERMINE)
        logger.info("argent_rollout_restart", tmux_session=name, direction=direction, ok=ok,
                    identity_status=result.get("identity_status") if isinstance(result, dict) else None)
        if not ok:
            await self._set_row(tenant, epoch, name, store.FAILED, NOT_RESUMED)
            return
        tether = await asyncio.to_thread(row_state.lookup, tenant, name)
        if direction == "off":
            await asyncio.to_thread(row_state.clear, tenant, tether["ref"])
            await self._set_row(tenant, epoch, name, store.RESTARTED, "direct")
        elif tether["state"] == row_state.NOT_TETHERED:
            await self._set_row(tenant, epoch, name, store.RESTARTED, f"not tethered: {tether['reason']}")
        else:
            await asyncio.to_thread(outage.record_retether, tenant, tether["ref"], "rollout", clock=self._clock)
            await self._set_row(tenant, epoch, name, store.RESTARTED, "pending first traffic")

    async def restart_direct(self, info: Any) -> str:
        async with self._lock:
            name, row_id = info.tmux_session, info.session_row_id
            hold = f"{HOLD_PREFIX}{row_id}" if row_id is not None else None
            if hold:
                await asyncio.to_thread(STORE.set_hold, hold, "restarting direct", [str(row_id)], await asyncio.to_thread(tenant_id))
            try:
                fresh = await self._manager.get_session_info(info.session.id)
                if fresh is None or fresh.tmux_session != name:
                    return "failed"
                why = await self._refusal(fresh, None)
                if why is not None:
                    return why
                dead = fresh.activity_status == "dead"
                try:
                    result = await self._manager.respawn_session(name, live_restart_confirmed=not dead, require_agent_resume=True, argent_rebuild=False,
                                                                 live_restart_reason=None if dead else LIVE_RESTART_REASON_ARGENT_ROLLOUT)
                except (ValueError, LookupError, RuntimeError, OSError) as exc:
                    logger.info("argent_restart_direct_refused", tmux_session=name, error_type=type(exc).__name__)
                    return "failed"
                ok = isinstance(result, dict) and result.get("ok") is True and result.get("conversation") == CONVERSATION_RESUMED
                logger.info("argent_restart_direct", tmux_session=name, ok=ok)
                return "ok" if ok else "failed"
            finally:
                if hold:
                    await asyncio.to_thread(STORE.clear_hold, hold)

    async def _finish_if_done(self, tenant: str, epoch: int) -> None:
        rows = await asyncio.to_thread(store.rows, tenant, epoch)
        if not any(r["state"] in store.OPEN_ROW_STATES for r in rows):
            await self._set_state(tenant, epoch, store.DONE, "")

    async def _set_row(self, tenant: str, epoch: int, name: str, state: str, reason: str) -> None:
        before = next((r for r in await asyncio.to_thread(store.rows, tenant, epoch) if r["tmux_name"] == name), None)
        if before is not None and (before["state"], before["reason"]) == (state, reason):
            return
        await asyncio.to_thread(store.set_row, tenant, epoch, name, state, reason)
        _notify()

    async def _set_state(self, tenant: str, epoch: int, state: str, reason: str) -> None:
        if await asyncio.to_thread(store.set_state, tenant, epoch, state, reason):
            _notify()


def _size(path: Any) -> int:
    try:
        return os.stat(path).st_size if path is not None else 0
    except OSError:
        return 0


async def begin(direction: str) -> Dict[str, Any]:
    tenant = await asyncio.to_thread(tenant_id)
    epoch = await asyncio.to_thread(store.start, tenant, direction)
    _notify()
    return await asyncio.to_thread(store.current, tenant) or {"epoch": epoch}


async def cancel() -> bool:
    return await _move((store.RUNNING, store.PAUSED), store.CANCELLED, "cancelled by the owner")


async def pause(reason: str) -> bool:
    return await _move((store.RUNNING,), store.PAUSED, reason)


async def resume() -> bool:
    return await _move((store.PAUSED,), store.RUNNING, "")


async def _move(from_states: Tuple[str, ...], to_state: str, reason: str) -> bool:
    tenant = await asyncio.to_thread(tenant_id)
    roll = await asyncio.to_thread(store.current, tenant)
    if roll is None or roll["state"] not in from_states:
        return False
    await asyncio.to_thread(store.set_state, tenant, int(roll["epoch"]), to_state, reason)
    _notify()
    return True


def view_sync(tenant: str) -> Dict[str, Any]:
    roll = store.current(tenant)
    if roll is None:
        return {"state": "none", "direction": "", "epoch": 0, "reason": "", "counts": {}, "reasons": {}, "rows": []}
    rows = [{"tmux_name": r["tmux_name"], "state": store.PENDING if r["state"] == store.PARKED else r["state"], "reason": r["reason"]}
            for r in store.rows(tenant, int(roll["epoch"]))]
    counts: Dict[str, int] = {}
    reasons: Dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        if r["reason"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {"state": roll["state"], "direction": roll["direction"], "epoch": roll["epoch"], "reason": roll["reason"],
            "counts": counts, "reasons": reasons, "rows": rows}


class _Timer:

    def __init__(self) -> None:
        self.task: Optional["asyncio.Task[None]"] = None
        self.app_state: Any = None
        self.wake: Optional[asyncio.Event] = None
        self.engine: Optional["RolloutEngine"] = None


_timer = _Timer()


def bind(app_state: Any) -> None:
    _timer.app_state = app_state


async def restart_now(manager: Any, name: str) -> str:
    engine = _timer.engine if is_running() and _timer.engine is not None else RolloutEngine(manager)
    result = await engine.restart_now(name)
    if is_running() and _timer.wake is not None:
        _timer.wake.set()
    return result


def is_running() -> bool:
    return _timer.task is not None and not _timer.task.done()


def ensure_running() -> bool:
    manager = getattr(_timer.app_state, "session_manager", None)
    if manager is None:
        return False
    if _timer.wake is not None:
        _timer.wake.set()
    if not is_running():
        _timer.wake = asyncio.Event()
        _timer.engine = RolloutEngine(manager)
        _timer.task = asyncio.get_running_loop().create_task(_loop(_timer.engine, _timer.wake))
    return True


async def resume_at_boot() -> None:
    tenant = await asyncio.to_thread(tenant_id)
    roll = await asyncio.to_thread(store.current, tenant)
    if roll is not None and roll["state"] == store.RUNNING:
        ensure_running()


async def stop() -> None:
    task, _timer.task = _timer.task, None
    if task is not None and not task.done():
        owner = task.get_loop()
        if owner is not asyncio.get_running_loop():
            if not owner.is_closed():
                owner.call_soon_threadsafe(task.cancel)
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _loop(engine: RolloutEngine, wake: asyncio.Event) -> None:
    while True:
        try:
            outcome = await engine.run_pass()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("argent_rollout_pass_failed", error_type=type(exc).__name__)
            outcome = RAN
        if outcome != RAN:
            _timer.task = None
            return
        wake.clear()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(wake.wait(), PASS_SECONDS)
