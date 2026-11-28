
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Mapping, Optional, Set

import structlog

from src.plugins.runtime import index_expiry, integrity, sandbox, watchdog
from src.plugins.runtime.children import ChildLedger
from src.plugins.runtime.dispatch import HostDispatcher
from src.plugins.runtime.process import PluginProcess, PluginSpec, ProcessEnded
from src.plugins.runtime.socket_server import PluginSocketManager

logger = structlog.get_logger()

INTENTIONAL = frozenset({"disabled", "revoked", "safe_mode", "shutdown", "crash_loop", "killed", "restart", "idle", "paused"})
IDLE = "idle"
TIER0_STATE = "declarative"
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


class SupervisorError(RuntimeError):
    pass


class Supervisor:

    def __init__(self, state_dir: Path, app_version: str, dispatcher: HostDispatcher, alert: Alert, cancel_side_effects: Cancel,
                 activity: Callable[[Dict[str, Any]], None], safe_mode: bool = False, index: Optional[Mapping[str, Any]] = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 sampler: watchdog.Sampler = watchdog.usage_of, children: Optional[ChildLedger] = None,
                 clock: Callable[[], float] = time.monotonic, call_later: Optional[CallLater] = None, idle_seconds: float = IDLE_SECONDS,
                 sockets: Optional[PluginSocketManager] = None) -> None:
        self._children = children
        self._sockets = sockets or PluginSocketManager()
        self._explicit_sockets = sockets is not None
        self.on_stopped: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_started: Optional[Callable[[PluginSpec], Awaitable[None]]] = None
        self.on_state_change: Optional[Callable[[str, str], None]] = None
        self._state_dir, self._app_version, self._dispatcher = Path(state_dir), app_version, dispatcher
        self._alert, self._cancel, self._activity = alert, cancel_side_effects, activity
        self._safe_mode, self._index, self._sleep, self._sampler = safe_mode, index, sleep, sampler
        self._specs: Dict[str, PluginSpec] = {}
        self._procs: Dict[str, PluginProcess] = {}
        self._strikes: Dict[str, watchdog.StrikeLedger] = {}
        self._state: Dict[str, str] = {}
        self._paused: set = set()
        self._restart_counts: Dict[str, int] = {}
        self._revoked: set = set()
        self._index_override: set = set()
        self._runtime_dir: Optional[Path] = None
        self._restarts: Dict[str, asyncio.Task] = {}
        self._clock, self._call_later, self._idle_seconds = clock, call_later, idle_seconds
        self._locks: Dict[str, asyncio.Lock] = {}
        self._lock_owners: Dict[str, asyncio.Task[Any]] = {}
        self._safe_mode_tasks: Set[asyncio.Task[Any]] = set()
        self._epochs: Dict[str, int] = {}
        self._last_used: Dict[str, float] = {}
        self._idle_timers: Dict[str, Any] = {}
        self._tasks: set = set()

    def _notify_state(self, plugin_id: str) -> None:
        if self.on_state_change is None:
            return
        try:
            self.on_state_change(plugin_id, self.state(plugin_id))
        except Exception:  # noqa: BLE001
            pass

    def state(self, plugin_id: str) -> str:
        return self._state.get(plugin_id, "unknown")

    def is_paused(self, plugin_id: str) -> bool:
        return plugin_id in self._paused or self._state.get(plugin_id) == "paused"

    def restart_count(self, plugin_id: str) -> int:
        return int(self._restart_counts.get(plugin_id, 0))

    def set_safe_mode(self, on: bool) -> None:
        self._safe_mode = on

    async def set_index(self, index: Optional[Mapping[str, Any]]) -> None:
        self._index = index
        for pid, spec in list(self._specs.items()):
            if spec.ctx.tier != "catalog" or not (pid in self._procs or self._state.get(pid) in (IDLE, TIER0_STATE, "backing_off")):
                continue
            if self._index_revokes(spec):
                await self.revoke(pid, "revoked_in_index")
            elif not self._index_fresh(pid):
                async with self._hold_lock(pid):
                    self._alert(pid, ALERT_INDEX, "index_expired")
                    await self._disable_locked(pid, "index_expired")
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
        if pid in self._paused:
            return "paused"
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

    def _wants_socket(self, spec: PluginSpec) -> bool:
        return (not spec.tier0) and (bool(spec.run_cmd) or self._explicit_sockets)

    def _layout(
        self,
        spec: PluginSpec,
        *,
        sock_path: Optional[Path] = None,
        carnivore_bin: Optional[Path] = None,
    ) -> sandbox.Layout:
        if self._runtime_dir is None:
            self._runtime_dir = sandbox.copy_runtime(self._state_dir, self._app_version)
        code_dir = Path(os.path.realpath(spec.code_dir))
        data_dir = Path(os.path.realpath(spec.ctx.data_dir))
        rt = sandbox.resolve_runtime(
            spec.run_cmd,
            code_dir,
            allow_fork_for_bin=bool(carnivore_bin is not None and bool(spec.run_cmd)),
        )
        return sandbox.Layout(
            interpreter=rt.interpreter,
            stdlib_root=rt.stdlib_root,
            runtime_dir=self._runtime_dir,
            code_dir=code_dir,
            data_dir=data_dir,
            runtime_kind=rt.kind,
            read_roots=rt.read_roots,
            exec_paths=rt.exec_paths,
            allow_fork=rt.allow_fork,
            socket_path=sock_path,
            carnivore_bin=carnivore_bin,
            plugin_id=spec.ctx.plugin_id if spec.run_cmd else "",
            run_mode=spec.run_mode,
            pythonpath_extra=rt.pythonpath_extra,
        )

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

    def _bump_epoch(self, plugin_id: str) -> int:
        nxt = self._epochs.get(plugin_id, 0) + 1
        self._epochs[plugin_id] = nxt
        return nxt

    @contextlib.asynccontextmanager
    async def _hold_lock(self, plugin_id: str) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and self._lock_owners.get(plugin_id) is task:
            yield
            return
        async with self._lock(plugin_id):
            if task is not None:
                self._lock_owners[plugin_id] = task
            try:
                yield
            finally:
                if self._lock_owners.get(plugin_id) is task:
                    self._lock_owners.pop(plugin_id, None)

    async def enable(self, spec: PluginSpec) -> str:
        async with self._hold_lock(spec.ctx.plugin_id):
            return await self._enable_locked(spec)

    async def _enable_locked(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        refused = await self._judge(spec)
        if refused is not None:
            existing = self._procs.get(pid)
            if existing is not None and not existing.ended:
                await self._disable_locked(pid, "disabled")
                self._state[pid] = refused
            elif existing is not None:
                self._procs.pop(pid, None)
            return refused
        if spec.tier0:
            existing = self._procs.get(pid)
            if existing is not None and not existing.ended:
                await self._disable_locked(pid, "restart")
            elif existing is not None:
                self._procs.pop(pid, None)
            self._state[pid] = TIER0_STATE
            if self.on_started is not None:
                await self.on_started(spec)
            return TIER0_STATE
        existing = self._procs.get(pid)
        if existing is not None and not existing.ended:
            await self._disable_locked(pid, "restart")
        elif existing is not None:
            self._procs.pop(pid, None)
        return await self._spawn(spec)

    async def activate(self, spec: PluginSpec) -> str:
        async with self._hold_lock(spec.ctx.plugin_id):
            return await self._activate_locked(spec)

    async def _activate_locked(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        if spec.tier0:
            was_tier0 = self._state.get(pid) == TIER0_STATE
            refused = await self._judge(spec)
            if refused is not None:
                if was_tier0 and self.on_stopped is not None:
                    await self.on_stopped(pid)
                return self._state[pid]
            self._state[pid] = TIER0_STATE
            if self.on_started is not None:
                await self.on_started(spec)
            return TIER0_STATE
        proc = self._procs.get(pid)
        if proc is not None and not proc.ended:
            return self._state.get(pid, "running")
        if spec.subscriptions or spec.timers:
            return await self._enable_locked(spec)
        refused = await self._judge(spec)
        if refused is None:
            self._state[pid] = IDLE
        return self._state[pid]

    async def ensure(self, plugin_id: str) -> Optional[PluginProcess]:
        async with self._hold_lock(plugin_id):
            if plugin_id in self._paused or self._state.get(plugin_id) == "paused":
                return None
            spec = self._specs.get(plugin_id)
            if spec is not None and spec.tier0:
                return None
            proc = self._procs.get(plugin_id)
            if proc is not None and not proc.ended:
                self.touch(plugin_id)
                return proc
            if spec is not None and self._state.get(plugin_id) == IDLE:
                await self._enable_locked(spec)
            proc = self._procs.get(plugin_id)
            return None if proc is None or bool(getattr(proc, "ended", None)) else proc

    async def deliver_event(self, plugin_id: str, family: str, seq: int, payload: Any) -> bool:
        proc = await self.ensure(plugin_id)
        return proc is not None and await proc.deliver_event(family, seq, payload)

    def touch(self, plugin_id: str) -> None:
        self._last_used[plugin_id] = self._clock()

    def available(self, plugin_id: str) -> bool:
        proc = self._procs.get(plugin_id)
        return (proc is not None and not proc.ended) or self._state.get(plugin_id) in (IDLE, TIER0_STATE)

    async def _recheck_mid_spawn(self, spec: PluginSpec, epoch: int) -> Optional[str]:
        pid = spec.ctx.plugin_id
        if self._epochs.get(pid, 0) != epoch or self._specs.get(pid) is not spec:
            return self._state.get(pid, "disabled")
        refused = self.admit(spec)
        if refused is not None:
            state = "disabled (safe mode)" if refused == "safe_mode" else refused
            if self._state.get(pid) not in ("revoked", "killed", "paused", "disabled", "disabled (safe mode)"):
                self._state[pid] = state
            return state
        if spec.code_digest is not None and not self._code_intact(spec):
            self._alert(pid, ALERT_INTEGRITY, "code_root_changed")
            await self.enter_safe_mode()
            self._state[pid] = "disabled (safe mode)"
            return "disabled (safe mode)"
        return None

    async def _spawn(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        epoch = self._epochs.get(pid, 0)
        sock_path: Optional[Path] = None
        carnivore_bin: Optional[Path] = None
        if self._wants_socket(spec):
            from src.core.cli_command import service as cli_service  # noqa: PLC0415

            shim = cli_service.shim_path(self._state_dir)
            if not shim.is_file():
                cli_service.write_shim(self._state_dir)
            carnivore_bin = Path(os.path.realpath(shim))
            sock_path = await self._sockets.ensure(
                self._state_dir,
                spec.ctx,
                self._dispatcher,
                is_active=lambda p=pid: p in self._procs or self._state.get(p) in ("running", IDLE),
            )
            aborted = await self._recheck_mid_spawn(spec, epoch)
            if aborted is not None:
                await self._sockets.stop(pid)
                return aborted
        try:
            if sock_path is None and carnivore_bin is None:
                layout = self._layout(spec)
            else:
                layout = self._layout(spec, sock_path=sock_path, carnivore_bin=carnivore_bin)
        except Exception:
            await self._sockets.stop(pid)
            raise
        prev_state = self._state.get(pid)
        proc_box: list[Optional[PluginProcess]] = [None]
        proc = PluginProcess(
            spec,
            layout,
            self._dispatcher,
            self._app_version,
            lambda reason, p=pid, ep=epoch, box=proc_box: self._exited(p, reason, proc=box[0], epoch=ep),
            self._sampler,
        )
        proc_box[0] = proc
        self._procs[pid] = proc
        try:
            await proc.start()
        except (ProcessEnded, asyncio.TimeoutError, OSError) as exc:
            if self._procs.get(pid) is proc:
                self._procs.pop(pid, None)
            await proc.stop("startup_failed")
            await self._sockets.stop(pid)
            reason = proc.ended if proc.ended and proc.ended != "startup_failed" else None
            if reason:
                logger.warning("cplug_start_failed", cplug=pid, reason=reason, error_type=type(exc).__name__)
            if self._epochs.get(pid, 0) == epoch and self._specs.get(pid) is spec:
                if reason == "integrity":
                    self._state[pid] = "integrity"
                    self._notify_state(pid)
                    self._alert(pid, ALERT_INTEGRITY, "integrity")
                elif prev_state != IDLE:
                    strike_reason = reason or "startup_failed"
                    if strike_reason not in INTENTIONAL:
                        ledger = self._strikes.setdefault(pid, watchdog.StrikeLedger())
                        if ledger.strike():
                            await self._crash_loop(pid, strike_reason)
                        else:
                            self._state[pid] = "backing_off"
                            self._notify_state(pid)
                            delay = ledger.backoff()
                            self._restarts[pid] = asyncio.create_task(self._restart_after(pid, delay))
            return self._state.get(pid, "disabled")
        aborted = await self._recheck_mid_spawn(spec, epoch)
        if aborted is not None:
            if self._procs.get(pid) is proc:
                self._procs.pop(pid, None)
            await proc.stop("disabled")
            await self._sockets.stop(pid)
            return aborted
        self._state[pid] = "running"
        self.touch(pid)
        if not spec.subscriptions and not spec.timers and spec.run_mode != "oneshot":
            self._arm_idle(pid, self._idle_seconds)
        if self._children is not None and proc.pid is not None:
            await asyncio.to_thread(self._children.record, pid, proc.pid)
            aborted = await self._recheck_mid_spawn(spec, epoch)
            if aborted is not None:
                if self._procs.get(pid) is proc:
                    self._procs.pop(pid, None)
                await proc.stop("disabled")
                await self._sockets.stop(pid)
                await asyncio.to_thread(self._children.forget, pid)
                return aborted
        if self.on_started is not None:
            await self.on_started(spec)
        self._notify_state(pid)
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
        async with self._hold_lock(pid):
            proc = self._procs.get(pid)
            if proc is None or proc.ended or self._state.get(pid) != "running":
                return
            if proc.busy > 0:
                self.touch(pid)
            left = self._last_used.get(pid, 0.0) + self._idle_seconds - self._clock()
            if left > 0:
                self._arm_idle(pid, left)
                return
            await self._disable_locked(pid, "idle")
            self._state[pid] = IDLE

    async def _exited(
        self,
        pid: str,
        reason: str,
        *,
        proc: Optional[PluginProcess] = None,
        epoch: Optional[int] = None,
    ) -> None:
        async with self._hold_lock(pid):
            if (epoch is not None and self._epochs.get(pid, 0) != epoch) or (
                proc is not None and self._procs.get(pid) is not proc
            ):
                return
            self._drop_idle(pid)
            await self._sockets.stop(pid)
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
            self._notify_state(pid)
            delay = ledger.backoff()
            self._restarts[pid] = asyncio.create_task(self._restart_after(pid, delay))

    async def _restart_after(self, pid: str, delay: float) -> None:
        await self._sleep(delay)
        async with self._hold_lock(pid):
            spec = self._specs.get(pid)
            if spec is not None and self._state.get(pid) == "backing_off":
                if self.admit(spec) is None:
                    self._restart_counts[pid] = self._restart_counts.get(pid, 0) + 1
                state = await self._enable_locked(spec)
                if state != "running":
                    self._notify_state(pid)

    async def _crash_loop(self, pid: str, reason: str) -> None:
        self._state[pid] = "crash_loop"
        self._notify_state(pid)
        self._alert(pid, ALERT_CRASH_LOOP, reason)
        self.cancel_effects(pid, "crash_loop")

    def cancel_effects(self, pid: str, why: str) -> None:
        counts = dict(self._cancel(pid))
        self._activity({"plugin": pid, "method": "side_effects.cancel", "outcome": why,
                       "detail": ",".join(f"{k}={v}" for k, v in sorted(counts.items()))})

    async def disable(self, plugin_id: str, reason: str = "disabled", *, stop_timeout: Optional[float] = None) -> None:
        async with self._hold_lock(plugin_id):
            await self._disable_locked(plugin_id, reason, stop_timeout=stop_timeout)

    async def _disable_locked(self, plugin_id: str, reason: str = "disabled", *, stop_timeout: Optional[float] = None) -> None:
        self._bump_epoch(plugin_id)
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        task = self._restarts.get(plugin_id)
        if task is not None and task is not current:
            self._restarts.pop(plugin_id, None)
            task.cancel()
        self._drop_idle(plugin_id)
        proc = self._procs.pop(plugin_id, None)
        self._state[plugin_id] = "disabled"
        await self._sockets.stop(plugin_id)
        if proc is not None:
            if stop_timeout is None:
                await proc.stop(reason)
            else:
                await proc.stop(reason, stop_timeout=stop_timeout)
            if self._children is not None:
                await asyncio.to_thread(self._children.forget, plugin_id)
        if self.on_stopped is not None and reason not in KEEP_HOST_STATE_REASONS:
            await self.on_stopped(plugin_id)
        self._notify_state(plugin_id)

    async def pause(self, plugin_id: str, *, stop_timeout: Optional[float] = None) -> str:
        self._paused.add(plugin_id)
        async with self._hold_lock(plugin_id):
            self._bump_epoch(plugin_id)
            task = self._restarts.pop(plugin_id, None)
            if task is not None:
                task.cancel()
            self._drop_idle(plugin_id)
            proc = self._procs.pop(plugin_id, None)
            self._state[plugin_id] = "paused"
            await self._sockets.stop(plugin_id)
            if proc is not None:
                if stop_timeout is None:
                    await proc.stop("paused")
                else:
                    await proc.stop("paused", stop_timeout=stop_timeout)
                if self._children is not None:
                    await asyncio.to_thread(self._children.forget, plugin_id)
            if self.on_stopped is not None:
                await self.on_stopped(plugin_id)
            self._notify_state(plugin_id)
            return "paused"

    async def resume(self, spec: PluginSpec) -> str:
        pid = spec.ctx.plugin_id
        async with self._hold_lock(pid):
            self._paused.discard(pid)
            if self._state.get(pid) == "paused":
                self._state.pop(pid, None)
            state = await self._activate_locked(spec)
            self._notify_state(pid)
            return state

    async def kill(self, plugin_id: str) -> None:
        async with self._hold_lock(plugin_id):
            await self._kill_locked(plugin_id)

    async def _kill_locked(self, plugin_id: str) -> None:
        self._bump_epoch(plugin_id)
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        task = self._restarts.get(plugin_id)
        if task is not None and task is not current:
            self._restarts.pop(plugin_id, None)
            task.cancel()
        self._drop_idle(plugin_id)
        proc = self._procs.pop(plugin_id, None)
        self._state[plugin_id] = "killed"
        await self._sockets.stop(plugin_id)
        if proc is not None:
            await proc.kill("killed")
            if self._children is not None:
                await asyncio.to_thread(self._children.forget, plugin_id)
        if self.on_stopped is not None:
            await self.on_stopped(plugin_id)
        self.cancel_effects(plugin_id, "killed")
        self._notify_state(plugin_id)

    async def restart(self, spec: PluginSpec, *, stop_timeout: Optional[float] = None) -> str:
        pid = spec.ctx.plugin_id
        async with self._hold_lock(pid):
            self._paused.discard(pid)
            self._restart_counts[pid] = self._restart_counts.get(pid, 0) + 1
            await self._disable_locked(pid, "restart", stop_timeout=stop_timeout)
            self._strikes.pop(pid, None)
            state = await self._enable_locked(spec)
            self._notify_state(pid)
            return state

    def forget(self, plugin_id: str) -> None:
        proc = self._procs.get(plugin_id)
        if proc is not None and not proc.ended:
            raise SupervisorError(f"cannot forget running plugin {plugin_id}; call disable() first")
        lock = self._locks.get(plugin_id)
        if lock is not None and lock.locked():
            try:
                task = asyncio.current_task()
            except RuntimeError:
                task = None
            if task is None or self._lock_owners.get(plugin_id) is not task:
                raise SupervisorError(f"cannot forget plugin {plugin_id} while a supervisor operation is in flight")
        self._bump_epoch(plugin_id)
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        task = self._restarts.get(plugin_id)
        if task is not None and task is not current:
            self._restarts.pop(plugin_id, None)
            task.cancel()
        self._drop_idle(plugin_id)
        for table in (self._specs, self._procs, self._strikes, self._state, self._last_used, self._restart_counts):
            table.pop(plugin_id, None)
        lock = self._locks.get(plugin_id)
        if lock is not None and not lock.locked():
            self._locks.pop(plugin_id, None)
        self._paused.discard(plugin_id)
        self._revoked.discard(plugin_id)
        self._index_override.discard(plugin_id)

    async def forget_plugin(self, plugin_id: str) -> None:
        async with self._hold_lock(plugin_id):
            proc = self._procs.get(plugin_id)
            if proc is not None and not proc.ended:
                await self._disable_locked(plugin_id, "purged")
            self.forget(plugin_id)

    async def revoke(self, plugin_id: str, reason: str = "revoked") -> None:
        self._revoked.add(plugin_id)
        self._bump_epoch(plugin_id)
        async with self._hold_lock(plugin_id):
            self._revoked.add(plugin_id)
            await self._disable_locked(plugin_id, "revoked")
            self._state[plugin_id] = "revoked"
            self._notify_state(plugin_id)
            self._alert(plugin_id, ALERT_REVOKED, reason)
            self.cancel_effects(plugin_id, "revoked")

    async def enter_safe_mode(self) -> None:
        self._safe_mode = True
        task = asyncio.current_task()
        if task is not None:
            self._safe_mode_tasks.add(task)
        try:
            targets = sorted({*self._procs, *(p for p, s in self._state.items() if s in (IDLE, TIER0_STATE))})
            for pid in targets:
                owner = self._lock_owners.get(pid)
                if owner is not None and owner is not task and owner in self._safe_mode_tasks:
                    continue
                async with self._hold_lock(pid):
                    await self._disable_locked(pid, "safe_mode")
                    self._state[pid] = "disabled (safe mode)"
                    self._notify_state(pid)
        finally:
            if task is not None:
                self._safe_mode_tasks.discard(task)

    async def shutdown(self) -> None:
        for pid in list({*self._procs, *(p for p, s in self._state.items() if s == TIER0_STATE)}):
            await self.disable(pid, "shutdown")
        await self._sockets.stop_all()

    def process(self, plugin_id: str) -> Optional[PluginProcess]:
        proc = self._procs.get(plugin_id)
        return None if proc is None or bool(getattr(proc, "ended", None)) else proc
