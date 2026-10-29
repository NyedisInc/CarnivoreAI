"""Tmux-backed session backend.

Uses a DEDICATED tmux server socket (``tmux -L cloude``) so we never touch
the user's default tmux server. Sessions are named ``cloude_<slug>``.

Key design points:

- **Binary-safe writes** (three-path routing):

  ``send-keys -l <text>`` for short, control-free UTF-8 - the fast path
  for regular typing.

  ``send-keys -H <hex pairs>`` for short byte sequences that contain
  control chars (arrow keys, Ctrl-X, Esc, Backspace - real keystrokes).
  tmux treats each hex pair as a literal byte delivered via key event,
  which interactive TUIs interpret correctly.

- **Output streaming**: ``tmux pipe-pane -o 'cat >> <fifo>'`` streams every
  pane byte to a file. We tail that file asynchronously and call
  `on_output(bytes)` for every chunk. The file is trimmed IN PLACE when it
  exceeds ``MAX_LOG_BYTES`` or is older than ``ROTATE_AGE_HOURS``: the shell
  running ``cat >>`` opened that path once and holds the descriptor, so
  renaming the file would strand the rotation on a decoy rather than
  reclaim anything. See ``src/core/pipe_rotation.py``.

- **Single-active invariant**: the backend itself does NOT enforce
  one-at-a-time; `SessionManager` does. This backend DOES refuse to start
  if a session with the same name already exists - callers must call
  ``discover_existing()`` first to re-attach.

- **Restart survival**: `discover_existing()` lists ``cloude_*`` sessions on
  the dedicated server. `SessionManager.lifespan_startup` uses it to
  re-register the slug stored in ``session_metadata.json``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core import debug_trace

from src.core.pane_locale import apply_pane_locale
from src.core import pipe_liveness
from src.core.pipe_rotation import rotation_reason, truncate_in_place
from src.core.pipe_wakeup import PipeWaiter
from src.core.product_identity import (
    TMUX_SESSION_PREFIX,
    TMUX_SOCKET_NAME,
    is_owned_session_name,
)
from src.core.debug_trace import is_secret_name
from src.core.hosts.tmux_quote import TmuxQuoteError, literal
from src.core.tmux_command_batch import (
    COMMAND_SEPARATOR, STDIN_SCRIPT_ARGS, BatchOutcome, environment_commands, redact_env_pair,
    run_on_stdin, run_optional_batch, stdin_script,
)
from src.core.tmux_server_config import write_server_config
from src.core.tmux_discovery import (
    TmuxVersionSkewError, pane_client_env, resolve_tmux_path, select_tmux, tmux_argv_prefix,
)
from src.core.iopolicy.materialize import spawn_preexec
from src.core.tmux_paste_buffer import paste_loaded_buffer
from src.core.tmux_control import route as control_route
from src.core.tmux_listing_parse import (
    LISTING_FORMAT,
    SCREEN_STAMP_FIELDS,
    SCREEN_STAMP_FORMAT,
    is_plumbing_session,
    parse_listing_row,
    parse_screen_stamp,
    resolve_ownership,
    split_listing_rows,
)
from src.core.tmux_listing import (
    REASON_PROBE_ERROR,
    REASON_TIMEOUT,
    REASON_TMUX_MISSING,
    REASON_VERSION_SKEW,
    TmuxListing,
    classify_listing_failure,
    listing_env,
)
from src.core.scrollback_replay import normalize_replay_newlines, with_cursor_restore
from src.core.session_backend import SessionBackend
from src.core.sessions.pane_listing_cache import (
    PANE_LISTING_CACHE, args_mutate_sessions, invalidate_pane_listing)
from src.core.session_respawn import (
    CONVERSATION_RESUMED,
    RESPAWN_AGENT,
    RESPAWN_PANE_FORMAT,
    RespawnResult,
    parse_respawn_probe,
    refuse_if_transcript_missing,
    resolve_respawn_plan,
)

logger = structlog.get_logger()


LIST_TIMEOUT_SECONDS: float = 5.0

MAX_LOG_BYTES: int = 10 * 1024 * 1024

ROTATE_AGE_HOURS: int = 24

INITIAL_COLS: int = 132
INITIAL_ROWS: int = 40

PASTE_THRESHOLD_BYTES: int = 256

DEFAULT_SOCKET_NAME: str = TMUX_SOCKET_NAME

HISTORY_LIMIT: int = 50000

PIPE_IDLE_POLL_SECONDS: float = 0.02

SESSION_PREFIX: str = TMUX_SESSION_PREFIX

PIPE_SUFFIX: str = ".pipe"




def _slugify(raw: str) -> str:
    out = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    return slug or "default"


def _has_control_chars(data: bytes) -> bool:
    safe = {0x09, 0x0a, 0x0d}
    return any((b < 0x20 and b not in safe) or b == 0x7f for b in data)


def _safe_target(session_name: str, pane: Optional[str] = None) -> str:
    if ":" in session_name or "." in session_name:
        raise ValueError(
            f"unsafe tmux session name {session_name!r}: "
            f"contains ':' or '.' which tmux parses as target separators"
        )
    if pane is None:
        return session_name
    return f"{session_name}:{pane}"


class PaneDeadError(RuntimeError):
    """A ``#{pane_dead}`` probe RAN and MEASURED the pane as dead.

    Description: raised by :meth:`TmuxBackend.attach_existing` only when
      tmux answered the probe with ``rc=0`` and the value ``"1"`` - a
      positive, completed measurement that the process behind the pane
      has exited. It is a distinct type from the bare ``RuntimeError``
      the same guard raises when the probe ITSELF could not run (tmux
      timed out, refused, or errored): that case is an unmeasured
      unknown and must never be treated as a confirmed death. Kept a
      ``RuntimeError`` subclass so every existing ``except RuntimeError``
      around ``attach_existing`` (the boot re-adopt's per-target gather,
      the single-session rehydrate's stale-metadata cleanup) keeps
      working unchanged; a caller that cares about the distinction -
      today, only the adopt route - catches this type specifically and
      answers a 409 ``session_gone`` instead of a 500, the same way a
      session found missing from a tmux listing already does.
    Inputs (constructor): message (str) - user-facing reason.
    Output: a PaneDeadError instance.
    """




class TmuxBackend(SessionBackend):

    def __init__(
        self,
        session_id: str,
        working_dir: Path,
        on_output: Optional[Callable[[bytes], Any]] = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
        scrollback_lines: int = 3000,
        session_name: Optional[str] = None,
        viewer_probe: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(session_id, working_dir, on_output)

        self.socket_name = socket_name
        self.scrollback_lines = scrollback_lines
        self.slug = _slugify(session_id)
        if session_name is not None:
            self.tmux_session = session_name
        else:
            self.tmux_session = f"{SESSION_PREFIX}{self.slug}"

        self._pipe_path: Optional[Path] = None

        self._reader_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_rotate_check = time.monotonic()
        self._rotation_started_at = time.monotonic()

        self._is_external: bool = False

        self._adopt_tail_start_offset: Optional[int] = None

        self._liveness = pipe_liveness.SilenceTracker()

        self._viewer_probe: Optional[Callable[[], bool]] = viewer_probe


    def has_viewers(self) -> bool:
        probe = self._viewer_probe
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "pipe_viewer_probe_failed",
                session=self.tmux_session,
                error=str(exc),
            )
            return False

    def _tmux_base(self) -> List[str]:
        return tmux_argv_prefix(self.socket_name)

    def _history_limit_command(self) -> tuple:
        return ("set-option", "-g", "history-limit", str(HISTORY_LIMIT))

    def _remain_on_exit_command(self) -> tuple:
        return ("set-option", "-wg", "remain-on-exit", "on")

    def _server_config_argv(self) -> List[str]:
        try:
            from src.config import settings

            state_dir = settings.get_state_dir()
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            logger.warning(
                "tmux_server_config_state_dir_unavailable",
                error=f"{type(exc).__name__}: {exc}",
            )
            return []

        path = write_server_config(
            state_dir,
            [self._history_limit_command(), self._remain_on_exit_command()],
        )
        if path is None:
            return []
        return ["-f", str(path)]

    async def _apply_pre_spawn_options(self) -> None:
        """Set scrollback depth and ``remain-on-exit`` in ONE tmux process.

        BOTH MUST LAND BEFORE ``new-session`` and both are best effort, so
        they share a batch. The batch runner re-runs them individually if
        the single invocation fails, which matters here more than
        anywhere: tmux aborts the rest of a command list at the first
        error, and ``remain-on-exit`` is what guarantees a fast-failing
        agent leaves a pane for the dead-on-arrival probe to read.
        Without the fallback, one socket that refused ``history-limit``
        would silently take ``remain-on-exit`` down with it.

        **THIS CALL DOES NOTHING AT ALL ON A COLD SOCKET, AND THAT IS
        TMUX, NOT A BUG HERE.** ``set-option`` does NOT start a tmux
        server. Measured on tmux 3.6a against a socket with no server:
        both commands exit 1 with ``error connecting to
        /private/tmp/tmux-<uid>/<socket> (No such file or directory)``,
        batched or separate, and ``check=False`` makes that silent. This
        call is still the ONLY thing that can make a pane be BORN at
        :data:`HISTORY_LIMIT`, which is why it stays: a pane's scrollback
        depth is fixed into its grid at creation and no later
        ``set-option`` moves it. On a warm socket - the common case, every
        session after the first - it lands and the pane is born correct.
        The post-spawn re-application in :meth:`start` is what stops a
        cold socket carrying tmux's stock defaults onward.

        Returns:
            None.
        """
        await run_optional_batch(
            self._run_tmux,
            [self._history_limit_command(), self._remain_on_exit_command()],
            note="pre_spawn_options",
        )

    async def read_history_limit(self) -> Optional[int]:
        """Read the socket's current global ``history-limit``.

        Verification seam: the point of the setting is the number tmux
        actually holds, and ``show-options`` is the only thing that
        reports it.

        Returns:
            The configured row count, or None when tmux could not be
            asked or answered with something non-numeric. None is a real
            third answer - "could not determine" - and callers must not
            read it as the default.
        """
        rc, out, _ = await self._run_tmux(
            "show-options", "-gv", "history-limit", check=False
        )
        if rc != 0:
            return None
        raw = out.decode("utf-8", errors="replace").strip()
        try:
            return int(raw)
        except ValueError:
            return None

    def _resolve_pipe_path(self) -> Path:
        if self._pipe_path is not None:
            return self._pipe_path
        try:
            from src.config import settings
            log_dir = settings.get_log_dir()
        except Exception:
            log_dir = Path("/tmp")

        self._pipe_path = log_dir / f"tmux_{_slugify(self.tmux_session)}{PIPE_SUFFIX}"
        return self._pipe_path

    def _legacy_pipe_paths(self) -> frozenset:
        current = self._resolve_pipe_path()
        names = {
            f"tmux_{self.slug}",
            f"tmux_ext_{_slugify(self.slug)}",
            f"tmux_ext_{_slugify(self.tmux_session)}",
            f"tmux_{_slugify('adopted:' + self.tmux_session)}",
        }
        return frozenset(
            str(current.parent / f"{name}{PIPE_SUFFIX}") for name in names
        ) - {str(current)}


    def _preflight_start(self) -> None:
        if resolve_tmux_path() is None:
            raise RuntimeError(
                "tmux was not found on PATH or at any well-known install "
                "location (see src/core/tmux_discovery.WELL_KNOWN_PATHS)"
            )
        select_tmux(self.socket_name)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    async def _reset_pipe_file(self) -> None:
        pipe_path = self._resolve_pipe_path()
        pipe_path.parent.mkdir(parents=True, exist_ok=True)
        pipe_path.write_bytes(b"")

    def _pipe_write_path(self) -> str:
        return str(self._resolve_pipe_path())

    async def _pipe_file_exists(self) -> bool:
        return self._resolve_pipe_path().exists()

    async def _ensure_pipe_file(self) -> None:
        pipe_path = self._resolve_pipe_path()
        pipe_path.parent.mkdir(parents=True, exist_ok=True)
        if not pipe_path.exists():
            pipe_path.touch()

    async def _spawn_session(self, args: List[str], tmux_env: Dict[str, str]) -> Tuple[int, bytes]:
        try:
            script = stdin_script(args)
        except TmuxQuoteError as exc:
            return 1, str(exc).encode("utf-8")
        argv = (self._tmux_base() + self._server_config_argv()
                + ["start-server", COMMAND_SEPARATOR, *STDIN_SCRIPT_ARGS])
        invalidate_pane_listing(self.socket_name)
        done = await asyncio.to_thread(
            subprocess.run, argv, input=script, capture_output=True, env=tmux_env,
            preexec_fn=spawn_preexec(), check=False)
        invalidate_pane_listing(self.socket_name)
        return done.returncode or 0, done.stderr

    async def is_alive_async(self) -> bool:
        return self.is_alive()

    async def _run_tmux(
        self,
        *args: str,
        stdin_bytes: Optional[bytes] = None,
        check: bool = True,
    ) -> tuple[int, bytes, bytes]:
        argv = self._tmux_base() + list(args)
        mutates = args_mutate_sessions(args)
        if mutates:
            invalidate_pane_listing(self.socket_name)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=stdin_bytes)
        if mutates:
            invalidate_pane_listing(self.socket_name)
        if check and proc.returncode != 0:
            logger.error(
                "tmux_command_failed",
                argv=argv,
                returncode=proc.returncode,
                stderr=stderr.decode("utf-8", errors="replace"),
            )
        return proc.returncode or 0, stdout, stderr

    async def _run_tmux_private(self, *args: str, check: bool = True) -> tuple[int, bytes, bytes]:
        return await run_on_stdin(self._run_tmux, *args, check=check)

    async def set_session_environment(
        self, target: str, values: Mapping[str, Optional[str]], *, note: str
    ) -> BatchOutcome:
        return await run_optional_batch(
            self._run_tmux_private, environment_commands(target, values), note=note)

    def _run_tmux_sync(
        self,
        *args: str,
        stdin_bytes: Optional[bytes] = None,
        check: bool = True,
        timeout: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
        probe: bool = False,
    ) -> tuple[int, bytes, bytes]:
        import subprocess

        argv = self._tmux_base() + list(args)
        mutates = args_mutate_sessions(args)
        if mutates:
            invalidate_pane_listing(self.socket_name)
        try:
            proc = subprocess.run(
                argv,
                input=stdin_bytes,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=env,
                close_fds=not probe,
            )
        finally:
            if mutates:
                invalidate_pane_listing(self.socket_name)
        if check and proc.returncode != 0:
            logger.debug(
                "tmux_command_nonzero",
                argv=argv,
                returncode=proc.returncode,
                stderr=proc.stderr.decode("utf-8", errors="replace")[:200],
            )
        return proc.returncode, proc.stdout, proc.stderr


    async def start(
        self,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
    ) -> None:
        if self._running:
            raise RuntimeError("TmuxBackend already running")

        self._preflight_start()

        pipe_path = self._resolve_pipe_path()
        await self._reset_pipe_file()

        use_cols = initial_cols if (initial_cols and initial_rows) else INITIAL_COLS
        use_rows = initial_rows if (initial_cols and initial_rows) else INITIAL_ROWS

        await self._apply_pre_spawn_options()

        args = [
            "new-session",
            "-d",
            "-s",
            self.tmux_session,
            "-c",
            literal(str(self.working_dir)),
            "-x",
            str(use_cols),
            "-y",
            str(use_rows),
        ]
        tmux_env = pane_client_env()
        tmux_env.setdefault("TERM", "xterm-256color")
        tmux_env.setdefault("COLORTERM", "truecolor")
        if env:
            tmux_env.update({k: v for k, v in env.items() if v is not None
                             and not is_secret_name(k)})
        removals = sorted(k for k, v in (env or {}).items() if v is None)
        for key in removals:
            tmux_env.pop(key, None)
            await self._run_tmux("set-environment", "-g", "-u", key, check=False)

        # already running
        apply_pane_locale(tmux_env)
        pane_lang = tmux_env.get("LANG")
        if pane_lang:
            args.extend(["-e", f"LANG={pane_lang}"])

        for key, value in sorted((env or {}).items()):
            if value is None:
                continue
            text = str(value)
            if "\n" in text or "\r" in text or not key or "=" in key:
                logger.warning(
                    "tmux_env_pair_skipped",
                    key=key,
                    reason="key or value cannot be expressed as one -e pair",
                )
                continue
            args.extend(["-e", f"{key}={text}"])

        if command:
            args.append(command)

        debug_trace.trace(
            "tmux.new_session",
            session=self.tmux_session,
            cwd=str(self.working_dir),
            env_keys_passed=sorted((env or {}).keys()),
            cloudecode_session_id=(env or {}).get("CLOUDECODE_SESSION_ID"),
            dash_e_pairs=[redact_env_pair(a) for i, a in enumerate(args) if i and args[i - 1] == "-e"],
            has_command=bool(command),
            argv_head=(self._tmux_base() + args)[:6],
        )
        returncode, stderr = await self._spawn_session(args, tmux_env)
        debug_trace.trace(
            "tmux.new_session.result",
            session=self.tmux_session,
            returncode=returncode,
            stderr=stderr.decode("utf-8", errors="replace").strip()[:300],
        )
        if returncode != 0:
            msg = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"tmux new-session failed: {msg.strip()}")

        await self._run_tmux(
            "set-option", "-t", self.tmux_session, "remain-on-exit", "on", check=False
        )

        await asyncio.sleep(0.25)

        target_for_probe = _safe_target(self.tmux_session)
        rc_probe, out_probe, _ = await self._run_tmux(
            "list-panes",
            "-t",
            self.tmux_session,
            "-F",
            "#{pane_dead} #{pane_dead_status}",
            check=False,
        )
        if rc_probe == 0:
            probe_line = out_probe.decode("utf-8", errors="replace").splitlines()[0] \
                if out_probe.strip() else ""
            parts = probe_line.split(" ", 1)
            pane_dead = parts[0].strip() if parts else ""
            pane_dead_status = parts[1].strip() if len(parts) > 1 else ""

            if pane_dead == "1" or pane_dead_status:
                rc_cap, out_cap, _ = await self._run_tmux(
                    "capture-pane",
                    "-t",
                    target_for_probe,
                    "-p",
                    "-S",
                    "-200",
                    check=False,
                )
                first_meaningful = ""
                if rc_cap == 0:
                    for raw_line in out_cap.decode("utf-8", errors="replace").splitlines():
                        cleaned = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw_line)
                        cleaned = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", cleaned)
                        cleaned = cleaned.strip()
                        if cleaned:
                            first_meaningful = cleaned
                            break

                await self._run_tmux(
                    "kill-session",
                    "-t",
                    self.tmux_session,
                    check=False,
                )

                logger.error(
                    "tmux_pane_dead_on_arrival",
                    session=self.tmux_session,
                    command=command,
                    pane_dead=pane_dead,
                    pane_dead_status=pane_dead_status,
                    capture=first_meaningful[:500],
                )

                if first_meaningful:
                    raise RuntimeError(
                        f"agent failed to launch: {first_meaningful}"
                    )
                raise RuntimeError(
                    f"agent failed to launch: process exited immediately "
                    f"(pane_dead_status={pane_dead_status or 'unknown'})"
                )

        # already exists
        await run_optional_batch(
            self._run_tmux,
            [
                self._history_limit_command(),
                self._remain_on_exit_command(),
                ("set-option", "-s", "extended-keys", "on"),
                ("set-option", "-g", "mouse", "on"),
                ("bind-key", "-T", "root", "WheelUpPane",
                 "if-shell", "-Ft=", "#{alternate_on}",
                 "copy-mode -e ; send-keys -X -N 3 scroll-up",
                 "send-keys -M"),
                ("bind-key", "-T", "root", "WheelDownPane",
                 "if-shell", "-Ft=", "#{pane_in_mode}",
                 "send-keys -X -N 3 scroll-down",
                 "send-keys -M"),
                ("set-option", "-as", "terminal-features",
                 "xterm-256color:extkeys"),
                ("set-option", "-s", "escape-time", "0"),
                ("set-option", "-t", self.tmux_session, "window-size", "manual"),
                ("set-option", "-t", self.tmux_session, "aggressive-resize", "off"),
            ],
            note="start_decoration",
        )

        pipe_cmd = f"cat >> {shlex.quote(self._pipe_write_path())}"
        rc, _, err = await self._run_tmux(
            "pipe-pane",
            "-t",
            _safe_target(self.tmux_session),
            "-o",
            pipe_cmd,
        )
        if rc != 0:
            logger.error(
                "tmux_pipe_pane_failed",
                stderr=err.decode("utf-8", errors="replace"),
            )

        self._running = True
        self._rotation_started_at = time.monotonic()

        await self.read_async()

        logger.info(
            "tmux_backend_started",
            session=self.tmux_session,
            socket=self.socket_name,
            cwd=str(self.working_dir),
            pipe=str(pipe_path),
        )

    def _record_tail_start_offset(self) -> None:
        """Pin the byte the tail loop must start from, as of RIGHT NOW.

        Description: reads the pipe file's current size and stores it in
          ``self._adopt_tail_start_offset``, which ``_tail_loop`` seeks to
          instead of ``SEEK_END`` when it finally opens the fd. Call it
          immediately after ``ensure_pipe_pane`` returns, on EVERY attach
          path - that call is the moment tmux is known to be appending to
          this path, so it is the earliest offset that cannot replay
          history and the latest one that cannot lose live output.
          A file that does not exist yet records 0, which replays nothing
          because there is nothing there, and a stat that fails records 0
          for the same reason: re-delivering a little is recoverable,
          dropping the stream is not.
        Inputs: none (reads ``self``).
        Output: None. Sets ``self._adopt_tail_start_offset``.
        Example: await self.ensure_pipe_pane(attaching=True)
                 self._record_tail_start_offset()
        """
        try:
            pipe_path = self._resolve_pipe_path()
            if pipe_path.exists():
                self._adopt_tail_start_offset = pipe_path.stat().st_size
            else:
                self._adopt_tail_start_offset = 0
        except OSError as exc:
            logger.warning(
                "adopt_fifo_offset_stat_failed",
                session=self.tmux_session,
                error=str(exc),
            )
            self._adopt_tail_start_offset = 0

    async def attach_existing(self, needs_pipe_setup: bool = False) -> None:
        if self._running:
            logger.debug("tmux_backend_attach_noop", session=self.tmux_session)
            return

        if not await self.is_alive_async():
            raise RuntimeError(
                f"attach_existing: tmux session {self.tmux_session} is not alive"
            )

        do_external_setup = needs_pipe_setup or self._is_external

        if do_external_setup:
            target = _safe_target(self.tmux_session)

            # could not
            rc, out, err = await self._run_tmux(
                "display-message", "-t", target, "-p", "#{pane_dead}",
                check=False,
            )
            if rc != 0:
                raise RuntimeError(
                    f"cannot adopt {self.tmux_session}: pane-dead probe failed: "
                    f"{err.decode('utf-8', errors='replace').strip()}"
                )
            if out.decode("utf-8", errors="replace").strip() == "1":
                raise PaneDeadError(
                    f"cannot adopt {self.tmux_session}: pane already dead"
                )

            await self.ensure_pipe_pane(attaching=True)

            self._record_tail_start_offset()

            await run_optional_batch(
                self._run_tmux,
                [
                    ("set-option", "-t", target, "remain-on-exit", "on"),
                    ("set-option", "-t", target, "window-size", "manual"),
                    ("set-option", "-t", target, "aggressive-resize", "off"),
                    self._history_limit_command(),
                ],
                note="attach_decoration",
            )

        pipe_path = self._resolve_pipe_path()
        if not do_external_setup:
            try:
                await self.ensure_pipe_pane(attaching=True)
                self._record_tail_start_offset()
            except RuntimeError as exc:
                # the session is gone
                # could not
                logger.warning(
                    "tmux_backend_pipe_missing_recreating",
                    session=self.tmux_session,
                    pipe=str(pipe_path),
                    error=str(exc),
                )
                pipe_path.parent.mkdir(parents=True, exist_ok=True)
                pipe_path.touch()

        self._pipe_path = pipe_path
        self._running = True
        self._rotation_started_at = time.monotonic()

        await self.read_async()

        logger.info(
            "tmux_backend_attached_existing",
            session=self.tmux_session,
            socket=self.socket_name,
            pipe=str(pipe_path),
            external=self._is_external,
        )

    async def ensure_pipe_pane(
        self, *, attaching: bool = False, force: bool = False
    ) -> None:
        """Start ``pipe-pane`` on pane 0, replacing any pipe already active.

        Why query-then-act instead of just calling ``pipe-pane``:
        ``pipe-pane -o`` is explicitly a TOGGLE in tmux (since 1.8): running
        it on a pane that already has an active pipe STOPS piping. So we query
        the pane first and branch on the answer rather than toggling blind.

        When a pipe IS already active (typically the user's own session
        logging) we close it with a bare ``pipe-pane`` and start ours. This
        overrides the user's pipe on purpose. The original behaviour was to
        log and return, leaving theirs alone, but an adopted session then had
        no pipe CloudeCode could read: the websocket streaming loop tailed an
        empty file forever and the browser showed a frozen terminal. Streaming
        the session is the whole point of adoption, so ours has to win.

        So the guard compares IDENTITY, not existence. This server records
        the exact path it tails in the pane user option
        ``@cloude_pipe_path`` (``src/core/pipe_liveness.py``) at the moment
        it starts the copier, and skips the re-issue ONLY when a copier is
        running, the option names THIS path, and that file still exists.
        Every other combination re-issues, which replaces whatever copier
        holds the pane. The option lives on the PANE, so it survives this
        server's restart and every other server on the socket can read it;
        tmux itself records no copier command (verified on 3.6a:
        ``#{pane_pipe_command}`` does not exist), so nothing else can answer
        the question.

        We use ``pipe-pane`` WITHOUT ``-o`` when we start ours, because ``-o``
        is the toggle form and by this point no pipe is active either way, so
        we want the explicit non-toggle start semantics.

        THE THIRD WAY TO SATISFY THE GUARD, and what it does and does
        not promise. The guard below means "this backend has a live pane
        to pipe from". ``_running`` proves that for a backend that
        CREATED its pane and ``_is_external`` proves it for one built by
        ``for_external``; neither is true of an OWNED backend attaching
        to a pane that already exists. ``attaching=True`` is passed only
        from inside ``attach_existing``, which has at minimum cleared
        ``is_alive()`` on the SESSION.

        THE PANE, HOWEVER, MAY BE DEAD. ``attach_existing`` runs its
        ``#{pane_dead}`` probe inside the external-setup block, and the
        second caller - the one covering the path where that block was
        skipped - reaches here WITHOUT it. A session can be alive while
        its pane has exited, and on such a pane tmux answers ``pipe-pane``
        with "target pane has exited". That is not a bug in either place:
        this method reports it as RuntimeError and the skipped-setup
        caller catches RuntimeError and falls back to creating the file,
        which is what it did before it called here at all. So the
        contract is "establish the pipe, or say clearly that you could
        not" - NOT "the pane is guaranteed pipeable". Every other caller
        is unchanged: the default is False, so nothing that is neither
        running nor external can reach tmux through here by accident.

        ``force`` IS FOR A CALLER THAT ALREADY MEASURED MORE THAN THE
        OPTION CAN SAY. A thief that does not RECORD the option leaves
        ours standing while taking the bytes, so the identity check above
        reads OWNED and would skip the very re-issue the repair exists
        to perform. ``_repair_stolen_pipe`` has by then measured the
        stronger fact - our file received nothing while the pane
        demonstrably produced output - and that outranks the option.
        MEASURED: without it the probe logged ``pipe_stream_stolen`` and
        then did nothing, which is a repair that reports success and
        leaves the terminal frozen.
        """
        if not (self._running or self._is_external or attaching):
            raise RuntimeError("backend not running")

        target = _safe_target(self.tmux_session)

        pipe_path = self._pipe_write_path()
        reading = await self.read_pipe_ownership()
        if reading is None:
            raise RuntimeError(
                "display-message pipe-ownership probe failed on "
                f"{self.tmux_session}"
            )

        verdict = pipe_liveness.classify_ownership(
            reading, pipe_path, await self._pipe_file_exists(),
            self._legacy_pipe_paths(),
        )

        if verdict == pipe_liveness.OWNED and not force:
            logger.debug(
                "pipe_pane_already_owned",
                session=self.tmux_session,
                pipe=pipe_path,
            )
            return

        if reading.piped:
            if verdict == pipe_liveness.LEGACY_OWNER:
                logger.info(
                    "pipe_pane_migrating_legacy_name",
                    session=self.tmux_session,
                    recorded_owner=reading.owner,
                    expected=pipe_path,
                )
            else:
                logger.info(
                    "pipe_pane_replacing_existing",
                    session=self.tmux_session,
                    reason=verdict,
                    recorded_owner=reading.owner or None,
                    expected=pipe_path,
                )
            await self._run_tmux(
                "pipe-pane", "-t", target,
                check=False,
            )

        await self._ensure_pipe_file()

        pipe_cmd = f"cat >> {shlex.quote(pipe_path)}"
        rc2, _, err2 = await self._run_tmux(
            "pipe-pane", "-t", target, pipe_cmd,
            check=False,
        )
        if rc2 != 0:
            raise RuntimeError(
                f"pipe-pane failed: "
                f"{err2.decode('utf-8', errors='replace').strip()}"
            )

        # could not
        rc3, _, err3 = await self._run_tmux(
            "set-option", "-p", "-t", target,
            pipe_liveness.PIPE_OWNER_OPTION, pipe_path,
            check=False,
        )
        if rc3 != 0:
            logger.warning(
                "pipe_owner_option_write_failed",
                session=self.tmux_session,
                option=pipe_liveness.PIPE_OWNER_OPTION,
                error=err3.decode("utf-8", errors="replace").strip(),
            )

        self._liveness.note_bytes()
        logger.info(
            "pipe_pane_started",
            session=self.tmux_session,
            pipe=pipe_path,
            reason=verdict,
            forced=force,
        )

    async def read_pipe_ownership(
        self,
    ) -> Optional[pipe_liveness.PaneReading]:
        """Read this pane's pipe state and recorded owner in ONE tmux call.

        Description: answers every question the attach guard and the
            liveness probe ask - is the pane dead, is a copier running,
            which path did a Cloude Code server record, and what did the
            pane look like just now - from a single
            ``display-message -p``. One invocation rather than four is
            the point: this runs on every attach and, for a watched
            session, once per silence interval.

            ``pipe-pane`` is never batched with anything (see
            ``src/core/tmux_command_batch.py``); this READ is a single
            command with a multi-field format, which is not a batch.
        Inputs: none. Reads ``self.tmux_session``.
        Output:
            PaneReading, or None when tmux could not be asked or answered
            something unparseable. None is "could not determine" - never
            "no pipe" and never "dead".
        Example: reading = await backend.read_pipe_ownership()
        """
        rc, out, _err = await self._run_tmux(
            "display-message", "-t", _safe_target(self.tmux_session),
            "-p", pipe_liveness.OWNERSHIP_FORMAT,
            check=False,
        )
        if rc != 0:
            return None
        return pipe_liveness.parse_reading(
            out.decode("utf-8", errors="replace")
        )

    @classmethod
    def for_external(
        cls,
        session_name: str,
        working_dir: Path,
        on_output: Optional[Callable[[bytes], Any]] = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
        scrollback_lines: int = 3000,
        viewer_probe: Optional[Callable[[], bool]] = None,
    ) -> "TmuxBackend":
        _safe_target(session_name)

        inst = cls(
            session_id=session_name,
            working_dir=working_dir,
            on_output=on_output,
            socket_name=socket_name,
            scrollback_lines=scrollback_lines,
            viewer_probe=viewer_probe,
        )
        inst.tmux_session = session_name
        inst.slug = session_name
        inst._is_external = True
        return inst

    def _run_listing(self, *args: str) -> tuple[Optional[TmuxListing], str]:
        import subprocess

        if resolve_tmux_path() is None:
            return (
                TmuxListing.unavailable(
                    REASON_TMUX_MISSING,
                    detail="tmux not found on PATH or at any well-known "
                           "install location",
                ),
                "",
            )

        try:
            rc, out, err = self._run_tmux_sync(
                *args,
                check=False,
                timeout=LIST_TIMEOUT_SECONDS,
                env=listing_env(),
                probe=True,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "tmux_listing_timeout",
                argv=args,
                socket=self.socket_name,
                timeout_seconds=LIST_TIMEOUT_SECONDS,
            )
            return (
                TmuxListing.unavailable(
                    REASON_TIMEOUT,
                    detail=f"tmux did not answer within {LIST_TIMEOUT_SECONDS}s",
                ),
                "",
            )
        except TmuxVersionSkewError as exc:
            return TmuxListing.unavailable(REASON_VERSION_SKEW, detail=str(exc)), ""
        except OSError as exc:
            logger.warning(
                "tmux_listing_probe_error",
                argv=args,
                socket=self.socket_name,
                error=str(exc),
            )
            return (
                TmuxListing.unavailable(REASON_PROBE_ERROR, detail=str(exc)),
                "",
            )

        if rc != 0:
            stderr_text = err.decode("utf-8", errors="replace")
            listing = classify_listing_failure(rc, stderr_text)
            if not listing.ok:
                logger.warning(
                    "tmux_listing_unavailable",
                    argv=args,
                    socket=self.socket_name,
                    returncode=rc,
                    reason=listing.reason,
                    stderr=stderr_text.strip()[:200],
                )
            return listing, ""

        return None, out.decode("utf-8", errors="replace")

    def list_attachable_sessions(
        self,
        owned_names: Optional[set] = None,
        owned_instances: Optional[set] = None,
    ) -> TmuxListing:
        failure, stdout_text = self._run_listing(
            "list-sessions", "-F", LISTING_FORMAT
        )
        if failure is not None:
            return failure

        raw_lines = split_listing_rows(stdout_text)
        live_names: set = set()
        results: List[Dict[str, Any]] = []
        refused_rows = 0

        for line in raw_lines:
            row = parse_listing_row(line)
            if row is None:
                refused_rows += 1
                if line.strip():
                    logger.warning(
                        "list_attachable_sessions_unparseable_row",
                        raw=line.strip()[:200],
                        note=(
                            "row did not match LISTING_FORMAT; refused "
                            "rather than parsed on a best-effort basis"
                        ),
                    )
                continue

            name = row["name"]
            if is_plumbing_session(name):
                continue
            created_at_epoch = row["created_at_epoch"]
            live_names.add(name)

            created_by_cloude = resolve_ownership(
                name,
                created_at_epoch,
                owned_instances,
                owned_names,
                prefix=SESSION_PREFIX,
            )

            results.append({
                "name": name,
                "created_by_cloude": created_by_cloude,
                "created_at_epoch": created_at_epoch,
                "window_count": row["window_count"],
                "tmux_session_id": row["session_id"],
            })

        if owned_names:
            stale = owned_names - live_names
            if stale:
                logger.warning(
                    "owned_tmux_sessions_not_in_live_listing",
                    stale=sorted(stale),
                    note="reconciler should prune these on next startup",
                )

        return TmuxListing.answered(results, refused_rows=refused_rows)

    async def probe_respawn(self) -> tuple:
        rc, out, _ = await self._run_tmux(
            "list-panes",
            "-t",
            self.tmux_session,
            "-F",
            RESPAWN_PANE_FORMAT,
            check=False,
        )
        decoded = out.decode("utf-8", errors="replace") if out else ""
        first_line = decoded.splitlines()[0] if decoded.strip() else ""
        if rc != 0 or not first_line:
            return False, None, None
        pane_dead, _dead_status, start_command = parse_respawn_probe(first_line)
        return True, pane_dead, start_command

    async def pane_dead_flag(self) -> Optional[bool]:
        """``#{pane_dead}`` of this session's current pane: True dead, False live, None when tmux did not answer.

        Output: Optional[bool]. Example: await backend.pane_dead_flag()  # False
        """
        rc, out, _ = await self._run_tmux(
            "display-message", "-p", "-t", _safe_target(self.tmux_session), "#{pane_dead}", check=False)
        text = out.decode("utf-8", errors="replace").strip() if out else ""
        return None if rc != 0 or text not in ("0", "1") else text == "1"

    async def session_created_epoch(self) -> Optional[int]:
        """``#{session_created}`` for this tmux session, or None.

        Description: the second half of the instance triple
            ``(tmux_socket, tmux_name, tmux_created_epoch)`` that the
            ``sessions`` row is keyed on, read straight from tmux. Split
            out so :meth:`respawn` can take it either side of a kill and
            PROVE the row still points at the instance it belongs to,
            rather than assuming it - see
            ``src/core/session_instance_rekey.py``.

        Inputs:
            none.

        Output:
            Optional[int]: the unix epoch tmux recorded when this session
                was created, or None when the read did not answer.
                None is cannot-determine and never zero.

        Example:
            >>> await backend.session_created_epoch()
            1788821572
        """
        from src.core.session_instance_rekey import parse_epoch

        rc, out, _ = await self._run_tmux(
            "display-message",
            "-p",
            "-t",
            _safe_target(self.tmux_session),
            "#{session_created}",
            check=False,
        )
        if rc != 0 or not out:
            return None
        return parse_epoch(out.decode("utf-8", errors="replace"))

    async def _resume_presence(self, uuid: str, family: Optional[str] = None) -> Tuple[str, str]:
        from src.core.session_transcript_presence import family_conversation_presence

        presence = family_conversation_presence(family, uuid, working_dir=str(self.working_dir))
        return presence.outcome, presence.detail

    async def respawn(
        self,
        agent_command: Optional[str] = None,
        *,
        chosen_agent_command: Optional[str] = None,
        chosen_agent_type: Optional[str] = None,
        resume_outcome: Optional[str] = None,
        live_restart_confirmed: bool = False,
        spawn_env: Optional[Mapping[str, Optional[str]]] = None,
        require_agent_resume: bool = False,
        resume_family: Optional[str] = None,
        live_restart_reason: Optional[str] = None,
        start_directory: Optional[str] = None,
    ) -> RespawnResult:
        target = _safe_target(self.tmux_session)

        probe_ok, pane_dead, start_command = await self.probe_respawn()

        plan = resolve_respawn_plan(
            probe_ok=probe_ok,
            pane_dead=pane_dead,
            pane_start_command=start_command,
            agent_command=agent_command,
            chosen_agent_command=chosen_agent_command,
            chosen_agent_type=chosen_agent_type,
            resume_outcome=resume_outcome,
            live_restart_confirmed=live_restart_confirmed,
            live_restart_reason=live_restart_reason,
        )

        if plan.resume_uuid:
            outcome, detail = await self._resume_presence(plan.resume_uuid, resume_family)
            guarded = refuse_if_transcript_missing(plan, outcome, detail)
            if guarded is not plan:
                logger.warning(
                    "respawn_transcript_missing",
                    session=self.tmux_session,
                    claude_session_uuid=plan.resume_uuid,
                    was_kind=plan.kind,
                )
            plan = guarded

        if not plan.actionable:
            logger.info(
                "tmux_respawn_refused",
                session=self.tmux_session,
                kind=plan.kind,
                detail=plan.detail,
            )
            return RespawnResult(
                kind=plan.kind,
                ok=False,
                detail=plan.detail,
                conversation=plan.conversation,
            )

        if (require_agent_resume or live_restart_reason is not None) and (
            plan.kind != RESPAWN_AGENT or plan.conversation != CONVERSATION_RESUMED
        ):
            logger.info(
                "tmux_respawn_refused_not_a_resume",
                session=self.tmux_session,
                kind=plan.kind,
                conversation=plan.conversation,
            )
            return RespawnResult(
                kind=plan.kind,
                ok=False,
                detail="refused: this restart would not resume the conversation in its agent",
                conversation=plan.conversation,
            )

        killing = bool(plan.kills_live_pane)

        epoch_before = await self.session_created_epoch() if killing else None

        if spawn_env:
            try:
                await self.set_session_environment(
                    target, spawn_env, note="respawn_set_environment")
            except OSError as exc:
                logger.warning(
                    "respawn_set_environment_failed",
                    session=self.tmux_session,
                    error=str(exc),
                )

        args: List[str] = ["respawn-pane"]
        if killing:
            args.append("-k")
        if start_directory:
            args += ["-c", literal(str(start_directory))]
        args += ["-t", target]
        if plan.command:
            args.append(plan.command)

        if killing:
            logger.warning(
                "tmux_respawn_killing_live_pane",
                session=self.tmux_session,
                kind=plan.kind,
                chosen=plan.chosen,
                conversation=plan.conversation,
                reason=plan.kill_reason,
            )

        rc_spawn, _, err_spawn = await self._run_tmux(*args, check=False)
        if rc_spawn != 0:
            stderr = err_spawn.decode("utf-8", errors="replace").strip()
            logger.error(
                "tmux_respawn_command_failed",
                session=self.tmux_session,
                kind=plan.kind,
                returncode=rc_spawn,
                stderr=stderr[:300],
            )
            return RespawnResult(
                kind=plan.kind,
                ok=False,
                detail=(
                    f"tmux refused to restart this pane: "
                    f"{stderr or 'no error text'}"
                ),
                command=plan.command,
                chosen=plan.chosen,
                conversation=plan.conversation,
                killed_live_pane=False,
                epoch_before=epoch_before,
            )

        await asyncio.sleep(0.25)

        epoch_after = await self.session_created_epoch() if killing else None

        rc_after, out_after, _ = await self._run_tmux(
            "list-panes",
            "-t",
            self.tmux_session,
            "-F",
            RESPAWN_PANE_FORMAT,
            check=False,
        )
        decoded_after = (
            out_after.decode("utf-8", errors="replace") if out_after else ""
        )
        if rc_after != 0 or not decoded_after.strip():
            return RespawnResult(
                kind=plan.kind,
                ok=False,
                detail=(
                    "the restart command succeeded but tmux did not answer "
                    "when asked whether the pane came back, so whether it is "
                    "running cannot be determined"
                ),
                command=plan.command,
                chosen=plan.chosen,
                conversation=plan.conversation,
                killed_live_pane=killing,
                epoch_before=epoch_before,
                epoch_after=epoch_after,
            )

        dead_after, status_after, _ = parse_respawn_probe(
            decoded_after.splitlines()[0]
        )
        if dead_after == "1":
            banner = await self._first_meaningful_pane_line(target)
            logger.error(
                "tmux_respawn_died_on_arrival",
                session=self.tmux_session,
                kind=plan.kind,
                pane_dead_status=status_after,
                capture=banner[:300],
            )
            reason = banner or f"exit status {status_after or 'unknown'}"
            return RespawnResult(
                kind=plan.kind,
                ok=False,
                detail=f"it started and exited again: {reason}",
                command=plan.command,
                chosen=plan.chosen,
                conversation=plan.conversation,
                killed_live_pane=killing,
                epoch_before=epoch_before,
                epoch_after=epoch_after,
            )

        logger.info(
            "tmux_respawn_ok",
            session=self.tmux_session,
            kind=plan.kind,
        )
        return RespawnResult(
            kind=plan.kind,
            ok=True,
            detail=plan.detail,
            command=plan.command,
            chosen=plan.chosen,
            conversation=plan.conversation,
            killed_live_pane=killing,
            epoch_before=epoch_before,
            epoch_after=epoch_after,
        )

    async def _first_meaningful_pane_line(self, target: str) -> str:
        rc, out, _ = await self._run_tmux(
            "capture-pane", "-t", target, "-p", "-S", "-200", check=False
        )
        if rc != 0:
            return ""
        for raw_line in reversed(out.decode("utf-8", errors="replace").splitlines()):
            cleaned = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw_line)
            cleaned = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", cleaned)
            cleaned = cleaned.strip()
            if cleaned and not cleaned.startswith("Pane is dead"):
                return cleaned
        return ""

    async def stop(self) -> None:
        if not self._running and self._reader_task is None:
            return

        logger.info("tmux_backend_stopping", session=self.tmux_session)
        self._running = False
        self._attention_stopping = True

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("tmux_reader_teardown_error", error=str(exc))
            self._reader_task = None

        await self._run_tmux(
            "pipe-pane",
            "-t",
            _safe_target(self.tmux_session),
            check=False,
        )

        await self._run_tmux(
            "kill-session",
            "-t",
            f"={self.tmux_session}",
            check=False,
        )

        logger.info("tmux_backend_stopped", session=self.tmux_session)

    async def write(self, data: bytes) -> None:
        if not self._running:
            raise RuntimeError("TmuxBackend is not running")
        if not data:
            return
        if len(data) <= PASTE_THRESHOLD_BYTES:
            data = await control_route.write(self, data)
            if not data:
                return

        if len(data) > PASTE_THRESHOLD_BYTES:
            await self._write_via_paste_buffer(data)
        elif _has_control_chars(data):
            await self._write_via_hex_keys(data)
        else:
            await self._write_via_send_keys_literal(data)

    async def paste_and_submit(
        self,
        text: str,
        gate: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        from src.core import tmux_one_shot

        if not self._running:
            raise RuntimeError("TmuxBackend is not running")
        await tmux_one_shot.paste_and_submit(self, text, gate)

    async def _write_via_send_keys_literal(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        if text.endswith(";"):
            text = text[:-1] + "\\;"
        rc, _, err = await self._run_tmux(
            "send-keys",
            "-l",
            "-t",
            _safe_target(self.tmux_session),
            # nothing at all
            "--",
            text,
            check=False,
        )
        if rc != 0:
            raise RuntimeError(
                f"tmux send-keys -l failed: {err.decode('utf-8', errors='replace').strip()}"
            )

    async def _write_via_hex_keys(self, data: bytes) -> None:
        hex_args = [f"{b:02x}" for b in data]
        rc, _, err = await self._run_tmux(
            "send-keys",
            "-H",
            "-t",
            _safe_target(self.tmux_session),
            *hex_args,
            check=False,
        )
        if rc != 0:
            raise RuntimeError(
                f"tmux send-keys -H failed: {err.decode('utf-8', errors='replace').strip()}"
            )

    async def _write_via_paste_buffer(
        self, data: bytes, *, bracketed: bool = False
    ) -> None:
        buf_name = f"cloude_{self.slug}"
        rc, _, err = await self._run_tmux(
            "load-buffer",
            "-b",
            buf_name,
            "-",
            stdin_bytes=data,
        )
        if rc != 0:
            raise RuntimeError(
                f"tmux load-buffer failed: {err.decode('utf-8', errors='replace').strip()}"
            )
        await paste_loaded_buffer(
            self._run_tmux,
            buf_name,
            _safe_target(self.tmux_session),
            bracketed=bracketed,
        )

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._run_tmux_sync(
                "resize-window",
                "-t",
                self.tmux_session,
                "-x",
                str(cols),
                "-y",
                str(rows),
                check=False,
            )
            self._run_tmux_sync(
                "refresh-client",
                "-S",
                check=False,
            )
        except Exception as exc:
            logger.debug("tmux_resize_error", error=str(exc))

    def is_alive(self) -> bool:
        rc, _, _ = self._run_tmux_sync(
            "has-session",
            "-t",
            f"={self.tmux_session}",
            check=False,
        )
        return rc == 0

    @property
    def pid(self) -> Optional[int]:
        """The OS pid of pane 0's foreground process, or None if unknown.

        Description: Queries ``#{pane_pid}`` via ``list-panes`` for this
            backend's session/pane. Mirrors ``PTYBackend.pid`` so
            ``SessionManager`` can call ``getattr(backend, "pid", None)``
            uniformly across both backends. Unlike PTYBackend (which tracks
            a single forked pid for the life of the process), a tmux pane's
            foreground pid can change as commands run inside it - this
            always reflects the CURRENT foreground process, not the shell
            that was originally spawned.

        Inputs: none (reads ``self.tmux_session`` / ``self.socket_name``).

        Output:
            Optional[int]: The pane's current foreground pid, or None if
                the session is gone or the query fails.

        Example:
            >>> backend.pid
            48213
        """
        rc, out, _ = self._run_tmux_sync(
            "display-message",
            "-t",
            _safe_target(self.tmux_session),
            "-p",
            "#{pane_pid}",
            check=False,
        )
        if rc != 0:
            return None
        raw = out.decode("utf-8", errors="replace").strip()
        try:
            return int(raw)
        except ValueError:
            return None

    def _pane_listing_cache_key(self) -> Optional[str]:
        return self.socket_name

    def list_pane_status_all(self, *, fresh: bool = False) -> TmuxListing:
        key = self._pane_listing_cache_key()
        if key is None:
            return self._probe_pane_status_all()
        return PANE_LISTING_CACHE.get(
            key, self._probe_pane_status_all, fresh=fresh, cacheable=lambda listing: listing.ok)

    def _probe_pane_status_all(self) -> TmuxListing:
        """Bulk-query activity status for every pane on this tmux server.

        Description: One ``list-panes -a`` call across the WHOLE dedicated
            tmux server, so callers building a status view for many sessions
            (owned + external) pay a single subprocess cost instead of one
            query per session. Only pane 0 of each session is meaningful for
            this app (we never create a second window/pane), so when a
            session reports multiple panes we keep the first line tmux
            returns for that session name.

        Inputs: none (reads ``self.socket_name``).

        Output:
            TmuxListing: ``ok=True`` with one row per LIVE tmux session on
                the socket, each ``{"name": str, "pane_dead": str,
                "pane_current_command": str, "pid": Optional[int],
                "status": str, "created_at_epoch": Optional[int],
                "pane_id": Optional[str]}``.
                ``status`` is pre-resolved via ``resolve_pane_status()`` so
                callers never touch the raw fields unless they want to.
                ``created_at_epoch`` is ``#{session_created}`` - the same
                instance-identity field ``session_store``/``write_state``
                key on - added so a caller that already paid for this one
                probe can scope a durable write to the exact tmux instance
                instead of guessing by name; it is ``None`` only when a
                row could not supply a fifth field (a stale test double,
                never real tmux) and callers must treat that as "instance
                unknown", not as epoch 0. ``ok=True, sessions=[],
                reason='no_server'`` when no server is running (a real
                answer of zero). ``ok=False`` when the probe could not
                run at all, in which case callers must fall back to
                ``STATUS_UNKNOWN`` rather than to "no panes".

        Example:
            >>> backend.list_pane_status_all().sessions
            [{'name': 'cloude_myproj', 'pane_dead': '0',
              'pane_current_command': 'claude', 'pid': 4821,
              'status': 'running', 'created_at_epoch': 1755000000}]
        """
        from src.core.session_status import resolve_pane_status

        failure, stdout_text = self._run_listing(
            "list-panes",
            "-a",
            "-F",
            "#{session_name}|#{pane_dead}|#{pane_current_command}|#{pane_pid}"
            "|#{session_created}|#{pane_id}"
            + SCREEN_STAMP_FORMAT
            + "|#{pane_current_path}",
        )
        if failure is not None:
            return failure

        seen: set = set()
        results: List[Dict[str, Any]] = []
        for line in split_listing_rows(stdout_text):
            line = line.strip()
            if not line or is_plumbing_session(line.split("|", 1)[0]):
                continue
            parts = line.split("|")
            if len(parts) < 4:
                logger.debug("list_pane_status_all_unparseable_row", raw=line)
                continue
            name, pane_dead, current_command, pid_raw = parts[0], parts[1], parts[2], parts[3]
            if name in seen:
                continue
            seen.add(name)
            try:
                pid_val: Optional[int] = int(pid_raw)
            except ValueError:
                pid_val = None
            created_at_epoch: Optional[int] = None
            if len(parts) >= 5:
                try:
                    created_at_epoch = int(parts[4])
                except ValueError:
                    created_at_epoch = None
            pane_id = parts[5].strip() if len(parts) >= 6 else ""
            stamp_end = 6 + SCREEN_STAMP_FIELDS
            pane_path = "|".join(parts[stamp_end:]) if len(parts) > stamp_end else ""
            row = {
                "name": name,
                "pane_dead": pane_dead,
                "pane_current_command": current_command,
                "pid": pid_val,
                "status": resolve_pane_status(pane_dead, current_command),
                "created_at_epoch": created_at_epoch,
                "pane_id": pane_id or None,
                "pane_current_path": pane_path or None,
            }
            row.update(parse_screen_stamp(parts[6:stamp_end]) if len(parts) >= stamp_end
                       else parse_screen_stamp(()))
            results.append(row)
        return TmuxListing.answered(results)

    async def rename_session(self, new_name: str) -> None:
        _safe_target(new_name)

        if not self.tmux_session:
            raise RuntimeError("rename_session: backend has no tmux session name")

        if new_name == self.tmux_session:
            return

        rc, _, err = await self._run_tmux(
            "rename-session",
            "-t",
            self.tmux_session,
            new_name,
            check=False,
        )
        if rc != 0:
            raise RuntimeError(
                f"tmux rename-session failed: "
                f"{err.decode('utf-8', errors='replace').strip()}"
            )

        logger.info(
            "tmux_backend_renamed",
            old=self.tmux_session,
            new=new_name,
            socket=self.socket_name,
        )
        self.tmux_session = new_name

    def discover_existing(self) -> TmuxListing:
        """List all sessions this app owns on our dedicated socket.

        Description: The startup reconciler's only view of live tmux
            state. It PRUNES persisted ownership against this answer, so
            a wrong empty here is not a display bug - it silently
            destroys the user's ownership records. That is why the
            unavailable case must stay distinguishable from zero.

            Recognition, not minting: a name is ours when
            :func:`product_identity.is_owned_session_name` says so, which
            covers both the current mint prefix (:data:`SESSION_PREFIX`)
            and every legacy prefix during the Carnivore rename's
            transition window. What this app MINTS for a brand new
            session is unrelated and still governed by
            ``SESSION_PREFIX`` alone.

        Inputs: none (reads ``self.socket_name``).

        Output:
            TmuxListing: ``ok=True`` with ``sessions`` a list of the
                session names this app recognises as its own, current or
                legacy prefix alike (empty list plus
                ``reason='no_server'`` means genuinely none);
                ``ok=False`` when the probe could not run, in which case
                the caller MUST NOT prune or clear anything.

        Example:
            >>> backend.discover_existing().sessions
            ['cloude_myproj']
        """
        failure, stdout_text = self._run_listing(
            "list-sessions",
            "-F",
            "#{session_name}",
        )
        if failure is not None:
            return failure
        names = split_listing_rows(stdout_text)
        return TmuxListing.answered(
            [n.strip() for n in names if is_owned_session_name(n.strip())]
        )

    def capture_scrollback(self, lines: int = 3000) -> bytes:
        if lines <= 0:
            lines = self.scrollback_lines

        self.replay_in_progress = True
        try:
            rc, out, _ = self._run_tmux_sync(
                "capture-pane",
                "-p",
                "-e",
                "-J",
                "-S",
                f"-{lines}",
                "-t",
                _safe_target(self.tmux_session),
                check=False,
                probe=True,
            )
            if rc != 0:
                return b""
            return normalize_replay_newlines(out)
        finally:
            self.replay_in_progress = False

    def pane_in_alternate_screen(self) -> bool:
        rc, out, _ = self._run_tmux_sync(
            "display-message",
            "-p",
            "-t",
            _safe_target(self.tmux_session),
            "#{alternate_on}",
            check=False,
        )
        if rc != 0:
            return False
        return out.decode("utf-8", errors="replace").strip() == "1"

    def session_age_seconds(self) -> Optional[float]:
        """How long this tmux session has existed, in seconds.

        Used by ``src/api/ws_startup_paint.py`` to tell a session that is
        merely young (nothing painted yet, perfectly normal) apart from
        one that has been alive for a while and has still produced no
        output at all - the signature of a shell startup script blocked
        on a prompt nobody can see.

        Returns:
            Age in seconds, or ``None`` when it cannot be determined -
            tmux failed, is not running, or returned an unparseable
            ``#{session_created}``. ``None`` is a distinct third outcome
            and must NOT be read as "young" or as "old"; the caller
            declines to make a claim.
        """
        rc, out, _ = self._run_tmux_sync(
            "display-message",
            "-p",
            "-t",
            _safe_target(self.tmux_session),
            "#{session_created}",
            check=False,
        )
        if rc != 0:
            return None
        try:
            created = int(out.decode("utf-8", errors="replace").strip())
        except ValueError:
            return None
        return max(0.0, time.time() - created)

    def capture_visible_screen(self) -> bytes:
        rc, out, _ = self._run_tmux_sync(
            "capture-pane",
            "-p",
            "-e",
            "-S",
            "0",
            "-t",
            _safe_target(self.tmux_session),
            check=False,
        )
        if rc != 0:
            return b""
        body = out.rstrip(b"\r\n")
        if not body.strip():
            return b""
        return with_cursor_restore(
            normalize_replay_newlines(body), self.pane_cursor_position())

    def pane_cursor_position(self) -> Optional[Tuple[int, int]]:
        rc, out, _ = self._run_tmux_sync(
            "display-message",
            "-p",
            "-t",
            _safe_target(self.tmux_session),
            "#{cursor_x} #{cursor_y}",
            check=False,
        )
        if rc != 0:
            return None
        parts = out.decode("utf-8", errors="replace").split()
        if len(parts) != 2:
            return None
        try:
            x, y = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        if x < 0 or y < 0:
            return None
        return x, y

    async def pane_geometry(self) -> Optional[Tuple[int, int]]:
        rc, out, _ = await self._run_tmux(
            "display-message",
            "-p",
            "-t",
            _safe_target(self.tmux_session),
            "#{pane_width} #{pane_height}",
            check=False,
        )
        if rc != 0:
            return None
        parts = out.decode("utf-8", errors="replace").split()
        if len(parts) != 2:
            return None
        try:
            cols, rows = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        if cols <= 0 or rows <= 0:
            return None
        return cols, rows

    async def read_async(self) -> None:
        if self._reader_task and not self._reader_task.done():
            return
        self._reader_task = asyncio.create_task(self._tail_loop())


    async def _tail_loop(self) -> None:
        pipe_path = self._resolve_pipe_path()

        deadline = time.monotonic() + 5.0
        while not pipe_path.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        try:
            fd = os.open(str(pipe_path), os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            logger.warning("tmux_pipe_file_missing", path=str(pipe_path))
            return

        try:
            if self._adopt_tail_start_offset is not None:
                try:
                    current_size = os.fstat(fd).st_size
                except OSError:
                    current_size = 0
                seek_to = min(self._adopt_tail_start_offset, current_size)
                try:
                    os.lseek(fd, seek_to, os.SEEK_SET)
                except OSError:
                    try:
                        os.lseek(fd, 0, os.SEEK_END)
                    except OSError:
                        pass
                logger.info(
                    "tmux_tail_seek_adopt_offset",
                    session=self.tmux_session,
                    offset=seek_to,
                    recorded=self._adopt_tail_start_offset,
                    file_size=current_size,
                )
                self._adopt_tail_start_offset = None
            else:
                try:
                    os.lseek(fd, 0, os.SEEK_END)
                except OSError:
                    pass

            waiter = PipeWaiter(fd)
            logger.debug(
                "tmux_tail_wakeup_mode",
                session=self.tmux_session,
                mode="kqueue" if waiter.watching else "poll",
            )

            while self._running:
                now = time.monotonic()
                if now - self._last_rotate_check > 1.0:
                    self._last_rotate_check = now
                    await self._maybe_rotate(pipe_path, fd)

                try:
                    chunk = os.read(fd, 8192)
                except BlockingIOError:
                    chunk = b""
                except OSError as exc:
                    logger.warning("tmux_pipe_read_error", error=str(exc))
                    await asyncio.sleep(0.1)
                    continue

                if not chunk:
                    if self._liveness.due(now, self.has_viewers()):
                        await self._repair_stolen_pipe(pipe_path)
                    await waiter.wait(waiter.backstop(PIPE_IDLE_POLL_SECONDS))
                    continue

                self._liveness.note_bytes()
                await self._emit_output(chunk)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("tmux_tail_loop_crashed", error=str(exc))
        finally:
            try:
                waiter.close()
            except (NameError, OSError, RuntimeError):
                pass
            try:
                os.close(fd)
            except OSError:
                pass

    async def _repair_stolen_pipe(self, pipe_path: Path) -> str:
        """Probe the pane once and re-issue ``pipe-pane`` if we lost it.

        Description: THE REPAIR USED TO RUN ONLY ON ATTACH, and that is
            the whole defect. ``ensure_pipe_pane`` is reached only from
            ``attach_existing`` - at boot re-adopt or on a reconcile
            attach - and opening a terminal websocket does not re-attach.
            So once a second server on this shared socket repointed the
            copier, nothing in the running server ever noticed: the
            browser showed a terminal that took keystrokes and painted
            nothing, and only leaving the session and coming back fixed
            it, because a re-attach takes a fresh ``capture-pane``
            snapshot and never touches this file.

            NOTHING HERE FIRES ON A TIMER ALONE. The caller has already
            established that our file is silent and that somebody is
            watching; this asks the PANE whether it has been producing
            output anyway, and only a positive answer re-issues.

            A MEASURED DEATH STOPS HERE. ``#{pane_dead} == 1`` is a
            reading, not an inference, and re-issuing onto a dead pane
            cannot succeed. A probe that could not RUN is unmeasured and
            changes nothing, exactly as ``PaneDeadError`` requires.

            A MISSING FILE IS REPORTED AND NOT REPAIRED. Our reader holds
            an open descriptor on one inode; re-issuing would create a
            NEW file that this descriptor can never see, so the stream
            would look repaired and stay dead. The attach path owns that
            recovery because it reopens.
        Inputs:
            pipe_path: the file this loop is tailing.
        Output:
            str - the verdict constant from
            :mod:`src.core.pipe_liveness`, for tests and logging.
        Example: verdict = await backend._repair_stolen_pipe(path)
        """
        reading = await self.read_pipe_ownership()
        verdict = self._liveness.verdict(
            reading,
            self._pipe_write_path(),
            time.monotonic(),
            file_exists=await self._pipe_file_exists(),
            legacy_paths=self._legacy_pipe_paths(),
        )

        if verdict not in pipe_liveness.REISSUE_VERDICTS:
            return verdict

        if verdict == pipe_liveness.FILE_MISSING:
            logger.warning(
                "pipe_file_missing_under_reader",
                session=self.tmux_session,
                pipe=str(pipe_path),
                note="reader holds an unlinked inode; a re-attach reopens",
            )
            return verdict

        if verdict in pipe_liveness.THEFT_VERDICTS:
            logger.warning(
                "pipe_stream_stolen",
                session=self.tmux_session,
                reason=verdict,
                pipe=str(pipe_path),
                recorded_owner=(
                    reading.owner if reading is not None and reading.owner
                    else None
                ),
            )

        try:
            await self.ensure_pipe_pane(force=True)
        except RuntimeError as exc:
            logger.warning(
                "pipe_stream_repair_failed",
                session=self.tmux_session,
                reason=verdict,
                error=str(exc),
            )
        return verdict

    async def _emit_output(self, chunk: bytes) -> None:
        if self.on_output is None:
            return
        try:
            result = self.on_output(chunk)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("tmux_on_output_error", error=str(exc))

    async def _drain_to_eof(self, current_fd: int) -> int:
        drained = 0
        while True:
            try:
                chunk = os.read(current_fd, 8192)
            except BlockingIOError:
                break
            except OSError as exc:
                logger.warning("tmux_pipe_drain_read_error", error=str(exc))
                break
            if not chunk:
                break
            drained += len(chunk)
            await self._emit_output(chunk)
        return drained

    async def _maybe_rotate(self, pipe_path: Path, current_fd: int) -> None:
        try:
            st = os.stat(str(pipe_path))
        except FileNotFoundError:
            return

        age_hours = (time.monotonic() - self._rotation_started_at) / 3600.0
        reason = rotation_reason(
            st.st_size, age_hours, MAX_LOG_BYTES, ROTATE_AGE_HOURS
        )
        if reason is None:
            return

        logger.info(
            "tmux_pipe_rotating",
            size=st.st_size,
            age_hours=round(age_hours, 2),
            reason=reason,
        )

        drained = await self._drain_to_eof(current_fd)

        if not truncate_in_place(pipe_path, current_fd):
            return

        self._rotation_started_at = time.monotonic()
        logger.info(
            "tmux_pipe_rotated",
            session=self.tmux_session,
            reason=reason,
            drained_bytes=drained,
        )
