
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctlerr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctlerr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_control.reader import close_readers, control_run
from src.core.tmux_transport.local import LocalTransport
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")

HOSTILE = "a'; kill-session -t =victim ; 'b#{pane_id}$(x)\""

UNSET = "CC2642_NEVER_SET"

ERROR_READS: List[List[str]] = [
    ["has-session", "-t", "=nosuch"],
    ["has-session", "-t", "=known"],
    ["show-environment", "-t", "=known", UNSET],
    ["show-environment", "-g", UNSET],
    ["show-environment", "-t", "=nosuch", UNSET],
    ["capture-pane", "-p", "-t", "=nosuch:"],
    ["capture-pane", "-p", "-t", "%99999"],
    ["list-panes", "-t", "=nosuch:", "-F", "#{pane_id}"],
    ["list-panes", "-s", "-t", "=nosuch", "-F", "#{pane_id}"],
    ["show-options", "-pv", "-t", "=nosuch:", "@cc2642"],
    ["show-options", "-pqv", "-t", "=nosuch:", "@cc2642"],
    ["show-options", "-v", "-t", "=nosuch", "status"],
    ["has-session", "-t", f"={HOSTILE}missing"],
    ["capture-pane", "-p", "-t", f"={HOSTILE}missing:"],
    ["show-environment", "-t", f"={HOSTILE}missing", UNSET],
    ["has-session", "-t", f"={HOSTILE}"],
]


def control_read(socket: str, args: List[str]) -> Optional[bytes]:
    answer = control_run(socket, args)
    return answer[1] if answer is not None and answer[0] == 0 else None


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


def _up(socket: str) -> None:
    for _ in range(100):
        if control_read(socket, ["list-sessions"]) is not None:
            return
        time.sleep(0.1)
    raise AssertionError("client never came up")


class _SpawnSpy:

    def __init__(self, monkeypatch: pytest.MonkeyPatch, socket: str) -> None:
        self.socket, self.spawns = socket, []  # type: ignore[var-annotated]
        real_run, real_popen, real_exec = subprocess.run, subprocess.Popen, asyncio.create_subprocess_exec

        def run(argv: Any, *a: Any, **k: Any) -> Any:
            self._note(argv)
            return real_run(argv, *a, **k)

        def popen(argv: Any, *a: Any, **k: Any) -> Any:
            self._note(argv)
            return real_popen(argv, *a, **k)

        async def exec_(*argv: Any, **k: Any) -> Any:
            self._note(argv)
            return await real_exec(*argv, **k)

        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)

    def _note(self, argv: Sequence[Any]) -> None:
        words = [str(w) for w in argv]
        if self.socket in words:
            self.spawns.append(words)


@pytest.fixture()
def socket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("ctlerr")
    for session in ("victim", "known", HOSTILE.replace("#", "##")):
        assert _tmux(name, "new-session", "-d", "-s", session, "-x", "80", "-y", "24", "cat").returncode == 0
    time.sleep(0.3)
    try:
        yield name
    finally:
        close_readers()
        _tmux(name, "kill-server")


def _subprocess_answers(monkeypatch: pytest.MonkeyPatch, reads: List[List[str]], socket: str) -> List[Tuple[int, bytes, bytes]]:
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    try:
        return [LocalTransport().run_sync(socket, r, check=False, probe=True) for r in reads]
    finally:
        monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")


def test_error_answers_equal_the_subprocess_and_spawn_nothing(socket, monkeypatch):
    truth = _subprocess_answers(monkeypatch, ERROR_READS, socket)
    assert truth[0][0] == 1 and truth[0][2] == b"can't find session: nosuch\n"
    assert truth[1] == (0, b"", b"") and truth[-1] == (0, b"", b"")
    _up(socket)
    spy = _SpawnSpy(monkeypatch, socket)
    sync = [LocalTransport().run_sync(socket, r, check=False, probe=True) for r in ERROR_READS]

    async def all_async() -> List[Tuple[int, bytes, bytes]]:
        return [await LocalTransport().run(socket, r, check=False) for r in ERROR_READS]

    via_async = asyncio.run(all_async())
    for args, want, got_sync, got_async in zip(ERROR_READS, truth, sync, via_async):
        assert got_sync == want, args
        assert got_async == want, args
    assert spy.spawns == []
    assert _tmux(socket, "has-session", "-t", "=victim").returncode == 0


PARSE_ERROR_READS: List[List[str]] = [
    ["has-session", "-x", "-t", "=known"],
    ["capture-pane", "-Z", "-p", "-t", "=known:"],
    ["show-environment", "-t", "=known", UNSET, "extra"],
]


def test_parse_errors_answer_exactly_like_the_subprocess(socket, monkeypatch):
    truth = _subprocess_answers(monkeypatch, PARSE_ERROR_READS, socket)
    assert truth[0] == (1, b"", b"command has-session: unknown flag -x\n")
    _up(socket)

    async def all_async() -> List[Tuple[int, bytes, bytes]]:
        return [await LocalTransport().run(socket, r, check=False) for r in PARSE_ERROR_READS]

    assert [LocalTransport().run_sync(socket, r, check=False, probe=True) for r in PARSE_ERROR_READS] == truth
    assert asyncio.run(all_async()) == truth


def test_backend_pid_and_is_alive_ride_the_control_client(socket, monkeypatch):
    truth_pid = int(_tmux(socket, "display-message", "-p", "-t", "=known:", "#{pane_pid}").stdout.strip())
    known = TmuxBackend(session_id="s", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="known")
    gone = TmuxBackend(session_id="g", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="nosuch")
    _up(socket)
    spy = _SpawnSpy(monkeypatch, socket)
    assert known.pid == truth_pid
    assert known.is_alive() is True
    assert gone.is_alive() is False
    assert spy.spawns == []
    assert gone.pid is None


