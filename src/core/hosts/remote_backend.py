
from __future__ import annotations

import asyncio
import dataclasses
import subprocess
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core import pipe_liveness
from src.core.hosts.pipe_stream import RemotePipeStream
from src.core.hosts.remote_host import (
    RemoteHost,
    RemoteHostUnavailable,
    RemoteSyncOnLoopError,
)
from src.core.hosts.ssh_exec import posix_quote
from src.core.hosts.tmux_quote import TmuxQuoteError, escape_expanded
from src.core.tmux_backend import (
    LIST_TIMEOUT_SECONDS,
    TmuxBackend,
    _slugify,
)
from src.core.tmux_command_batch import COMMAND_SEPARATOR
from src.core.tmux_listing import (
    REASON_HOST_UNREACHABLE,
    REASON_PROBE_ERROR,
    REASON_TIMEOUT,
    TmuxListing,
    classify_listing_failure,
)
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME

logger = structlog.get_logger()

REMOTE_ENV_NAMES = frozenset({"CLOUDECODE_SESSION_ID", "TERM", "COLORTERM", "LANG", "LC_ALL",
                              "LC_CTYPE"})

_SYNC_GRACE_SECONDS = 2.0


def remote_env(env: Optional[Dict[str, Optional[str]]], login_path: Optional[str]
               ) -> Dict[str, Optional[str]]:
    kept = {key: value for key, value in (env or {}).items()
            if value is None or key in REMOTE_ENV_NAMES or key.startswith("CLAUDE_CODE_")}
    if login_path:
        kept["PATH"] = login_path
    return kept


def split_commands(args: Sequence[str]) -> List[List[str]]:
    commands: List[List[str]] = [[]]
    for word in args:
        if word == COMMAND_SEPARATOR:
            commands.append([])
        else:
            commands[-1].append(word)
    return [command for command in commands if command]


