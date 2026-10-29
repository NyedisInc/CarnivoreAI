
from __future__ import annotations

import json
import os
import shlex
from typing import Iterator

import pytest

from src.core.hosts import probe
from src.core.hosts.probe import (
    DEFAULT_REMOTE_SOCKET,
    NONE,
    RUNNING,
    UNKNOWN,
    build_probe_script,
    parse_probe_output,
    parse_tmux_version,
    probe_host,
    tail_kind,
)
from src.core.hosts import store
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.core.tmux_discovery import resolve_tmux_path
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture

DEST = SshDestination("acme@fakehost")
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


@pytest.fixture
def host() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def stage(host: FakeSshHost, *, tmux: str = "tmux 3.7c", running: tuple = (), procs: str = "",
          shell: str = "/bin/sh", profile: str = "") -> None:
    path = f"{host.bin_dir}:{SYSTEM_PATH}"
    host.set("shell", shell)
    host.set("path", path)
    (host.root / "home" / ".profile").write_text(
        profile + f'PATH="{path}"; export PATH\n', encoding="utf-8")
    host.add_tool("ps", f"printf '%s\\n' {shlex.quote(procs)}\n" if procs else ":\n")
    host.add_tool("claude", "exit 0\n")
    if tmux:
        host.add_fake_tmux(tmux, running)


async def run_probe(host: FakeSshHost, **options) -> probe.ProbeResult:
    settings = dict(ssh_binary=host.ssh_binary, timeout=20.0, tmux_candidates=())
    settings.update(options)
    return await probe_host(DEST, **settings)


@pytest.mark.asyncio
async def test_a_ready_host_reads_every_field(host: FakeSshHost) -> None:
    stage(host)
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.tmux_path == str(host.bin_dir / "tmux") and result.tmux_version == "3.7c"
    assert result.login_shell == "/bin/sh"
    assert result.login_path == f"{host.bin_dir}:{SYSTEM_PATH}"
    assert dict(result.agent_paths) == {"claude": str(host.bin_dir / "claude")}
    assert result.machine_id and result.os_name
    assert (result.remote_carnivore, result.socket_server) == (NONE, NONE)
    assert result.tail_kind in ("gnu", "bsd", "busybox")
    assert [c["mode"] for c in host.calls()] == ["config", "direct"]


@pytest.mark.asyncio
async def test_a_missing_tmux_is_named_in_the_hosts_own_words(host: FakeSshHost) -> None:
    for directory in SYSTEM_PATH.split(":"):
        if os.path.exists(os.path.join(directory, "tmux")):
            pytest.skip(f"{directory}/tmux exists, so a host without tmux cannot be staged")
    stage(host, tmux="")
    result = await run_probe(host)
    assert result.verdict == "tmux_missing"
    said = result.detail.partition("the host said: ")[2]
    assert "not found" in said, f"the host's own error text was discarded: {result.detail}"
    assert result.tmux_path is None and result.tmux_version is None
    assert (result.remote_carnivore, result.socket_server) == (UNKNOWN, UNKNOWN)


@pytest.mark.asyncio
async def test_a_tmux_on_a_well_known_path_is_found_off_the_login_path(host: FakeSshHost) -> None:
    stage(host, tmux="")
    elsewhere = host.root / "opt" / "tmux"
    elsewhere.parent.mkdir()
    elsewhere.write_text('#!/bin/sh\n[ "$1" = "-V" ] && echo "tmux 3.4" && exit 0\n'
                         'echo "no server running on /x/$2" >&2; exit 1\n')
    elsewhere.chmod(0o755)
    result = await run_probe(host, tmux_candidates=(str(host.root / "nope"), str(elsewhere)))
    assert (result.verdict, result.tmux_path, result.tmux_version) == ("ok", str(elsewhere), "3.4")


@pytest.mark.asyncio
@pytest.mark.parametrize("version,verdict,shown", [
    ("tmux 3.1c", "tmux_too_old", "3.1c"),
    ("tmux 2.9", "tmux_too_old", "2.9"),
    ("tmux openbsd-7.4", "tmux_version_unknown", "openbsd-7.4"),
    ("tmux 3.2", "ok", "3.2"),
    ("tmux next-3.6", "ok", "next-3.6"),
])
async def test_the_tmux_version_gate(host: FakeSshHost, version: str, verdict: str,
                                     shown: str) -> None:
    stage(host, tmux=version)
    result = await run_probe(host)
    assert result.verdict == verdict, result.detail
    assert shown in (result.tmux_version or result.detail)


