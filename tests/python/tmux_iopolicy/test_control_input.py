
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import os
import pty
import random
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctlin_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctlin_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import PaneDeadError, TmuxBackend
from src.core.tmux_control.client import get_control_input, shutdown_all
from src.core.tmux_control.errors import ControlStaleServer
from src.core.tmux_control.names import control_input_enabled, is_control_input_session
from src.core.tmux_listing_parse import is_plumbing_session
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, check=False, timeout=15)


class Rig:

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.socket = derive_test_socket("ctlin")
        self.n = 0

    def pane(self, size: str = "120x30") -> tuple[TmuxBackend, Path]:
        self.n += 1
        name = f"ctlin_{self.n}"
        out = self.tmp / f"pane_{self.n}"
        cols, rows = size.split("x")
        made = _tmux(self.socket, "new-session", "-d", "-s", name, "-x", cols, "-y", rows,
                     f"sh -c 'stty raw -echo; cat > {out}'")
        assert made.returncode == 0, made.stderr
        backend = TmuxBackend(session_id=f"sess-{name}", working_dir=self.tmp,
                              socket_name=self.socket, session_name=name)
        backend._running = True
        time.sleep(0.3)
        return backend, out

    def sessions(self) -> list[str]:
        return _tmux(self.socket, "list-sessions", "-F", "#{session_name}").stdout.split()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    r = Rig(tmp_path)
    try:
        yield r
    finally:
        _tmux(r.socket, "kill-server")


