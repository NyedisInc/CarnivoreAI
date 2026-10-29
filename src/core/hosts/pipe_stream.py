
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.core.hosts.remote_host import RemoteHostUnavailable
from src.core.hosts.ssh_exec import posix_quote
from src.core.hosts.ssh_master import backoff_delay

logger = structlog.get_logger()

IDLE = "idle"
CONNECTING = "connecting"
STREAMING = "streaming"
RETRYING = "retrying"
STOPPED = "stopped"

_READ_BYTES = 64 * 1024


def tail_script(remote_path: str, offset: int) -> str:
    return (f"tail -c +{int(offset) + 1} -F {posix_quote(remote_path)} & t=$!; "
            "trap 'kill $t 2>/dev/null' EXIT HUP INT TERM; cat >/dev/null; kill $t 2>/dev/null")


class RemotePipeStream:

    def __init__(self, host: Any, remote_path: str, mirror_path: Path,
                 has_viewers: Callable[[], bool], *, name: str = "", gate_interval: float = 0.5,
                 linger: float = 30.0, stable_after: float = 30.0,
                 delay: Callable[[int], float] = backoff_delay) -> None:
        self.host = host
        self.remote_path = remote_path
        self.mirror_path = mirror_path
        self._has_viewers = has_viewers
        self.name = name
        self._gate = gate_interval
        self._linger = linger
        self._stable_after = stable_after
        self._delay = delay
        self.state = IDLE
        self.detail = ""
        self.position: Optional[int] = None
        self.bytes_copied = 0
        self.restarts = 0
        self._wanted_until = float("-inf")
        self._task: Optional[asyncio.Task[None]] = None
        self._wake = asyncio.Event()
        self._changed = asyncio.Event()
        self._channel: Any = None


    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._supervise(), name=f"remote-pipe-{self.name}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close_channel()
        self._set(STOPPED)

    async def ensure_streaming(self, timeout: float = 10.0) -> bool:
        self._wanted_until = asyncio.get_running_loop().time() + self._linger
        self.start()
        self._wake.set()
        try:
            async with asyncio.timeout(timeout):
                while self.state != STREAMING:
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            return False
        return True


    def _wanted(self, now: float) -> bool:
        try:
            viewed = bool(self._has_viewers())
        except Exception as exc:  # noqa: BLE001
            logger.warning("remote_pipe_viewer_probe_failed", name=self.name, error=str(exc))
            viewed = False
        if viewed:
            self._wanted_until = now + self._linger
        return now < self._wanted_until

    def _set(self, state: str, detail: str = "") -> None:
        if (state, detail) != (self.state, self.detail):
            self.state, self.detail = state, detail
            logger.info("remote_pipe_state", host=self.host.host_key, name=self.name, state=state,
                        detail=detail)
        self._changed.set()

    async def _pause(self, seconds: float) -> None:
        self._wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        attempt = 0
        while True:
            if not self._wanted(loop.time()):
                if self._channel is not None:
                    await self._close_channel()
                self.position = None
                attempt = 0
                self._set(IDLE)
                await self._pause(self._gate)
                continue
            self._set(CONNECTING)
            try:
                channel = await self._open()
            except (RemoteHostUnavailable, OSError) as exc:
                self._set(RETRYING, str(exc))
                await self._pause(self._delay(attempt))
                attempt += 1
                continue
            began = loop.time()
            self._set(STREAMING)
            if await self._run(channel):
                continue
            self.restarts += 1
            if loop.time() - began >= self._stable_after:
                attempt = 0
            self._set(RETRYING, "the output channel ended")
            await self._pause(self._delay(attempt))
            attempt += 1

    async def _open(self) -> Any:
        size = await self.host.file_size(self.remote_path)
        if self.position is None:
            self.position = size
        elif self.position > size:
            logger.info("remote_pipe_far_file_shrank", host=self.host.host_key, name=self.name,
                        position=self.position, size=size)
            self.position = 0
        channel = await self.host.spawn(tail_script(self.remote_path, self.position))
        self._channel = channel
        return channel

    async def _run(self, channel: Any) -> bool:
        loop = asyncio.get_running_loop()
        pump = asyncio.create_task(self._pump(channel))
        errors = asyncio.create_task(self._drain_stderr(channel))
        try:
            while True:
                done, _ = await asyncio.wait({pump}, timeout=self._gate)
                if done:
                    exc = pump.exception()
                    if exc is not None:
                        logger.warning("remote_pipe_copy_failed", host=self.host.host_key,
                                       name=self.name, error=f"{type(exc).__name__}: {exc}")
                    await self._close_channel()
                    return False
                if not self._wanted(loop.time()):
                    await self._close_channel()
                    return True
        finally:
            for task in (pump, errors):
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _pump(self, channel: Any) -> None:
        stdout = channel.process.stdout
        fd = os.open(str(self.mirror_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            while True:
                chunk = await stdout.read(_READ_BYTES)
                if not chunk:
                    return
                view = memoryview(chunk)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                self.position = (self.position or 0) + len(chunk)
                self.bytes_copied += len(chunk)
        finally:
            os.close(fd)

    async def _drain_stderr(self, channel: Any) -> None:
        stderr = channel.process.stderr
        if stderr is None:
            return
        while True:
            line = await stderr.readline()
            if not line:
                return
            logger.info("remote_pipe_tail_message", host=self.host.host_key, name=self.name,
                        message_bytes=len(line))

    async def _close_channel(self) -> None:
        channel, self._channel = self._channel, None
        if channel is None:
            return
        stdin = channel.process.stdin
        if stdin is not None:
            with contextlib.suppress(OSError, RuntimeError):
                stdin.close()
        await channel.close()
