
from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, replace
from typing import Dict, Mapping, Optional, Sequence, Tuple

from src.core.hosts.ssh_exec import (
    FAILURE_SSH,
    FAILURE_SSH_UNAVAILABLE,
    POSIX_SHELLS,
    SH_STDIN_COMMAND,
    SSH_BINARY,
    SshArgumentError,
    SshDestination,
    config_argv,
    direct_argv,
    failure_detail,
    first_line,
    is_posix_shell,
    parse_effective_config,
    posix_quote,
    run_process,
)
from src.core.hosts.store import (
    DEFAULT_REMOTE_SOCKET,
    RESERVED_SOCKETS,
    SOCKET_RE,
    validate_socket,
)
from src.core.tmux_discovery import WELL_KNOWN_PATHS
from src.core.tmux_stderr import STDERR_NO_SERVER, classify_tmux_stderr

CARNIVORE_SOCKETS: Tuple[str, ...] = tuple(sorted(RESERVED_SOCKETS))

MIN_TMUX_VERSION = (3, 2)

PROBE_OK = "ok"
PROBE_KNOWN_HOSTS_DISABLED = "known_hosts_disabled"
PROBE_FAILED = "probe_failed"
PROBE_SHELL_UNSUPPORTED = "shell_unsupported"
PROBE_TMUX_MISSING = "tmux_missing"
PROBE_TMUX_UNUSABLE = "tmux_unusable"
PROBE_TMUX_VERSION_UNKNOWN = "tmux_version_unknown"
PROBE_TMUX_TOO_OLD = "tmux_too_old"

RUNNING = "running"
NONE = "none"
UNKNOWN = "unknown"

TAIL_GNU = "gnu"
TAIL_BSD = "bsd"
TAIL_BUSYBOX = "busybox"

AGENT_NAMES: Tuple[str, ...] = ("claude", "codex")

MAX_PROBE_OUTPUT = 64 << 10

_TMUX_VERSION_RE = re.compile(r"tmux (?:next-)?(\d+)\.(\d+)[a-z]?(?:-rc\d*)?")
_FIELD_RE = re.compile(r"[a-z][a-z0-9_]{0,40}")
_MAX_VALUE = 1024


@dataclass(frozen=True)
class ProbeResult:

    verdict: str
    detail: str
    login_shell: Optional[str] = None
    login_path: Optional[str] = None
    tmux_path: Optional[str] = None
    tmux_version: Optional[str] = None
    agent_paths: Optional[Mapping[str, str]] = None
    machine_id: Optional[str] = None
    remote_carnivore: str = UNKNOWN
    socket_server: str = UNKNOWN
    tail_kind: str = UNKNOWN
    os_name: Optional[str] = None
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.verdict == PROBE_OK

    def host_columns(self) -> Dict[str, Optional[str]]:
        return {
            "probe_state": self.verdict,
            "probe_detail": self.detail,
            "login_shell": self.login_shell,
            "login_path": self.login_path,
            "tmux_path": self.tmux_path,
            "tmux_version": self.tmux_version,
            "agent_paths_json": None if self.agent_paths is None else json.dumps(
                dict(sorted(self.agent_paths.items()))),
            "machine_id": self.machine_id,
            "remote_carnivore": self.remote_carnivore,
        }


def _plain_socket(name: object) -> str:
    if not isinstance(name, str) or SOCKET_RE.fullmatch(name) is None:
        raise SshArgumentError(f"tmux socket name {str(name)[:64]!r} is refused")
    return name