async def _wait_for(path: Path, expected: bytes, timeout: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout
    got = b""
    while time.monotonic() < deadline:
        got = path.read_bytes() if path.exists() else b""
        if got == expected:
            break
        await asyncio.sleep(0.02)
    return got


async def _ref(backend: TmuxBackend, socket: str):
    return await get_control_input(socket).active_pane(backend.tmux_session)


def _kill_client(client) -> None:
    conn = client._conn
    if conn is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(conn.proc.pid, signal.SIGKILL)


def test_the_switch_is_on_unless_it_is_exactly_zero(monkeypatch):
    for name in ("CARNIVORE_CONTROL_INPUT", "CLOUDE_CONTROL_INPUT"):
        monkeypatch.delenv(name, raising=False)
    assert control_input_enabled() is True
    for value, expected in (("0", False), ("", True), ("yes", True), ("1", True)):
        monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", value)
        assert control_input_enabled() is expected
    monkeypatch.delenv("CARNIVORE_CONTROL_INPUT")
    monkeypatch.setenv("CLOUDE_CONTROL_INPUT", "0")
    assert control_input_enabled() is False
    monkeypatch.setenv("CLOUDE_CONTROL_INPUT", "1")
    assert control_input_enabled() is True
    assert is_plumbing_session("_carnivore_ctl") and is_plumbing_session("_carnivore_ctl_in_7")
    assert not is_plumbing_session("carnivore_x") and not is_control_input_session("cloude_x")


@pytest.mark.asyncio
async def test_switch_off_creates_no_control_session_and_uses_the_subprocess_path(rig, monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    backend, out = rig.pane()
    await backend.write(b"plain text")
    assert await _wait_for(out, b"plain text") == b"plain text"
    assert not [n for n in rig.sessions() if is_plumbing_session(n)]
    assert _tmux(rig.socket, "list-clients").stdout.strip() == ""


@pytest.mark.asyncio
async def test_64kib_is_byte_exact_through_send_keys_h(rig):
    backend, out = rig.pane()
    payload = random.Random(7).randbytes(64 * 1024)
    client = get_control_input(rig.socket)
    ref = await _ref(backend, rig.socket)
    await client.send(ref.pane_id, ref.server_pid, payload)
    got = await _wait_for(out, payload)
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(payload).hexdigest()
    dropped = got[:1000] + got[1001:]
    assert hashlib.sha256(dropped).hexdigest() != hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio
async def test_write_uses_the_control_client_byte_exact_with_no_send_keys_spawn(rig, monkeypatch):
    backend, out = rig.pane()
    spawns: list[str] = []
    real_run = TmuxBackend._run_tmux

    async def counting_run(self, *args, **kwargs):
        if args and args[0] == "send-keys":
            spawns.append(args[1])
        return await real_run(self, *args, **kwargs)

    monkeypatch.setattr(TmuxBackend, "_run_tmux", counting_run)
    frames = [b"abc", b"\x7f", b"-", b"\x1b[A", "é☃".encode(), b"- hello", b"\x00\x01", b"x" * 256]
    for frame in frames:
        await backend.write(frame)
    expected = b"".join(frames)
    assert await _wait_for(out, expected) == expected
    assert spawns == []
    assert [n for n in rig.sessions() if is_control_input_session(n)], "the control session must exist while it is used"


@pytest.mark.asyncio
async def test_interleaved_writes_to_two_panes_keep_each_panes_order(rig):
    (ba, out_a), (bb, out_b) = rig.pane(), rig.pane()
    client = get_control_input(rig.socket)
    ra, rb = await _ref(ba, rig.socket), await _ref(bb, rig.socket)
    tokens_a = [f"A{i:04d};".encode() for i in range(200)]
    tokens_b = [f"B{i:04d};".encode() for i in range(200)]
    jobs = []
    for ta, tb in zip(tokens_a, tokens_b):
        jobs.append(client.send(ra.pane_id, ra.server_pid, ta))
        jobs.append(client.send(rb.pane_id, rb.server_pid, tb))
    await asyncio.gather(*jobs)
    assert await _wait_for(out_a, b"".join(tokens_a)) == b"".join(tokens_a)
    assert await _wait_for(out_b, b"".join(tokens_b)) == b"".join(tokens_b)


STREAMS, TOKENS_PER_STREAM = 4, 40


async def _stream(backend: TmuxBackend, trial: int, stream: int, rng_gap: random.Random) -> list[bytes]:
    tokens = [f"s{stream}t{trial:03d}_{i:04d},".encode() for i in range(TOKENS_PER_STREAM)]
    for tok in tokens:
        await backend.write(tok)
        if rng_gap.random() < 0.1:
            await asyncio.sleep(0)
    return tokens


@pytest.mark.asyncio
async def test_killing_the_client_mid_stream_loses_and_duplicates_nothing_over_200_trials(rig):
    backend, out = rig.pane()
    client = get_control_input(rig.socket)
    rng = random.Random(11)
    restarts = fallbacks = 0
    offset = 0
    real_fallback = TmuxBackend._write_via_send_keys_literal

    async def counting_fallback(self, data):
        nonlocal fallbacks
        fallbacks += 1
        await real_fallback(self, data)

    TmuxBackend._write_via_send_keys_literal = counting_fallback
    try:
        for trial in range(200):
            before = client._conn
            killer = asyncio.get_running_loop().call_later(rng.uniform(0.001, 0.015), lambda: _kill_client(client))
            sent = await asyncio.gather(*(_stream(backend, trial, n, rng) for n in range(STREAMS)))
            killer.cancel()
            restarts += client._conn is not before
            expected = sorted(tok for tokens in sent for tok in tokens)
            offset += sum(len(tok) for tokens in sent for tok in tokens)
            deadline = time.monotonic() + 10
            while out.stat().st_size < offset and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.02)
            typed = out.read_bytes()
            assert len(typed) == offset, f"trial {trial}: lost or duplicated keys ({len(typed)} bytes, wanted {offset})"
            got = typed[offset - sum(len(t) for t in expected):].split(b",")[:-1]
            assert sorted(tok + b"," for tok in got) == expected, f"trial {trial}: wrong keys"
            for n, tokens in enumerate(sent):
                mine = [tok for tok in got if tok.startswith(f"s{n}".encode())]
                assert [tok + b"," for tok in mine] == tokens, f"trial {trial}: writer {n} out of order"
    finally:
        TmuxBackend._write_via_send_keys_literal = real_fallback
    assert restarts >= 100, f"only {restarts} of 200 trials actually killed a live client; the test proved nothing"
    assert fallbacks >= 1, "no write ever finished through the subprocess path; the fallback order was never exercised"


@pytest.mark.parametrize("next_server_up", [True, False], ids=["new_server_up_before_recovery", "new_server_up_later"])
@pytest.mark.asyncio
async def test_keys_unacknowledged_when_the_server_dies_never_reach_another_servers_pane(rig, next_server_up):
    orig, orig_out = rig.pane()
    await orig.write(b"first;")
    assert await _wait_for(orig_out, b"first;") == b"first;"
    client = get_control_input(rig.socket)
    server = int(_tmux(rig.socket, "display-message", "-p", "#{pid}").stdout.strip())
    os.kill(server, signal.SIGSTOP)
    try:
        task = asyncio.ensure_future(orig.write(b"KEYS-MEANT-FOR-ORIG\r"))
        await asyncio.sleep(0.3)
        assert not task.done(), "the line must still be unacknowledged when the server dies"
    finally:
        os.kill(server, signal.SIGKILL)
    victim = None
    if next_server_up:
        victim, victim_out = rig.pane()
        victim_pane = _tmux(rig.socket, "display-message", "-p", "-t", f"={victim.tmux_session}:", "#{pane_id}")
        assert victim_pane.stdout.strip() == "%0", "population check: the victim must reuse the old pane id"
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, 40)
    assert all(not st.unacked for st in client._panes.values()), "a failed write must not leave lines queued for a later replay"
    if victim is None:
        victim, victim_out = rig.pane()
        client._retry_after = 0.0
    await victim.write(b"victim-own;")
    await asyncio.sleep(0.6)
    assert victim_out.read_bytes() == b"victim-own;"


