
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import (
    HARDENING_OPTIONS,
    SH_STDIN_COMMAND,
    SshArgumentError,
    SshDestination,
    argv_command,
    classify_ssh_failure,
    config_argv,
    control_argv,
    direct_argv,
    is_posix_shell,
    master_argv,
    mux_argv,
    parse_effective_config,
    posix_join,
    posix_quote,
    run_process,
    sh_c,
    validate_control_path,
    validate_ssh_port,
)

REAL_SSH = "/usr/bin/ssh"
needs_real_ssh = pytest.mark.skipif(not os.access(REAL_SSH, os.X_OK), reason="no /usr/bin/ssh")
CP = "/tmp/cm/studio-1a2b3c4d-0"



@pytest.mark.parametrize("target", [
    "studio", "alex@studio", "studio.local", "a_b", "user@host-1.example.com", "10.0.0.5",
    "alex@10.0.0.5", "host+x", "_x", "u+x@h", "_svc@box", "a" * 254,
])
def test_ordinary_targets_pass(target: str) -> None:
    assert SshDestination(target).target == target


@pytest.mark.parametrize("target", [
    "-oProxyCommand=touch x", "-p", "-", "--", "alex@-oProxyCommand=x", "alex@-x",
    "alex@-oBatchMode", "alex@", "@studio",
    "a@b@c", "studio;id", "studio id", "$(id)", "`id`", "studio\n", "studio\x00", "", "a" * 255,
    "studio/../x", "studiö", "studio:22", "'studio'", "studio|x", "studio&", "~studio", ".@studio",
    "u%r@h", "studio%h", ".studio", "alex@.studio",
])
def test_option_and_shell_shaped_targets_are_refused(target: str) -> None:
    with pytest.raises(SshArgumentError):
        SshDestination(target)


def test_the_sink_and_the_store_accept_exactly_the_same_targets() -> None:
    from src.core.hosts import store

    corpus = ["studio", "alex@studio", "a" * 254, "a" * 255, "u%r@h", "alex@-x", "-p22", "@studio",
              "alex@", "a@b@c", ".studio", "_x", "u+x@h", "studio;id", "100.64.0.1", "studio\n", "",
              "x.y@z.w", "my_host-1", "stu:dio", "alex@.studio", "__", "a+@b"]
    for target in corpus:
        try:
            store.validate_ssh_target(target)
            stored = True
        except store.HostInvalid:
            stored = False
        try:
            SshDestination(target)
            sink = True
        except SshArgumentError:
            sink = False
        assert stored == sink, target