_PROBE_BODY = r"""
emit() { printf '%s=' "$1"; printf '%s' "$2" | tr '\r\n' '  '; printf '\n'; }
absolute() { case "$1" in /*) printf '%s' "$1" ;; esac; }
{
printf '__CARNIVORE_PROBE_BEGIN_%s__\n' "$N"
emit stage start
emit shell "${SHELL:-}"
emit remote_path "${PATH:-}"
PATH="${PATH:+$PATH:}/usr/bin:/bin:/usr/sbin:/sbin"; export PATH
emit os "$(uname -s 2>&1)"
login_path=
emit stage login_shell
case " $POSIX_SHELLS " in
*" ${SHELL##*/} "*)
  out=$("$SHELL" -l -c 'printf "\n__CARNIVORE_LOGIN_PATH_%s__%s\n" "$1" "$PATH"' carnivore-probe "$N" 2>&1)
  login_path=$(printf '%s\n' "$out" | sed -n "s/^__CARNIVORE_LOGIN_PATH_${N}__//p" | head -n 1)
  ;;
esac
emit login_path "$login_path"
lookup=${login_path:-$PATH}
emit stage carnivore
emit carnivore_procs "$(ps -A -o args= 2>/dev/null | grep -c -E -e '-m src[.]main( |$)')"
emit stage tmux
tmux_path=$(absolute "$(PATH=$lookup; export PATH; command -v tmux 2>/dev/null)")
if [ -z "$tmux_path" ]; then
  for c in $TMUX_CANDIDATES; do
    if [ -f "$c" ] && [ -x "$c" ]; then tmux_path=$c; break; fi
  done
fi
emit tmux_path "$tmux_path"
if [ -n "$tmux_path" ]; then
  out=$("$tmux_path" -V 2>&1); emit tmux_version_rc "$?"; emit tmux_version_out "$out"
  emit stage sockets
  i=0
  for s in $SOCKETS; do
    out=$(LC_ALL=C "$tmux_path" -L "$s" list-sessions -F x 2>&1); rc=$?
    emit "socket_${i}_rc" "$rc"
    [ "$rc" = 0 ] || emit "socket_${i}_err" "$out"
    i=$((i + 1))
  done
else
  out=$(PATH=$lookup; export PATH; LC_ALL=C tmux -V 2>&1); emit tmux_missing_rc "$?"
  emit tmux_missing_out "$out"
fi
emit stage agents
for a in $AGENTS; do
  emit "agent_$a" "$(absolute "$(PATH=$lookup; export PATH; command -v "$a" 2>/dev/null)")"
done
emit stage machine
mid=
if [ -r /etc/machine-id ]; then mid=$(cat /etc/machine-id)
elif [ -r /var/lib/dbus/machine-id ]; then mid=$(cat /var/lib/dbus/machine-id)
elif command -v ioreg >/dev/null 2>&1; then
  mid=$(ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null | sed -n 's/.*"IOPlatformUUID" = "\([^"]*\)".*/\1/p' | head -n 1)
fi
emit machine_id "$mid"
emit stage tail
emit tail_version "$(tail --version 2>&1 | head -n 2)"
emit tail_link "$(ls -l "$(command -v tail)" 2>/dev/null)"
emit stage done
printf '__CARNIVORE_PROBE_END_%s__\n' "$N"
} </dev/null
exit 0
"""


def build_probe_script(nonce: str, sockets: Sequence[str],
                       tmux_candidates: Sequence[str] = WELL_KNOWN_PATHS) -> str:
    header = "\n".join((
        "set -f",
        f"N={posix_quote(nonce)}",
        f"POSIX_SHELLS={posix_quote(' '.join(sorted(POSIX_SHELLS)))}",
        f"TMUX_CANDIDATES={posix_quote(' '.join(tmux_candidates))}",
        f"SOCKETS={posix_quote(' '.join(_plain_socket(s) for s in sockets))}",
        f"AGENTS={posix_quote(' '.join(AGENT_NAMES))}",
    ))
    return header + _PROBE_BODY


