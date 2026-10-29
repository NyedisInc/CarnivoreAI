
from __future__ import annotations

import asyncio
import re
from typing import Callable, List, Optional, Sequence

import pytest

from src.core.hosts.tmux_control import (
    FAILURE_DESYNC,
    FAILURE_EXIT,
    FAILURE_HANDSHAKE,
    FAILURE_SPAWN,
    FAILURE_TIMEOUT,
    RETRYING,
    UP,
    ControlChannelDown,
    ControlParser,
    ControlReplyTooLarge,
    ControlTimeout,
    Notification,
    TmuxControlChannel,
    control_argv,
)
from src.core.hosts.tmux_quote import TmuxQuoteError
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME

Handler = Callable[["FakeTmux", str], Optional[bytes]]


def block(number: int, lines: Sequence[bytes] = (), *, ok: bool = True, flags: int = 1,
          time: int = 1790000000) -> bytes:
    guard = f"{time} {number} {flags}".encode()
    end = b"%end " if ok else b"%error "
    return b"%begin " + guard + b"\n" + b"".join(x + b"\n" for x in lines) + end + guard + b"\n"


class _Stdin:
    def __init__(self, tmux: "FakeTmux") -> None:
        self._tmux = tmux
        self._buffer = b""

    def write(self, data: bytes) -> None:
        if self._tmux.closed:
            raise BrokenPipeError()
        self._buffer += data
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            self._tmux.receive(line.decode())

    async def drain(self) -> None:
        if self._tmux.closed:
            raise ConnectionResetError()


class _Process:
    def __init__(self, tmux: "FakeTmux") -> None:
        self.stdin = _Stdin(tmux)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()


class FakeTmux:

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.process = _Process(self)
        self.closed = False
        self.lines: List[str] = []
        self.number = 100

    def receive(self, line: str) -> None:
        self.lines.append(line)
        self.number += 1
        if line.startswith("refresh-client"):
            self.emit(block(self.number))
            return
        out = self.handler(self, line)
        if out is not None:
            self.emit(out)

    def emit(self, data: bytes) -> None:
        if not self.closed:
            self.process.stdout.feed_data(data)

    def hang_up(self, stderr: bytes = b"") -> None:
        if stderr:
            self.process.stderr.feed_data(stderr)
        self.closed = True
        self.process.stdout.feed_eof()
        self.process.stderr.feed_eof()

    async def close(self) -> None:
        if not self.closed:
            self.hang_up()


def echo(tmux: FakeTmux, line: str) -> bytes:
    return block(tmux.number, [line.encode()])


class Opener:

    def __init__(self, handler: Handler = echo, fail_first: int = 0,
                 greeting: bytes = b"") -> None:
        self.handler = handler
        self.fail_first = fail_first
        self.greeting = greeting
        self.opened: List[FakeTmux] = []
        self.argvs: List[List[str]] = []

    async def __call__(self, argv: Sequence[str]) -> FakeTmux:
        self.argvs.append(list(argv))
        if self.fail_first:
            self.fail_first -= 1
            raise ConnectionRefusedError("host fake slot 0 is retrying: unreachable")
        tmux = FakeTmux(self.handler)
        tmux.emit(self.greeting or block(1, flags=0) + b"%sessions-changed\n")
        self.opened.append(tmux)
        return tmux


def make_channel(opener: Opener, **options) -> TmuxControlChannel:
    settings = dict(command_timeout=2.0, connect_timeout=2.0, delay=lambda attempt: 0.02)
    settings.update(options)
    return TmuxControlChannel("fake", opener, "/usr/bin/tmux", "carnivore-remote", **settings)


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "condition never became true"
        await asyncio.sleep(0.01)



STREAM = (block(1, flags=0) + b"%sessions-changed\n" + block(5, [b"one", b"%end 1790000000 4 1",
          b"%error 1790000000 5 0", b"%begin 1 2 1", b"%sessions-changed", b""])
          + b"%window-add @3\n" + block(6, [b"bad"], ok=False))


def summarize(events) -> list:
    return [(type(e).__name__, getattr(e, "name", None), getattr(e, "lines", None),
             getattr(e, "ok", None), getattr(e, "flags", None)) for e in events]


