
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.core import pipe_liveness
from src.core.hosts.pipe_stream import RemotePipeStream
from src.core.hosts.remote_host import RemoteHost, RemoteHostUnavailable
from src.core.hosts.ssh_exec import posix_quote
from src.core.tmux_transport.target import exact_pane_target
from src.core.tmux_transport.lifecycle import LocalLifecycle, script_word_needs_hex

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend

logger = structlog.get_logger()

REMOTE_ENV_NAMES = frozenset({"CLOUDECODE_SESSION_ID", "TERM", "COLORTERM", "LANG", "LC_ALL",
                              "LC_CTYPE"})


def remote_env(env: Optional[Dict[str, Optional[str]]], login_path: Optional[str]
               ) -> Dict[str, Optional[str]]:
    kept = {key: value for key, value in (env or {}).items()
            if value is None or key in REMOTE_ENV_NAMES or key.startswith("CLAUDE_CODE_")}
    if login_path:
        kept["PATH"] = login_path
    return kept


class RemoteLifecycle:

    def __init__(self, backend: "TmuxBackend", host: RemoteHost,
                 stream_options: Optional[Dict[str, Any]] = None) -> None:
        self._backend = backend
        self._host = host
        self._sync = LocalLifecycle(backend)
        self._stream: Optional[RemotePipeStream] = None
        self._stream_options = dict(stream_options or {})
        self._pending_size: Optional[Tuple[int, int]] = None
        self._resize_task: Optional[asyncio.Task[None]] = None
        self._alive: Optional[bool] = None
        self._alive_task: Optional[asyncio.Task[bool]] = None

    def spawn_env(self, env: Optional[dict]) -> Optional[dict]:
        return remote_env(env, self._host.login_path)

    def started(self) -> None:
        self._alive = True

    def literal_needs_hex(self, data: bytes) -> bool:
        return script_word_needs_hex(data)


    def resize(self, cols: int, rows: int) -> None:
        loop = self._host.loop
        if loop is None:
            return
        self._pending_size = (int(cols), int(rows))
        loop.call_soon_threadsafe(self._kick_resize)

    def _kick_resize(self) -> None:
        if self._resize_task is None or self._resize_task.done():
            self._resize_task = asyncio.ensure_future(self._send_resizes())

    async def _send_resizes(self) -> None:
        while self._pending_size is not None:
            cols, rows = self._pending_size
            self._pending_size = None
            try:
                await self._backend._run_tmux("resize-window", "-t", exact_pane_target(self._backend.tmux_session),
                                              "-x", str(cols), "-y", str(rows), check=False)
            except RemoteHostUnavailable as exc:
                logger.debug("remote_tmux_resize_error", host=self._host.host_key, error=str(exc))


    async def is_alive_async(self) -> bool:
        rc, _, _ = await self._backend._run_tmux(
            "has-session", "-t", f"={self._backend.tmux_session}", check=False)
        self._alive = rc == 0
        return self._alive

    def is_alive(self) -> bool:
        loop = self._host.loop
        try:
            on_loop = loop is not None and asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if not on_loop:
            self._alive = self._sync.is_alive()
            return self._alive
        if self._alive_task is None or self._alive_task.done():
            self._alive_task = loop.create_task(self._remeasure())
        return bool(self._alive)

    async def _remeasure(self) -> bool:
        try:
            return await self.is_alive_async()
        except RemoteHostUnavailable as exc:
            logger.debug("remote_liveness_unmeasured", host=self._host.host_key, error=str(exc))
            return bool(self._alive)

    def pid(self) -> Optional[int]:
        return None

    async def resume_presence(self, uuid: str, family: Optional[str]) -> Tuple[str, str]:
        from src.core.hosts.remote_claude_files import far_transcript_presence

        return await far_transcript_presence(self._host, uuid)


    def _ensure_stream(self) -> RemotePipeStream:
        if self._stream is None:
            from src.core.tmux_backend import _slugify

            backend = self._backend
            self._stream = RemotePipeStream(self._host, backend._pipe_write_path(),
                                            backend._resolve_pipe_path(), backend.has_viewers,
                                            name=_slugify(backend.slug), **self._stream_options)
        return self._stream

    async def read_started(self) -> None:
        self._ensure_stream().start()

    async def ensure_streaming(self, timeout: float) -> bool:
        return await self._ensure_stream().ensure_streaming(timeout)

    async def repair_stolen_pipe(self, repair: Callable[[], Awaitable[str]]) -> str:
        try:
            verdict = await repair()
            if verdict == pipe_liveness.FILE_MISSING:
                await self._backend.ensure_pipe_pane(force=True)
            return verdict
        except (RemoteHostUnavailable, RuntimeError) as exc:
            logger.info("remote_pipe_repair_unmeasured", host=self._host.host_key, error=str(exc))
            return "unmeasured"

    async def stopping(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        if self._alive_task is not None:
            self._alive_task.cancel()

    async def stopped(self) -> None:
        self._alive = False
        try:
            await self._host.exec(script=f"rm -f {posix_quote(self._backend._pipe_write_path())}")
        except RemoteHostUnavailable as exc:
            logger.info("remote_pipe_file_left", host=self._host.host_key, error=str(exc))
