
from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

import structlog

from src.plugins.runtime import frames, guards, log_redaction, sandbox, watchdog
from src.plugins.runtime.dispatch import HostDispatcher, PluginContext

logger = structlog.get_logger()

API_VERSION = "1.0"
REQUEST_TIMEOUT = 5.0
TOOL_CALL_TIMEOUT = 30.0
STOP_TIMEOUT = 5.0
PING_INTERVAL = 10.0
DISK_INTERVAL = 60.0
EVENTS_PER_SECOND = 20
ERROR_MESSAGE_LOG_CHARS = 200
MAX_ONESHOT_STDOUT_BYTES = frames.MAX_FRAME_BYTES
MAX_ONESHOT_STDERR_BYTES = frames.MAX_CALL_OUTPUT_BYTES
UI_RENDER_METHOD = "ui.render"
SDK_UNHANDLED_MESSAGE = "KeyError"
FEED_GRANTS = {"feed.meta": ("feed.view: meta", "feed.view: scrubbed", "feed.view: raw", "feed:meta", "feed:scrub", "feed:raw"),
               "feed.scrubbed": ("feed.view: scrubbed", "feed.view: raw", "feed:scrub", "feed:raw"),
               "feed.raw": ("feed.view: raw", "feed:raw"),
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
    timers: Mapping[str, int] = field(default_factory=dict)
    run_cmd: Tuple[str, ...] = ()
    run_mode: str = "rpc"
    tier0: bool = False


class ProcessEnded(Exception):

    def __init__(self, reason: str, code: Optional[int] = None, message: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code
        self.message = message
        self.no_such_surface = False


def is_no_such_surface(method: Optional[str], code: Optional[int], message: str) -> bool:
    return method == UI_RENDER_METHOD and (code == frames.METHOD_NOT_FOUND or (code == frames.INTERNAL_ERROR and message == SDK_UNHANDLED_MESSAGE))


def plugin_error_of(plugin_id: str, method: Optional[str], error: Dict[str, Any]) -> ProcessEnded:
    raw_code = error.get("code")
    code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
    message = str(error.get("message", ""))[:ERROR_MESSAGE_LOG_CHARS]
    known = is_no_such_surface(method, code, message)
    (logger.debug if known else logger.info)("cplug_error_frame", cplug=plugin_id, method=method, code=code, message=message)
    exc = ProcessEnded("plugin_error", code, message)
    exc.no_such_surface = known
    return exc


async def _kill_pgid_and_wait(pgid: int, timeout: float = 0.5) -> None:
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        pass

    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            pass
        if time.monotonic() >= deadline:
            return
        await asyncio.sleep(0.005)


def _signal_subprocess_group(proc: Any) -> None:
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            if getattr(proc, "returncode", None) is None and callable(getattr(proc, "kill", None)):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    tr = getattr(proc, "_transport", None)
    if tr is not None:
        try:
            tr.close()
        except RuntimeError:
            pass


async def _cleanup_subprocess(proc: Any) -> None:
    _signal_subprocess_group(proc)
    wait_fn = getattr(proc, "wait", None)
    if not callable(wait_fn):
        return
    if getattr(proc, "returncode", None) is None:
        try:
            await asyncio.wait_for(wait_fn(), timeout=2.0)
        except (asyncio.TimeoutError, RuntimeError):
            pass
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        await _kill_pgid_and_wait(pid)


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
        self._methods: Dict[int, str] = {}
        self._tasks: Set[asyncio.Task] = set()
        self._active_oneshots: Set[asyncio.subprocess.Process] = set()
        self._oneshot_tasks: Set[asyncio.Task[Any]] = set()
        self._stderr_log = log_redaction.StderrLog(spec.ctx.plugin_id)
        self.stderr = self._stderr_log.kept
        self.ended: Optional[str] = None
        self.started_at = 0.0
        self.startup_seconds = 0.0
        self.negotiated: Dict[str, Any] = {}
        self._event_window: List[float] = []
        self.busy = 0
        self._busy_wake = asyncio.Event()
        self._profile_path: Optional[Path] = None

    @property
    def pid(self) -> Optional[int]:
        return None if self._proc is None else self._proc.pid

    def _resolve_script_args(self, rt: sandbox.ResolvedRuntime) -> Tuple[List[str], bool]:
        code_real = Path(os.path.realpath(self._layout.code_dir))
        out: List[str] = []
        replaced = False
        first = True
        for arg in rt.args:
            if not replaced and not arg.startswith("-"):
                if first and rt.kind == "bun" and arg == "run":
                    first = False
                    out.append(arg)
                    continue
                arg_path = Path(arg)
                cand = Path(os.path.realpath(arg_path if arg_path.is_absolute() else code_real / arg_path))
                if not cand.is_relative_to(code_real):
                    raise ProcessEnded("violation:script_outside_code_dir")
                if cand.is_file():
                    out.append(str(cand))
                    replaced = True
                    first = False
                    continue
            first = False
            out.append(arg)
        return out, replaced

    def _argv_and_env(self) -> Tuple[List[str], Dict[str, str]]:
        rt = sandbox.resolve_runtime(
            getattr(self.spec, "run_cmd", ()),
            self._layout.code_dir,
            allow_fork_for_bin=bool(self._layout.carnivore_bin),
        )
        profile = None if self.spec.unrestricted else (self._profile_path or sandbox.write_profile(self._layout))
        self._profile_path = profile
        env = sandbox.allow_env(self._layout, self.spec.locale, self.spec.unrestricted)
        if getattr(self.spec, "run_mode", "rpc") == "oneshot":
            if rt.kind in ("python", "uv"):
                script_args, found_script = self._resolve_script_args(rt)
                if not found_script:
                    script_rel = self.spec.entry.replace(".", "/") + ".py"
                    code_real = Path(os.path.realpath(self._layout.code_dir))
                    entry_path = Path(os.path.realpath(code_real / script_rel))
                    if not entry_path.is_relative_to(code_real):
                        raise ProcessEnded("violation:script_outside_code_dir")
                    script_args = [*script_args, str(entry_path)]
                cmd = [str(rt.primary_exec), "-B", "-s", *script_args]
                extra_pp = [str(self._layout.runtime_dir), str(self._layout.code_dir), *(str(p) for p in rt.pythonpath_extra)]
                env["PYTHONPATH"] = os.pathsep.join(extra_pp)
            else:
                cmd_args, _ = self._resolve_script_args(rt)
                if rt.kind == "node":
                    preload = self._layout.runtime_dir / "sdk_ts" / "node_preload.mjs"
                    if preload.is_file():
                        cmd_args = [f"--import={preload}", *cmd_args]
                elif rt.kind == "bun":
                    tsconfig = self._layout.runtime_dir / "sdk_ts" / "bun_paths.json"
                    if tsconfig.is_file():
                        cmd_args = [f"--tsconfig-override={tsconfig}", *cmd_args]
                cmd = [str(rt.primary_exec), *cmd_args]
            return sandbox.build_polyglot_command(self._layout, profile, cmd, unrestricted=self.spec.unrestricted), env

        if rt.kind in ("python", "uv"):
            if self.spec.unrestricted:
                argv = sandbox.build_unrestricted_command(self._layout, self.spec.entry, watchdog.DISK_QUOTA_BYTES)
            else:
                assert profile is not None
                argv = sandbox.build_command(self._layout, profile, self.spec.entry, watchdog.DISK_QUOTA_BYTES)
            return argv, env

        cmd_args, _ = self._resolve_script_args(rt)
        if rt.kind == "node":
            preload = self._layout.runtime_dir / "sdk_ts" / "node_preload.mjs"
            if preload.is_file():
                cmd_args = [f"--import={preload}", *cmd_args]
        elif rt.kind == "bun":
            tsconfig = self._layout.runtime_dir / "sdk_ts" / "bun_paths.json"
            if tsconfig.is_file():
                cmd_args = [f"--tsconfig-override={tsconfig}", *cmd_args]
        cmd = [str(rt.primary_exec), *cmd_args]
        return sandbox.build_polyglot_command(self._layout, profile, cmd, unrestricted=self.spec.unrestricted), env

    async def start(self) -> None:
        files = self._layout.files_dir
        files.mkdir(parents=True, exist_ok=True)
        began = time.monotonic()
        if getattr(self.spec, "run_mode", "rpc") == "oneshot":
            if not self.spec.unrestricted:
                self._profile_path = sandbox.write_profile(self._layout)
            self.negotiated = {
                "capabilities": sorted(self.spec.capabilities),
                "subscriptions": sorted(self.spec.subscriptions),
            }
            self.started_at = time.monotonic()
            self.startup_seconds = self.started_at - began
            return
        argv, env = self._argv_and_env()
        self._proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd=str(files), start_new_session=True)
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

    async def _oneshot_request(self, method: str, params: Dict[str, Any], timeout: float) -> Any:
        if self.ended:
            raise ProcessEnded(self.ended)
        if method in ("ping", "shutdown"):
            return {}
        files = self._layout.files_dir
        files.mkdir(parents=True, exist_ok=True)
        payload = frames.encode({"id": 1, "method": method, "params": params})
        argv, env = self._argv_and_env()
        if method == "service.call" and isinstance(params, dict) and isinstance(params.get("_bus_token"), str) and params["_bus_token"]:
            env["CARNIVORE_BUS_TOKEN"] = params["_bus_token"]
        proc_holder: List[Optional[asyncio.subprocess.Process]] = [None]
        stdout_buf = bytearray()
        call_stderr = log_redaction.StderrLog(self.spec.ctx.plugin_id)

        async def _run_oneshot() -> None:
            proc: Optional[asyncio.subprocess.Process] = None
            counted = False
            cancelled_exc: Optional[BaseException] = None
            try:
                self.busy += 1
                counted = True
                proc = await asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env=env, cwd=str(files), start_new_session=True)
                proc_holder[0] = proc
                self._active_oneshots.add(proc)
                if self.ended:
                    raise ProcessEnded(self.ended)

                async def _write_stdin() -> None:
                    assert proc.stdin is not None
                    try:
                        proc.stdin.write(payload)
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        try:
                            proc.stdin.close()
                        except (OSError, RuntimeError):
                            pass

                async def _read_stdout() -> None:
                    assert proc.stdout is not None
                    while True:
                        chunk = await proc.stdout.read(65536)
                        if not chunk:
                            return
                        if len(stdout_buf) + len(chunk) > MAX_ONESHOT_STDOUT_BYTES:
                            raise ProcessEnded(
                                "violation:frame_too_large",
                                frames.TOO_LARGE,
                                f"oneshot output exceeded {MAX_ONESHOT_STDOUT_BYTES} bytes",
                            )
                        stdout_buf.extend(chunk)

                async def _drain_stderr() -> None:
                    assert proc.stderr is not None
                    total = 0
                    try:
                        while True:
                            chunk = await proc.stderr.read(4096)
                            if not chunk:
                                return
                            total += len(chunk)
                            if total > MAX_ONESHOT_STDERR_BYTES:
                                raise ProcessEnded(
                                    "violation:call_output_exceeded",
                                    frames.TOO_LARGE,
                                    f"oneshot stderr exceeded {MAX_ONESHOT_STDERR_BYTES} bytes",
                                )
                            call_stderr.feed(chunk)
                    finally:
                        call_stderr.close()

                tasks = [
                    asyncio.create_task(_write_stdin()),
                    asyncio.create_task(_read_stdout()),
                    asyncio.create_task(_drain_stderr()),
                    asyncio.create_task(proc.wait()),
                ]
                try:
                    await asyncio.gather(*tasks)
                except BaseException:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    _signal_subprocess_group(proc)
                    if tasks:
                        gather_fut = asyncio.gather(*tasks, return_exceptions=True)
                        while not gather_fut.done():
                            try:
                                await asyncio.shield(gather_fut)
                            except asyncio.CancelledError as exc:
                                cancelled_exc = exc
                    raise
            finally:
                if proc is not None:
                    cleanup_task = asyncio.ensure_future(_cleanup_subprocess(proc))
                    while not cleanup_task.done():
                        try:
                            await asyncio.shield(cleanup_task)
                        except asyncio.CancelledError as exc:
                            cancelled_exc = exc
                    self._active_oneshots.discard(proc)
                if counted:
                    self.busy -= 1
                if call_stderr.kept:
                    room = max(0, log_redaction.STDERR_CAP - len(self._stderr_log.kept))
                    if room:
                        self._stderr_log.kept.extend(bytes(call_stderr.kept[:room]))
            if cancelled_exc is not None:
                raise cancelled_exc

        run_task = asyncio.create_task(_run_oneshot())
        self._oneshot_tasks.add(run_task)
        run_task.add_done_callback(self._oneshot_tasks.discard)
        try:
            await asyncio.wait_for(run_task, timeout)
        except asyncio.CancelledError:
            cur = asyncio.current_task()
            if self.ended and (cur is None or cur.cancelling() == 0):
                raise ProcessEnded(self.ended) from None
            raise

        proc = proc_holder[0]
        assert proc is not None

        text = bytes(stdout_buf).decode("utf-8", errors="replace").strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            last = lines[-1]
            try:
                doc = json.loads(last)
            except ValueError:
                doc = None
            if isinstance(doc, dict) and doc.get("jsonrpc") == "2.0" and ("result" in doc or "error" in doc):
                if doc.get("error"):
                    raise plugin_error_of(self.spec.ctx.plugin_id, method, doc["error"])
                if proc.returncode != 0:
                    raise ProcessEnded("plugin_error", frames.INTERNAL_ERROR, f"oneshot_exit_{proc.returncode}")
                return doc.get("result")
        if proc.returncode != 0:
            raise ProcessEnded("plugin_error", frames.INTERNAL_ERROR, f"oneshot_exit_{proc.returncode}")
        if lines:
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if parsed is not None:
                if method == "route.handle":
                    if isinstance(parsed, dict) and "status" in parsed and "body" in parsed:
                        return parsed
                    return {"status": 200, "body": parsed}
                if method == "tools/call":
                    if isinstance(parsed, dict) and "content" in parsed:
                        return parsed
                    return {"content": [{"type": "text", "text": json.dumps(parsed)}]}
                return parsed
            if method == "route.handle":
                return {"status": 200, "body": {"text": text}}
            if method == "tools/call":
                return {"content": [{"type": "text", "text": text}]}
            return {"text": text}
        return {} if method != "route.handle" else {"status": 200, "body": {}}

    async def request(self, method: str, params: Dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> Any:
        if getattr(self.spec, "run_mode", "rpc") == "oneshot":
            return await self._oneshot_request(method, params, timeout)
        if self._proc is None or self.ended:
            raise ProcessEnded(self.ended or "not_started")
        self._next_id += 1
        rid = self._next_id
        data = frames.encode({"id": rid, "method": method, "params": params})
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiting[rid] = fut
        self._methods[rid] = method
        self._guard.expect_response(rid)
        counted = method != "ping"
        if counted:
            self.busy += 1
            self._busy_wake.set()
        try:
            await self._send(data)
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, ProcessEnded):
            self._guard.forget(rid)
            self._waiting.pop(rid, None)
            raise
        finally:
            self._methods.pop(rid, None)
            if counted:
                self.busy -= 1

    async def deliver_event(self, family: str, seq: int, payload: Any) -> bool:
        if family not in self.negotiated.get("subscriptions", ()):
            return False
        needed = FEED_GRANTS.get(family)
        if needed is not None:
            if not any(g in self.spec.ctx.granted for g in needed):
                return False
        elif family.startswith("webhook."):
            hook_name = family.removeprefix("webhook.")
            if f"hooks.inbound:{hook_name}" not in self.spec.ctx.granted:
                return False
        else:
            if f"events:{family}" not in self.spec.ctx.granted:
                return False
        if getattr(self.spec, "run_mode", "rpc") == "oneshot":
            try:
                await self._oneshot_request("event.deliver", {"family": family, "seq": seq, "payload": payload}, REQUEST_TIMEOUT)
                return True
            except (ProcessEnded, asyncio.TimeoutError, OSError):
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
        if self._proc is None or self._proc.stdin is None or self._proc.stdin.is_closing():
            raise ProcessEnded("exited")
        try:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, RuntimeError) as exc:
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
                    fut.set_exception(plugin_error_of(self.spec.ctx.plugin_id, self._methods.get(frame.id or 0), frame.error))
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
        try:
            while True:
                chunk = await self._proc.stderr.read(4096)
                if not chunk:
                    return
                self._stderr_log.feed(chunk)
        finally:
            self._stderr_log.close()

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
        if self._proc is not None:
            _signal_subprocess_group(self._proc)
        oneshots = list(self._active_oneshots)
        for oproc in oneshots:
            _signal_subprocess_group(oproc)
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(ProcessEnded(reason))
        self._waiting.clear()
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        oneshot_tasks = [t for t in self._oneshot_tasks if t is not current]
        for task in oneshot_tasks:
            if not task.done():
                task.cancel()
        if oneshot_tasks:
            await asyncio.gather(*oneshot_tasks, return_exceptions=True)
        for oproc in oneshots:
            await _cleanup_subprocess(oproc)
        if self._proc is not None:
            await _cleanup_subprocess(self._proc)
        await self._on_exit(reason)

    async def kill(self, reason: str = "killed") -> None:
        await self._end(reason)
        if self._oneshot_tasks:
            await asyncio.gather(*list(self._oneshot_tasks), return_exceptions=True)
        for oproc in list(self._active_oneshots):
            await _cleanup_subprocess(oproc)
        if self._proc is not None and callable(getattr(self._proc, "wait", None)):
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, RuntimeError):
                pass

    async def stop(self, reason: str = "disabled", *, stop_timeout: Optional[float] = None) -> None:
        timeout = STOP_TIMEOUT if stop_timeout is None else stop_timeout
        if not self.ended and self._proc is not None and timeout > 0:
            try:
                await self.request("shutdown", {"reason": reason}, timeout=timeout)
            except (asyncio.TimeoutError, ProcessEnded, frames.FrameViolation):
                pass
        await self._end(reason)
        if self._oneshot_tasks:
            await asyncio.gather(*list(self._oneshot_tasks), return_exceptions=True)
        for oproc in list(self._active_oneshots):
            await _cleanup_subprocess(oproc)
        if self._proc is not None and callable(getattr(self._proc, "wait", None)):
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, RuntimeError):
                pass
