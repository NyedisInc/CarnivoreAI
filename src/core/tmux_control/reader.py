
from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import select
import subprocess
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.hosts.tmux_control import ControlParser, Notification, _Block, _Desync
from src.core.hosts.tmux_quote import TmuxQuoteError, command_line
from src.core.tmux_control.names import CONTROL_INPUT_SESSION_PREFIX, control_input_enabled, is_control_input_session
from src.core.tmux_control.read_shape import READ_VERBS, Answer, answer_of, block_stdout, segments, shape
from src.core.tmux_discovery import TmuxVersionSkewError, register_live_version_source, tmux_argv_prefix

logger = structlog.get_logger()

LOOP_TIMEOUT_SECONDS = 0.25
REAP_TIMEOUT_SECONDS = 1.0
REFUSED_COOLDOWN_SECONDS = 600.0
START_TIMEOUT_SECONDS = 5.0
RESTART_COOLDOWN_SECONDS = 5.0
IDLE_SERVER_COOLDOWN_SECONDS = 60.0
CLOSE_LOCK_TIMEOUT_SECONDS = 1.0
MAX_REPLY_BYTES = 8 * 1024 * 1024
STALE_REPLY_SECONDS = 5.0
MAX_LINE_BYTES = 8192

HANDSHAKE = "refresh-client -f ignore-size,no-output"


class _Dead(Exception):
    pass


class _Late(_Dead):
    pass


class _Idle(_Dead):
    pass


class _Refused(_Dead):
    pass