def test_parser_frames_blocks_and_notifications() -> None:
    events = ControlParser(1 << 20).feed(STREAM)
    assert summarize(events) == [
        ("_Block", None, (), True, 0),
        ("Notification", "sessions-changed", None, None, None),
        ("_Block", None, (b"one", b"%end 1790000000 4 1", b"%error 1790000000 5 0",
                          b"%begin 1 2 1", b"%sessions-changed", b""), True, 1),
        ("Notification", "window-add", None, None, None),
        ("_Block", None, (b"bad",), False, 1),
    ]
    assert events[3].args == b"@3"


@pytest.mark.parametrize("size", [1, 2, 3, 7, 64])
def test_parser_is_indifferent_to_how_reads_split(size: int) -> None:
    parser = ControlParser(1 << 20)
    events = []
    for start in range(0, len(STREAM), size):
        events += parser.feed(STREAM[start:start + size])
    assert summarize(events) == summarize(ControlParser(1 << 20).feed(STREAM))


def test_parser_splits_on_newline_only() -> None:
    events = ControlParser(1024).feed(block(2, ["a\u0085b c\rd".encode()]))
    assert events[0].lines == ("a\u0085b c\rd".encode(),)


def test_parser_caps_a_reply_and_keeps_framing() -> None:
    parser = ControlParser(10)
    events = parser.feed(block(2, [b"12345", b"67890"]) + block(3, [b"x" * 50]) + block(4, [b"ok"]))
    assert [(e.overflow, e.lines) for e in events] == [
        (True, (b"12345",)), (True, ()), (False, (b"ok",))]
    assert not parser.in_block


def test_parser_reports_a_guard_outside_a_block() -> None:
    events = ControlParser(1024).feed(b"%end 1 2 1\n")
    assert type(events[0]).__name__ == "_Desync"



def test_control_argv_attaches_to_the_hidden_session_on_the_named_socket() -> None:
    assert control_argv("/opt/homebrew/bin/tmux", "carnivore-remote") == [
        "/opt/homebrew/bin/tmux", "-u", "-L", "carnivore-remote", "-C", "new-session", "-A", "-s",
        CONTROL_SESSION_NAME, "exec cat"]


