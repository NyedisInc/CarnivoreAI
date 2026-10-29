
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

import structlog

from src.cplugs.runtime import index_expiry, integrity, sandbox, watchdog
from src.cplugs.runtime.children import ChildLedger
from src.cplugs.runtime.dispatch import HostDispatcher
from src.cplugs.runtime.process import PluginProcess, PluginSpec, ProcessEnded

logger = structlog.get_logger()

INTENTIONAL = frozenset({"disabled", "revoked", "safe_mode", "shutdown", "crash_loop", "killed", "restart", "idle"})
IDLE = "idle"
NEEDS_APPROVAL = "needs_approval"
IDLE_SECONDS = 600.0
ALERT_CRASH_LOOP, ALERT_REVOKED, ALERT_INTEGRITY, ALERT_INDEX = "crash_loop", "revoked", "integrity", "index_expired"
ALERT_SAFE_MODE = "safe_mode"

CallLater = Callable[..., Any]
Alert = Callable[[str, str, str], None]
Cancel = Callable[[str], Mapping[str, int]]


def safe_mode_from_env() -> bool:
    from src.core.product_identity import env_value  # noqa: PLC0415

    return (env_value("CPLUGS_SAFE_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


KEEP_HOST_STATE_REASONS = frozenset({"idle", "restart"})


class Supervisor:

    def __init__(self, state_dir: Path, app_version: str, dispatcher: HostDispatcher, alert: Alert, cancel_side_effects: Cancel,
                 activity: Callable[[Dict[str, Any]], None], safe_mode: bool = False, index: Optional[Mapping[str, Any]] = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 sampler: watchdog.Sampler = watchdog.usage_of, children: Optional[ChildLedger] = None,
                 clock: Callable[[], float] = time.monotonic, call_later: Optional[CallLater] = None, idle_seconds: float = IDLE_SECONDS) -> None:
        self._children = children
        self.on_stopped: Optional[Callable[[str], Awaitable[None]]] = None
        self._state_dir, self._app_version, self._dispatcher = Path(state_dir), app_version, dispatcher
        self._alert, self._cancel, self._activity = alert, cancel_side_effects, activity
        self._safe_mode, self._index, self._sleep, self._sampler = safe_mode, index, sleep, sampler
        self._specs: Dict[str, PluginSpec] = {}
        self._procs: Dict[str, PluginProcess] = {}
        self._strikes: Dict[str, watchdog.StrikeLedger] = {}
        self._state: Dict[str, str] = {}
        self._revoked: set = set()
        self._index_override: set = set()
        self._runtime_dir: Optional[Path] = None
        self._restarts: Dict[str, asyncio.Task] = {}
        self._clock, self._call_later, self._idle_seconds = clock, call_later, idle_seconds
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_used: Dict[str, float] = {}
        self._idle_timers: Dict[str, Any] = {}
        self._tasks: set = set()

    def state(self, plugin_id: str) -> str:
        return self._state.get(plugin_id, "unknown")

    def set_safe_mode(self, on: bool) -> None:
        self._safe_mode = on

    async def set_index(self, index: Optional[Mapping[str, Any]]) -> None:
        self._index = index
        for pid, spec in list(self._specs.items()):
            if spec.ctx.tier != "catalog" or not (pid in self._procs or self._state.get(pid) == IDLE):
                continue
            if self._index_revokes(spec):
                await self.revoke(pid, "revoked_in_index")
            elif not self._index_fresh(pid):
                self._alert(pid, ALERT_INDEX, "index_expired")
                await self.disable(pid, "index_expired")
                self._state[pid] = "index_expired"

    def _index_fresh(self, plugin_id: str) -> bool:
        return index_expiry.may_run_third_party(index_expiry.index_state(self._index), plugin_id in self._index_override)

    def _index_revokes(self, spec: PluginSpec) -> bool:
        entries = self._index.get("revoked") if self._index else None
        mine = {spec.catalog_id or spec.ctx.plugin_id, spec.ctx.plugin_id}
        return any(isinstance(e, Mapping) and e.get("id") in mine and e.get("version") in (None, "", spec.version)
                   for e in (entries if isinstance(entries, list) else []))

    def override_index(self, plugin_id: str, on: bool) -> None:
        (self._index_override.add if on else self._index_override.discard)(plugin_id)

    def admit(self, spec: PluginSpec) -> Optional[str]:
        pid = spec.ctx.plugin_id
        if self._safe_mode:
            return "safe_mode"
        if spec.consent_owed:
            return NEEDS_APPROVAL
        if spec.trust_refusal:
            return "trust_refused"
        if pid in self._revoked or self._index_revokes(spec):
            return "revoked"
        if spec.ctx.tier == "catalog" and not self._index_fresh(pid):
            return "index_expired"
        return None

    @staticmethod
    def _code_intact(spec: PluginSpec) -> bool:
        try:
            return integrity.tree_digest(spec.code_dir) == spec.code_digest
        except integrity.IntegrityError:
            return False

    def _layout(self, spec: PluginSpec) -> sandbox.Layout:
        if self._runtime_dir is None:
            self._runtime_dir = sandbox.copy_runtime(self._state_dir, self._app_version)
        interp = sandbox.find_interpreter()
        return sandbox.Layout(interpreter=interp, stdlib_root=sandbox.stdlib_root(interp), runtime_dir=self._runtime_dir,
                              code_dir=Path(spec.code_dir).resolve(), data_dir=Path(spec.ctx.data_dir).resolve())

    async def _judge(self, spec: PluginSpec) -> Optional[str]:
        pid = spec.ctx.plugin_id
        self._specs[pid] = spec
        refused = self.admit(spec)
        if refused is None and spec.ctx.tier == "catalog" and spec.code_digest is None:
            self._alert(pid, ALERT_INTEGRITY, "no_code_digest")
            self._state[pid] = "integrity"
            return "integrity"
        if refused is None and spec.code_digest is not None and not self._code_intact(spec):
            self._alert(pid, ALERT_INTEGRITY, "code_root_changed")
            await self.enter_safe_mode()
            refused = "safe_mode"
        if refused is None:
            return None
        self._state[pid] = "disabled (safe mode)" if refused == "safe_mode" else refused
        if refused == "index_expired":
            self._alert(pid, ALERT_INDEX, refused)
        elif refused == "safe_mode":
            self._alert(pid, ALERT_SAFE_MODE, refused)
        elif refused == "trust_refused":
            self._alert(pid, ALERT_INTEGRITY, f"trust_refused:{spec.trust_refusal}")
        return self._state[pid]

    def _lock(self, plugin_id: str) -> asyncio.Lock:
        return self._locks.setdefault(plugin_id, asyncio.Lock())

    async def enable(self, spec: PluginSpec) -> str:
        async with self._lock(spec.ctx.plugin_id):
            return await self._enable_locked(spec)

    async def _enable_locked(self, spec: PluginSpec) -> str:
        refused = await self._judge(spec)
        return refused if refused is not None else await self._spawn(spec)

    async def activate(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        async with self._lock(pid):
            proc = self._procs.get(pid)
            if proc is not None and not proc.ended:
                return self._state.get(pid, "running")
            if spec.subscriptions:
                return await self._enable_locked(spec)
            refused = await self._judge(spec)
            if refused is None:
                self._state[pid] = IDLE
            return self._state[pid]

    async def ensure(self, plugin_id: str) -> Optional[PluginProcess]:
        async with self._lock(plugin_id):
            proc = self._procs.get(plugin_id)
            if proc is not None and not proc.ended:
                self.touch(plugin_id)
                return proc
            spec = self._specs.get(plugin_id)
            if spec is not None and self._state.get(plugin_id) == IDLE:
                await self._enable_locked(spec)
            return self._procs.get(plugin_id)

    async def deliver_event(self, plugin_id: str, family: str, seq: int, payload: Any) -> bool:
        proc = await self.ensure(plugin_id)
        return proc is not None and await proc.deliver_event(family, seq, payload)

    def touch(self, plugin_id: str) -> None:
        self._last_used[plugin_id] = self._clock()

    def available(self, plugin_id: str) -> bool:
        proc = self._procs.get(plugin_id)
        return (proc is not None and not proc.ended) or self._state.get(plugin_id) == IDLE

    async def _spawn(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        proc = PluginProcess(spec, self._layout(spec), self._dispatcher, self._app_version,
                             lambda reason, p=pid: self._exited(p, reason), self._sampler)
        self._procs[pid] = proc
        try:
            await proc.start()
        except (ProcessEnded, asyncio.TimeoutError, OSError) as exc:
            await proc.stop("startup_failed")
            if proc.ended and proc.ended != "startup_failed":
                logger.warning("cplug_start_failed", cplug=pid, reason=proc.ended, error_type=type(exc).__name__)
            return self._state.get(pid, "disabled")
        self._state[pid] = "running"
        self.touch(pid)
        if not spec.subscriptions:
            self._arm_idle(pid, self._idle_seconds)
        if self._children is not None and proc.pid is not None:
            await asyncio.to_thread(self._children.record, pid, proc.pid)
        return "running"

    def _arm_idle(self, pid: str, delay: float) -> None:
        self._drop_idle(pid)
        later = self._call_later or asyncio.get_running_loop().call_later
        self._idle_timers[pid] = later(delay, self._idle_fired, pid)

    def _drop_idle(self, pid: str) -> None:
        handle = self._idle_timers.pop(pid, None)
        if handle is not None:
            handle.cancel()

    def _idle_fired(self, pid: str) -> None:
        self._idle_timers.pop(pid, None)
        task = asyncio.get_running_loop().create_task(self._idle_check(pid))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _idle_check(self, pid: str) -> None:
        async with self._lock(pid):
            proc = self._procs.get(pid)
            if proc is None or proc.ended or self._state.get(pid) != "running":
                return
            if proc.busy > 0:
                self.touch(pid)
            left = self._last_used.get(pid, 0.0) + self._idle_seconds - self._clock()
            if left > 0:
                self._arm_idle(pid, left)
                return
            await self.disable(pid, "idle")
            self._state[pid] = IDLE

    async def _exited(self, pid: str, reason: str) -> None:
        self._drop_idle(pid)
        if self._children is not None:
            await asyncio.to_thread(self._children.forget, pid)
        if reason in INTENTIONAL or self._procs.get(pid) is None:
            return
        if reason == "integrity":
            self._alert(pid, ALERT_INTEGRITY, reason)
        ledger = self._strikes.setdefault(pid, watchdog.StrikeLedger())
        if ledger.strike():
            await self._crash_loop(pid, reason)
            return
        self._state[pid] = "backing_off"
        delay = ledger.backoff()
        self._restarts[pid] = asyncio.create_task(self._restart_after(pid, delay))

    async def _restart_after(self, pid: str, delay: float) -> None:
        await self._sleep(delay)
        spec = self._specs.get(pid)
        if spec is not None and self._state.get(pid) == "backing_off":
            await self.enable(spec)

    async def _crash_loop(self, pid: str, reason: str) -> None:
        self._state[pid] = "crash_loop"
        self._alert(pid, ALERT_CRASH_LOOP, reason)
        self.cancel_effects(pid, "crash_loop")

    def cancel_effects(self, pid: str, why: str) -> None:
        counts = dict(self._cancel(pid))
        self._activity({"plugin": pid, "method": "side_effects.cancel", "outcome": why,
                       "detail": ",".join(f"{k}={v}" for k, v in sorted(counts.items()))})

    async def disable(self, plugin_id: str, reason: str = "disabled") -> None:
        task = self._restarts.pop(plugin_id, None)
        if task is not None:
            task.cancel()
        self._drop_idle(plugin_id)
        proc = self._procs.pop(plugin_id, None)
        self._state[plugin_id] = "disabled"
        if proc is not None:
            await proc.stop(reason)
            if self._children is not None:
                await asyncio.to_thread(self._children.forget, plugin_id)
        if self.on_stopped is not None and reason not in KEEP_HOST_STATE_REASONS:
            await self.on_stopped(plugin_id)

    async def kill(self, plugin_id: str) -> None:
        task = self._restarts.pop(plugin_id, None)
        if task is not None:
            task.cancel()
        self._drop_idle(plugin_id)
        proc = self._procs.pop(plugin_id, None)
        self._state[plugin_id] = "killed"
        if proc is not None:
            await proc.kill("killed")
            if self._children is not None:
                await asyncio.to_thread(self._children.forget, plugin_id)
        self.cancel_effects(plugin_id, "killed")

    async def restart(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        await self.disable(pid, "restart")
        self._strikes.pop(pid, None)
        return await self.enable(spec)

    def forget(self, plugin_id: str) -> None:
        task = self._restarts.pop(plugin_id, None)
        if task is not None:
            task.cancel()
        self._drop_idle(plugin_id)
        for table in (self._specs, self._procs, self._strikes, self._state, self._locks, self._last_used):
            table.pop(plugin_id, None)
        self._revoked.discard(plugin_id)
        self._index_override.discard(plugin_id)

    async def revoke(self, plugin_id: str, reason: str = "revoked") -> None:
        self._revoked.add(plugin_id)
        await self.disable(plugin_id, "revoked")
        self._state[plugin_id] = "revoked"
        self._alert(plugin_id, ALERT_REVOKED, reason)
        self.cancel_effects(plugin_id, "revoked")

    async def enter_safe_mode(self) -> None:
        self._safe_mode = True
        for pid in {*self._procs, *(p for p, s in self._state.items() if s == IDLE)}:
            await self.disable(pid, "safe_mode")
            self._state[pid] = "disabled (safe mode)"

    async def shutdown(self) -> None:
        for pid in list(self._procs):
            await self.disable(pid, "shutdown")

    def process(self, plugin_id: str) -> Optional[PluginProcess]:
        return self._procs.get(plugin_id)