def _on_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class ControlReader:

    def __init__(self, socket_name: str) -> None:
        self.socket_name = socket_name
        self._session = f"{CONTROL_INPUT_SESSION_PREFIX}rd_{os.getpid()}"
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._parser: Optional[ControlParser] = None
        self._retry_after = 0.0
        self._warming = False
        self._late: Optional[Tuple[bytes, float]] = None
        self._holder: Optional[int] = None

    def query(self, args: Sequence[str]) -> Optional[Answer]:
        parts = segments(args)
        shaped = [shape(p) for p in parts] if parts else [None]
        if any(item is None for item in shaped):
            return None
        try:
            lines = [command_line(a[0], a[1:]) for a, _ in shaped]  # type: ignore[misc]
        except TmuxQuoteError:
            return None
        if self._late is not None or self._holder == threading.get_ident():
            return None
        on_loop = _on_loop_thread()
        if on_loop:
            got = self._lock.acquire(blocking=False)
        else:
            got = self._lock.acquire(timeout=LOOP_TIMEOUT_SECONDS)
        if not got:
            return None
        self._holder = threading.get_ident()
        try:
            if self._late is not None or not self._ensure_up(True):
                return None
            try:
                blocks = self._exchange(lines, LOOP_TIMEOUT_SECONDS)
            except _Late:
                threading.Thread(target=self._drain_late, name="tmux-control-reader-drain", daemon=True).start()
                return None
            except _Dead:
                self._fail(short=True)
                return None
        finally:
            self._holder = None
            self._lock.release()
        return None if blocks is None else answer_of(blocks, shaped)  # type: ignore[arg-type]

    def close(self) -> None:
        got = self._lock.acquire(timeout=CLOSE_LOCK_TIMEOUT_SECONDS)
        self._holder = threading.get_ident() if got else self._holder
        try:
            self._kill(reap=False)
            if got:
                self._reap()
        finally:
            if got:
                self._holder = None
                self._lock.release()


    def _kill(self, reap: bool = True) -> None:
        proc, self._proc, self._parser, self._late = self._proc, None, None, None
        if proc is None:
            return
        with contextlib.suppress(Exception):  # noqa: BLE001
            proc.kill()
            proc.wait(timeout=START_TIMEOUT_SECONDS)
        for stream in (proc.stdin, proc.stdout):
            with contextlib.suppress(Exception):  # noqa: BLE001
                if stream is not None:
                    stream.close()
        if reap:
            self._reap()

    def _reap(self) -> None:
        with contextlib.suppress(Exception):  # noqa: BLE001
            subprocess.run(tmux_argv_prefix(self.socket_name) + ["kill-session", "-t", f"={self._session}"],
                           capture_output=True, timeout=REAP_TIMEOUT_SECONDS, check=False, close_fds=False)

    def _fail(self, cooldown: float = RESTART_COOLDOWN_SECONDS, short: bool = False) -> None:
        self._kill(reap=not (short or _on_loop_thread()))
        self._retry_after = time.monotonic() + cooldown

    def _ensure_up(self, short: bool) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        self._kill(reap=not short)
        if time.monotonic() < self._retry_after:
            return False
        if short:
            if not self._warming:
                self._warming = True
                threading.Thread(target=self._warm, name="tmux-control-reader-start", daemon=True).start()
            return False
        try:
            self._start()
        except _Refused as exc:
            self._fail(REFUSED_COOLDOWN_SECONDS)
            logger.info("tmux_control_reader_refused", socket=self.socket_name, reason=str(exc))
            return False
        except _Idle as exc:
            self._fail(IDLE_SERVER_COOLDOWN_SECONDS)
            logger.debug("tmux_control_reader_idle_server", socket=self.socket_name, reason=str(exc))
            return False
        except (_Dead, OSError, subprocess.SubprocessError, TmuxVersionSkewError) as exc:
            self._fail()
            logger.debug("tmux_control_reader_start_failed", socket=self.socket_name, reason=str(exc))
            return False
        return True

    def _warm(self) -> None:
        with self._lock:
            self._holder = threading.get_ident()
            try:
                self._ensure_up(False)
            finally:
                self._warming = False
                self._holder = None

    def _start(self) -> None:
        argv = tmux_argv_prefix(self.socket_name)
        probe = subprocess.run(argv + ["list-sessions", "-F", "#{session_attached} #{session_name}"],
                               capture_output=True, timeout=START_TIMEOUT_SECONDS, check=False, close_fds=False)
        if probe.returncode != 0:
            raise _Dead("no tmux server on the socket")
        for row in probe.stdout.decode("utf-8", "replace").split("\n"):
            attached, _, name = row.partition(" ")
            if attached == "0" and is_control_input_session(name) and name != self._session:
                subprocess.run(argv + ["kill-session", "-t", f"={name}"], capture_output=True,
                               timeout=START_TIMEOUT_SECONDS, check=False, close_fds=False)
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
        self._proc = subprocess.Popen(
            argv + ["-u", "-C", "new-session", "-A", "-s", self._session, "exec cat"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, bufsize=0)
        self._parser = ControlParser(MAX_REPLY_BYTES)
        shook = self._exchange([HANDSHAKE], START_TIMEOUT_SECONDS)
        if not shook or not shook[0].ok:
            raise _Refused("handshake refused")
        listed = self._exchange([command_line("list-sessions", ["-F", "#{session_name}"])], START_TIMEOUT_SECONDS)
        names = (block_stdout(listed[0]) if listed and listed[0].ok else b"").decode("utf-8", "replace").split("\n")
        if not any(n and not n.startswith("_carnivore_ctl") for n in names):
            raise _Idle("the server has no session but the hidden ones")
        logger.info("tmux_control_reader_started", socket=self.socket_name, session=self._session)

    def _exchange(self, lines: Sequence[str], timeout: float) -> Optional[List[_Block]]:
        proc, parser = self._proc, self._parser
        assert proc is not None and proc.stdin is not None and proc.stdout is not None and parser is not None
        nonce = secrets.token_hex(16)
        raw = ("".join(f"{line}\n" for line in lines) + f"display-message -p {nonce}\n").encode("utf-8")
        if len(raw) > MAX_LINE_BYTES:
            return None
        try:
            fd = proc.stdout.fileno()
        except ValueError as exc:
            raise _Dead("client closed") from exc
        self._read(fd, parser, 0.0, None)
        try:
            proc.stdin.write(raw)
        except (OSError, ValueError) as exc:
            raise _Dead("write failed") from exc
        try:
            blocks = self._read(fd, parser, timeout, nonce.encode("ascii"))
        except _Late:
            self._late = (nonce.encode("ascii"), time.monotonic())
            raise
        if len(blocks) != len(lines) + 1 or not blocks[-1].ok:
            raise _Dead("ambiguous framing")
        return blocks[:-1]

    def _drain_late(self) -> None:
        with self._lock:
            self._holder = threading.get_ident()
            try:
                self._drain_locked()
            finally:
                self._holder = None

    def _drain_locked(self) -> None:
        late, proc, parser = self._late, self._proc, self._parser
        if late is None or proc is None or proc.stdout is None or parser is None:
            return
        nonce, since = late
        try:
            self._read(proc.stdout.fileno(), parser, max(0.0, since + STALE_REPLY_SECONDS - time.monotonic()), nonce)
        except (_Dead, ValueError) as exc:
            self._fail()
            logger.debug("tmux_control_reader_late_reply_lost", socket=self.socket_name, reason=str(exc))
            return
        self._late = None

    @staticmethod
    def _read(fd: int, parser: ControlParser, timeout: float, nonce: Optional[bytes]) -> List[_Block]:
        deadline = time.monotonic() + timeout
        blocks: List[_Block] = []
        while True:
            wait = max(0.0, deadline - time.monotonic())
            try:
                poller = select.poll()
                poller.register(fd, select.POLLIN)
                ready = poller.poll(wait * 1000)
                data = os.read(fd, 65536) if ready else b""
            except (OSError, ValueError) as exc:
                raise _Dead("client closed") from exc
            if not ready:
                if nonce is not None:
                    raise _Late("reply timed out")
                return blocks
            if not data:
                raise _Dead("client ended")
            for event in parser.feed(data):
                if isinstance(event, _Desync):
                    raise _Dead("desync")
                if isinstance(event, Notification) and event.name == "exit":
                    raise _Dead("exit")
                if isinstance(event, _Block) and event.flags == 1 and nonce is not None:
                    blocks.append(event)
                    if event.lines == (nonce,):
                        return blocks


_READERS: Dict[str, ControlReader] = {}
_READERS_LOCK = threading.Lock()


def control_run(socket_name: Optional[str], args: Sequence[str]) -> Optional[Answer]:
    if not socket_name or not control_input_enabled():
        return None
    with _READERS_LOCK:
        reader = _READERS.get(socket_name)
        if reader is None:
            reader = _READERS[socket_name] = ControlReader(socket_name)
    return reader.query(args)


def control_server_version(socket_name: Optional[str]) -> Optional[str]:
    with _READERS_LOCK:
        reader = _READERS.get(socket_name) if socket_name else None
    if reader is None or not control_input_enabled():
        return None
    answer = reader.query(["display-message", "-p", "#{version}"])
    text = answer[1].decode("utf-8", "replace").strip() if answer is not None and answer[0] == 0 else ""
    return text or None


async def control_run_async(socket_name: Optional[str], args: Sequence[str]) -> Optional[Answer]:
    if not args or args[0] not in READ_VERBS:
        return None
    return await asyncio.to_thread(control_run, socket_name, args)


def close_readers() -> None:
    with _READERS_LOCK:
        readers = list(_READERS.values())
        _READERS.clear()
    for reader in readers:
        reader.close()


register_live_version_source(control_server_version)
