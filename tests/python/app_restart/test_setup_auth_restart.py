from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import setup_auth  # noqa: E402
from src.core.app_restart import restart as app_restart  # noqa: E402
from src.core.owner_identity.otpauth import ISSUER  # noqa: E402
from src.core.product_identity import BUNDLE_ID, PRODUCT_NAME  # noqa: E402

ENGINE_PID = 4242
OTHER_PID = 777
SERVER_DIR = "/srv/carnivore-engine"
START = "Thu Oct 29 10:00:00 2026"
UID = os.getuid()


class Proc:

    def __init__(self, command: str = "/venv/bin/python3 -m src.main", uid: int = UID,
                 cwd: str = SERVER_DIR, start: str = START, stat: str = "S") -> None:
        self.command, self.uid, self.cwd, self.start, self.stat = command, uid, cwd, start, stat


class FakeSystem:

    def __init__(self, app_running: bool, procs: Dict[int, Proc], listeners: List[int],
                 quit_rc: int = 0, accepts: bool = False, accepts_after_kill: bool = False) -> None:
        self.app_running, self.procs, self.listeners = app_running, procs, list(listeners)
        self.quit_rc, self.accepts, self.accepts_after_kill = quit_rc, accepts, accepts_after_kill
        self.commands: List[List[str]] = []
        self.kills: List[Tuple[int, int]] = []
        self.timeouts: List[Optional[float]] = []

    def run(self, argv: List[str], **kw: Any) -> "subprocess.CompletedProcess[str]":
        self.commands.append(list(argv))
        self.timeouts.append(kw.get("timeout"))
        tool, out, code = argv[0], "", 0
        if tool == "pgrep":
            code = 0 if self.app_running and argv[-1] == PRODUCT_NAME else 1
        elif tool == "lsof" and "-d" in argv:
            proc = self.procs.get(int(argv[argv.index("-p") + 1]))
            out = f"p1\nn{proc.cwd}\n" if proc else ""
        elif tool == "lsof":
            out = "\n".join(str(p) for p in self.listeners)
        elif tool == "ps":
            out = self._ps(int(argv[2]), argv[-1].rstrip("="))
        elif tool == "osascript":
            code = self.quit_rc
            self.app_running = self.app_running and self.quit_rc != 0
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")

    def _ps(self, pid: int, column: str) -> str:
        proc = self.procs.get(pid)
        if proc is None:
            return ""
        return {"command": proc.command, "uid": str(proc.uid), "lstart": proc.start, "stat": proc.stat}[column]

    def kill(self, pid: int, sig: int) -> None:
        self.kills.append((pid, sig))
        self.listeners = [p for p in self.listeners if p != pid]
        self.procs.pop(pid, None)

    def connect(self, _port: int) -> bool:
        return self.accepts or (self.accepts_after_kill and bool(self.kills))