def parse_probe_output(stdout: str, nonce: str) -> Tuple[Dict[str, str], bool, bool]:
    begin, end = f"__CARNIVORE_PROBE_BEGIN_{nonce}__", f"__CARNIVORE_PROBE_END_{nonce}__"
    lines = stdout.splitlines()
    if begin not in lines:
        return {}, False, False
    fields: Dict[str, str] = {}
    for line in lines[lines.index(begin) + 1:]:
        if line == end:
            return fields, True, True
        key, sep, value = line.partition("=")
        if not sep or _FIELD_RE.fullmatch(key) is None:
            continue
        value = value.strip()[:_MAX_VALUE]
        if key == "stage":
            fields[key] = value
        else:
            fields.setdefault(key, value)
    return fields, True, False


def parse_tmux_version(text: str) -> Optional[Tuple[str, Tuple[int, int]]]:
    line = first_line(text)
    if line == "tmux master":
        return "master", (99, 0)
    match = _TMUX_VERSION_RE.fullmatch(line)
    if match is None:
        return None
    return line[len("tmux "):], (int(match.group(1)), int(match.group(2)))


def tail_kind(os_name: Optional[str], version_text: str, link_text: str) -> str:
    text = f"{version_text} {link_text}".lower()
    if "busybox" in text:
        return TAIL_BUSYBOX
    if "coreutils" in text:
        return TAIL_GNU
    if os_name in ("Darwin", "FreeBSD", "OpenBSD", "NetBSD", "DragonFly"):
        return TAIL_BSD
    return UNKNOWN


def known_hosts_disabled(config: Mapping[str, str]) -> bool:
    files = config.get("userknownhostsfile", "").split()
    return bool(files) and all(name in ("/dev/null", "none") for name in files)


def _socket_state(fields: Mapping[str, str], index: int) -> str:
    rc = fields.get(f"socket_{index}_rc")
    if rc == "0":
        return RUNNING
    if rc is None:
        return UNKNOWN
    err = fields.get(f"socket_{index}_err", "")
    return NONE if classify_tmux_stderr(err) == STDERR_NO_SERVER else UNKNOWN


def judge(fields: Mapping[str, str], *, socket: str, sockets: Sequence[str],
          tmux_candidates: Sequence[str] = WELL_KNOWN_PATHS, elapsed_ms: int = 0) -> ProbeResult:
    shell = fields.get("shell") or None
    login_path = fields.get("login_path") or None
    tmux_path = fields.get("tmux_path") or None
    procs = fields.get("carnivore_procs", "")
    process = RUNNING if procs.isdigit() and int(procs) > 0 else (NONE if procs == "0" else UNKNOWN)
    base = ProbeResult(
        PROBE_OK, "", login_shell=shell, login_path=login_path, tmux_path=tmux_path,
        remote_carnivore=RUNNING if process == RUNNING else UNKNOWN,
        agent_paths={name: fields[f"agent_{name}"] for name in AGENT_NAMES
                     if fields.get(f"agent_{name}", "").startswith("/")},
        machine_id=fields.get("machine_id") or None, os_name=fields.get("os") or None,
        tail_kind=tail_kind(fields.get("os"), fields.get("tail_version", ""),
                            fields.get("tail_link", "")),
        elapsed_ms=elapsed_ms)
    if not is_posix_shell(shell):
        return replace(base, verdict=PROBE_SHELL_UNSUPPORTED, detail=(
            f"the login shell {shell or '(none reported)'} is not sh, bash, zsh, dash or ksh; "
            "commands for this host are quoted for those shells, so it is refused"))
    if tmux_path is None:
        said = first_line(fields.get("tmux_missing_out", ""))
        return replace(base, verdict=PROBE_TMUX_MISSING, detail=(
            f"tmux was not found on the login PATH ({login_path or fields.get('remote_path') or '?'})"
            f" or at {', '.join(tmux_candidates)}" + (f"; the host said: {said}" if said else "")
            + "; install tmux 3.2 or later there"))
    version_out = fields.get("tmux_version_out", "")
    if fields.get("tmux_version_rc") != "0":
        return replace(base, verdict=PROBE_TMUX_UNUSABLE, detail=(
            f"{tmux_path} -V exited {fields.get('tmux_version_rc', '?')}: "
            f"{first_line(version_out) or 'no output'}"))
    parsed = parse_tmux_version(version_out)
    if parsed is None:
        return replace(base, verdict=PROBE_TMUX_VERSION_UNKNOWN, detail=(
            f"no tmux version could be read from {first_line(version_out)!r}; "
            "remote sessions need tmux 3.2 or later"))
    version, number = parsed
    base = replace(base, tmux_version=version)
    if number < MIN_TMUX_VERSION:
        return replace(base, verdict=PROBE_TMUX_TOO_OLD, detail=(
            f"tmux {version} at {tmux_path} is older than 3.2, which remote control mode needs"))
    states = [_socket_state(fields, index) for index in range(len(sockets))]
    theirs = [process] + [state for name, state in zip(sockets, states) if name in CARNIVORE_SOCKETS]
    remote_carnivore = RUNNING if RUNNING in theirs else (
        NONE if all(state == NONE for state in theirs) else UNKNOWN)
    base = replace(base, remote_carnivore=remote_carnivore, socket_server=states[0])
    return replace(base, detail=f"tmux {version} at {tmux_path}, login shell {shell}" + (
        "; this host runs its own Carnivore" if remote_carnivore == RUNNING else ""))


