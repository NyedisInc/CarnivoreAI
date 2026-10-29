
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.tmux_quote import TmuxQuoteError
from src.core.iopolicy.materialize import spawn_preexec
from src.core.tmux_control.reader import control_read, control_read_async
from src.core.sessions.pane_listing_cache import args_mutate_sessions, invalidate_pane_listing
from src.core.tmux_command_batch import COMMAND_SEPARATOR, STDIN_SCRIPT_ARGS, stdin_script
from src.core.tmux_transport.lifecycle import LocalLifecycle
from src.core.tmux_discovery import TmuxVersionSkewError, resolve_tmux_path, select_tmux, tmux_argv_prefix
from src.core.tmux_listing import (
    REASON_PROBE_ERROR, REASON_TIMEOUT, REASON_TMUX_MISSING, REASON_VERSION_SKEW, TmuxListing,
)
from src.core.tmux_control.tmux_error import TmuxError
from src.core.tmux_server_config import write_server_config

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend

logger = structlog.get_logger()

PIPE_SUFFIX: str = ".pipe"


LIST_TIMEOUT_SECONDS: float = 5.0


class LocalTransport:

    host_key: str = LOCAL_HOST_KEY
    is_remote: bool = False
    argv_visible_locally: bool = True
    host = None
    listing_errors: Tuple[type, ...] = (subprocess.TimeoutExpired, TmuxVersionSkewError, OSError)

    def argv_prefix(self, socket_name: str) -> List[str]:
        return tmux_argv_prefix(socket_name)

    def server_config_argv(self, commands: Sequence[Sequence[str]]) -> List[str]:
        try:
            from src.config import settings

            state_dir = settings.get_state_dir()
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            logger.warning("tmux_server_config_state_dir_unavailable",
                           error=f"{type(exc).__name__}: {exc}")
            return []
        path = write_server_config(state_dir, commands)
        return [] if path is None else ["-f", str(path)]

    async def run(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                  check: bool = True) -> Tuple[int, bytes, bytes]:
        if stdin_bytes is None:
            answered = await control_read_async(socket_name, args)
            if answered is not None:
                return 0, answered, b""
        argv = self.argv_prefix(socket_name) + list(args)
        mutates = args_mutate_sessions(args)
        if mutates:
            invalidate_pane_listing(socket_name)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=stdin_bytes)
        if mutates:
            invalidate_pane_listing(socket_name)
        if check and proc.returncode != 0:
            logger.error("tmux_command_failed", argv=argv, returncode=proc.returncode,
                         stderr=stderr.decode("utf-8", errors="replace"))
        return proc.returncode or 0, stdout, stderr

    def run_sync(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                 check: bool = True, timeout: Optional[float] = None,
                 env: Optional[Dict[str, str]] = None, probe: bool = False) -> Tuple[int, bytes, bytes]:
        if probe and stdin_bytes is None:
            answered = control_read(socket_name, args)
            if answered is not None:
                return 0, answered, b""
        argv = self.argv_prefix(socket_name) + list(args)
        mutates = args_mutate_sessions(args)
        if mutates:
            invalidate_pane_listing(socket_name)
        try:
            proc = subprocess.run(argv, input=stdin_bytes, capture_output=True, check=False,
                                  timeout=timeout, env=env, close_fds=not probe)
        finally:
            if mutates:
                invalidate_pane_listing(socket_name)
        if check and proc.returncode != 0:
            logger.debug("tmux_command_nonzero", argv=argv, returncode=proc.returncode,
                         stderr=proc.stderr.decode("utf-8", errors="replace")[:200])
        return proc.returncode, proc.stdout, proc.stderr

    async def spawn_session(self, socket_name: str, args: Sequence[str], tmux_env: Dict[str, str],
                            config_commands: Sequence[Sequence[str]]) -> Tuple[int, bytes]:
        try:
            script = stdin_script(args)
        except TmuxQuoteError as exc:
            return 1, str(exc).encode("utf-8")
        argv = (self.argv_prefix(socket_name) + self.server_config_argv(config_commands)
                + ["start-server", COMMAND_SEPARATOR, *STDIN_SCRIPT_ARGS])
        invalidate_pane_listing(socket_name)
        done = await asyncio.to_thread(
            subprocess.run, argv, input=script, capture_output=True, env=tmux_env,
            preexec_fn=spawn_preexec(), check=False)
        invalidate_pane_listing(socket_name)
        return done.returncode or 0, done.stderr

    def pipe_read_path(self, tmux_slug: str, backend_slug: str) -> Path:
        try:
            from src.config import settings
            log_dir = settings.get_log_dir()
        except Exception:  # noqa: BLE001
            log_dir = Path("/tmp")
        return log_dir / f"tmux_{tmux_slug}{PIPE_SUFFIX}"

    def pipe_write_path(self, read_path: Path, backend_slug: str) -> str:
        return str(read_path)

    async def ensure_pipe_file(self, read_path: Path, write_path: str, *, truncate: bool) -> None:
        read_path.parent.mkdir(parents=True, exist_ok=True)
        if truncate:
            read_path.write_bytes(b"")
        elif not read_path.exists():
            read_path.touch()

    async def pipe_file_exists(self, write_path: str) -> bool:
        return Path(write_path).exists()

    def preflight(self, socket_name: str, working_dir: Path) -> None:
        if resolve_tmux_path() is None:
            raise TmuxError(
                "tmux was not found on PATH or at any well-known install "
                "location (see src/core/tmux_discovery.WELL_KNOWN_PATHS)"
            )
        select_tmux(socket_name)
        working_dir.mkdir(parents=True, exist_ok=True)


    def listing_gate(self) -> Optional[TmuxListing]:
        if resolve_tmux_path() is not None:
            return None
        return TmuxListing.unavailable(
            REASON_TMUX_MISSING, detail="tmux not found on PATH or at any well-known install location")

    def listing_failure(self, exc: BaseException, socket_name: str, args: Sequence[str]) -> TmuxListing:
        if isinstance(exc, subprocess.TimeoutExpired):
            logger.warning("tmux_listing_timeout", argv=args, socket=socket_name,
                           timeout_seconds=LIST_TIMEOUT_SECONDS)
            return TmuxListing.unavailable(
                REASON_TIMEOUT, detail=f"tmux did not answer within {LIST_TIMEOUT_SECONDS}s")
        if isinstance(exc, TmuxVersionSkewError):
            return TmuxListing.unavailable(REASON_VERSION_SKEW, detail=str(exc))
        logger.warning("tmux_listing_probe_error", argv=args, socket=socket_name, error=str(exc))
        return TmuxListing.unavailable(REASON_PROBE_ERROR, detail=str(exc))

    def pane_listing_cache_key(self, socket_name: str) -> Optional[str]:
        return socket_name

    def shape_pane_listing(self, listing: TmuxListing) -> TmuxListing:
        return listing

    def make_lifecycle(self, backend: "TmuxBackend") -> LocalLifecycle:
        return LocalLifecycle(backend)