@pytest.mark.asyncio
async def test_a_tmux_that_cannot_run_is_unusable(host: FakeSshHost) -> None:
    stage(host, tmux="")
    host.add_tool("tmux", 'echo "dyld: Library not loaded: libevent" >&2; exit 134\n')
    result = await run_probe(host)
    assert result.verdict == "tmux_unusable"
    assert "134" in result.detail and "libevent" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("shell", ["/usr/local/bin/fish", "/bin/csh", "/bin/tcsh"])
async def test_a_login_shell_outside_the_posix_family_is_refused(host: FakeSshHost,
                                                                  shell: str) -> None:
    stage(host, shell=shell)
    result = await run_probe(host)
    assert result.verdict == "shell_unsupported" and shell in result.detail
    assert result.login_shell == shell and result.login_path is None


@pytest.mark.asyncio
async def test_a_zsh_login_shell_is_used_for_the_login_path(host: FakeSshHost) -> None:
    if not os.access("/bin/zsh", os.X_OK):
        pytest.skip("no zsh")
    stage(host, shell="/bin/zsh")
    (host.root / "home" / ".zprofile").write_text(f'PATH="{host.bin_dir}:/zsh-only:{SYSTEM_PATH}"\n')
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.login_path == f"{host.bin_dir}:/zsh-only:{SYSTEM_PATH}"


@pytest.mark.asyncio
@pytest.mark.parametrize("procs,running,expected", [
    ("/opt/homebrew/bin/python3 -m src.main", (), RUNNING),
    ("", ("carnivore",), RUNNING),
    ("", ("cloude",), RUNNING),
    ("python3 -m src.mainframe_tool", (), NONE),
    ("/usr/bin/python3 -m src.main --reload", (), RUNNING),
    ("python3 -m srcXmain", (), NONE),
    ("", ("carnivore-remote",), NONE),
    ("", (), NONE),
])
async def test_the_far_boxs_own_carnivore_is_reported(host: FakeSshHost, procs: str,
                                                     running: tuple, expected: str) -> None:
    stage(host, procs=procs, running=running)
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.remote_carnivore == expected
    assert result.socket_server == (RUNNING if DEFAULT_REMOTE_SOCKET in running else NONE)


@pytest.mark.asyncio
@pytest.mark.parametrize("socket", ["carnivore", "cloude"])
async def test_a_carnivore_socket_is_refused_before_anything_is_contacted(
        host: FakeSshHost, socket: str) -> None:
    stage(host)
    with pytest.raises(store.HostInvalid) as refused:
        await run_probe(host, socket=socket)
    assert refused.value.code == "host_socket_reserved"
    assert host.calls() == []


@pytest.mark.asyncio
async def test_login_noise_and_forged_markers_are_ignored(host: FakeSshHost) -> None:
    stage(host, profile=(
        'echo "welcome to the box"\n'
        'echo "__CARNIVORE_LOGIN_PATH_deadbeefdeadbeef__/evil"\n'
        'echo "__CARNIVORE_PROBE_END_deadbeefdeadbeef__"\n'
        'echo "tmux_path=/evil/tmux"\n'))
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.login_path == f"{host.bin_dir}:{SYSTEM_PATH}"
    assert result.tmux_path == str(host.bin_dir / "tmux")


@pytest.mark.asyncio
async def test_a_tool_that_reads_stdin_cannot_eat_the_script(host: FakeSshHost) -> None:
    stage(host)
    host.add_tool("uname", "cat\necho Darwin\n")
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.os_name == "Darwin"


@pytest.mark.asyncio
async def test_a_hanging_login_shell_times_out_at_its_step(host: FakeSshHost) -> None:
    stage(host, profile="sleep 30\n")
    result = await run_probe(host, timeout=1.0)
    assert result.verdict == "timeout" and "login_shell" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,verdict,words", [
    ("unreachable", "unreachable", "Connection refused"),
    ("auth_failed", "auth_failed", "Permission denied"),
    ("host_key_changed", "host_key_changed", "REMOTE HOST IDENTIFICATION HAS CHANGED"),
])
async def test_ssh_failures_become_verdicts(host: FakeSshHost, scenario: str, verdict: str,
                                            words: str) -> None:
    stage(host)
    host.set("scenario", scenario)
    result = await run_probe(host)
    assert result.verdict == verdict and words in result.detail