@pytest.mark.asyncio
async def test_handshake_then_replies_in_order_with_notifications_routed() -> None:
    seen: List[Notification] = []

    def chatty(tmux: FakeTmux, line: str) -> bytes:
        return (block(tmux.number, [line.encode()]) + block(9, [b"HOOK"], flags=0)
                + b"%sessions-changed\n")

    opener = Opener(chatty)
    channel = make_channel(opener, on_notification=seen.append)
    try:
        assert (await channel.start()).state == UP
        assert opener.opened[0].lines[0] == "refresh-client '-f' 'no-output'"
        replies = await asyncio.gather(*(channel.command("display-message", "-p", str(i))
                                         for i in range(200)))
        assert [r.lines for r in replies] == [
            (f"display-message '-p' '{i}'".encode(),) for i in range(200)]
        assert all(r.ok and r.returncode == 0 for r in replies)
        assert [n.name for n in seen].count("sessions-changed") >= 200
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_error_reply_is_a_nonzero_returncode_not_an_exception() -> None:
    opener = Opener(lambda t, line: block(t.number, [b"parse error: unknown command: x"], ok=False))
    channel = make_channel(opener)
    try:
        await channel.start()
        reply = await channel.command("has-session", "-Z")
        assert (reply.ok, reply.returncode, reply.text) == (
            False, 1, "parse error: unknown command: x")
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_an_oversize_reply_fails_only_its_own_command() -> None:
    def big(tmux: FakeTmux, line: str) -> bytes:
        return block(tmux.number, [b"x" * 5000] if "big" in line else [b"small"])

    channel = make_channel(Opener(big), max_reply_bytes=1024)
    try:
        await channel.start()
        with pytest.raises(ControlReplyTooLarge):
            await channel.command("capture-pane", "big")
        assert (await channel.command("display-message", "next")).lines == (b"small",)
        with pytest.raises(ControlReplyTooLarge):
            await channel.command("display-message", "next", max_reply_bytes=3)
        assert channel.is_up
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_disconnect_mid_command_fails_it_at_once_then_reconnects() -> None:
    held: List[FakeTmux] = []

    def hang(tmux: FakeTmux, line: str) -> Optional[bytes]:
        if "hold" in line:
            held.append(tmux)
            return None
        return block(tmux.number, [b"ok"])

    opener = Opener(hang)
    channel = make_channel(opener, command_timeout=30.0)
    try:
        await channel.start()
        pending = asyncio.create_task(channel.command("capture-pane", "hold"))
        await wait_until(lambda: bool(held))
        loop = asyncio.get_running_loop()
        began = loop.time()
        held[0].hang_up(b"tmux: lost server\n")
        with pytest.raises(ControlChannelDown):
            await pending
        assert loop.time() - began < 1.0
        await wait_until(lambda: channel.is_up and len(opener.opened) == 2)
        assert (await channel.command("display-message", "again")).lines == (b"ok",)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_a_missed_deadline_times_out_and_recycles_the_connection() -> None:
    states = []
    opener = Opener(lambda t, line: None if "slow" in line else block(t.number, [b"ok"]))
    channel = make_channel(opener, on_change=states.append)
    try:
        await channel.start()
        others = [asyncio.create_task(channel.command("display-message", "slow", timeout=5))]
        with pytest.raises(ControlTimeout):
            await channel.command("display-message", "slow", timeout=0.2)
        with pytest.raises(ControlChannelDown):
            await others[0]
        await wait_until(lambda: channel.is_up and len(opener.opened) == 2)
        assert any(s.failure == FAILURE_TIMEOUT for s in states)
        assert (await channel.command("display-message", "fast")).ok
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_an_unsolicited_reply_is_a_desync_and_recycles() -> None:
    states = []
    opener = Opener()
    channel = make_channel(opener, on_change=states.append)
    try:
        await channel.start()
        opener.opened[0].emit(block(77, [b"nobody asked"]))
        await wait_until(lambda: len(opener.opened) == 2 and channel.is_up)
        assert any(s.failure == FAILURE_DESYNC for s in states)
        opener.opened[1].emit(b"%end 1 2 1\n")
        await wait_until(lambda: len(opener.opened) == 3 and channel.is_up)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_exit_notification_ends_the_connection() -> None:
    states = []
    opener = Opener()
    channel = make_channel(opener, on_change=states.append)
    try:
        await channel.start()
        opener.opened[0].emit(b"%exit server exited\n")
        await wait_until(lambda: len(opener.opened) == 2 and channel.is_up)
        assert any(s.failure == FAILURE_EXIT and "server exited" in s.detail for s in states)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_open_failures_retry_with_backoff_until_up() -> None:
    delays: List[int] = []
    opener = Opener(fail_first=3)

    def delay(attempt: int) -> float:
        delays.append(attempt)
        return 0.01

    channel = make_channel(opener, delay=delay)
    try:
        status = await channel.start()
        assert status.state == RETRYING and status.failure == FAILURE_SPAWN
        await wait_until(lambda: channel.is_up)
        assert delays == [0, 1, 2]
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_a_refused_handshake_is_named() -> None:
    class Old(FakeTmux):
        def receive(self, line: str) -> None:
            self.number += 1
            self.emit(block(self.number, [b"unknown flag -f"], ok=False))

    class OldOpener(Opener):
        async def __call__(self, argv):
            tmux = Old(echo)
            self.opened.append(tmux)
            return tmux

    channel = make_channel(OldOpener())
    try:
        status = await channel.start()
        assert status.state == RETRYING and status.failure == FAILURE_HANDSHAKE
        assert "3.2 or later" in status.detail and "unknown flag -f" in status.detail
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_a_stream_that_ends_before_the_handshake_says_why() -> None:
    class Missing(Opener):
        async def __call__(self, argv):
            tmux = FakeTmux(echo)
            tmux.hang_up(b"sh: 1: /usr/bin/tmux: not found\n")
            self.opened.append(tmux)
            return tmux

    channel = make_channel(Missing())
    try:
        status = await channel.start()
        assert status.state == RETRYING and status.failure == "tmux_start_failed"
        assert "not found" in status.detail
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_commands_refuse_while_down_and_stop_fails_pending() -> None:
    channel = make_channel(Opener(lambda t, line: None))
    with pytest.raises(ControlChannelDown):
        await channel.command("list-sessions")
    await channel.start()
    pending = asyncio.create_task(channel.command("list-sessions", timeout=30))
    await asyncio.sleep(0.05)
    await channel.stop()
    with pytest.raises(ControlChannelDown):
        await pending
    assert channel.status.state == "disconnected"


@pytest.mark.asyncio
async def test_a_newline_argument_never_reaches_the_stream() -> None:
    opener = Opener()
    channel = make_channel(opener)
    try:
        await channel.start()
        with pytest.raises(TmuxQuoteError):
            await channel.command("new-session", "-s", "x\nkill-server")
        assert not any(re.search("kill-server", line) for line in opener.opened[0].lines)
    finally:
        await channel.stop()
