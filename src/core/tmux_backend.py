
from __future__ import annotations

import asyncio
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core import debug_trace
from src.core.tmux_control.tmux_error import TmuxError
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
from src.core.hosts.tmux_quote import literal
from src.core.tmux_command_batch import (
    COMMAND_SEPARATOR, BatchOutcome, environment_commands, redact_env_pair, run_on_stdin, run_optional_batch,
)
from src.core.tmux_discovery import (
    pane_client_env,
)
from src.core.pane_tail.tail_supervisor import supervise_tail
from src.core.tmux_paste_buffer import paste_loaded_buffer, unique_buffer_name
from src.core.tmux_transport.pane_listing import PANE_LISTING_FORMAT, parse_pane_listing
from src.core.tmux_transport.target import exact_pane_target, exact_session_target
from src.core.tmux_control import route as control_route
from src.core.tmux_listing_parse import LISTING_FORMAT, split_listing_rows
from src.core.tmux_listing import TmuxListing, classify_listing_failure
from src.core.tmux_stderr import listing_env
from src.core.scrollback_replay import normalize_replay_newlines, with_cursor_restore
from src.core.session_backend import SessionBackend
from src.core.tmux_transport.local import LIST_TIMEOUT_SECONDS, PIPE_SUFFIX, LocalTransport
from src.core.tmux_transport.protocol import TmuxTransport
from src.core.sessions.pane_listing_cache import PANE_LISTING_CACHE
from src.core.sessions.tmux_listing_fold import FoldedListing, FoldedRead, attachable_listing_from_rows
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



MAX_LOG_BYTES: int = 10 * 1024 * 1024

ROTATE_AGE_HOURS: int = 24

INITIAL_COLS: int = 132
INITIAL_ROWS: int = 40

PASTE_THRESHOLD_BYTES: int = 256

DEFAULT_SOCKET_NAME: str = TMUX_SOCKET_NAME

HISTORY_LIMIT: int = 50000

PIPE_IDLE_POLL_SECONDS: float = 0.02

SESSION_PREFIX: str = TMUX_SESSION_PREFIX





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