class RemoteTmuxBackend(TmuxBackend):

    def __init__(self, host: RemoteHost, session_id: str, working_dir: Path,
                 on_output: Optional[Callable[[bytes], Any]] = None, *,
                 scrollback_lines: int = 3000, session_name: Optional[str] = None,
                 viewer_probe: Optional[Callable[[], bool]] = None,
                 stream_options: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(session_id, working_dir, on_output, socket_name=host.socket,
                         scrollback_lines=scrollback_lines, session_name=session_name,
                         viewer_probe=viewer_probe)
        self.host = host
        self.host_key = host.host_key
        self._stream: Optional[RemotePipeStream] = None
        self._stream_options = dict(stream_options or {})
        self._pending_size: Optional[Tuple[int, int]] = None
        self._resize_task: Optional[asyncio.Task[None]] = None
        self._alive: Optional[bool] = None
        self._alive_task: Optional[asyncio.Task[bool]] = None


    def _file_slug(self) -> str:
        return _slugify(self.slug)

    def _tmux_base(self) -> List[str]:
        return [self.host.tmux_path, "-L", self.host.socket]

    def _server_config_argv(self) -> List[str]:
        return []

    def _resolve_pipe_path(self) -> Path:
        if self._pipe_path is None:
            self._pipe_path = self.host.mirror_path(self._file_slug())
        return self._pipe_path

    def _pipe_write_path(self) -> str:
        return self.host.pipe_path(self._file_slug())


    def _preflight_start(self) -> None:
        if not self.host.is_up:
            raise RuntimeError(f"host {self.host_key} is not connected")

    def _touch_mirror(self, truncate: bool) -> None:
        mirror = self._resolve_pipe_path()
        mirror.parent.mkdir(parents=True, exist_ok=True)
        if truncate or not mirror.exists():
            mirror.write_bytes(b"")

    async def _far_file(self, truncate: bool) -> None:
        op = ":>" if truncate else ":>>"
        result = await self.host.exec(script=f"umask 077; mkdir -p {posix_quote(self.host.pipe_dir)} && "
                                             f"{op} {posix_quote(self._pipe_write_path())}")
        if result.returncode != 0:
            raise RuntimeError(f"host {self.host_key}: the output file could not be created")

    async def _reset_pipe_file(self) -> None:
        self._touch_mirror(truncate=True)
        await self._far_file(truncate=True)

    async def _ensure_pipe_file(self) -> None:
        self._touch_mirror(truncate=False)
        await self._far_file(truncate=False)

    async def _pipe_file_exists(self) -> bool:
        result = await self.host.exec(script=f"[ -f {posix_quote(self._pipe_write_path())} ]")
        return result.returncode == 0

    async def _spawn_session(self, args: List[str], tmux_env: Dict[str, str]) -> Tuple[int, bytes]:
        rc, _, err = await self._run_tmux(*args, check=False)
        return rc, err

    async def start(self, command: Optional[str] = None, env: Optional[dict] = None,
                    initial_cols: Optional[int] = None, initial_rows: Optional[int] = None) -> None:
        await super().start(command, remote_env(env, self.host.login_path), initial_cols,
                            initial_rows)
        self._alive = True


    async def _run_tmux(self, *args: str, stdin_bytes: Optional[bytes] = None,
                        check: bool = True) -> Tuple[int, bytes, bytes]:
        """Run one tmux command (or a ``;`` batch) on the far socket.

        Output: (returncode, stdout, stderr) as a tmux exec would give them.
        Raises: RemoteHostUnavailable - the host could not be asked.
        """
        return await self._remote(args, stdin_bytes, None, check)

    async def _run_tmux_private(self, *args: str, check: bool = True) -> Tuple[int, bytes, bytes]:
        return await self._run_tmux(*args, check=check)

    async def _remote(self, args: Sequence[str], stdin_bytes: Optional[bytes],
                      timeout: Optional[float], check: bool) -> Tuple[int, bytes, bytes]:
        if stdin_bytes is not None:
            result = await self.host.exec([*self._tmux_base(), *args], stdin_data=stdin_bytes,
                                          timeout=timeout)
            return self._outcome(args[0] if args else "", check, result.returncode or 0,
                                 result.stdout, result.stderr)
        out = bytearray()
        for command in split_commands(args):
            verb = command[0]
            try:
                reply = await self.host.command(verb, *escape_expanded(verb, command[1:]),
                                                timeout=timeout)
            except TmuxQuoteError as exc:
                return self._outcome(verb, check, 1, bytes(out), str(exc).encode("utf-8"))
            text = b"".join(line + b"\n" for line in reply.lines)
            if not reply.ok:
                return self._outcome(verb, check, 1, bytes(out), text)
            out += text
        return 0, bytes(out), b""

    def _outcome(self, verb: str, check: bool, rc: int, out: bytes, err: bytes
                 ) -> Tuple[int, bytes, bytes]:
        if check and rc != 0:
            logger.error("remote_tmux_command_failed", host=self.host_key, verb=verb,
                         returncode=rc, stderr_bytes=len(err))
        return rc, out, err

    async def _write_via_send_keys_literal(self, data: bytes) -> None:
        if b"\r" in data or b"\n" in data:
            await self._write_via_hex_keys(data)
        else:
            await super()._write_via_send_keys_literal(data)

    def _run_tmux_sync(self, *args: str, stdin_bytes: Optional[bytes] = None, check: bool = True,
                       timeout: Optional[float] = None, env: Optional[Dict[str, str]] = None,
                       probe: bool = False,
                       ) -> Tuple[int, bytes, bytes]:
        """Run a command from a worker thread on the host's loop and wait for it.

        The local backend's ``probe`` controls process descriptor inheritance;
        this backend uses an existing control channel, so the flag has no
        transport effect. It is accepted to preserve the shared tmux contract.

        Raises: RemoteSyncOnLoopError - called on that loop;
          subprocess.TimeoutExpired - ``timeout`` passed;
          RemoteHostUnavailable - the host could not be asked.
        """
        loop = self.host.loop
        if loop is None:
            raise RemoteHostUnavailable(f"host {self.host_key} is not prepared")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            raise RemoteSyncOnLoopError(
                f"host {self.host_key}: a synchronous tmux call on the event loop; "
                "call it through asyncio.to_thread")
        future = asyncio.run_coroutine_threadsafe(
            self._remote(args, stdin_bytes, timeout, check), loop)
        budget = (timeout if timeout is not None else self.host.command_timeout) \
            + _SYNC_GRACE_SECONDS
        try:
            return future.result(budget)
        except FutureTimeout as exc:
            future.cancel()
            raise subprocess.TimeoutExpired(args[:1], budget) from exc

    def _run_listing(self, *args: str) -> tuple[Optional[TmuxListing], str]:
        try:
            rc, out, err = self._run_tmux_sync(*args, check=False, timeout=LIST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return TmuxListing.unavailable(
                REASON_TIMEOUT, detail=f"host {self.host_key} did not answer in time"), ""
        except RemoteHostUnavailable as exc:
            reason = REASON_TIMEOUT if exc.timed_out else REASON_HOST_UNREACHABLE
            return TmuxListing.unavailable(reason, detail=str(exc)), ""
        except RemoteSyncOnLoopError as exc:
            return TmuxListing.unavailable(REASON_PROBE_ERROR, detail=str(exc)), ""
        if rc != 0:
            listing = classify_listing_failure(rc, err.decode("utf-8", errors="replace"))
            if not listing.ok:
                logger.warning("remote_tmux_listing_unavailable", host=self.host_key,
                               verb=args[0] if args else "", reason=listing.reason)
            return listing, ""
        return None, out.decode("utf-8", errors="replace")

    def _pane_listing_cache_key(self) -> Optional[str]:
        return None

    def list_pane_status_all(self, *, fresh: bool = False) -> TmuxListing:
        listing = super().list_pane_status_all(fresh=fresh)
        if not listing.ok:
            return listing
        rows = [dict(row, pid=None, far_pid=row.get("pid")) for row in listing.sessions
                if row.get("name") != CONTROL_SESSION_NAME]
        return dataclasses.replace(listing, sessions=rows)

    async def is_alive_async(self) -> bool:
        rc, _, _ = await self._run_tmux("has-session", "-t", f"={self.tmux_session}", check=False)
        self._alive = rc == 0
        return self._alive

    def is_alive(self) -> bool:
        loop = self.host.loop
        try:
            on_loop = loop is not None and asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if not on_loop:
            self._alive = super().is_alive()
            return self._alive
        if self._alive_task is None or self._alive_task.done():
            self._alive_task = loop.create_task(self._remeasure())
        return bool(self._alive)

    async def _remeasure(self) -> bool:
        try:
            return await self.is_alive_async()
        except RemoteHostUnavailable as exc:
            logger.debug("remote_liveness_unmeasured", host=self.host_key, error=str(exc))
            return bool(self._alive)

    async def _resume_presence(self, uuid: str, family: Optional[str] = None) -> Tuple[str, str]:
        from src.core.hosts.remote_claude_files import far_transcript_presence

        return await far_transcript_presence(self.host, uuid)

    @property
    def pid(self) -> Optional[int]:
        return None

    def resize(self, cols: int, rows: int) -> None:
        loop = self.host.loop
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
                await self._run_tmux("resize-window", "-t", self.tmux_session, "-x", str(cols),
                                     "-y", str(rows), check=False)
            except RemoteHostUnavailable as exc:
                logger.debug("remote_tmux_resize_error", host=self.host_key, error=str(exc))


    def _ensure_stream(self) -> RemotePipeStream:
        if self._stream is None:
            self._stream = RemotePipeStream(self.host, self._pipe_write_path(),
                                            self._resolve_pipe_path(), self.has_viewers,
                                            name=self._file_slug(), **self._stream_options)
        return self._stream

    async def read_async(self) -> None:
        await super().read_async()
        self._ensure_stream().start()

    async def ensure_streaming(self, timeout: float = 10.0) -> bool:
        return await self._ensure_stream().ensure_streaming(timeout)

    async def _repair_stolen_pipe(self, pipe_path: Path) -> str:
        """The liveness repair over the channel; an unreachable host changes nothing.

        Description: unlike a local file, a missing FAR file is repaired by
          re-issuing ``pipe-pane``: ``tail -F`` follows the path by name.
        Output: str - the verdict, or "unmeasured" when the host could not be asked.
        """
        try:
            verdict = await super()._repair_stolen_pipe(pipe_path)
            if verdict == pipe_liveness.FILE_MISSING:
                await self.ensure_pipe_pane(force=True)
            return verdict
        except (RemoteHostUnavailable, RuntimeError) as exc:
            logger.info("remote_pipe_repair_unmeasured", host=self.host_key, error=str(exc))
            return "unmeasured"

    async def stop(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        if self._alive_task is not None:
            self._alive_task.cancel()
        await super().stop()
        self._alive = False
        try:
            await self.host.exec(script=f"rm -f {posix_quote(self._pipe_write_path())}")
        except RemoteHostUnavailable as exc:
            logger.info("remote_pipe_file_left", host=self.host_key, error=str(exc))

