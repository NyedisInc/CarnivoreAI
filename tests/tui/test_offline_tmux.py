
from __future__ import annotations

import os
import random
import re
from pathlib import Path

import pytest

from src.tui import attach
from src.tui.offline import listing, socket_check, tmux_cmd
from src.tui.offline.launch import EXIT_NOT_RUNNING, EXIT_REFUSED, offline_message
from src.tui.offline.socket_check import SocketRefused, check_socket, resolve_offline
from src.tui.offline.tmux_cmd import SEP, TmuxNotRunning, TmuxTarget
from tests.tui.offline_stub import Stub

ROOT = Path(__file__).resolve().parents[2]
ARGV_SOURCES = sorted((ROOT / "src/tui/offline").glob("*.py")) + [ROOT / "src/tui/attach.py"]
SERVER_STARTERS = ("new-session", "start-server", "new", "start")
HAZARD_NAMES = ["it's", 'say "hi"', "$HOME", "`id`", "a b", "line\nbreak", "-t", "--", "-L cloude", "=x", "a;b", "a:b"]


def sessions_out(*rows: tuple[str, str, str, str]) -> str:
    return "".join(SEP.join(r) + "\n" for r in rows)


def starters_in(text: str) -> list[str]:
    found = {w for w in ("new-session", "start-server") if w in text}
    found |= {w for w in SERVER_STARTERS if re.search(rf"[\"']{re.escape(w)}[\"']", text)}
    return sorted(found)


def test_no_server_starting_command_in_any_argv_builder() -> None:
    assert len(ARGV_SOURCES) >= 6 and all(p.is_file() for p in ARGV_SOURCES)
    for path in ARGV_SOURCES:
        assert starters_in(path.read_text(encoding="utf-8")) == [], path
    assert not set(SERVER_STARTERS) & tmux_cmd.ALLOWED_COMMANDS
    target = TmuxTarget("/bin/tmux", "/tmp/tmux-1/s")
    for word in SERVER_STARTERS:
        with pytest.raises(ValueError):
            tmux_cmd.command_argv(target, word)


def test_the_ban_can_go_red() -> None:
    assert starters_in('argv = prefix + ("new-session", "-d")') == ["new-session"]
    assert starters_in("argv = prefix + ('new', '-d')") == ["new"]
    assert starters_in('run(["tmux", "start"])') == ["start"]
    assert starters_in('argv = prefix + ("list-sessions",)') == []


def test_builders_address_the_socket_by_path() -> None:
    target = TmuxTarget("/opt/tmux", "/private/tmp/tmux-501/cloude")
    for argv in (tmux_cmd.list_sessions_argv(target), tmux_cmd.list_panes_argv(target), tmux_cmd.server_info_argv(target)):
        assert argv[:3] == ("/opt/tmux", "-S", "/private/tmp/tmux-501/cloude")
    assert tmux_cmd.pane_size_argv(target.prefix(), "carnivore_a")[6:9] == ("-p", "-t", "=carnivore_a:")


def _names(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    alphabet = list("'\"$` \n-;:=\\*?!{}()<>|&") + list("abcXYZ019_")
    made = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12))) for _ in range(count)]
    return HAZARD_NAMES + made


@pytest.mark.parametrize("name", _names(1862, 60))
def test_attach_target_is_one_argv_element(name: str) -> None:
    prefix = ("/opt/tmux", "-S", "/private/tmp/tmux-501/cloude")
    for read_only in (False, True):
        for fit in (False, True):
            plan = attach.plan_attach(name, "cloude", {}, prefix=prefix, read_only=read_only, fit=fit)
            argv = plan.argvs[0]
            assert argv.count(f"={name}") == 1
            assert argv[argv.index(f"={name}") - 1] == "-t"
            if fit:
                assert argv.count(f"={name}:") == 1


@pytest.mark.parametrize("name", HAZARD_NAMES)
def test_stub_tmux_receives_the_name_untouched(stub: Stub, name: str) -> None:
    stub.answer({"attach-session": ["", "", 0]})
    plan = attach.plan_attach(name, "x", dict(os.environ), prefix=(stub.binary, "-S", stub.socket_path))
    assert attach.run(plan) == 0
    (logged,) = stub.calls()
    assert logged[1:] == list(plan.argvs[0][1:])
    assert logged.count(f"={name}") == 1


def test_watch_fit_and_env() -> None:
    prefix = ("/opt/tmux", "-S", "/s/cloude")
    env = {"TMUX": "/s/cloude,1,0", "PATH": "/x"}
    watch = attach.plan_attach("n", "cloude", env, prefix=prefix, read_only=True)
    assert watch.suspend and "TMUX" not in watch.env
    assert watch.argvs[0][3:] == ("attach-session", "-r", "-f", "ignore-size", "-t", "=n")
    fit = attach.plan_attach("n", "cloude", {}, prefix=prefix, fit=True)
    assert fit.argvs[0][3:] == ("attach-session", "-t", "=n", ";", "resize-window", "-A", "-t", "=n:")
    plain = attach.plan_attach("n", "cloude", {}, prefix=prefix)
    assert "ignore-size" in plain.argvs[0]