@pytest.mark.asyncio
async def test_a_connection_that_never_answers_times_out(host: FakeSshHost) -> None:
    stage(host)
    host.set("scenario", "hang")
    result = await run_probe(host, timeout=0.5)
    assert result.verdict == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,verdict", [
    ("/dev/null", "known_hosts_disabled"),
    ("none", "known_hosts_disabled"),
    ("/dev/null none", "known_hosts_disabled"),
    ("/dev/null ~/.ssh/known_hosts", "ok"),
])
async def test_a_config_that_can_never_notice_a_changed_key_is_refused(
        host: FakeSshHost, setting: str, verdict: str) -> None:
    stage(host)
    host.set("known_hosts_setting", setting)
    result = await run_probe(host)
    assert result.verdict == verdict, result.detail
    if verdict != "ok":
        assert not host.calls("direct"), "the host was contacted anyway"


@pytest.mark.asyncio
async def test_the_real_local_tmux_through_the_fake_host(host: FakeSshHost) -> None:
    real = resolve_tmux_path()
    if real is None:
        pytest.skip("no tmux on this machine")
    stage(host, tmux="")
    (host.bin_dir / "tmux").symlink_to(real)
    result = await run_probe(host)
    assert result.verdict == "ok", result.detail
    assert result.tmux_path == str(host.bin_dir / "tmux")
    assert result.tmux_version and parse_tmux_version("tmux " + result.tmux_version)
    assert (result.remote_carnivore, result.socket_server) == (NONE, NONE)



@pytest.mark.parametrize("text,expected", [
    ("tmux 3.7c", ("3.7c", (3, 7))), ("tmux 3.2", ("3.2", (3, 2))),
    ("tmux next-3.6", ("next-3.6", (3, 6))), ("tmux 3.4-rc", ("3.4-rc", (3, 4))),
    ("tmux master", ("master", (99, 0))), ("tmux 10.1a\n", ("10.1a", (10, 1))),
    ("tmux openbsd-7.4", None), ("", None), ("zsh: command not found: tmux", None),
])
def test_parse_tmux_version(text: str, expected) -> None:
    assert parse_tmux_version(text) == expected


@pytest.mark.parametrize("os_name,version,link,kind", [
    ("Linux", "tail (GNU coreutils) 9.4", "", "gnu"),
    ("Darwin", "tail: illegal option -- -", "", "bsd"),
    ("Linux", "tail: unrecognized option '--version' BusyBox v1.36.1", "", "busybox"),
    ("Linux", "", "lrwxrwxrwx 1 root root 12 /bin/tail -> /bin/busybox", "busybox"),
    ("Linux", "", "", "unknown"),
])
def test_tail_kind(os_name, version, link, kind) -> None:
    assert tail_kind(os_name, version, link) == kind


def test_host_columns_are_the_designs_columns() -> None:
    result = probe.ProbeResult("ok", "fine", tmux_version="3.7c", agent_paths={"codex": "/c",
                                                                               "claude": "/a"})
    columns = result.host_columns()
    assert set(columns) == {"probe_state", "probe_detail", "login_shell", "login_path",
                            "tmux_path", "tmux_version", "agent_paths_json", "machine_id",
                            "remote_carnivore"}
    assert json.loads(columns["agent_paths_json"]) == {"claude": "/a", "codex": "/c"}


@pytest.mark.parametrize("name", ["", "a b", "x;y", "-L", "../x", "a/b", "$(id)", "a" * 65, None,
                                  "a.b", "a\nb"])
def test_socket_names_are_plain_names(name) -> None:
    with pytest.raises(SshArgumentError):
        build_probe_script("ab", [name])


def test_parse_probe_output_reads_only_this_runs_lines() -> None:
    text = ("banner\nshell=/evil\n__CARNIVORE_PROBE_BEGIN_ab__\nstage=start\nshell=/bin/zsh\n"
            "shell=/second\nNot A Key=x\nstage=tmux\n__CARNIVORE_PROBE_END_ab__\nshell=/after\n")
    assert parse_probe_output(text, "ab") == ({"stage": "tmux", "shell": "/bin/zsh"}, True, True)
    assert parse_probe_output(text, "cd") == ({}, False, False)
    assert parse_probe_output("__CARNIVORE_PROBE_BEGIN_ab__\nstage=sockets\n", "ab") == (
        {"stage": "sockets"}, True, False)