class PaneDeadError(TmuxError):
    pass




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
        *,
        transport: Optional[TmuxTransport] = None,
    ) -> None:
        super().__init__(session_id, working_dir, on_output)

        self._transport: TmuxTransport = transport if transport is not None else LocalTransport()
        self.host_key = self._transport.host_key
        self.host = self._transport.host
        self._lifecycle = self._transport.make_lifecycle(self)
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

    @property
    def is_remote(self) -> bool:
        return self._transport.is_remote

    def _tmux_base(self) -> List[str]:
        return self._transport.argv_prefix(self.socket_name)

    def _history_limit_command(self) -> tuple:
        return ("set-option", "-g", "history-limit", str(HISTORY_LIMIT))

    def _remain_on_exit_command(self) -> tuple:
        return ("set-option", "-wg", "remain-on-exit", "on")

    def _server_config_argv(self) -> List[str]:
        return self._transport.server_config_argv(
            [self._history_limit_command(), self._remain_on_exit_command()])

    async def _apply_pre_spawn_options(self) -> None:
        await run_optional_batch(
            self._run_tmux,
            [self._history_limit_command(), self._remain_on_exit_command()],
            note="pre_spawn_options",
        )

    async def read_history_limit(self) -> Optional[int]:
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
        if self._pipe_path is None:
            self._pipe_path = self._transport.pipe_read_path(_slugify(self.tmux_session), _slugify(self.slug))
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
        self._transport.preflight(self.socket_name, self.working_dir)

    async def _reset_pipe_file(self) -> None:
        await self._transport.ensure_pipe_file(self._resolve_pipe_path(), self._pipe_write_path(), truncate=True)

    def _pipe_write_path(self) -> str:
        return self._transport.pipe_write_path(self._resolve_pipe_path(), _slugify(self.slug))

    def _copier_command(self) -> str:
        return f"cat >> {shlex.quote(self._pipe_write_path())}"

    async def _pipe_file_exists(self) -> bool:
        return await self._transport.pipe_file_exists(self._pipe_write_path())

    async def _ensure_pipe_file(self) -> None:
        await self._transport.ensure_pipe_file(self._resolve_pipe_path(), self._pipe_write_path(), truncate=False)

    async def _spawn_session(self, args: List[str], tmux_env: Dict[str, str]) -> Tuple[int, bytes]:
        return await self._transport.spawn_session(
            self.socket_name, args, tmux_env,
            [self._history_limit_command(), self._remain_on_exit_command()])

    async def is_alive_async(self) -> bool:
        return await self._lifecycle.is_alive_async()

    async def _run_tmux(
        self,
        *args: str,
        stdin_bytes: Optional[bytes] = None,
        check: bool = True,
    ) -> tuple[int, bytes, bytes]:
        return await self._transport.run(self.socket_name, args, stdin_bytes=stdin_bytes, check=check)

    async def _run_tmux_private(self, *args: str, check: bool = True) -> tuple[int, bytes, bytes]:
        if not self._transport.argv_visible_locally:
            return await self._run_tmux(*args, check=check)
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
        return self._transport.run_sync(self.socket_name, args, stdin_bytes=stdin_bytes, check=check,
                                        timeout=timeout, env=env, probe=probe)


    async def start(
        self,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
    ) -> None:
        if self._running:
            raise RuntimeError("TmuxBackend already running")
        try:
            await self._start_unguarded(command, env, initial_cols, initial_rows)
        except BaseException:
            await self._lifecycle.stopping()
            await self._lifecycle.stopped()
            raise

    async def _start_unguarded(
        self,
        command: Optional[str],
        env: Optional[dict],
        initial_cols: Optional[int],
        initial_rows: Optional[int],
    ) -> None:
        if self._running:
            raise RuntimeError("TmuxBackend already running")

        self._preflight_start()
        env = self._lifecycle.spawn_env(env)

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
            raise TmuxError(f"tmux new-session failed: {msg.strip()}")

        await self._run_tmux(
            "set-option", "-t", exact_pane_target(self.tmux_session), "remain-on-exit", "on", check=False
        )

        await asyncio.sleep(0.25)

        target_for_probe = exact_pane_target(self.tmux_session)
        rc_probe, out_probe, _ = await self._run_tmux(
            "list-panes",
            "-t",
            exact_pane_target(self.tmux_session),
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
                    exact_session_target(self.tmux_session),
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
                    raise TmuxError(
                        f"agent failed to launch: {first_meaningful}"
                    )
                raise TmuxError(
                    f"agent failed to launch: process exited immediately "
                    f"(pane_dead_status={pane_dead_status or 'unknown'})"
                )

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
                ("set-option", "-t", exact_pane_target(self.tmux_session), "window-size", "manual"),
                ("set-option", "-t", exact_pane_target(self.tmux_session), "aggressive-resize", "off"),
            ],
            note="start_decoration",
        )

        rc, _, err = await self._run_tmux("pipe-pane", "-t", exact_pane_target(self.tmux_session), "-o",
                                          self._copier_command())
        if rc != 0:
            logger.error(
                "tmux_pipe_pane_failed",
                stderr=err.decode("utf-8", errors="replace"),
            )

        self._running = True
        self._lifecycle.started()
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
            raise TmuxError(
                f"attach_existing: tmux session {self.tmux_session} is not alive"
            )

        do_external_setup = needs_pipe_setup or self._is_external

        if do_external_setup:
            target = exact_pane_target(self.tmux_session)

            rc, out, err = await self._run_tmux(
                "display-message", "-t", target, "-p", "#{pane_dead}",
                check=False,
            )
            if rc != 0:
                raise TmuxError(
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
        if not (self._running or self._is_external or attaching):
            raise RuntimeError("backend not running")

        target = exact_pane_target(self.tmux_session)

        pipe_path = self._pipe_write_path()
        reading = await self.read_pipe_ownership()
        if reading is None:
            raise TmuxError(
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

        rc2, _, err2 = await self._run_tmux("pipe-pane", "-t", target, self._copier_command(), check=False)
        if rc2 != 0:
            raise TmuxError(
                f"pipe-pane failed: "
                f"{err2.decode('utf-8', errors='replace').strip()}"
            )

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
        rc, out, _err = await self._run_tmux(
            "display-message", "-t", exact_pane_target(self.tmux_session),
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
        exact_pane_target(session_name)

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
        gate = self._transport.listing_gate()
        if gate is not None:
            return gate, ""
        try:
            rc, out, err = self._run_tmux_sync(*args, check=False, timeout=LIST_TIMEOUT_SECONDS,
                                               env=listing_env(), probe=True)
        except self._transport.listing_errors as exc:
            return self._transport.listing_failure(exc, self.socket_name, args), ""

        if rc != 0:
            stderr_text = err.decode("utf-8", errors="replace")
            listing = classify_listing_failure(rc, stderr_text)
            if not listing.ok:
                logger.warning("tmux_listing_unavailable", argv=args, socket=self.socket_name,
                               host=self.host_key, returncode=rc, reason=listing.reason,
                               stderr=stderr_text.strip()[:200])
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
        return attachable_listing_from_rows(
            split_listing_rows(stdout_text), owned_names, owned_instances)

    def list_sessions_and_panes(
        self,
        owned_names: Optional[set] = None,
        owned_instances: Optional[set] = None,
    ) -> FoldedListing:
        if self._transport.is_remote:
            return FoldedListing(self.list_attachable_sessions(owned_names, owned_instances), None)
        read = FoldedRead(self._run_listing, owned_names, owned_instances)
        key = self._pane_listing_cache_key()
        if key is None:
            read.load()
        else:
            PANE_LISTING_CACHE.get(key, read.load, fresh=True, cacheable=lambda listing: listing.ok)
        if read.separate or read.sessions is None:
            return FoldedListing(self.list_attachable_sessions(owned_names, owned_instances), None)
        panes = read.panes
        if panes is not None and panes.ok:
            panes = self._transport.shape_pane_listing(panes)
        return FoldedListing(read.sessions, panes)

    async def probe_respawn(self) -> tuple:
        rc, out, _ = await self._run_tmux(
            "list-panes",
            "-t",
            exact_pane_target(self.tmux_session),
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
        rc, out, _ = await self._run_tmux(
            "display-message", "-p", "-t", exact_pane_target(self.tmux_session), "#{pane_dead}", check=False)
        text = out.decode("utf-8", errors="replace").strip() if out else ""
        return None if rc != 0 or text not in ("0", "1") else text == "1"

    async def session_created_epoch(self) -> Optional[int]:
        from src.core.session_instance_rekey import parse_epoch

        rc, out, _ = await self._run_tmux(
            "display-message",
            "-p",
            "-t",
            exact_pane_target(self.tmux_session),
            "#{session_created}",
            check=False,
        )
        if rc != 0 or not out:
            return None
        return parse_epoch(out.decode("utf-8", errors="replace"))

    async def _resume_presence(self, uuid: str, family: Optional[str] = None) -> Tuple[str, str]:
        return await self._lifecycle.resume_presence(uuid, family)

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
        target = exact_pane_target(self.tmux_session)

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
        await self._ensure_pipe_file()
        args += [COMMAND_SEPARATOR, "pipe-pane", "-t", target, self._copier_command()]

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
            exact_pane_target(self.tmux_session),
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
            await self._lifecycle.stopping()
            await self._lifecycle.stopped()
            return

        logger.info("tmux_backend_stopping", session=self.tmux_session)
        await self._lifecycle.stopping()
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
            exact_pane_target(self.tmux_session),
            check=False,
        )

        await self._run_tmux(
            "kill-session",
            "-t",
            f"={self.tmux_session}",
            check=False,
        )

        await self._lifecycle.stopped()
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
        if self._lifecycle.literal_needs_hex(data):
            await self._write_via_hex_keys(data)
            return
        text = data.decode("utf-8", errors="replace")
        rc, _, err = await self._run_tmux_private(
            "send-keys",
            "-l",
            "-t",
            exact_pane_target(self.tmux_session),
            "--",
            text,
            check=False,
        )
        if rc != 0:
            raise TmuxError(
                f"tmux send-keys -l failed: {err.decode('utf-8', errors='replace').strip()}"
            )

    async def _write_via_hex_keys(self, data: bytes) -> None:
        hex_args = [f"{b:02x}" for b in data]
        rc, _, err = await self._run_tmux_private(
            "send-keys",
            "-H",
            "-t",
            exact_pane_target(self.tmux_session),
            *hex_args,
            check=False,
        )
        if rc != 0:
            raise TmuxError(
                f"tmux send-keys -H failed: {err.decode('utf-8', errors='replace').strip()}"
            )

    async def _write_via_paste_buffer(
        self, data: bytes, *, bracketed: bool = False
    ) -> None:
        buf_name = unique_buffer_name(self.slug)
        rc, _, err = await self._run_tmux(
            "load-buffer",
            "-b",
            buf_name,
            "-",
            stdin_bytes=data,
        )
        if rc != 0:
            raise TmuxError(
                f"tmux load-buffer failed: {err.decode('utf-8', errors='replace').strip()}"
            )
        await paste_loaded_buffer(
            self._run_tmux,
            buf_name,
            exact_pane_target(self.tmux_session),
            bracketed=bracketed,
        )

    def resize(self, cols: int, rows: int) -> None:
        self._lifecycle.resize(cols, rows)

    def is_alive(self) -> bool:
        return self._lifecycle.is_alive()

    @property
    def pid(self) -> Optional[int]:
        return self._lifecycle.pid()

    def _pane_listing_cache_key(self) -> Optional[str]:
        return self._transport.pane_listing_cache_key(self.socket_name)

    def list_pane_status_all(self, *, fresh: bool = False) -> TmuxListing:
        key = self._pane_listing_cache_key()
        listing = (self._probe_pane_status_all() if key is None else PANE_LISTING_CACHE.get(
            key, self._probe_pane_status_all, fresh=fresh, cacheable=lambda listing: listing.ok))
        return self._transport.shape_pane_listing(listing) if listing.ok else listing

    def _probe_pane_status_all(self) -> TmuxListing:
        failure, stdout_text = self._run_listing("list-panes", "-a", "-F", PANE_LISTING_FORMAT)
        if failure is not None:
            return failure
        rows, refused = parse_pane_listing(stdout_text)
        return TmuxListing.answered(rows, refused_rows=refused)

    async def rename_session(self, new_name: str) -> None:
        exact_pane_target(new_name)

        if not self.tmux_session:
            raise TmuxError("rename_session: backend has no tmux session name")

        if new_name == self.tmux_session:
            return

        rc, _, err = await self._run_tmux(
            "rename-session",
            "-t",
            exact_session_target(self.tmux_session),
            new_name,
            check=False,
        )
        if rc != 0:
            raise TmuxError(
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
                exact_pane_target(self.tmux_session),
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
            exact_pane_target(self.tmux_session),
            "#{alternate_on}",
            check=False,
        )
        if rc != 0:
            return False
        return out.decode("utf-8", errors="replace").strip() == "1"

    def session_age_seconds(self) -> Optional[float]:
        rc, out, _ = self._run_tmux_sync(
            "display-message",
            "-p",
            "-t",
            exact_pane_target(self.tmux_session),
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
            exact_pane_target(self.tmux_session),
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
            exact_pane_target(self.tmux_session),
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
            exact_pane_target(self.tmux_session),
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
        if not self._reader_task or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._tail_loop())
        await self._lifecycle.read_started()

    async def ensure_streaming(self, timeout: float = 10.0) -> bool:
        return await self._lifecycle.ensure_streaming(timeout)


    async def _tail_loop(self) -> None:
        await supervise_tail(self._tail_once, is_running=lambda: self._running, session=self.tmux_session)

    async def _tail_once(self) -> None:
        pipe_path = self._resolve_pipe_path()

        deadline = time.monotonic() + 5.0
        while not pipe_path.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        try:
            fd = os.open(str(pipe_path), os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            logger.warning("tmux_pipe_file_missing", path=str(pipe_path))
            raise

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
        return await self._lifecycle.repair_stolen_pipe(lambda: self._probe_and_repair_pipe(pipe_path))

    async def _probe_and_repair_pipe(self, pipe_path: Path) -> str:
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
