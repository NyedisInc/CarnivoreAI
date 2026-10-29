
from __future__ import annotations

import asyncio
import contextlib
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, List, Optional, Sequence, Tuple, Union

import structlog

from src.core.hosts.ssh_master import backoff_delay
from src.core.hosts.tmux_quote import command_line
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME

logger = structlog.get_logger()

DISCONNECTED = "disconnected"
CONNECTING = "connecting"
UP = "up"
RETRYING = "retrying"

FAILURE_SPAWN = "spawn_failed"
FAILURE_START = "tmux_start_failed"
FAILURE_HANDSHAKE = "handshake_refused"
FAILURE_EOF = "channel_closed"
FAILURE_EXIT = "tmux_exit"
FAILURE_TIMEOUT = "timeout"
FAILURE_DESYNC = "desync"

HANDSHAKE = ("refresh-client", ("-f", "no-output"))

_GUARD_RE = re.compile(rb"%(begin|end|error) (\d{1,20}) (\d{1,20}) (\d{1,3})")

MAX_NOTIFICATION_BYTES = 64 * 1024


class ControlChannelError(Exception):
    pass


class ControlChannelDown(ControlChannelError):
    pass


class ControlTimeout(ControlChannelError):
    pass


class ControlReplyTooLarge(ControlChannelError):
    pass


@dataclass(frozen=True)
class ControlReply:

    ok: bool
    lines: Tuple[bytes, ...]
    number: int

    @property
    def returncode(self) -> int:
        return 0 if self.ok else 1

    @property
    def text(self) -> str:
        return b"\n".join(self.lines).decode("utf-8", "replace")


@dataclass(frozen=True)
class Notification:

    name: str
    args: bytes


@dataclass(frozen=True)
class _Block:

    ok: bool
    flags: int
    number: int
    lines: Tuple[bytes, ...]
    overflow: bool


@dataclass(frozen=True)
class _Desync:

    detail: str


ParserEvent = Union[_Block, Notification, _Desync]


class ControlParser:

    def __init__(self, max_reply_bytes: int) -> None:
        self._cap = max_reply_bytes
        self._partial = bytearray()
        self._discarding = False
        self._guard: Optional[Tuple[bytes, bytes, bytes]] = None
        self._lines: List[bytes] = []
        self._size = 0
        self._overflow = False

    @property
    def in_block(self) -> bool:
        return self._guard is not None

    def feed(self, data: bytes) -> List[ParserEvent]:
        events: List[ParserEvent] = []
        start = 0
        while True:
            newline = data.find(b"\n", start)
            if newline < 0:
                self._hold(data[start:])
                return events
            chunk = data[start:newline]
            start = newline + 1
            if self._discarding:
                self._discarding = False
                self._partial.clear()
                continue
            if self._partial:
                self._partial += chunk
                line = bytes(self._partial)
                self._partial.clear()
            else:
                line = chunk
            event = self._line(line)
            if event is not None:
                events.append(event)

    def _hold(self, tail: bytes) -> None:
        if self._discarding or not tail:
            return
        self._partial += tail
        if len(self._partial) > self._cap:
            self._partial.clear()
            self._discarding = True
            if self._guard is not None:
                self._overflow = True
            else:
                logger.warning("tmux_control_oversize_line_dropped", cap=self._cap)

    def _line(self, line: bytes) -> Optional[ParserEvent]:
        if self._guard is not None:
            match = _GUARD_RE.fullmatch(line)
            if match is not None and match.group(1) != b"begin" and \
                    (match.group(2), match.group(3), match.group(4)) == self._guard:
                return self._close(match.group(1) == b"end")
            self._size += len(line) + 1
            if self._size > self._cap:
                self._overflow = True
            if not self._overflow:
                self._lines.append(line)
            return None
        match = _GUARD_RE.fullmatch(line)
        if match is not None:
            if match.group(1) != b"begin":
                return _Desync(f"%{match.group(1).decode()} outside any block")
            self._guard = (match.group(2), match.group(3), match.group(4))
            self._lines, self._size, self._overflow = [], 0, False
            return None
        if line.startswith(b"%"):
            if len(line) > MAX_NOTIFICATION_BYTES:
                logger.warning("tmux_control_oversize_notification_dropped", size=len(line))
                return None
            name, _, args = line[1:].partition(b" ")
            return Notification(name.decode("ascii", "replace"), args)
        logger.warning("tmux_control_stray_line", size=len(line))
        return None

    def _close(self, ok: bool) -> _Block:
        guard = self._guard
        assert guard is not None
        self._guard = None
        block = _Block(ok, int(guard[2]), int(guard[1]), tuple(self._lines), self._overflow)
        self._lines, self._size, self._overflow = [], 0, False
        return block