def test_preamble_resizes_and_says_how_to_detach() -> None:
    size = attach.parse_pane_size(SEP.join(("200", "59", "on", "C-a")) + "\n")
    assert size == attach.PaneSize(200, 59, 1, "C-a")
    text = attach.attach_preamble(size, resize_terminal=True, read_only=False)
    assert text.startswith("\x1b[8;60;200t") and "C-a then d" in text and "leaves the session running" in text
    watch = attach.attach_preamble(size, resize_terminal=False, read_only=True)
    assert "\x1b[" not in watch and "read only" in watch
    assert "C-b then d" in attach.attach_preamble(None, resize_terminal=True, read_only=False)
    assert attach.parse_pane_size("garbage") is None


def test_socket_check_refuses_loose_or_foreign(stub: Stub) -> None:
    sock, uid = Path(stub.socket_path), os.getuid()
    check_socket(sock, uid)
    with pytest.raises(SocketRefused) as err:
        check_socket(sock, uid + 1)
    assert err.value.reason == "parent_owner"
    stub.uid_dir.chmod(0o750)
    with pytest.raises(SocketRefused) as err:
        check_socket(sock, uid)
    assert err.value.reason == "parent_mode"
    stub.uid_dir.chmod(0o700)
    plain = stub.uid_dir / "plain"
    plain.write_text("", encoding="utf-8")
    with pytest.raises(SocketRefused) as err:
        check_socket(plain, uid)
    assert err.value.reason == "socket_not_socket"
    link = stub.uid_dir / "link"
    link.symlink_to(sock)
    with pytest.raises(SocketRefused) as err:
        check_socket(link, uid)
    assert err.value.reason == "socket_symlink"
    linked_dir = stub.root / "linkdir"
    linked_dir.symlink_to(stub.uid_dir)
    with pytest.raises(SocketRefused) as err:
        check_socket(linked_dir / sock.name, uid)
    assert err.value.reason == "parent_symlink"
    text, code = offline_message(err.value)
    assert code == EXIT_REFUSED and "symlink" in text


def _resolve(stub: Stub, monkeypatch: pytest.MonkeyPatch, **kw: object) -> socket_check.OfflineContext:
    monkeypatch.setattr(socket_check, "DEFAULT_TMPDIR", str(stub.root))
    return resolve_offline(os.path.basename(stub.socket_path), os.environ, os.getuid(), stub.binary, **kw)  # type: ignore[arg-type]


def test_resolve_picks_server_binary_only_when_ours(stub: Stub, monkeypatch: pytest.MonkeyPatch) -> None:
    stub.answer({
        "list-sessions": [sessions_out(("$1", "10", "0", "carnivore_a")), "", 0],
        "display-message": [f"4242{SEP}{stub.socket_path}\n", "", 0],
    })
    mine = _resolve(stub, monkeypatch, exe_of=lambda pid: "/srv/tmux" if pid == 4242 else None, uid_of=lambda pid: os.getuid())
    assert mine.target == TmuxTarget("/srv/tmux", stub.socket_path) and mine.binary_source == "server"
    foreign = _resolve(stub, monkeypatch, exe_of=lambda pid: "/srv/tmux", uid_of=lambda pid: os.getuid() + 1)
    assert foreign.target.binary == stub.binary and foreign.binary_source == "resolved"
    unknown = _resolve(stub, monkeypatch, exe_of=lambda pid: None, uid_of=lambda pid: os.getuid())
    assert unknown.target.binary == stub.binary
    assert all(call[1] == "-S" and call[2] == stub.socket_path for call in stub.calls())


def test_resolve_refuses_before_running_tmux(stub: Stub, monkeypatch: pytest.MonkeyPatch) -> None:
    stub.uid_dir.chmod(0o755)
    try:
        with pytest.raises(SocketRefused):
            _resolve(stub, monkeypatch)
    finally:
        stub.uid_dir.chmod(0o700)
    assert stub.calls() == []


def test_no_server_running_says_sessions_are_gone(stub: Stub, monkeypatch: pytest.MonkeyPatch) -> None:
    stub.answer({"list-sessions": ["", f"no server running on {stub.socket_path}\n", 1]})
    with pytest.raises(TmuxNotRunning) as err:
        _resolve(stub, monkeypatch)
    text, code = offline_message(err.value)
    assert code == EXIT_NOT_RUNNING and "sessions are gone" in text and "reopen" in text
    monkeypatch.setattr(socket_check, "DEFAULT_TMPDIR", str(stub.root / "nowhere"))
    with pytest.raises(TmuxNotRunning):
        resolve_offline("cloude", {}, os.getuid(), stub.binary)


