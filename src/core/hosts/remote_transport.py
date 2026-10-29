
from __future__ import annotations

import asyncio
import dataclasses
import subprocess
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.hosts.remote_lifecycle import RemoteLifecycle
from src.core.hosts.remote_host import RemoteHost, RemoteHostUnavailable, RemoteSyncOnLoopError
from src.core.hosts.ssh_exec import posix_quote
from src.core.hosts.tmux_quote import TmuxQuoteError, escape_expanded
from src.core.tmux_command_batch import COMMAND_SEPARATOR
from src.core.tmux_control.tmux_error import TmuxError
from src.core.tmux_listing import REASON_HOST_UNREACHABLE, REASON_PROBE_ERROR, REASON_TIMEOUT, TmuxListing
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend

logger = structlog.get_logger()

SYNC_GRACE_SECONDS = 2.0


def split_commands(args: Sequence[str]) -> List[List[str]]:
    commands: List[List[str]] = [[]]
    for word in args:
        if word == COMMAND_SEPARATOR:
            commands.append([])
        else:
            commands[-1].append(word)
    return [command for command in commands if command]


class RemoteTransport:

    is_remote: bool = True
    argv_visible_locally: bool = False
    listing_errors: Tuple[type, ...] = (subprocess.TimeoutExpired, RemoteHostUnavailable, RemoteSyncOnLoopError)

    def __init__(self, host: RemoteHost, stream_options: Optional[Dict[str, Any]] = None) -> None:
        self.host = host
        self.stream_options = dict(stream_options or {})
        self.host_key: str = host.host_key

    def argv_prefix(self, socket_name: str) -> List[str]:
        return [self.host.tmux_path, "-L", self.host.socket]

    def server_config_argv(self, commands: Sequence[Sequence[str]]) -> List[str]:
        return []

    async def run(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                  check: bool = True) -> Tuple[int, bytes, bytes]:
        return await self._remote(args, stdin_bytes, None, check)

    async def spawn_session(self, socket_name: str, args: Sequence[str], tmux_env: Dict[str, str],
                            config_commands: Sequence[Sequence[str]]) -> Tuple[int, bytes]:
        rc, _, err = await self.run(socket_name, args, check=False)
        return rc, err

    async def _remote(self, args: Sequence[str], stdin_bytes: Optional[bytes],
                      timeout: Optional[float], check: bool) -> Tuple[int, bytes, bytes]:
        if stdin_bytes is not None:
            result = await self.host.exec([*self.argv_prefix(""), *args], stdin_data=stdin_bytes,
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

    def run_sync(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                 check: bool = True, timeout: Optional[float] = None,
                 env: Optional[Dict[str, str]] = None, probe: bool = False) -> Tuple[int, bytes, bytes]:
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
        budget = (timeout if timeout is not None else self.host.command_timeout) + SYNC_GRACE_SECONDS
        try:
            return future.result(budget)
        except FutureTimeout as exc:
            future.cancel()
            raise subprocess.TimeoutExpired(list(args[:1]), budget) from exc


    def pipe_read_path(self, tmux_slug: str, backend_slug: str) -> Path:
        return self.host.mirror_path(backend_slug)

    def pipe_write_path(self, read_path: Path, backend_slug: str) -> str:
        return self.host.pipe_path(backend_slug)

    async def ensure_pipe_file(self, read_path: Path, write_path: str, *, truncate: bool) -> None:
        read_path.parent.mkdir(parents=True, exist_ok=True)
        if truncate or not read_path.exists():
            read_path.write_bytes(b"")
        op = ":>" if truncate else ":>>"
        result = await self.host.exec(script=f"umask 077; mkdir -p {posix_quote(self.host.pipe_dir)} && "
                                             f"{op} {posix_quote(write_path)}")
        if result.returncode != 0:
            raise TmuxError(f"host {self.host_key}: the output file could not be created")

    async def pipe_file_exists(self, write_path: str) -> bool:
        result = await self.host.exec(script=f"[ -f {posix_quote(write_path)} ]")
        return result.returncode == 0

    def preflight(self, socket_name: str, working_dir: Path) -> None:
        if not self.host.is_up:
            raise TmuxError(f"host {self.host_key} is not connected")


    def listing_gate(self) -> Optional[TmuxListing]:
        return None

    def listing_failure(self, exc: BaseException, socket_name: str, args: Sequence[str]) -> TmuxListing:
        if isinstance(exc, subprocess.TimeoutExpired):
            return TmuxListing.unavailable(REASON_TIMEOUT, detail=f"host {self.host_key} did not answer in time")
        if isinstance(exc, RemoteHostUnavailable):
            reason = REASON_TIMEOUT if exc.timed_out else REASON_HOST_UNREACHABLE
            return TmuxListing.unavailable(reason, detail=str(exc))
        return TmuxListing.unavailable(REASON_PROBE_ERROR, detail=str(exc))

    def pane_listing_cache_key(self, socket_name: str) -> Optional[str]:
        return None

    def shape_pane_listing(self, listing: TmuxListing) -> TmuxListing:
        rows = [dict(row, pid=None, far_pid=row.get("pid")) for row in listing.sessions
                if row.get("name") != CONTROL_SESSION_NAME]
        return dataclasses.replace(listing, sessions=rows)

    def make_lifecycle(self, backend: "TmuxBackend") -> RemoteLifecycle:
        return RemoteLifecycle(backend, self.host, self.stream_options)