@pytest.fixture(autouse=True)
def _guard(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a real process or socket call escaped the stub")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(os, "kill", boom)
    monkeypatch.setattr(app_restart, "port_accepts", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setenv("CARNIVORE_ENGINE_DIR", SERVER_DIR)


def _ours() -> Dict[int, Proc]:
    return {ENGINE_PID: Proc(), OTHER_PID: Proc(command="/usr/bin/python3 -m http.server")}


def _restart(fake: FakeSystem) -> app_restart.RestartOutcome:
    return app_restart.restart_app_and_engine(8000, run=fake.run, kill=fake.kill,
                                              sleep=lambda _s: None, connect=fake.connect)


def test_guard_catches_a_real_kill_through_the_defaults() -> None:
    out = app_restart.RestartOutcome()
    fake = FakeSystem(False, _ours(), [ENGINE_PID])
    with pytest.raises(AssertionError):
        app_restart.stop_engine(8000, out, run=fake.run, sleep=lambda _s: None, connect=fake.connect)


def test_guard_catches_a_real_run_through_the_defaults() -> None:
    with pytest.raises(AssertionError):
        app_restart.app_is_running()


def test_targets_carnivore_by_bundle_id_and_uid() -> None:
    fake = FakeSystem(True, _ours(), [ENGINE_PID])
    _restart(fake)
    flat = " ".join(" ".join(c) for c in fake.commands)
    assert "Cloude Code" not in flat
    assert ["pgrep", "-u", str(UID), "-x", PRODUCT_NAME] in fake.commands
    assert ["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'] in fake.commands
    assert ["open", "-b", BUNDLE_ID] in fake.commands


def test_every_call_has_a_timeout_and_every_lsof_is_nonblocking() -> None:
    fake = FakeSystem(True, _ours(), [ENGINE_PID])
    _restart(fake)
    assert all(t for t in fake.timeouts)
    assert all("-b" in c for c in fake.commands if c[0] == "lsof")


def test_running_app_is_quit_then_engine_stopped_then_reopened() -> None:
    fake = FakeSystem(True, _ours(), [ENGINE_PID])
    out = _restart(fake)
    tools = [c[0] for c in fake.commands]
    assert tools.index("osascript") < tools.index("open")
    assert fake.kills == [(ENGINE_PID, signal.SIGTERM)]
    assert out.stopped_pids == [ENGINE_PID] and out.reopened and out.restarted


def test_app_not_running_still_stops_engine_but_does_not_open() -> None:
    fake = FakeSystem(False, _ours(), [ENGINE_PID])
    out = _restart(fake)
    assert fake.kills == [(ENGINE_PID, signal.SIGTERM)] and out.restarted
    assert not out.reopened and ["open", "-b", BUNDLE_ID] not in fake.commands


def test_rule1_command_must_contain_dash_m_src_main() -> None:
    procs = {ENGINE_PID: Proc(command="/venv/bin/python3 other.py")}
    fake = FakeSystem(False, procs, [ENGINE_PID])
    _restart(fake)
    assert fake.kills == []


def test_rule2_foreign_uid_is_not_signalled() -> None:
    fake = FakeSystem(False, {ENGINE_PID: Proc(uid=UID + 1)}, [ENGINE_PID])
    _restart(fake)
    assert fake.kills == []


def test_rule3_cwd_must_be_the_installed_engine_folder() -> None:
    fake = FakeSystem(False, {ENGINE_PID: Proc(cwd="/Users/x/repo-checkout")}, [ENGINE_PID])
    out = _restart(fake)
    assert fake.kills == [] and not out.restarted


def test_rule5_start_time_change_before_signal_refuses() -> None:
    fake = FakeSystem(False, {ENGINE_PID: Proc()}, [ENGINE_PID])
    original = fake._ps
    seen = {"n": 0}

    def reused(pid: int, column: str) -> str:
        if column == "lstart":
            seen["n"] += 1
            return START if seen["n"] == 1 else "Fri Oct 30 11:00:00 2026"
        return original(pid, column)

    fake._ps = reused  # type: ignore[method-assign]
    out = _restart(fake)
    assert fake.kills == [] and any("changed identity" in n for n in out.notes)


def test_rule6_one_foreign_listener_refuses_everything() -> None:
    fake = FakeSystem(False, _ours(), [ENGINE_PID, OTHER_PID])
    out = _restart(fake)
    assert fake.kills == [] and not out.restarted


def test_rule7_connect_probe_refuses_when_lsof_shows_no_listener() -> None:
    fake = FakeSystem(False, {}, [], accepts=True)
    out = _restart(fake)
    assert fake.kills == [] and not out.restarted and any("accepts connections" in n for n in out.notes)


def test_rule9_vanished_listener_counts_as_stopped() -> None:
    fake = FakeSystem(False, {}, [ENGINE_PID])
    fake.listeners = [ENGINE_PID]
    out = app_restart.RestartOutcome()
    fake.listeners = []
    app_restart.stop_engine(8000, out, run=fake.run, kill=fake.kill, sleep=lambda _s: None, connect=fake.connect)
    assert out.port_free and fake.kills == []


def test_rule9_zombie_listener_is_not_signalled() -> None:
    fake = FakeSystem(False, {ENGINE_PID: Proc(stat="Z")}, [ENGINE_PID])
    _restart(fake)
    assert fake.kills == []


def test_lsof_failure_is_unmeasured_not_free() -> None:
    fake = FakeSystem(False, _ours(), [ENGINE_PID])
    real = fake.run

    def broken(argv: List[str], **kw: Any) -> "subprocess.CompletedProcess[str]":
        if argv[0] == "lsof":
            raise subprocess.TimeoutExpired(argv, 1)
        return real(argv, **kw)

    out = app_restart.restart_app_and_engine(8000, run=broken, kill=fake.kill, sleep=lambda _s: None, connect=fake.connect)
    assert fake.kills == [] and not out.port_free and not out.restarted


def test_failed_quit_reports_not_restarted_and_touches_no_engine() -> None:
    fake = FakeSystem(True, _ours(), [ENGINE_PID], quit_rc=1)
    out = _restart(fake)
    assert not out.restarted and not out.port_free and not out.app_quit
    assert fake.kills == [] and any("did not quit" in n for n in out.notes)
    after_quit = fake.commands[[c[0] for c in fake.commands].index("osascript") + 1:]
    assert after_quit == []


def test_default_outcome_is_not_free() -> None:
    assert app_restart.RestartOutcome().port_free is False


def test_port_is_validated() -> None:
    assert app_restart.parse_port("8123", 8000) == 8123
    assert [app_restart.parse_port(t, 8000) for t in ("0", "65536", "abc", "", None)] == [8000] * 5
    with pytest.raises(ValueError):
        app_restart.restart_app_and_engine(70000)


def test_restart_reads_port_from_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    seen: List[int] = []

    def rec(port: int) -> app_restart.RestartOutcome:
        seen.append(port)
        return app_restart.RestartOutcome()

    env.write_text("PORT=8123\n")
    setup_auth.restart_running_install(env, restart=rec)
    env.write_text("PORT=99999\n")
    setup_auth.restart_running_install(env, restart=rec)
    assert seen == [8123, 8000]


def _setup(monkeypatch: pytest.MonkeyPatch, outcome: app_restart.RestartOutcome) -> List[str]:
    order: List[str] = []
    monkeypatch.setattr(setup_auth, "restart_running_install", lambda *_a, **_k: order.append("restart") or outcome)
    monkeypatch.setattr(setup_auth, "start_server", lambda *_a: order.append("start"))
    monkeypatch.setattr(setup_auth, "port_accepts", lambda _p: order.append("probe") or False)
    return order


def test_rotate_restarts_before_starting_a_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARNIVORE_ENGINE_DIR", str(tmp_path))
    order = _setup(monkeypatch, app_restart.RestartOutcome(port_free=True))
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=True)
    assert order == ["restart", "start"]


def test_failed_quit_starts_no_second_server_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    outcome = app_restart.RestartOutcome(app_was_running=True, notes=["Carnivore did not quit"])
    monkeypatch.setenv("CARNIVORE_ENGINE_DIR", str(tmp_path))
    order = _setup(monkeypatch, outcome)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=True)
    text = capsys.readouterr().out
    assert order == ["restart"]
    assert "restarted (it starts" not in text and "no second server was started" in text
    assert "next time you restart the app" in text


def test_unchanged_secrets_do_not_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _setup(monkeypatch, app_restart.RestartOutcome())
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=False)
    assert "restart" not in order