@pytest.mark.asyncio
async def test_a_second_callers_recovery_does_not_touch_the_first_callers_lines_in_flight(rig):
    backend, out = rig.pane()
    client = get_control_input(rig.socket)
    ref = await _ref(backend, rig.socket)
    await client.send(ref.pane_id, ref.server_pid, b"warm")
    sent = [b"warm"]
    for k in range(6):
        tok = (f"<{k:04d}:" + "x" * (32 * 1024 - 8) + ">").encode()
        sent.append(tok)
        task = asyncio.ensure_future(client.send(ref.pane_id, ref.server_pid, tok))
        await asyncio.sleep(0)
        await client._recover(ref.pane_id, [])
        await task
    expected = b"".join(sent)
    assert await _wait_for(out, expected) == expected


@pytest.mark.asyncio
async def test_keystrokes_follow_the_sessions_active_pane_like_the_subprocess_path(rig):
    backend, out0 = rig.pane()
    await backend.write(b"a")
    assert await _wait_for(out0, b"a") == b"a"
    out1 = rig.tmp / "window1"
    assert _tmux(rig.socket, "new-window", "-t", f"={backend.tmux_session}:",
                 f"sh -c 'stty raw -echo; cat > {out1}'").returncode == 0
    time.sleep(0.4)
    await backend.write(b"keys")
    assert await _wait_for(out1, b"keys") == b"keys"
    await backend.write(b"P" * 300)
    assert await _wait_for(out1, b"keys" + b"P" * 300) == b"keys" + b"P" * 300
    assert out0.read_bytes() == b"a"