def control_argv(tmux_path: str, socket: str) -> List[str]:
    return [tmux_path, "-u", "-L", socket, "-C", "new-session", "-A", "-s", CONTROL_SESSION_NAME,
            "exec cat"]


class _Pending:

    __slots__ = ("future", "verb")

    def __init__(self, future: "asyncio.Future[ControlReply]", verb: str) -> None:
        self.future = future
        self.verb = verb


class _Connection:

    def __init__(self, channel: Any, max_reply_bytes: int) -> None:
        self.channel = channel
        self.parser = ControlParser(max_reply_bytes)
        self.pending: Deque[_Pending] = deque()
        self.write_lock = asyncio.Lock()
        self.closed = asyncio.get_running_loop().create_future()
        self.stderr = bytearray()
        self.tasks: List[asyncio.Task[None]] = []

    def end(self, failure: str, detail: str) -> None:
        if not self.closed.done():
            self.closed.set_result((failure, detail))
        while self.pending:
            waiter = self.pending.popleft()
            if not waiter.future.done():
                waiter.future.set_exception(ControlChannelDown(f"{failure}: {detail}"))
                waiter.future.exception()

    @property
    def is_open(self) -> bool:
        return not self.closed.done()


@dataclass(frozen=True)
class ControlStatus:

    host_key: str
    state: str
    failure: Optional[str]
    detail: str
    retry_in: Optional[float]


Opener = Callable[[Sequence[str]], Awaitable[Any]]