def test_an_unset_pane_profile_variable_spawns_nothing(socket, monkeypatch):
    from src.core.account_switch.pane_account import read_pane_profile

    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    truth_unset = asyncio.run(read_pane_profile(socket, "known", UNSET))
    truth_gone = asyncio.run(read_pane_profile(socket, "nosuch", UNSET))
    assert _tmux(socket, "set-environment", "-g", "CC2642_GLOBAL", "/g/x").returncode == 0
    truth_global = asyncio.run(read_pane_profile(socket, "known", "CC2642_GLOBAL"))
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    assert truth_unset.readable and truth_unset.value is None and not truth_gone.readable and truth_global.value == "/g/x"
    _up(socket)
    spy = _SpawnSpy(monkeypatch, socket)
    assert asyncio.run(read_pane_profile(socket, "known", UNSET)) == truth_unset
    assert asyncio.run(read_pane_profile(socket, "nosuch", UNSET)) == truth_gone
    assert asyncio.run(read_pane_profile(socket, "known", "CC2642_GLOBAL")) == truth_global
    assert spy.spawns == []


def test_a_name_no_control_line_can_carry_still_answers_through_the_subprocess(socket, monkeypatch):
    reads = [["has-session", "-t", "=x\nkill-server"], ["capture-pane", "-p", "-t", "=x\rkill-server:"],
             ["show-environment", "-t", "=x\nkill-server", UNSET]]
    truth = _subprocess_answers(monkeypatch, reads, socket)
    _up(socket)
    assert [LocalTransport().run_sync(socket, r, check=False, probe=True) for r in reads] == truth
    assert all(rc == 1 for rc, _, _ in truth)
    assert _tmux(socket, "has-session", "-t", "=victim").returncode == 0


class _RecordingLock:

    def __init__(self, inner: Any) -> None:
        self.inner, self.asked = inner, []  # type: ignore[var-annotated]

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self.asked.append((blocking, timeout))
        return self.inner.acquire(blocking, timeout)

    def release(self) -> None:
        self.inner.release()


def test_is_alive_on_the_loop_thread_never_waits_for_a_held_lock(socket, monkeypatch):
    import threading

    from src.core.tmux_control import reader as reader_mod

    known = TmuxBackend(session_id="s", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="known")
    _up(socket)
    reader = reader_mod._READERS[socket]
    lock = _RecordingLock(reader._lock)
    monkeypatch.setattr(reader, "_lock", lock)
    held, done = threading.Event(), threading.Event()

    def hold() -> None:
        with lock.inner:
            held.set()
            done.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    lock.asked.clear()

    async def on_the_loop() -> "Tuple[bool, float]":
        t0 = time.monotonic()
        alive = known.is_alive()
        return alive, time.monotonic() - t0

    try:
        alive, took = asyncio.run(on_the_loop())
    finally:
        done.set()
        holder.join(5)
    assert alive is True
    assert lock.asked == [(False, -1)]
    assert took < reader_mod.LOOP_TIMEOUT_SECONDS


GUARD, NONCE_GUARD, NONCE = b"1700000000 42 1", b"1700000000 43 1", "ab" * 16


class _ScriptedClient:

    def __init__(self, reply: bytes) -> None:
        self._r, self._w = os.pipe()
        self.stdout = os.fdopen(self._r, "rb", buffering=0)
        self.stdin = self
        self._reply = reply

    def write(self, _raw: bytes) -> None:
        os.write(self._w, self._reply)

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        pass

    def wait(self, timeout: float = 0) -> int:
        return 0

    def close(self) -> None:
        if self._w >= 0:
            os.close(self._w)
            self._w = -1


def _scripted_answer(monkeypatch: pytest.MonkeyPatch, body: List[bytes], end: bytes) -> "Any":
    from src.core.hosts.tmux_control import ControlParser
    from src.core.tmux_control import reader as reader_mod

    monkeypatch.setattr(reader_mod.secrets, "token_hex", lambda _n: NONCE)
    reply = (b"%begin " + GUARD + b"\n" + b"".join(line + b"\n" for line in body) + end + b" " + GUARD + b"\n"
             + b"%begin " + NONCE_GUARD + b"\n" + NONCE.encode() + b"\n%end " + NONCE_GUARD + b"\n")
    reader = reader_mod.ControlReader("cc2642-scripted-no-server")
    client = _ScriptedClient(reply)
    reader._proc = client  # type: ignore[assignment]
    reader._parser = ControlParser(reader_mod.MAX_REPLY_BYTES)
    try:
        return reader.query(["capture-pane", "-p", "-t", "=forger:"])
    finally:
        reader._proc = None
        client.close()
        client.stdout.close()


@pytest.mark.parametrize("forged", [b"%error", b"%end"])
def test_a_pane_printed_error_guard_is_never_taken_for_an_answer(monkeypatch, forged):
    body = [b"top line", forged + b" " + GUARD, b"REAL-TAIL-LINE"]
    assert _scripted_answer(monkeypatch, body, b"%end") is None


def test_the_scripted_client_answers_when_nothing_is_forged(monkeypatch):
    assert _scripted_answer(monkeypatch, [b"top line", b"REAL-TAIL-LINE"], b"%end") == (0, b"top line\nREAL-TAIL-LINE\n", b"")
    assert _scripted_answer(monkeypatch, [b"can't find session: forger"], b"%error") == (1, b"", b"can't find session: forger\n")
