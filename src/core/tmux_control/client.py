
from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import time
import weakref
from collections import deque
from typing import Deque, Dict, List, NamedTuple, Optional

import structlog

from src.core.hosts.tmux_control import ControlParser, Notification, _Block, _Desync
from src.core.tmux_control import changes
from src.core.tmux_control.errors import (
    ControlFallback,
    ControlPaneGone,
    ControlStaleServer,
    ControlUnavailable,
    ControlWriteUnknown,
)
from src.core.tmux_control.framing import (
    PANE_GONE_TEXT,
    PANE_ID_RE,
    SESSION_GONE_TEXT,
    SESSION_NAME_RE,
    active_pane_line,
    chunks,
    keys_line,
    marker_option,
    marker_read_line,
)
from src.core.tmux_control.names import control_input_session_name, is_control_input_session
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

REPLY_TIMEOUT_SECONDS = 2.0
START_TIMEOUT_SECONDS = 5.0
RESTART_COOLDOWN_SECONDS = 5.0
MAX_RECOVERY_ATTEMPTS = 3
MAX_REPLY_BYTES = 64 * 1024

HANDSHAKE = "refresh-client -f ignore-size,no-output"

_APPLIED, _GONE, _FALLBACK, _UNKNOWN = "applied", "gone", "fallback", "unknown"


class PaneRef(NamedTuple):

    server_pid: int
    pane_id: str


class _ClientDied(Exception):
    pass


class _Transient(Exception):
    pass


class _Line:

    __slots__ = ("pane_id", "seq", "data", "raw", "outcome", "pending")

    def __init__(self, pane_id: str, seq: int, data: bytes, raw: bytes) -> None:
        self.pane_id, self.seq, self.data, self.raw = pane_id, seq, data, raw
        self.outcome: Optional[str] = None
        self.pending: Optional["_Pending"] = None


class _Pending:

    __slots__ = ("future", "line", "conn", "need", "seen")

    def __init__(self, future: "asyncio.Future[_Block]", line: Optional[_Line], conn: "_Conn") -> None:
        self.future, self.line, self.conn = future, line, conn
        self.need, self.seen = (2 if line is not None else 1), 0
        future.add_done_callback(lambda f: f.cancelled() or f.exception())


class _PaneState:

    __slots__ = ("seq", "unacked")

    def __init__(self) -> None:
        self.seq = 0
        self.unacked: Dict[int, _Line] = {}


class _Conn:

    __slots__ = ("proc", "inflight", "reader", "dead")

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self.inflight: Deque[_Pending] = deque()
        self.reader: Optional["asyncio.Task[None]"] = None
        self.dead = False


