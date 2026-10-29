
from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import select
import subprocess
import threading
import time
from typing import Dict, List, Optional, Sequence

import structlog

from src.core.hosts.tmux_control import ControlParser, Notification, _Block, _Desync
from src.core.hosts.tmux_quote import TmuxQuoteError, command_line
from src.core.tmux_control.names import CONTROL_INPUT_SESSION_PREFIX, control_input_enabled, is_control_input_session
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

LOOP_TIMEOUT_SECONDS = 0.25
REAP_TIMEOUT_SECONDS = 1.0
REFUSED_COOLDOWN_SECONDS = 600.0
START_TIMEOUT_SECONDS = 5.0
RESTART_COOLDOWN_SECONDS = 5.0
IDLE_SERVER_COOLDOWN_SECONDS = 60.0
CLOSE_LOCK_TIMEOUT_SECONDS = 1.0
MAX_REPLY_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 8192

READ_VERBS = frozenset({"list-panes", "list-sessions", "capture-pane", "show-options", "show-environment", "display-message"})

_SEP = "\x1f"

HANDSHAKE = "refresh-client -f ignore-size,no-output"


class _Dead(Exception):
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


def _segments(args: Sequence[str]) -> Optional[List[List[str]]]:
    parts: List[List[str]] = [[]]
    for word in args:
        if word == ";":
            parts.append([])
        else:
            parts[-1].append(word)
    return parts if all(parts) else None


def _unsafe(args: Sequence[str]) -> bool:
    return any(a.endswith(";") for a in args)


def _display_message(args: Sequence[str]) -> Optional[List[str]]:
    rest = list(args[1:])
    if "-p" not in rest or rest.count("-t") != 1:
        return None
    rest.remove("-p")
    at = rest.index("-t")
    if at + 1 >= len(rest):
        return None
    target = rest[at + 1]
    positional = rest[:at] + rest[at + 2:]
    if len(positional) != 1 or positional[0].startswith("-") or not target:
        return None
    return ["display-message", "-p", "-t", target, f"#{{session_name}}{_SEP}{positional[0]}"]


def _strip_session(out: bytes) -> Optional[bytes]:
    name, sep, rest = out.partition(_SEP.encode())
    text = name.decode("utf-8", "replace")
    if not sep or not text or is_control_input_session(text):
        return None
    return rest


class ControlReader:

    def __init__(self, socket_name: str) -> None:
        self.socket_name = socket_name
        self._session = f"{CONTROL_INPUT_SESSION_PREFIX}rd_{os.getpid()}"
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._parser: Optional[ControlParser] = None
        self._retry_after = 0.0
        self._warming = False

    def run(self, args: Sequence[str]) -> Optional[bytes]:
        parts = _segments(args)
        shaped = [self._shape(p) for p in parts] if parts else [None]
        if any(item is None for item in shaped):
            return None
        try:
            lines = [command_line(a[0], a[1:]) for a, _ in shaped]  # type: ignore[misc]
        except TmuxQuoteError:
            return None
        on_loop = _on_loop_thread()
        began = time.monotonic()
        if on_loop:
            got = self._lock.acquire(blocking=False)
        else:
            got = self._lock.acquire(timeout=LOOP_TIMEOUT_SECONDS)
        if not got:
            return None
        try:
            if not self._ensure_up(True):
                return None
            try:
                budget = LOOP_TIMEOUT_SECONDS if on_loop else max(0.05, LOOP_TIMEOUT_SECONDS - (time.monotonic() - began))
                outs = self._exchange(lines, budget)
            except _Dead:
                self._fail(short=True)
                return None
        finally:
            self._lock.release()
        if outs is None:
            return None
        done = []
        for out, (_, strip) in zip(outs, shaped):  # type: ignore[misc]
            out = _strip_session(out) if strip else out
            if out is None:
                return None
            done.append(out)
        return b"".join(done)

    @staticmethod
    def _shape(args: List[str]) -> "Optional[tuple[List[str], bool]]":
        if not args or args[0] not in READ_VERBS or _unsafe(args):
            return None
        verb, rest = args[0], args[1:]
        if verb == "display-message":
            rewritten = _display_message(args)
            return (rewritten, True) if rewritten else None
        if verb == "list-panes" and "-a" not in rest and "-t" not in rest:
            return None
        if verb in ("capture-pane", "show-options", "show-environment") and "-t" not in rest and not any(
                a.startswith("-") and not a.startswith("--") and "g" in a for a in rest):
            return None
        return args, False

    def close(self) -> None:
        got = self._lock.acquire(timeout=CLOSE_LOCK_TIMEOUT_SECONDS)
        try:
            self._kill(reap=False)
            if got:
                self._reap()
        finally:
            if got:
                self._lock.release()


    def _kill(self, reap: bool = True) -> None:
        proc, self._proc, self._parser = self._proc, None, None
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
            try:
                self._ensure_up(False)
            finally:
                self._warming = False

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
        if self._exchange([HANDSHAKE], START_TIMEOUT_SECONDS) is None:
            raise _Refused("handshake refused")
        listed = self._exchange([command_line("list-sessions", ["-F", "#{session_name}"])], START_TIMEOUT_SECONDS)
        names = (listed[0] if listed else b"").decode("utf-8", "replace").split("\n")
        if not any(n and not n.startswith("_carnivore_ctl") for n in names):
            raise _Idle("the server has no session but the hidden ones")
        logger.info("tmux_control_reader_started", socket=self.socket_name, session=self._session)

    def _exchange(self, lines: Sequence[str], timeout: float) -> Optional[List[bytes]]:
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
        blocks = self._read(fd, parser, timeout, nonce.encode("ascii"))
        if len(blocks) != len(lines) + 1:
            raise _Dead("ambiguous framing")
        if any(b.overflow or not b.ok for b in blocks):
            return None
        return [b"".join(line + b"\n" for line in b.lines) for b in blocks[:-1]]

    @staticmethod
    def _read(fd: int, parser: ControlParser, timeout: float, nonce: Optional[bytes]) -> List[_Block]:
        deadline = time.monotonic() + timeout
        blocks: List[_Block] = []
        while True:
            wait = max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([fd], [], [], wait)
                data = os.read(fd, 65536) if ready else b""
            except (OSError, ValueError) as exc:
                raise _Dead("client closed") from exc
            if not ready:
                if nonce is not None:
                    raise _Dead("reply timed out")
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


def control_read(socket_name: Optional[str], args: Sequence[str]) -> Optional[bytes]:
    if not socket_name or not control_input_enabled():
        return None
    with _READERS_LOCK:
        reader = _READERS.get(socket_name)
        if reader is None:
            reader = _READERS[socket_name] = ControlReader(socket_name)
    return reader.run(args)


async def control_read_async(socket_name: Optional[str], args: Sequence[str]) -> Optional[bytes]:
    if not args or args[0] not in READ_VERBS:
        return None
    return await asyncio.to_thread(control_read, socket_name, args)


def close_readers() -> None:
    with _READERS_LOCK:
        readers = list(_READERS.values())
        _READERS.clear()
    for reader in readers:
        reader.close()