def test_list_rows_owned_default_show_all_and_dead(stub: Stub) -> None:
    stub.answer({
        "list-sessions": [sessions_out(
            ("$1", "10", "1", "carnivore_live"), ("$2", "11", "0", "cloude_husk"), ("$3", "12", "0", "hand made"),
        ), "", 0],
        "list-panes": [SEP.join(("$1", "0", "")) + "\n" + SEP.join(("$2", "1", "0")) + "\n" + SEP.join(("$3", "0", "")) + "\n", "", 0],
    })
    target = TmuxTarget(stub.binary, stub.socket_path)
    owned = listing.list_rows(target, None, show_all=False)
    assert [r.tmux_name for r in owned] == ["carnivore_live", "cloude_husk"]
    assert [r.dead for r in owned] == [False, True] and not owned[1].attachable and owned[0].attached == 1
    every = listing.list_rows(target, None, show_all=True)
    assert [r.tmux_name for r in every][-1] == "hand made" and not every[-1].owned


def test_query_failures_are_typed(stub: Stub) -> None:
    stub.answer({"list-sessions": ["", "protocol version mismatch\nmore\n", 1]})
    target = TmuxTarget(stub.binary, stub.socket_path)
    with pytest.raises(tmux_cmd.TmuxCommandFailed) as err:
        tmux_cmd.run_query(tmux_cmd.list_sessions_argv(target))
    assert err.value.detail == "protocol version mismatch"
    with pytest.raises(tmux_cmd.TmuxCommandFailed):
        tmux_cmd.run_query(tmux_cmd.list_sessions_argv(TmuxTarget(str(stub.root / "absent" / "tmux"), stub.socket_path)))


def test_query_env_drops_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/elsewhere,1,0")
    assert "TMUX" not in tmux_cmd.clean_env(os.environ) and "PATH" in tmux_cmd.clean_env(os.environ)


def test_offline_prefix_loads_no_user_config() -> None:
    target = TmuxTarget("/opt/tmux", "/private/tmp/tmux-501/cloude")
    assert target.prefix()[3:5] == ("-f", "/dev/null")
    argv = tmux_cmd.list_sessions_argv(target)
    assert argv[3:5] == ("-f", "/dev/null") and tmux_cmd.command_word(argv) == "list-sessions"


def test_probe_session_runs_has_session_and_never_starts_a_server(stub: Stub) -> None:
    prefix = TmuxTarget(stub.binary, stub.socket_path).prefix()
    stub.answer({"has-session": ["", "", 0]})
    tmux_cmd.probe_session(prefix, "carnivore_a")
    assert [tmux_cmd.command_word(c) for c in stub.calls()] == ["has-session"] and stub.calls()[0][-2:] == ["-t", "=carnivore_a"]
    stub.answer({"has-session": ["", f"no server running on {stub.socket_path}\n", 1]})
    with pytest.raises(TmuxNotRunning):
        tmux_cmd.probe_session(prefix, "carnivore_a")
    stub.answer({"has-session": ["", "can't find session: carnivore_a\n", 1]})
    with pytest.raises(tmux_cmd.TmuxCommandFailed):
        tmux_cmd.probe_session(prefix, "carnivore_a")


def test_every_offline_attach_is_preceded_by_the_probe_and_a_failed_probe_blocks_it() -> None:
    src = (ROOT / "src/tui/offline/app.py").read_text(encoding="utf-8")
    assert src.count("attach.run(") == 2 and src.index("probe_session(") < src.index("attach.read_pane_size(") < src.index("attach.run(")


def test_pid_executable_requires_exact_tmux_and_skips_ps_when_kernel_answered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evil, good = tmp_path / "tmux-evil", tmp_path / "tmux"
    for f in (evil, good):
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    asked: list[str] = []
    monkeypatch.setattr(socket_check, "_ps_field", lambda pid, field: asked.append(field) or str(good))
    monkeypatch.setattr(socket_check, "_proc_pidpath", lambda pid: str(evil))
    assert socket_check.pid_executable(1) is None and asked == []
    monkeypatch.setattr(socket_check, "_proc_pidpath", lambda pid: None)
    assert socket_check.pid_executable(1) == str(good) and asked == ["comm"]
    monkeypatch.setattr(socket_check, "_ps_field", lambda pid, field: str(evil))
    assert socket_check.pid_executable(1) is None


def test_attach_run_writes_the_preamble_only_to_a_tty(stub: Stub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stub.answer({"attach-session": ["", "", 0]})
    plan = attach.plan_attach("n", "x", dict(os.environ), prefix=(stub.binary, "-S", stub.socket_path), preamble="\x1b[8;60;200thelp\r\n")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert attach.run(plan) == 0
    assert "help" not in capsys.readouterr().out
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    assert attach.run(plan) == 0
    assert "help" in capsys.readouterr().out