class ControlInput:

    def __init__(self, socket_name: str) -> None:
        self.socket_name = socket_name
        self._session = control_input_session_name()
        self._option = marker_option(secrets.token_hex(4))
        self._order = asyncio.Lock()
        self._conn: Optional[_Conn] = None
        self._server_pid: Optional[int] = None
        self._epoch_pid: Optional[int] = None
        self._panes: Dict[str, _PaneState] = {}
        self._retry_after = 0.0
        self.reply_timeout = REPLY_TIMEOUT_SECONDS

    @property
    def session_name(self) -> str:
        return self._session

    async def send(self, pane_id: str, server_pid: int, data: bytes) -> None:
        if not data:
            return
        if not PANE_ID_RE.fullmatch(pane_id):
            raise ControlUnavailable(f"not a pane id: {pane_id!r}")
        async with self._order:
            await self._ensure_up()
            if server_pid != self._server_pid:
                raise ControlStaleServer("pane id belongs to another tmux server")
            conn = self._conn
            assert conn is not None
            state = self._panes.setdefault(pane_id, _PaneState())
            lines: List[_Line] = []
            for piece in chunks(data):
                state.seq += 1
                line = _Line(pane_id, state.seq, piece, keys_line(pane_id, self._option, state.seq, piece))
                state.unacked[line.seq] = line
                lines.append(line)
                self._submit(conn, line.raw, line)
            await self._drain(conn)
        await self._settle(pane_id, lines)

    async def active_pane(self, session: str) -> PaneRef:
        if not SESSION_NAME_RE.fullmatch(session):
            raise ControlUnavailable("session name is not safe for a control line")
        async with self._order:
            await self._ensure_up()
            conn = self._conn
            assert conn is not None
            pending = self._submit(conn, (active_pane_line(session) + "\n").encode("ascii"), None)
            await self._drain(conn)
        block = await self._wait(pending)
        if block is None:
            raise ControlUnavailable("control client ended before it answered")
        text = _block_text(block)
        if not block.ok:
            if SESSION_GONE_TEXT in text or PANE_GONE_TEXT in text:
                raise ControlPaneGone(f"{SESSION_GONE_TEXT}: {session}")
            raise ControlUnavailable("tmux refused the pane lookup")
        pid_text, _, rest = text.strip().partition("|")
        pane, _, answered = rest.partition("|")
        if not pid_text.isdigit() or answered != session or not PANE_ID_RE.fullmatch(pane):
            raise ControlPaneGone(f"{SESSION_GONE_TEXT}: {session}")
        return PaneRef(int(pid_text), pane)

    async def listen(self) -> bool:
        try:
            async with self._order:
                await self._ensure_up()
        except ControlUnavailable:
            return False
        return self._alive()

    async def close(self) -> None:
        conn, self._conn, self._server_pid = self._conn, None, None
        if conn is None:
            return
        conn.dead = True
        await self._probe(["kill-session", "-t", f"={self._session}"])
        with contextlib.suppress(ProcessLookupError):
            conn.proc.kill()
        with contextlib.suppress(Exception):  # noqa: BLE001
            await asyncio.wait_for(conn.proc.wait(), START_TIMEOUT_SECONDS)
        if conn.reader is not None:
            conn.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await conn.reader
        self._fail_all(conn)


    async def _settle(self, pane_id: str, lines: List[_Line]) -> None:
        conn_waits = [self._wait(ln.pending) for ln in lines if ln.pending is not None]
        await asyncio.gather(*conn_waits)
        if any(ln.outcome is None for ln in lines):
            await self._recover(pane_id, lines)
        if any(ln.outcome == _GONE for ln in lines):
            raise ControlPaneGone(f"{PANE_GONE_TEXT}: {pane_id}")
        rest = b"".join(ln.data for ln in lines if ln.outcome == _FALLBACK)
        if rest:
            logger.warning("tmux_control_input_fallback", socket=self.socket_name, unapplied=len(rest))
            raise ControlFallback(rest)

    async def _recover(self, pane_id: str, lines: List[_Line]) -> None:
        async with self._order:
            mine = [ln for ln in lines if ln.outcome is None]
            with contextlib.suppress(ControlUnavailable):
                await self._ensure_up()
            state = self._panes.get(pane_id)
            mine = [ln for ln in mine if ln.outcome is None]
            if not mine or state is None:
                return
            try:
                self._apply_marker(state, await self._marker_via_subprocess(pane_id))
            except ControlPaneGone:
                self._fail_pane(state, _GONE)
                return
            except ControlWriteUnknown:
                self._finish(state, mine, _UNKNOWN)
                raise
            self._finish(state, [ln for ln in mine if ln.outcome is None], _FALLBACK)
            logger.info("tmux_control_input_recovered_by_subprocess_marker", socket=self.socket_name)

    async def _replay_all(self, conn: _Conn) -> None:
        for pane_id, state in list(self._panes.items()):
            if not state.unacked:
                continue
            try:
                self._apply_marker(state, await self._marker_via_client(conn, pane_id))
            except ControlPaneGone:
                self._fail_pane(state, _GONE)
                continue
            tail = list(state.unacked.values())
            for line in tail:
                self._submit(conn, line.raw, line)
            await self._drain(conn)
            await asyncio.gather(*(self._wait(ln.pending) for ln in tail))
            if state.unacked:
                raise _Transient()
        logger.info("tmux_control_input_replayed", socket=self.socket_name)

    @staticmethod
    def _apply_marker(state: _PaneState, applied: int) -> None:
        for seq in [s for s in state.unacked if s <= applied]:
            state.unacked.pop(seq).outcome = _APPLIED

    @staticmethod
    def _finish(state: _PaneState, lines: List[_Line], outcome: str) -> None:
        for line in lines:
            state.unacked.pop(line.seq, None)
            line.outcome = outcome

    def _abandon_panes(self) -> None:
        for state in self._panes.values():
            self._fail_pane(state, _GONE)
        self._panes.clear()

    @staticmethod
    def _fail_pane(state: _PaneState, outcome: str) -> None:
        for line in state.unacked.values():
            line.outcome = outcome
        state.unacked.clear()

    async def _marker_via_client(self, conn: _Conn, pane_id: str) -> int:
        block = await self._command(conn, marker_read_line(pane_id, self._option), self.reply_timeout)
        if block is None:
            raise _Transient()
        if not block.ok:
            if PANE_GONE_TEXT in _block_text(block):
                raise ControlPaneGone(pane_id)
            raise _Transient()
        return _parse_marker(_block_text(block))

    async def _marker_via_subprocess(self, pane_id: str) -> int:
        rc, out = await self._probe(["show-options", "-pqv", "-t", pane_id, self._option])
        if rc == 0:
            try:
                return _parse_marker(out)
            except ValueError as exc:
                raise ControlWriteUnknown("sequence marker unreadable") from exc
        if PANE_GONE_TEXT in out:
            raise ControlPaneGone(pane_id)
        raise ControlWriteUnknown("could not measure what the control client applied")


    def _alive(self) -> bool:
        conn = self._conn
        return conn is not None and not conn.dead and conn.proc.returncode is None

    async def _ensure_up(self) -> None:
        for _ in range(MAX_RECOVERY_ATTEMPTS):
            if self._alive():
                return
            if time.monotonic() < self._retry_after:
                raise ControlUnavailable("control client cooling down after a failed start")
            try:
                await self._start()
                conn = self._conn
                assert conn is not None
                await self._replay_all(conn)
            except _Transient:
                continue
            except ControlUnavailable:
                self._retry_after = time.monotonic() + RESTART_COOLDOWN_SECONDS
                raise
        if not self._alive():
            self._retry_after = time.monotonic() + RESTART_COOLDOWN_SECONDS
            raise ControlUnavailable("control client kept dying during replay")

    async def _start(self) -> None:
        try:
            argv = tmux_argv_prefix(self.socket_name)
        except TmuxVersionSkewError as exc:
            raise ControlUnavailable("no tmux binary matches the running server") from exc
        pid = await self._server_pid_and_reap(argv)
        if self._epoch_pid is not None and pid != self._epoch_pid:
            logger.warning("tmux_control_input_server_changed", socket=self.socket_name)
            self._abandon_panes()
        self._epoch_pid = pid
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, "-C", "new-session", "-A", "-s", self._session, "exec cat",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")})
        except OSError as exc:
            raise ControlUnavailable(f"could not spawn the control client: {exc}") from exc
        conn = _Conn(proc)
        conn.reader = asyncio.create_task(self._read_loop(conn))
        self._conn = conn
        block = await self._command(conn, HANDSHAKE, START_TIMEOUT_SECONDS)
        if block is None or not block.ok:
            self._terminate(conn)
            raise ControlUnavailable("control client handshake failed")
        self._server_pid = pid
        logger.info("tmux_control_input_started", socket=self.socket_name, session=self._session)

    async def _server_pid_and_reap(self, argv: List[str]) -> int:
        rc, out = await self._probe(
            ["list-sessions", "-F", "#{pid} #{session_attached} #{session_name}"], argv)
        if rc != 0 or not out.strip():
            raise ControlUnavailable("no tmux server on the socket")
        pid = 0
        for row in out.split("\n"):
            parts = row.split(" ", 2)
            if len(parts) != 3 or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            name = parts[2]
            if is_control_input_session(name) and name != self._session and parts[1] == "0":
                await self._probe(["kill-session", "-t", f"={name}"], argv)
                logger.info("tmux_control_input_stale_session_reaped", socket=self.socket_name)
        if not pid:
            raise ControlUnavailable("tmux listing carried no server pid")
        return pid

    async def _probe(self, args: List[str], argv: Optional[List[str]] = None) -> "tuple[int, str]":
        try:
            base = argv if argv is not None else tmux_argv_prefix(self.socket_name)
            proc = await asyncio.create_subprocess_exec(
                *base, *args, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(proc.communicate(), START_TIMEOUT_SECONDS)
        except (OSError, TmuxVersionSkewError, asyncio.TimeoutError):
            return 255, ""
        return proc.returncode or 0, out.decode("utf-8", errors="replace")

    def _submit(self, conn: _Conn, raw: bytes, line: Optional[_Line]) -> _Pending:
        pending = _Pending(asyncio.get_running_loop().create_future(), line, conn)
        if line is not None:
            line.pending = pending
        if conn.dead:
            pending.future.set_exception(_ClientDied())
            return pending
        conn.inflight.append(pending)
        try:
            assert conn.proc.stdin is not None
            conn.proc.stdin.write(raw)
        except (OSError, RuntimeError):
            self._terminate(conn)
        return pending

    async def _drain(self, conn: _Conn) -> None:
        try:
            assert conn.proc.stdin is not None
            await asyncio.wait_for(conn.proc.stdin.drain(), self.reply_timeout)
        except (OSError, RuntimeError, asyncio.TimeoutError):
            self._terminate(conn)

    async def _command(self, conn: _Conn, text: str, timeout: float) -> Optional[_Block]:
        pending = self._submit(conn, (text + "\n").encode("ascii"), None)
        await self._drain(conn)
        return await self._wait(pending, timeout)

    async def _wait(self, pending: Optional[_Pending], timeout: Optional[float] = None) -> Optional[_Block]:
        if pending is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(pending.future), timeout or self.reply_timeout)
        except asyncio.TimeoutError:
            self._terminate(pending.conn)
        except _ClientDied:
            return None
        try:
            return await asyncio.wait_for(pending.future, START_TIMEOUT_SECONDS)
        except (_ClientDied, asyncio.TimeoutError):
            return None

    def _terminate(self, conn: _Conn) -> None:
        conn.dead = True
        with contextlib.suppress(ProcessLookupError):
            conn.proc.kill()


    async def _read_loop(self, conn: _Conn) -> None:
        parser = ControlParser(MAX_REPLY_BYTES)
        why = "eof"
        stream = conn.proc.stdout
        assert stream is not None
        try:
            while True:
                data = await stream.read(65536)
                if not data:
                    break
                for event in parser.feed(data):
                    if isinstance(event, _Block):
                        if event.flags == 1 and not self._reply(conn, event):
                            why = "reply_without_command"
                            return
                    elif isinstance(event, Notification):
                        if event.name == "exit":
                            why = "exit"
                            return
                        changes.emit(self.socket_name, event.name)
                    elif isinstance(event, _Desync):
                        logger.warning("tmux_control_input_desync", detail=event.detail)
                        why = "desync"
                        return
        except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
            logger.warning("tmux_control_input_read_failed", error=str(exc))
            why = "read_failed"
        finally:
            self._terminate(conn)
            if self._conn is conn:
                self._conn, self._server_pid = None, None
            self._fail_all(conn)
            with contextlib.suppress(Exception):  # noqa: BLE001
                await asyncio.wait_for(conn.proc.wait(), START_TIMEOUT_SECONDS)
            logger.info("tmux_control_input_client_ended", socket=self.socket_name, why=why)
            changes.emit(self.socket_name, "sessions-changed")

    def _reply(self, conn: _Conn, block: _Block) -> bool:
        if not conn.inflight:
            return False
        pending = conn.inflight[0]
        pending.seen += 1
        if block.ok and pending.seen < pending.need:
            return True
        conn.inflight.popleft()
        line = pending.line
        if line is not None and line.outcome is None:
            if block.ok:
                line.outcome = _APPLIED
                state = self._panes.get(line.pane_id)
                if state is not None:
                    state.unacked.pop(line.seq, None)
            elif PANE_GONE_TEXT in _block_text(block):
                line.outcome = _GONE
                state = self._panes.get(line.pane_id)
                if state is not None:
                    state.unacked.pop(line.seq, None)
            else:
                self._terminate(conn)
        if not pending.future.done():
            pending.future.set_result(block)
        return True

    @staticmethod
    def _fail_all(conn: _Conn) -> None:
        while conn.inflight:
            pending = conn.inflight.popleft()
            if not pending.future.done():
                pending.future.set_exception(_ClientDied())


def _block_text(block: _Block) -> str:
    return b"\n".join(block.lines).decode("utf-8", "replace")


def _parse_marker(text: str) -> int:
    text = text.strip()
    return int(text) if text else 0


_REGISTRY: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, ControlInput]]" = (
    weakref.WeakKeyDictionary())


def get_control_input(socket_name: str) -> ControlInput:
    per_loop = _REGISTRY.setdefault(asyncio.get_running_loop(), {})
    client = per_loop.get(socket_name)
    if client is None:
        client = per_loop[socket_name] = ControlInput(socket_name)
    return client


async def shutdown_all() -> None:
    for client in list(_REGISTRY.pop(asyncio.get_running_loop(), {}).values()):
        await client.close()
