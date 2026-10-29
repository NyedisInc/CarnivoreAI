
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctlrd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctlrd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_control import reader as reader_mod
from src.core.tmux_control.reader import close_readers, control_read
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")

HOSTILE = "a'; kill-session -t =victim ; 'b#{pane_id}$(x)\""


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


def _up(socket: str) -> None:
    for _ in range(100):
        if control_read(socket, ["list-sessions"]) is not None:
            return
        time.sleep(0.1)
    raise AssertionError("client never came up")


@pytest.fixture()
def socket(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("ctlrd")
    assert _tmux(name, "new-session", "-d", "-s", "victim", "-x", "80", "-y", "24", "cat").returncode == 0
    body = "printf 'plain\\n\\033[1mbold\\033[0m  trailing   \\nuni \\303\\251\\342\\202\\254 back\\\\slash\\n%%end x\\n'; sleep 60"
    assert _tmux(name, "new-session", "-d", "-s", "known", "-x", "80", "-y", "24", f"sh -c \"{body}\"").returncode == 0
    assert _tmux(name, "new-session", "-d", "-s", HOSTILE.replace("#", "##"), "-x", "80", "-y", "24", "cat").returncode == 0
    time.sleep(0.5)
    try:
        yield name
    finally:
        close_readers()
        _tmux(name, "kill-server")


def test_list_panes_and_capture_match_the_subprocess_and_a_dead_client_falls_back(socket):
    listing = ["list-panes", "-a", "-F", "#{session_name}\t#{pane_id}\t#{pane_dead}"]
    _up(socket)
    via_control = control_read(socket, listing)
    assert via_control is not None
    direct = _tmux(socket, *listing).stdout
    rows = [r for r in via_control.decode().splitlines() if not r.startswith("_carnivore_ctl")]
    assert rows == [r for r in direct.decode().splitlines() if not r.startswith("_carnivore_ctl")]

    cap = ["capture-pane", "-p", "-e", "-J", "-S", "-50", "-t", "=known:"]
    assert control_read(socket, cap) == _tmux(socket, *cap).stdout

    reader = reader_mod._READERS[socket]
    reader._proc.kill()
    reader._proc.wait()
    reader._retry_after = time.monotonic() + 60
    assert control_read(socket, listing) is None
    backend = TmuxBackend(session_id="s", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="known")
    rc, out, _ = backend._run_tmux_sync(*listing, check=False, probe=True)
    assert rc == 0 and b"known\t" in out


def test_a_hostile_session_name_is_one_target_not_a_second_command(socket):
    direct = _tmux(socket, "capture-pane", "-p", "-t", f"={HOSTILE}:")
    assert direct.returncode == 0
    _up(socket)
    assert control_read(socket, ["capture-pane", "-p", "-t", f"={HOSTILE}:"]) == direct.stdout
    for evil in ("x\nkill-server", "x\rkill-server", "x\0y", "x;", ";"):
        assert control_read(socket, ["capture-pane", "-p", "-t", f"={evil}:"]) is None
    assert control_read(socket, ["display-message", "-p", "-t", "=nosuch:", "#{pane_dead}"]) is None
    assert _tmux(socket, "has-session", "-t", "=victim").returncode == 0


def test_capture_screen_bytes_equal_the_subprocess_capture(socket):
    from src.core.attention.screen_read import capture_screen

    def direct(*flags: str) -> str:
        return _tmux(socket, "capture-pane", "-p", *flags, "-t", "=known:").stdout.decode("utf-8", errors="replace")

    spawned: list = []
    real_run = subprocess.run
    subprocess.run = lambda *a, **k: spawned.append(a) or real_run(*a, **k)  # type: ignore[assignment]
    try:
        _up(socket)
        spawned.clear()
        plain = capture_screen(socket, "known")
        history = capture_screen(socket, "known", 20)
        row = capture_screen(socket, "known", row=1)
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
    assert plain == direct("-S", "0") and "plain" in plain and "back\\slash" in plain and "é€" in plain
    assert history == direct("-S", "-20")
    assert row == direct("-e", "-S", "1", "-E", "1") and "bold" in row and "\x1b[" in row
    assert spawned == []


def test_idle_pollers_spawn_no_tmux_process_over_ten_seconds(socket, monkeypatch):
    import asyncio

    from src.core.account_switch.pane_account import read_pane_profile
    from src.core.pack.load import agents
    from src.core.pack.reserve import throttle
    from src.core.session_pane_facts import read_pane_facts
    from src.core.swarm import body_death
    from src.core.tmux_discovery import tmux_argv_prefix

    assert _tmux(socket, "set-environment", "-t", "known", "CLAUDE_CONFIG_DIR", "/p/x").returncode == 0
    spawns: list = []
    real_popen, real_exec, real_run = subprocess.Popen, asyncio.create_subprocess_exec, subprocess.run

    def popen(argv, *a, **k):
        spawns.append(argv)
        return real_popen(argv, *a, **k)

    async def exec_(*argv, **k):
        spawns.append(argv)
        return await real_exec(*argv, **k)

    backend = TmuxBackend(session_id="s", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="known")
    prefix = tmux_argv_prefix(socket)

    async def one_pass() -> None:
        folded = await asyncio.to_thread(backend.list_sessions_and_panes)
        assert folded.panes is not None and folded.panes.ok and folded.sessions.ok
        assert "known" in (throttle._run(prefix + ["list-panes", "-a", "-F", "#{session_name}"]) or "")
        assert (await read_pane_facts(socket, "known")).cwd
        assert (await read_pane_profile(socket, "known", "CLAUDE_CONFIG_DIR")).value == "/p/x"
        assert await body_death._pane_dead("known", socket) is False
        rc, out, _ = await backend._run_tmux("show-options", "-gv", "history-limit", check=False)
        assert rc == 0 and out.strip().isdigit()
        rc, out, _ = await backend._run_tmux("display-message", "-p", "-t", "=known:", "#{pane_pipe}", check=False)
        assert rc == 0 and out.strip() == b"0"
        assert (socket, "known") in agents.pane_pids([socket])

    async def window() -> None:
        for _ in range(50):
            try:
                await one_pass()
                break
            except AssertionError:
                await asyncio.sleep(0.2)
        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(subprocess, "run", lambda argv, *a, **k: spawns.append(argv) or real_run(argv, *a, **k))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
        for _ in range(10):
            await one_pass()
            await asyncio.sleep(1)

    asyncio.run(window())
    assert [a for a in spawns if "#{version}" not in list(a)] == []


def test_the_folded_listing_runs_as_two_control_commands_and_equals_the_subprocess(socket):
    from src.core.sessions.tmux_listing_fold import FOLDED_LISTING_ARGS

    _up(socket)
    via_control = control_read(socket, list(FOLDED_LISTING_ARGS))
    assert via_control is not None
    direct = _tmux(socket, *FOLDED_LISTING_ARGS).stdout
    keep = lambda b: [r for r in b.decode().splitlines() if "_carnivore_ctl" not in r]  # noqa: E731
    assert keep(via_control) == keep(direct) and any(r.startswith("S|") for r in keep(direct)) and any(r.startswith("P|") for r in keep(direct))
    assert control_read(socket, ["list-sessions", ";"]) is None and control_read(socket, [";", "list-sessions"]) is None


def test_non_ascii_names_round_trip_whatever_the_engine_locale(socket, monkeypatch):
    env = {**os.environ, "LC_ALL": "en_US.UTF-8"}
    made = subprocess.run(["tmux", "-u", "-L", socket, "new-session", "-d", "-s", "café 中", "cat"], env=env, capture_output=True, check=False)
    assert made.returncode == 0
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.delenv("LANG", raising=False)
    close_readers()
    args = ["list-sessions", "-F", "#{session_name}"]
    direct = subprocess.run(["tmux", "-L", socket, *args], env={**os.environ, "LC_ALL": "C"}, capture_output=True, check=False).stdout
    _up(socket)
    via_control = control_read(socket, args)
    assert via_control is not None and "café 中".encode() in direct
    assert sorted(r for r in via_control.split(b"\n") if b"_carnivore_ctl" not in r) == sorted(r for r in direct.split(b"\n") if b"_carnivore_ctl" not in r)


def _server_command_counter(socket: str) -> int:
    out = subprocess.run(["tmux", "-L", socket, "-C", "display-message", "-p", "x"], input=b"", capture_output=True,
                         check=False, timeout=15).stdout.decode()
    return int(next(line for line in out.split("\n") if line.startswith("%begin")).split()[2])


def test_pane_printed_guard_lines_cannot_truncate_a_capture(socket, tmp_path):
    _up(socket)
    now = int(time.time())
    base = _server_command_counter(socket)
    forged = tmp_path / "forged.txt"
    forged.write_text("".join(f"%end {t} {n} 1\n" for t in range(now - 3, now + 3) for n in range(base, base + 80)) + "REAL-TAIL-LINE\n")
    assert _tmux(socket, "new-session", "-d", "-s", "forger", "-x", "80", "-y", "24", f"sh -c 'cat {forged}; sleep 60'").returncode == 0
    time.sleep(1.0)
    cap = ["capture-pane", "-p", "-S", "-3000", "-t", "=forger:"]
    direct = _tmux(socket, *cap).stdout
    assert b"REAL-TAIL-LINE" in direct
    first = control_read(socket, cap)
    assert first is None, "the forged guard missed the real one (widen the range) or the framing check regressed"
    assert control_read(socket, cap) in (None, direct)


def test_close_removes_the_hidden_session(socket):
    _up(socket)
    assert b"_carnivore_ctl_in_rd_" in _tmux(socket, "list-sessions", "-F", "#{session_name}").stdout
    close_readers()
    assert b"_carnivore_ctl_in_rd_" not in _tmux(socket, "list-sessions", "-F", "#{session_name}").stdout


def test_a_wedged_server_never_stalls_the_event_loop_and_cools_down(socket):
    import asyncio
    import signal

    listing = ["list-panes", "-a", "-F", "#{pane_id}"]
    pid = int(_tmux(socket, "display-message", "-p", "#{pid}").stdout.strip())

    async def go() -> None:
        t0 = time.monotonic()
        assert control_read(socket, listing) is None and time.monotonic() - t0 < 0.2
        for _ in range(50):
            await asyncio.sleep(0.2)
            if control_read(socket, listing) is not None:
                break
        else:
            raise AssertionError("client never came up")
        os.kill(pid, signal.SIGSTOP)
        try:
            t0 = time.monotonic()
            assert control_read(socket, listing) is None
            assert time.monotonic() - t0 < 0.6
            t0 = time.monotonic()
            assert control_read(socket, listing) is None and time.monotonic() - t0 < 0.05
        finally:
            os.kill(pid, signal.SIGCONT)

    asyncio.run(go())
    assert reader_mod._READERS[socket]._retry_after > time.monotonic()


def test_a_tmux_that_refuses_the_handshake_is_not_retried_every_few_seconds(socket, monkeypatch):
    monkeypatch.setattr(reader_mod, "HANDSHAKE", "refresh-client -C notasize")
    for _ in range(100):
        assert control_read(socket, ["list-sessions"]) is None
        if reader_mod._READERS[socket]._retry_after - time.monotonic() > 500:
            break
        time.sleep(0.1)
    assert reader_mod._READERS[socket]._retry_after - time.monotonic() > 500


def test_a_wedged_server_does_not_starve_the_default_thread_pool(socket):
    import asyncio
    import signal

    listing = ["list-panes", "-a", "-F", "#{pane_id}"]
    pid = int(_tmux(socket, "display-message", "-p", "#{pid}").stdout.strip())

    async def go() -> float:
        for _ in range(50):
            if await reader_mod.control_read_async(socket, listing) is not None:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("client never came up")
        os.kill(pid, signal.SIGSTOP)
        try:
            flood = [asyncio.create_task(reader_mod.control_read_async(socket, listing)) for _ in range(60)]
            await asyncio.sleep(0.05)
            t0 = time.monotonic()
            assert await asyncio.to_thread(lambda: 1) == 1
            waited = time.monotonic() - t0
            assert all(r is None for r in await asyncio.gather(*flood))
            return waited
        finally:
            os.kill(pid, signal.SIGCONT)

    assert asyncio.run(go()) < 1.0


def test_a_sync_pool_caller_on_a_wedged_server_is_bounded_and_the_listing_budget_holds(socket):
    import asyncio
    import signal

    listing = ["list-panes", "-a", "-F", "#{pane_id}"]
    _up(socket)
    pid = int(_tmux(socket, "display-message", "-p", "#{pid}").stdout.strip())
    backend = TmuxBackend(session_id="s", working_dir=Path(tempfile.gettempdir()), socket_name=socket, session_name="known")

    async def go() -> "tuple[float, float]":
        os.kill(pid, signal.SIGSTOP)
        try:
            t0 = time.monotonic()
            with pytest.raises(subprocess.TimeoutExpired):
                await asyncio.to_thread(lambda: backend._run_tmux_sync(*listing, check=False, probe=True, timeout=5.0))
            listing_took = time.monotonic() - t0
            flood = [asyncio.create_task(asyncio.to_thread(control_read, socket, listing)) for _ in range(40)]
            await asyncio.sleep(0.05)
            t0 = time.monotonic()
            assert await asyncio.to_thread(lambda: 1) == 1
            waited = time.monotonic() - t0
            assert all(r is None for r in await asyncio.gather(*flood))
            return listing_took, waited
        finally:
            os.kill(pid, signal.SIGCONT)

    listing_took, waited = asyncio.run(go())
    assert listing_took < 5.5, "the listing's documented 5 s budget must hold (the control wait is on top of the subprocess fallback)"
    assert waited < 2.0


def test_close_is_bounded_under_an_in_flight_reader_and_that_reader_never_raises(socket, monkeypatch):
    import signal
    import threading

    _up(socket)
    pid = int(_tmux(socket, "display-message", "-p", "#{pid}").stdout.strip())
    reader = reader_mod._READERS[socket]
    monkeypatch.setattr(reader_mod, "LOOP_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(reader_mod, "CLOSE_LOCK_TIMEOUT_SECONDS", 0.2)
    outcome: list = []

    def read() -> None:
        try:
            outcome.append(reader.run(["list-panes", "-a", "-F", "#{pane_id}"]))
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)

    os.kill(pid, signal.SIGSTOP)
    try:
        worker = threading.Thread(target=read)
        worker.start()
        time.sleep(0.4)
        t0 = time.monotonic()
        reader.close()
        assert time.monotonic() - t0 < 1.5
        worker.join(5)
        assert not worker.is_alive() and outcome == [None], outcome
    finally:
        os.kill(pid, signal.SIGCONT)


def test_a_read_on_a_closed_pipe_is_a_dead_client_not_an_oserror():
    from src.core.hosts.tmux_control import ControlParser

    r, w = os.pipe()
    os.close(r)
    os.close(w)
    with pytest.raises(reader_mod._Dead):
        reader_mod.ControlReader._read(r, ControlParser(1024), 0.1, None)


def test_a_server_with_only_hidden_sessions_is_rechecked_only_once_a_minute(monkeypatch):
    reader = reader_mod.ControlReader("nosuch-idle-sock")

    def idle() -> None:
        raise reader_mod._Idle("only hidden sessions")

    monkeypatch.setattr(reader, "_start", idle)
    assert reader._ensure_up(False) is False
    assert reader._retry_after - time.monotonic() > 50