@pytest.mark.asyncio
async def test_the_naive_resend_rule_duplicates_keys_so_the_marker_is_what_makes_it_pass(rig):
    backend, out = rig.pane()
    ref = await _ref(backend, rig.socket)
    rng = random.Random(5)
    duplicated_trials = 0

    async def client_process():
        return await asyncio.create_subprocess_exec(
            "tmux", "-L", rig.socket, "-C", "new-session", "-A", "-s", "naive_ctl", "exec cat",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

    for trial in range(30):
        tokens = [f"n{trial:02d}_{i:04d};".encode() for i in range(1500)]
        proc = await client_process()
        for i, tok in enumerate(tokens):
            proc.stdin.write(f"send-keys -H -t {ref.pane_id} {tok.hex(' ')}\n".encode())
        await asyncio.sleep(rng.uniform(0.003, 0.025))
        proc.kill()
        data = await proc.stdout.read()
        replied = data.count(b"%end") - 1
        proc2 = await client_process()
        for tok in tokens[max(replied, 0):]:
            proc2.stdin.write(f"send-keys -H -t {ref.pane_id} {tok.hex(' ')}\n".encode())
        await proc2.stdin.drain()
        await asyncio.sleep(0.2)
        proc2.kill()
        await proc2.wait()
        _tmux(rig.socket, "kill-session", "-t", "=naive_ctl")
        got = out.read_bytes()
        out.write_bytes(b"") if False else None
        text = got.decode("latin-1")
        if any(text.count(t.decode()) > 1 for t in tokens):
            duplicated_trials += 1
        _tmux(rig.socket, "respawn-pane", "-k", "-t", ref.pane_id, f"sh -c 'stty raw -echo; cat > {out}'")
        await asyncio.sleep(0.2)
    assert duplicated_trials > 0, "the naive rule never duplicated: the kill landed too late to test anything"


@pytest.mark.asyncio
async def test_a_session_killed_under_the_client_is_pane_dead_not_a_hang(rig):
    backend, out = rig.pane()
    await backend.write(b"alive")
    assert await _wait_for(out, b"alive") == b"alive"
    assert _tmux(rig.socket, "kill-session", "-t", f"={backend.tmux_session}").returncode == 0
    with pytest.raises(PaneDeadError):
        await asyncio.wait_for(backend.write(b"dead"), timeout=15)
    other, other_out = rig.pane()
    await other.write(b"still works")
    assert await _wait_for(other_out, b"still works") == b"still works"


@pytest.mark.asyncio
async def test_a_pane_id_from_another_server_is_refused_not_typed(rig):
    backend, out = rig.pane()
    client = get_control_input(rig.socket)
    ref = await _ref(backend, rig.socket)
    await client.send(ref.pane_id, ref.server_pid, b"ok")
    with pytest.raises(ControlStaleServer):
        await client.send(ref.pane_id, ref.server_pid + 1, b"WRONG")
    assert await _wait_for(out, b"ok") == b"ok"
    await asyncio.sleep(0.2)
    assert out.read_bytes() == b"ok"


@pytest.mark.asyncio
async def test_the_pane_size_is_unchanged_by_the_control_client(rig):
    backend, out = rig.pane("100x30")
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 41, 140, 0, 0))
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env["TERM"] = "xterm-256color"
    viewer = subprocess.Popen(["tmux", "-L", rig.socket, "attach", "-t", f"={backend.tmux_session}"],
                              stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    try:
        size = lambda: _tmux(rig.socket, "display-message", "-p", "-t", f"={backend.tmux_session}:",  # noqa: E731
                             "#{window_width}x#{window_height}").stdout.strip()
        deadline = time.monotonic() + 5
        while size() == "100x30" and time.monotonic() < deadline:
            time.sleep(0.05)
        before = size()
        assert before != "100x30", "the normal client never resized the window; the comparison would prove nothing"
        await backend.write(b"hello")
        assert await _wait_for(out, b"hello") == b"hello"
        flags = _tmux(rig.socket, "list-clients", "-F", "#{client_flags}").stdout
        assert "ignore-size" in flags
        assert size() == before
    finally:
        viewer.kill()
        viewer.wait()
        os.close(master)
        os.close(slave)


@pytest.mark.asyncio
async def test_the_control_session_is_absent_from_listing_and_adoption_and_stale_ones_are_reaped(rig):
    backend, out = rig.pane()
    stale = "_carnivore_ctl_in_99999999"
    assert _tmux(rig.socket, "new-session", "-d", "-s", stale, "sleep 600").returncode == 0
    user = "_carnivore_ctl_in_but_attached_elsewhere"
    del user
    await backend.write(b"x")
    assert await _wait_for(out, b"x") == b"x"
    raw = rig.sessions()
    ours = get_control_input(rig.socket).session_name
    assert ours in raw, "population check: the control session must exist on the socket for the absence checks to mean anything"
    assert stale not in raw, "a stale control session (no client attached) is reaped by the next engine"
    assert not any(is_plumbing_session(row["name"]) for row in backend.list_attachable_sessions().sessions)
    assert not any(is_plumbing_session(row["name"]) for row in backend._probe_pane_status_all().sessions)
    assert not any(is_plumbing_session(n) for n in backend.discover_existing().sessions)
    await shutdown_all()
    assert ours not in rig.sessions()
    assert backend.tmux_session in rig.sessions()