def test_secrets_changed_only_when_a_secret_moved() -> None:
    kept = {"totp_action": "kept", "jwt_action": "kept"}
    assert not setup_auth.secrets_changed(kept)
    assert setup_auth.secrets_changed({**kept, "jwt_action": "rotated"})
    assert setup_auth.secrets_changed({**kept, "totp_action": "created"})


def test_qr_issuer_comes_from_the_shared_constant() -> None:
    assert setup_auth.generate_qr_code.__defaults__ == (ISSUER,)


def test_import_without_structlog_works(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    monkeypatch.setitem(sys.modules, "structlog", None)
    for name in ("setup_auth", "src.core.app_restart.restart"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    fresh = importlib.import_module("setup_auth")
    assert fresh.restart_app_and_engine is not None


def test_restart_refused_when_project_is_not_the_installed_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    order = _setup(monkeypatch, app_restart.RestartOutcome(port_free=True))
    monkeypatch.setattr(setup_auth, "port_accepts", lambda _p: True)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=True)
    assert order == []
    assert "restart Carnivore yourself" in capsys.readouterr().out


def test_first_setup_from_a_source_checkout_starts_the_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _setup(monkeypatch, app_restart.RestartOutcome())
    monkeypatch.setattr(setup_auth, "app_is_running", lambda: False)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=True)
    assert order == ["probe", "start"]


def test_running_app_still_refuses_for_a_foreign_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _setup(monkeypatch, app_restart.RestartOutcome())
    monkeypatch.setattr(setup_auth, "app_is_running", lambda: True)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=True)
    assert order == ["probe"]


def test_restart_allowed_when_project_is_the_installed_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARNIVORE_ENGINE_DIR", str(tmp_path))
    assert app_restart.is_installed_engine_root(tmp_path)
    assert not app_restart.is_installed_engine_root(tmp_path / "other")


def test_foreign_listener_after_sigterm_is_not_free() -> None:
    fake = FakeSystem(False, _ours(), [ENGINE_PID], accepts_after_kill=True)
    out = _restart(fake)
    assert fake.kills == [(ENGINE_PID, signal.SIGTERM)]
    assert not out.port_free and not out.restarted


def test_app_is_not_reopened_while_port_is_not_free() -> None:
    fake = FakeSystem(True, {OTHER_PID: Proc(command="/usr/bin/python3 -m http.server")}, [OTHER_PID])
    out = _restart(fake)
    assert not out.port_free and not out.reopened
    assert ["open", "-b", BUNDLE_ID] not in fake.commands


def test_socket_guard_covers_both_port_accepts() -> None:
    with pytest.raises(AssertionError):
        setup_auth.port_accepts(8000)
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 8000))


def test_unchanged_path_says_already_running_only_for_our_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    order = _setup(monkeypatch, app_restart.RestartOutcome())
    monkeypatch.setattr(setup_auth, "port_accepts", lambda _p: True)
    monkeypatch.setattr(setup_auth, "engine_owns_port", lambda _p: True)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=False)
    assert "already running" in capsys.readouterr().out
    monkeypatch.setattr(setup_auth, "engine_owns_port", lambda _p: False)
    setup_auth.apply_running_install(tmp_path, tmp_path / ".env", changed=False)
    text = capsys.readouterr().out
    assert "already running" not in text and "held by something other" in text and "start" not in order


def test_engine_owns_port_judges_by_identity() -> None:
    assert app_restart.engine_owns_port(8000, run=FakeSystem(False, _ours(), [ENGINE_PID]).run)
    assert not app_restart.engine_owns_port(8000, run=FakeSystem(False, _ours(), [ENGINE_PID, OTHER_PID]).run)
    assert not app_restart.engine_owns_port(8000, run=FakeSystem(False, {}, []).run)
