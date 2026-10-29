
from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Set

import structlog

from src.cplugs.runtime import frames, guards, sandbox, watchdog
from src.cplugs.runtime.dispatch import HostDispatcher, PluginContext

logger = structlog.get_logger()

API_VERSION = "1.0"
REQUEST_TIMEOUT = 5.0
TOOL_CALL_TIMEOUT = 30.0
STOP_TIMEOUT = 5.0
PING_INTERVAL = 10.0
DISK_INTERVAL = 60.0
STDERR_CAP = 64 * 1024
EVENTS_PER_SECOND = 20
FEED_GRANTS = {"feed.meta": ("feed:meta", "feed:scrub", "feed:raw"), "feed.scrubbed": ("feed:scrub", "feed:raw"),
               "feed.raw": ("feed:raw",),
               "mcp.health": ("mcp.health.read",)}


@dataclass(frozen=True)
class PluginSpec:

    ctx: PluginContext
    code_dir: Path
    entry: str
    settings: Dict[str, Any] = field(default_factory=dict)
    capabilities: FrozenSet[str] = frozenset()
    subscriptions: FrozenSet[str] = frozenset()
    locale: str = "en"
    code_digest: Optional[str] = None
    catalog_id: str = ""
    version: str = ""
    unrestricted: bool = False
    trust_refusal: str = ""
    consent_owed: bool = False