async def probe_host(dest: SshDestination, *, socket: str = DEFAULT_REMOTE_SOCKET,
                     ssh_binary: str = SSH_BINARY, timeout: float = 30.0,
                     tmux_candidates: Sequence[str] = WELL_KNOWN_PATHS) -> ProbeResult:
    started = time.monotonic()
    socket = validate_socket(socket)

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    config = await run_process(config_argv(dest, ssh_binary=ssh_binary), timeout=10.0,
                               verb="config", host=dest.target)
    if config.failure == FAILURE_SSH_UNAVAILABLE:
        return ProbeResult(FAILURE_SSH_UNAVAILABLE, failure_detail(
            FAILURE_SSH_UNAVAILABLE, config.spawn_error or ""), elapsed_ms=elapsed())
    if not config.ok:
        failure = config.failure or FAILURE_SSH
        return ProbeResult(failure, failure_detail(failure, config.stderr_text),
                           elapsed_ms=elapsed())
    effective = parse_effective_config(config.stdout_text)
    if known_hosts_disabled(effective):
        return ProbeResult(PROBE_KNOWN_HOSTS_DISABLED, (
            f"the ssh config for {dest.target} keeps host keys in "
            f"{effective['userknownhostsfile']}, so a changed host key could never be noticed; "
            "remove that UserKnownHostsFile setting for this host"), elapsed_ms=elapsed())

    nonce = secrets.token_hex(8)
    sockets = (socket, *CARNIVORE_SOCKETS)
    script = build_probe_script(nonce, sockets, tmux_candidates)
    result = await run_process(direct_argv(dest, SH_STDIN_COMMAND, ssh_binary=ssh_binary),
                               stdin_data=script.encode("utf-8"), timeout=timeout,
                               max_output=MAX_PROBE_OUTPUT, verb="probe", host=dest.target)
    fields, began, finished = parse_probe_output(result.stdout_text, nonce)
    if finished:
        return judge(fields, socket=socket, sockets=sockets, tmux_candidates=tmux_candidates,
                     elapsed_ms=elapsed())
    reached = f"; the probe had reached its {fields['stage']} step" if fields.get("stage") else ""
    if result.failure is not None:
        return ProbeResult(result.failure, failure_detail(result.failure, result.stderr_text)
                           + reached, elapsed_ms=elapsed())
    said = first_line(result.stderr_text) or first_line(result.stdout_text)
    return ProbeResult(PROBE_FAILED, (
        f"the probe script did not finish (exit {result.returncode})" + reached
        + (f": {said}" if said else "")), elapsed_ms=elapsed())