@pytest.mark.parametrize("value", [None, 5, b"studio", ["studio"]])
def test_non_string_targets_are_refused(value: object) -> None:
    with pytest.raises(SshArgumentError):
        SshDestination(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("port,ok", [(None, True), (1, True), (22, True), (65535, True),
                                     (0, False), (65536, False), (-1, False), (True, False),
                                     ("22", False), (22.0, False)])
def test_port_is_an_integer_in_range(port: object, ok: bool) -> None:
    if ok:
        assert validate_ssh_port(port) == port
    else:
        with pytest.raises(SshArgumentError):
            SshDestination("studio", port)  # type: ignore[arg-type]


@needs_real_ssh
def test_a_dash_target_never_becomes_an_option(tmp_path: Path) -> None:
    canary = tmp_path / "pwned"
    payload = f"-oProxyCommand=touch {canary}"
    with pytest.raises(SshArgumentError):
        SshDestination(payload)

    dest = SshDestination("studio")
    object.__setattr__(dest, "target", payload)
    argv = direct_argv(dest, "true", ssh_binary=REAL_SSH)
    assert argv[argv.index("--") + 1] == payload
    run = subprocess.run([REAL_SSH, "-F", "/dev/null", *argv[1:]], capture_output=True,
                         timeout=20, stdin=subprocess.DEVNULL)
    assert run.returncode == 255
    assert not canary.exists()

    unguarded = [word for word in argv if word != "--"]
    subprocess.run([REAL_SSH, "-F", "/dev/null", *unguarded[1:]], capture_output=True,
                   timeout=20, stdin=subprocess.DEVNULL)
    assert canary.exists(), "the negative control did not run the payload, so it proves nothing"



EXPECTED_HARDENING = {
    "BatchMode": "yes", "StrictHostKeyChecking": "accept-new", "ForwardAgent": "no",
    "ForwardX11": "no", "ClearAllForwardings": "yes", "Tunnel": "no", "PermitLocalCommand": "no",
    "RemoteCommand": "none", "RequestTTY": "no", "EscapeChar": "none", "LogLevel": "ERROR",
    "ConnectTimeout": "15", "ServerAliveInterval": "15", "ServerAliveCountMax": "3",
}


def _pairs(argv: list) -> list:
    return [tuple(argv[i + 1].split("=", 1)) for i, word in enumerate(argv) if word == "-o"]


def _all_shapes(port=None) -> dict:
    dest = SshDestination("alex@studio", port)
    return {
        "master": master_argv(dest, CP), "mux": mux_argv(dest, CP, "exec /bin/sh -c 'true'"),
        "direct": direct_argv(dest, SH_STDIN_COMMAND), "check": control_argv(dest, CP, "check"),
        "exit": control_argv(dest, CP, "exit"), "config": config_argv(dest),
    }


def test_the_hardening_set_is_exactly_the_reviewed_one() -> None:
    assert dict(HARDENING_OPTIONS) == EXPECTED_HARDENING
    assert len(HARDENING_OPTIONS) == len(EXPECTED_HARDENING)


@pytest.mark.parametrize("port", [None, 2222])
def test_every_command_line_carries_every_hardening_option(port) -> None:
    for shape, argv in _all_shapes(port).items():
        pairs = _pairs(argv)
        for key, value in EXPECTED_HARDENING.items():
            assert (key, value) in pairs, f"{shape} lacks -o {key}={value}"
        host_key_values = [v for k, v in pairs if k == "StrictHostKeyChecking"]
        assert host_key_values == ["accept-new"], f"{shape}: {host_key_values}"
        dd = argv.index("--")
        assert argv[dd + 1] == "alex@studio"
        assert len(argv) - dd - 2 == (1 if shape in ("mux", "direct") else 0)
        assert argv.count("--") == 1
        if port is None:
            assert "-p" not in argv
        else:
            assert argv[argv.index("-p") + 1] == "2222" and argv.index("-p") < dd


def test_each_shape_carries_its_own_control_options() -> None:
    shapes = _all_shapes()
    assert {("ControlMaster", "yes"), ("ControlPersist", "no"), ("ControlPath", CP)} <= set(
        _pairs(shapes["master"])) and "-N" in shapes["master"]
    assert {("ControlMaster", "no"), ("ControlPath", CP), ("ProxyCommand", "false")} <= set(
        _pairs(shapes["mux"]))
    assert {("ControlMaster", "no"), ("ControlPath", "none")} <= set(_pairs(shapes["direct"]))
    assert shapes["check"][shapes["check"].index("-O") + 1] == "check"
    assert shapes["config"][1] == "-G"


HOSTILE_CONFIG = """Host *
  BatchMode no
  StrictHostKeyChecking no
  ForwardAgent yes
  ForwardX11 yes
  ClearAllForwardings no
  PermitLocalCommand yes
  LocalCommand touch {canary}
  RemoteCommand tmux attach
  RequestTTY force
  LogLevel QUIET
  ConnectTimeout 999
  ServerAliveInterval 0
  ServerAliveCountMax 9
  Tunnel yes
  EscapeChar ~
  ControlMaster auto
  ControlPath ~/.ssh/cm-%C
  ControlPersist 10m
  ProxyJump jumpy
"""

EFFECTIVE = {
    "batchmode": "yes", "stricthostkeychecking": "accept-new", "forwardagent": "no",
    "forwardx11": "no", "clearallforwardings": "yes", "tunnel": "false",
    "permitlocalcommand": "no", "requesttty": "false", "escapechar": "none", "loglevel": "ERROR",
    "connecttimeout": "15", "serveraliveinterval": "15", "serveralivecountmax": "3",
}


def _effective(argv: list, config: Path) -> dict:
    words = [w for w in argv[1:] if w not in ("-N", "-G")]
    if "-O" in words:
        at = words.index("-O")
        del words[at:at + 2]
    dd = words.index("--")
    words = words[:dd + 2]
    run = subprocess.run([REAL_SSH, "-F", str(config), "-G", *words], capture_output=True,
                         text=True, timeout=20, stdin=subprocess.DEVNULL)
    assert run.returncode == 0, run.stderr
    return parse_effective_config(run.stdout)


@needs_real_ssh
def test_the_options_win_over_a_hostile_user_config(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(HOSTILE_CONFIG.format(canary=tmp_path / "local-command-ran"))
    alone = _effective([REAL_SSH, "--", "studio"], config)
    for key, value in EFFECTIVE.items():
        assert alone.get(key) != value, f"the hostile config does not contest {key}"
    assert alone.get("remotecommand") == "tmux attach"

    for shape, argv in _all_shapes().items():
        got = _effective(argv, config)
        for key, value in EFFECTIVE.items():
            assert got.get(key) == value, f"{shape}: {key} is {got.get(key)!r}"
        assert "remotecommand" not in got, shape
    master = _effective(_all_shapes()["master"], config)
    assert (master["controlmaster"], master["controlpersist"], master["controlpath"]) == (
        "true", "no", CP)
    assert master["proxyjump"] == "jumpy", "the user's own ProxyJump must still work"
    mux = _effective(_all_shapes()["mux"], config)
    assert (mux["controlmaster"], mux["proxycommand"]) == ("false", "false")


def test_control_path_is_short_and_plain() -> None:
    assert validate_control_path(CP) == CP
    for bad in ("relative/x", "/tmp/a b", "/tmp/%h", "/tmp/~x", "/tmp/'x", "/" + "a" * 90):
        with pytest.raises(SshArgumentError):
            validate_control_path(bad)
    with pytest.raises(SshArgumentError):
        control_argv(SshDestination("studio"), CP, "stop")
    for bad in ("", "a\x00b"):
        with pytest.raises(SshArgumentError):
            mux_argv(SshDestination("studio"), CP, bad)



def _hostile_words(canary: Path) -> list:
    return [
        "", " ", "a b", "it's", "'", "''", '"', f"$(touch {canary})", f"`touch {canary}`",
        f"; touch {canary}", f"&& touch {canary}", "| cat", "\n", "a\nb", "*", "~", "=ls",
        "-n", "--", "\\", "\\'", "$HOME", "${IFS}", "!", "#x", "é", "\t", "\x01", "%s",
    ]


SHELLS = [s for s in ("/bin/sh", "/bin/bash", "/bin/zsh", "/bin/dash") if os.access(s, os.X_OK)]


@pytest.mark.parametrize("shell", SHELLS)
def test_quoted_words_arrive_verbatim_under_each_login_shell(shell: str, tmp_path: Path) -> None:
    canary = tmp_path / "ran"
    words = _hostile_words(canary)
    command = argv_command(["printf", "%s\\0", *words])
    run = subprocess.run([shell, "-c", command], capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr
    assert run.stdout.split(b"\0")[:-1] == [w.encode() for w in words]
    assert not canary.exists()


def test_the_injection_canary_is_live_without_the_quoting(tmp_path: Path) -> None:
    canary = tmp_path / "ran"
    subprocess.run(["/bin/sh", "-c", f"printf %s $(touch {canary})"], capture_output=True,
                   timeout=10)
    assert canary.exists()


@pytest.mark.skipif(not os.access("/bin/zsh", os.X_OK), reason="no zsh")
def test_zsh_needs_every_word_quoted() -> None:
    bare = subprocess.run(["/bin/zsh", "-c", "printf %s " + shlex.quote("=ls")],
                          capture_output=True, text=True, timeout=10)
    assert bare.stdout != "=ls", "zsh no longer expands =word, so this control proves nothing"
    quoted = subprocess.run(["/bin/zsh", "-c", "printf %s " + posix_quote("=ls")],
                            capture_output=True, text=True, timeout=10)
    assert quoted.stdout == "=ls"


def test_quoting_refuses_what_a_command_line_cannot_carry() -> None:
    for bad in ("a\x00b", None, 5):
        with pytest.raises(SshArgumentError):
            posix_quote(bad)  # type: ignore[arg-type]
    for bad in ([], "printf", ()):
        with pytest.raises(SshArgumentError):
            posix_join(bad)  # type: ignore[arg-type]
    for bad in ("", "   "):
        with pytest.raises(SshArgumentError):
            sh_c(bad)
    assert posix_quote("it's") == "'it'\"'\"'s'"
    assert sh_c("true") == "exec /bin/sh -c 'true'"


@pytest.mark.parametrize("shell,ok", [("/bin/zsh", True), ("/bin/bash", True), ("/bin/sh", True),
                                      ("/usr/bin/dash", True), ("/bin/ksh", True),
                                      ("/usr/local/bin/fish", False), ("/bin/csh", False),
                                      ("/bin/tcsh", False), ("", False), (None, False),
                                      ("/bin/zsh-5.9", False)])
def test_is_posix_shell(shell, ok: bool) -> None:
    assert is_posix_shell(shell) is ok



CHANGED_BANNER = """@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Host key for studio has changed and you have requested strict checking.
Host key verification failed.
"""


@pytest.mark.parametrize("stderr,expected", [
    (CHANGED_BANNER, "host_key_changed"),
    ("No ED25519 host key is known for studio and you have requested strict checking.\n"
     "Host key verification failed.\n", "host_key_unverified"),
    ("alex@studio: Permission denied (publickey,password,keyboard-interactive).", "auth_failed"),
    ("ssh: Could not resolve hostname nosuch.invalid: nodename nor servname provided, or not known",
     "unreachable"),
    ("ssh: connect to host studio port 1: Connection refused", "unreachable"),
    ("ssh: connect to host studio port 22: Operation timed out", "unreachable"),
    ("Connection closed by UNKNOWN port 65535", "unreachable"),
    ("kex_exchange_identification: read: Connection reset by peer", "unreachable"),
    ("Timeout, server studio not responding.", "unreachable"),
    ("channel 3: open failed: administratively prohibited: open failed", "channel_refused"),
    ("command-line line 0: Bad configuration option: forwardagnet", "ssh_failed"),
    ("", "ssh_failed"),
])
def test_failures_are_named_from_ssh_wording(stderr: str, expected: str) -> None:
    assert classify_ssh_failure(stderr) == expected


def test_failure_detail_says_meaning_then_ssh_words() -> None:
    detail = ssh_exec.failure_detail("host_key_changed", CHANGED_BANNER)
    assert detail.startswith("the host key changed since it was first trusted")
    assert detail.endswith("(WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!)")


def test_parse_effective_config_keeps_first_values() -> None:
    config = parse_effective_config("BatchMode yes\nidentityfile ~/a\nidentityfile ~/b\n\n")
    assert config == {"batchmode": "yes", "identityfile": "~/a"}



@pytest.mark.asyncio
async def test_runner_keeps_stderr_and_exit_code() -> None:
    result = await run_process(["/bin/sh", "-c", "echo out; echo oops >&2; exit 3"], timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (3, b"out\n", b"oops\n")
    assert result.failure is None and not result.ok


@pytest.mark.asyncio
async def test_runner_names_exit_255_from_stderr() -> None:
    result = await run_process(["/bin/sh", "-c", "echo 'ssh: connect to host h port 22: "
                                "Connection refused' >&2; exit 255"], timeout=10)
    assert result.failure == "unreachable"


@pytest.mark.asyncio
async def test_runner_feeds_stdin() -> None:
    result = await run_process(["/bin/sh", "-s"], stdin_data=b"echo from-stdin\n", timeout=10)
    assert result.ok and result.stdout == b"from-stdin\n"


@pytest.mark.asyncio
async def test_runner_caps_a_flood_and_kills_it() -> None:
    result = await run_process(["/bin/sh", "-c", "yes | head -c 5000000"], timeout=10,
                               max_output=1000)
    assert result.overflowed and result.returncode is None
    assert len(result.stdout) == 1000 and result.failure == "output_overflow"


@pytest.mark.asyncio
async def test_runner_deadline_kills_a_hang() -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await run_process(["/bin/sh", "-c", "echo partial; exec sleep 30"], timeout=0.5)
    assert result.timed_out and result.returncode is None and result.failure == "timeout"
    assert result.stdout == b"partial\n", "partial output must be kept, never discarded"
    assert loop.time() - started < 5


@pytest.mark.asyncio
async def test_runner_names_a_missing_binary(tmp_path: Path) -> None:
    result = await run_process([str(tmp_path / "no-ssh-here"), "-V"], timeout=5)
    assert result.failure == "ssh_unavailable" and result.spawn_error