class TmuxControlChannel:

    def __init__(self, host_key: str, opener: Opener, tmux_path: str, socket: str, *,
                 command_timeout: float = 10.0, connect_timeout: float = 15.0,
                 max_reply_bytes: int = 4 << 20, max_in_flight: int = 64,
                 stable_after: float = 30.0, delay: Callable[[int], float] = backoff_delay,
                 on_notification: Optional[Callable[[Notification], None]] = None,
                 on_change: Optional[Callable[[ControlStatus], None]] = None) -> None:
        self.host_key = host_key
        self._opener = opener
        self._argv = control_argv(tmux_path, socket)
        self._command_timeout = command_timeout
        self._connect_timeout = connect_timeout
        self._max_reply = max_reply_bytes
        self._slots = asyncio.Semaphore(max_in_flight)
        self._stable_after = stable_after
        self._delay = delay
        self._on_notification = on_notification
        self._on_change = on_change
        self._wanted = False
        self._task: Optional[asyncio.Task[None]] = None
        self._conn: Optional[_Connection] = None
        self._wake = asyncio.Event()
        self._changed = asyncio.Event()
        self._status = ControlStatus(host_key, DISCONNECTED, None, "", None)


    @property
    def status(self) -> ControlStatus:
        return self._status

    @property
    def is_up(self) -> bool:
        return self._status.state == UP and self._conn is not None and self._conn.is_open

    async def start(self, *, wait: bool = True) -> ControlStatus:
        self._wanted = True
        if self._task is None or self._task.done():
            self._set(CONNECTING)
            self._task = asyncio.create_task(self._supervise(), name=f"tmux-control-{self.host_key}")
        else:
            self._wake.set()
        if wait:
            while self._status.state in (CONNECTING, DISCONNECTED) and self._wanted:
                await self._changed.wait()
        return self._status

    async def stop(self) -> None:
        self._wanted = False
        self._wake.set()
        conn = self._conn
        if conn is not None:
            conn.end(FAILURE_EOF, "the control channel was stopped")
        task, self._task = self._task, None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._set(DISCONNECTED)

    async def command(self, verb: str, *args: str, timeout: Optional[float] = None,
                      max_reply_bytes: Optional[int] = None) -> ControlReply:
        line = command_line(verb, args).encode("utf-8") + b"\n"
        conn = self._conn
        if conn is None or not conn.is_open or self._status.state != UP:
            raise ControlChannelDown(f"host {self.host_key}: the control channel is "
                                     f"{self._status.state}")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self._command_timeout if timeout is None else timeout)
        reply = await self._send(conn, verb, line, deadline)
        if max_reply_bytes is not None and sum(len(x) + 1 for x in reply.lines) > max_reply_bytes:
            raise ControlReplyTooLarge(f"host {self.host_key}: {verb} replied over "
                                       f"{max_reply_bytes} bytes")
        return reply


    async def _send(self, conn: _Connection, verb: str, line: bytes, deadline: float
                    ) -> ControlReply:
        future: "asyncio.Future[ControlReply]" = asyncio.get_running_loop().create_future()
        try:
            async with asyncio.timeout_at(deadline):
                async with self._slots:
                    async with conn.write_lock:
                        if not conn.is_open:
                            raise ControlChannelDown(f"host {self.host_key}: the channel closed")
                        conn.pending.append(_Pending(future, verb))
                        stdin = conn.channel.process.stdin
                        stdin.write(line)
                        await stdin.drain()
                    return await asyncio.shield(future)
        except TimeoutError:
            conn.end(FAILURE_TIMEOUT, f"{verb} got no reply in time")
            logger.warning("tmux_control_command_timeout", host=self.host_key, verb=verb)
            raise ControlTimeout(f"host {self.host_key}: {verb} got no reply in time") from None
        except (ConnectionError, BrokenPipeError) as exc:
            conn.end(FAILURE_EOF, f"write failed ({type(exc).__name__})")
            raise ControlChannelDown(f"host {self.host_key}: the channel closed") from exc


    def _set(self, state: str, failure: Optional[str] = None, detail: str = "",
             retry_in: Optional[float] = None) -> None:
        new = ControlStatus(self.host_key, state, failure, detail, retry_in)
        if new == self._status:
            return
        self._status = new
        (logger.warning if failure else logger.info)(
            "tmux_control_state", host=self.host_key, state=state, failure=failure,
            detail=detail[:200], retry_in=retry_in)
        self._changed.set()
        self._changed = asyncio.Event()
        if self._on_change is not None:
            try:
                self._on_change(new)
            except Exception:  # noqa: BLE001
                logger.exception("tmux_control_on_change_failed", host=self.host_key)

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        attempts = 0
        try:
            while self._wanted:
                self._wake.clear()
                self._set(CONNECTING)
                failure, detail, up_for = await self._one_connection(loop)
                if not self._wanted:
                    break
                if up_for is not None and up_for >= self._stable_after:
                    attempts = 0
                delay = self._delay(attempts)
                attempts += 1
                self._set(RETRYING, failure, detail, retry_in=round(delay, 1))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("tmux_control_supervisor_failed", host=self.host_key)
            self._set(RETRYING, FAILURE_SPAWN, f"the control supervisor failed ({type(exc).__name__})")

    async def _one_connection(self, loop: asyncio.AbstractEventLoop
                              ) -> Tuple[str, str, Optional[float]]:
        try:
            channel = await asyncio.wait_for(self._opener(self._argv), self._connect_timeout)
        except TimeoutError:
            return FAILURE_SPAWN, "the ssh channel did not open in time", None
        except Exception as exc:  # noqa: BLE001
            return FAILURE_SPAWN, str(exc)[:300] or type(exc).__name__, None
        conn = _Connection(channel, self._max_reply)
        self._conn = conn
        conn.tasks = [asyncio.create_task(self._read(conn)), asyncio.create_task(self._drain(conn))]
        up_at: Optional[float] = None
        try:
            verb, args = HANDSHAKE
            try:
                reply = await self._send(conn, verb, command_line(verb, args).encode() + b"\n",
                                         loop.time() + self._connect_timeout)
            except ControlChannelError:
                failure, detail = await self._ended(conn, FAILURE_START)
                return failure, detail, None
            if not reply.ok:
                return FAILURE_HANDSHAKE, (f"tmux refused {verb} -f no-output (tmux 3.2 or later "
                                           f"is required): {reply.text[:200]}"), None
            up_at = loop.time()
            self._set(UP)
            failure, detail = await conn.closed
            return failure, detail, loop.time() - up_at
        finally:
            conn.end(FAILURE_EOF, "the connection was closed")
            self._conn = None
            with contextlib.suppress(Exception):  # noqa: BLE001
                await channel.close()
            for task in conn.tasks:
                task.cancel()
            await asyncio.gather(*conn.tasks, return_exceptions=True)

    async def _ended(self, conn: _Connection, fallback: str) -> Tuple[str, str]:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(conn.closed), timeout=2)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(conn.tasks[1]), timeout=1)
        failure, detail = conn.closed.result() if conn.closed.done() else (fallback, "")
        said = bytes(conn.stderr).decode("utf-8", "replace").strip().splitlines()
        if failure in (FAILURE_EOF, FAILURE_TIMEOUT) and said:
            detail = f"{detail}; the far side said: {said[-1][:200]}"
        return (fallback if failure == FAILURE_EOF else failure), detail

    async def _read(self, conn: _Connection) -> None:
        stdout = conn.channel.process.stdout
        try:
            while conn.is_open:
                data = await stdout.read(65536)
                if not data:
                    conn.end(FAILURE_EOF, "the control stream ended")
                    return
                for event in conn.parser.feed(data):
                    self._dispatch(conn, event)
                    if not conn.is_open:
                        return
        except (ConnectionError, OSError) as exc:
            conn.end(FAILURE_EOF, f"reading failed ({type(exc).__name__})")

    def _dispatch(self, conn: _Connection, event: ParserEvent) -> None:
        if isinstance(event, _Block):
            if event.flags != 1:
                return
            if not conn.pending:
                conn.end(FAILURE_DESYNC, "a reply arrived that no command was waiting for")
                return
            waiter = conn.pending.popleft()
            if waiter.future.done():
                return
            if event.overflow:
                waiter.future.set_exception(ControlReplyTooLarge(
                    f"host {self.host_key}: {waiter.verb} replied over {self._max_reply} bytes"))
            else:
                waiter.future.set_result(ControlReply(event.ok, event.lines, event.number))
            return
        if isinstance(event, _Desync):
            conn.end(FAILURE_DESYNC, event.detail)
            return
        if event.name == "exit":
            conn.end(FAILURE_EXIT, "tmux ended the control client" + (
                f" ({event.args.decode('utf-8', 'replace')[:200]})" if event.args else ""))
            return
        if self._on_notification is not None:
            try:
                self._on_notification(event)
            except Exception:  # noqa: BLE001
                logger.exception("tmux_control_on_notification_failed", host=self.host_key)

    @staticmethod
    async def _drain(conn: _Connection) -> None:
        stderr = conn.channel.process.stderr
        if stderr is None:
            return
        while chunk := await stderr.read(4096):
            conn.stderr += chunk
            if len(conn.stderr) > 4096:
                del conn.stderr[:-4096]