class ProcessEnded(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PluginProcess:

    def __init__(self, spec: PluginSpec, layout: sandbox.Layout, dispatcher: HostDispatcher, app_version: str,
                 on_exit: Callable[[str], Awaitable[None]], sampler: watchdog.Sampler = watchdog.usage_of) -> None:
        self.spec, self._layout, self._dispatcher, self._app_version = spec, layout, dispatcher, app_version
        self._on_exit, self._sampler = on_exit, sampler
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._guard = frames.FrameGuard()
        self._split = frames.LineSplitter()
        self._next_id = 0
        self._waiting: Dict[int, asyncio.Future] = {}
        self._tasks: Set[asyncio.Task] = set()
        self.stderr = bytearray()
        self.ended: Optional[str] = None
        self.started_at = 0.0
        self.startup_seconds = 0.0
        self.negotiated: Dict[str, Any] = {}
        self._event_window: List[float] = []
        self.busy = 0
        self._busy_wake = asyncio.Event()

    @property
    def pid(self) -> Optional[int]:
        return None if self._proc is None else self._proc.pid

    async def start(self) -> None:
        files = self._layout.files_dir
        files.mkdir(parents=True, exist_ok=True)
        if self.spec.unrestricted:
            argv = sandbox.build_unrestricted_command(self._layout, self.spec.entry, watchdog.DISK_QUOTA_BYTES)
        else:
            profile = self._layout.data_dir / "profile.sb"
            profile.write_text(sandbox.render_profile(self._layout), encoding="utf-8")
            argv = sandbox.build_command(self._layout, profile, self.spec.entry, watchdog.DISK_QUOTA_BYTES)
        began = time.monotonic()
        self._proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=sandbox.allow_env(self._layout, self.spec.locale, self.spec.unrestricted), cwd=str(files), start_new_session=True)
        self._tasks = {asyncio.create_task(self._pump()), asyncio.create_task(self._drain_stderr()),
                       asyncio.create_task(self._watch())}
        try:
            reply = await self.request("initialize", {
                "api_version": API_VERSION, "app_version": self._app_version, "plugin_id": self.spec.ctx.plugin_id,
                "install_name": self.spec.ctx.plugin_id, "granted": sorted(self.spec.ctx.granted),
                "data_dir": str(self._layout.files_dir), "settings": self.spec.settings, "tier": self.spec.ctx.tier,
                "locale": self.spec.locale})
            caps = reply.get("capabilities") if isinstance(reply, dict) else None
            subs = reply.get("subscriptions") if isinstance(reply, dict) else None
            if not isinstance(caps, dict) or not isinstance(subs, list):
                await self._end("integrity")
                raise ProcessEnded("integrity")
            self.negotiated = {"capabilities": sorted(k for k, v in caps.items() if v and k in self.spec.capabilities),
                               "subscriptions": sorted(s for s in subs if isinstance(s, str) and s in self.spec.subscriptions)}
            if self.spec.ctx.manifest_tools:
                guards.pin_tools(list(self.spec.ctx.manifest_tools), await self.request("tools/list", {}))
        except guards.Refused:
            await self._end("integrity")
            raise ProcessEnded("integrity") from None
        self.started_at = time.monotonic()
        self.startup_seconds = self.started_at - began

    async def request(self, method: str, params: Dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> Any:
        if self._proc is None or self.ended:
            raise ProcessEnded(self.ended or "not_started")
        self._next_id += 1
        rid = self._next_id
        data = frames.encode({"id": rid, "method": method, "params": params})
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiting[rid] = fut
        self._guard.expect_response(rid)
        counted = method != "ping"
        if counted:
            self.busy += 1
            self._busy_wake.set()
        try:
            await self._send(data)
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._guard.forget(rid)
            self._waiting.pop(rid, None)
            raise
        finally:
            if counted:
                self.busy -= 1

    async def deliver_event(self, family: str, seq: int, payload: Any) -> bool:
        needed = FEED_GRANTS.get(family)
        if family not in self.negotiated.get("subscriptions", ()) or (needed and not any(g in self.spec.ctx.granted for g in needed)):
            return False
        return await self._notify("event.deliver", {"family": family, "seq": seq, "payload": payload})

    async def _notify(self, method: str, params: Dict[str, Any]) -> bool:
        now = time.monotonic()
        self._event_window = [t for t in self._event_window if now - t < 1.0]
        if self.ended or self._proc is None or len(self._event_window) >= EVENTS_PER_SECOND:
            return False
        self._event_window.append(now)
        await self._send(frames.encode({"method": method, "params": params}))
        return True

    async def _send(self, data: bytes) -> None:
        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ProcessEnded("exited") from exc

    async def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                chunk = await self._proc.stdout.read(65536)
                if not chunk:
                    await self._end("exited")
                    return
                for line in self._split.feed(chunk):
                    await self._frame(self._guard.parse(line))
        except frames.FrameViolation as exc:
            logger.warning("cplug_frame_violation", cplug=self.spec.ctx.plugin_id, code=exc.code)
            await self._end(f"violation:{exc.code}")

    async def _frame(self, frame: frames.Frame) -> None:
        if frame.kind == "response":
            fut = self._waiting.pop(frame.id, None)
            if fut is not None and not fut.done():
                if frame.error:
                    fut.set_exception(ProcessEnded("plugin_error"))
                else:
                    fut.set_result(frame.result)
        elif frame.kind == "request":
            task = asyncio.create_task(self._serve(frame))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif frame.method == "log" and isinstance(frame.params, dict):
            try:
                await self._dispatcher.handle(self.spec.ctx, "log", frame.params)
            except guards.Refused:
                return

    async def _serve(self, frame: frames.Frame) -> None:
        try:
            outcome: Any = await self._dispatcher.handle(self.spec.ctx, frame.method or "", frame.params)
        except guards.Refused as refusal:
            outcome = refusal
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_service_error", cplug=self.spec.ctx.plugin_id, method=frame.method, error_type=type(exc).__name__)
            self._dispatcher.record(self.spec.ctx, frame.method or "", "internal_error", type(exc).__name__)
            outcome = guards.Refused("internal_error", type(exc).__name__)
        finally:
            self._guard.request_done()
        try:
            await self._send(self._dispatcher.reply(frame.id or 0, outcome))
        except ProcessEnded:
            return

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while True:
            chunk = await self._proc.stderr.read(4096)
            if not chunk:
                return
            self.stderr.extend(chunk[:max(0, STDERR_CAP - len(self.stderr))])

    async def _watch(self) -> None:
        began = last_ping = last_disk = time.monotonic()
        cpu = watchdog.CpuMeter()
        last_sample = 0.0
        while not self.ended:
            self._busy_wake.clear()
            try:
                await asyncio.wait_for(self._busy_wake.wait(), watchdog.next_delay(self.busy > 0, time.monotonic() - began))
            except asyncio.TimeoutError:
                pass
            if self._proc is None or self.ended:
                return
            gap = watchdog.BUSY_SAMPLE_SECONDS - (time.monotonic() - last_sample)
            if gap > 0 and last_sample:
                await asyncio.sleep(gap)
                if self._proc is None or self.ended:
                    return
            last_sample = time.monotonic()
            usage = await asyncio.to_thread(self._sampler, self._proc.pid)
            verdict = watchdog.check_memory(usage)
            now = time.monotonic()
            if verdict.ok and now - last_disk >= DISK_INTERVAL:
                last_disk = now
                verdict = await asyncio.to_thread(watchdog.check_disk, self._layout.files_dir)
            if verdict.ok and usage is not None:
                verdict = cpu.sample(usage.cpu)
            if not verdict.ok:
                logger.warning("cplug_resource_abuse", cplug=self.spec.ctx.plugin_id, reason=verdict.reason)
                await self._end("resource_abuse")
                return
            if now - last_ping >= PING_INTERVAL:
                last_ping = now
                try:
                    await self.request("ping", {})
                except (asyncio.TimeoutError, ProcessEnded):
                    await self._end("ping")
                    return

    async def _end(self, reason: str) -> None:
        if self.ended:
            return
        self.ended = reason
        if self._proc is not None and self._proc.returncode is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self._proc.kill()
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(ProcessEnded(reason))
        self._waiting.clear()
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        await self._on_exit(reason)

    async def kill(self, reason: str = "killed") -> None:
        await self._end(reason)
        if self._proc is not None:
            await self._proc.wait()

    async def stop(self, reason: str = "disabled") -> None:
        if not self.ended and self._proc is not None:
            try:
                await self.request("shutdown", {"reason": reason}, timeout=STOP_TIMEOUT)
            except (asyncio.TimeoutError, ProcessEnded, frames.FrameViolation):
                pass
        await self._end(reason)
        if self._proc is not None:
            await self._proc.wait()
