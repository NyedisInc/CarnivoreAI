
from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.hosts import ssh_exec

log = structlog.get_logger(__name__)

SSH_BINARY = ssh_exec.SSH_BINARY
SSH_KEYGEN = "/usr/bin/ssh-keygen"

BLOCKERS = ("unreachable", "auth_failed", "host_key_changed", "not_posix_shell", "no_console_login", "needs_homebrew",
            "installer_too_old", "needs_owner", "joined_elsewhere")

PROBE_SCRIPT = r"""
printf 'shell=%s\n' "$SHELL"
c="$(stat -f %Su /dev/console 2>/dev/null)"; u="$(id -un)"
if [ -n "$c" ] && [ "$c" = "$u" ] && launchctl print "gui/$(id -u)" >/dev/null 2>&1; then echo console_user_ok=1; else echo console_user_ok=0; fi
if [ -x /opt/homebrew/bin/brew ]; then echo brew=1; else echo brew=0; fi
printf 'installed_version=%s\n' "$(plutil -extract CFBundleShortVersionString raw -o - /Applications/Carnivore.app/Contents/Info.plist 2>/dev/null)"
p="$(sed -n 's/^PORT=//p' "$HOME/Library/Application Support/Carnivore Menubar/server/.env" 2>/dev/null | head -n 1 | tr -cd 0-9)"
h="$(curl -fsS --max-time 3 "http://127.0.0.1:${p:-8000}/health" 2>/dev/null)"
printf 'setup_status=%s\n' "$(printf '%s' "$h" | sed -n 's/.*"setup_status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
printf 'joined=%s\n' "$(printf '%s' "$h" | sed -n 's/.*"joined"[[:space:]]*:[[:space:]]*\([a-z]*\).*/\1/p' | head -n 1)"
printf 'installer_protocol=%s\n' "$(curl -fsSL --max-time 15 --proto '=https' --tlsv1.2 https://carnivore.ai/install.sh 2>/dev/null | grep -c '^INSTALLER_PROTOCOL=2$')"
"""

_FP_LINE = re.compile(r"(SHA256:[A-Za-z0-9+/=]+)\s.*\(([A-Za-z0-9_-]+)\)\s*$")
_FP_FOUND = re.compile(r"^\S+ ([A-Za-z0-9_-]+) (SHA256:[A-Za-z0-9+/=]+)\s*$")
_PROBE_VALUES = {
    "shell": re.compile(r"^[A-Za-z0-9._/-]{1,64}$"), "console_user_ok": re.compile(r"^[01]$"), "brew": re.compile(r"^[01]$"),
    "installed_version": re.compile(r"^[A-Za-z0-9.+-]{0,32}$"), "setup_status": re.compile(r"^[a-z_]{0,24}$"),
    "joined": re.compile(r"^(true|false|null)?$"), "installer_protocol": re.compile(r"^[0-9]{1,3}$"),
}


@dataclass(frozen=True)
class HostKeyJail:

    directory: str
    known_hosts: str
    alias: str

    @classmethod
    def create(cls, tag: str) -> "HostKeyJail":
        directory = tempfile.mkdtemp(prefix="carnivore-add-")
        known = os.path.join(directory, "known_hosts")
        with open(known, "w", encoding="ascii"):
            pass
        return cls(directory, known, f"carnivore-add-{tag}")

    def options(self, strict: str) -> Tuple[Tuple[str, str], ...]:
        return (("UserKnownHostsFile", self.known_hosts), ("GlobalKnownHostsFile", "/dev/null"), ("HostKeyAlias", self.alias),
                ("StrictHostKeyChecking", strict))

    def remove(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


async def resolve_lookup(dest: ssh_exec.SshDestination) -> Tuple[str, List[str]]:
    """How ssh itself will look the host up: ``(known_hosts name, [known_hosts files])`` from ``ssh -G`` (as ``pair_driver.host_key_pinned``).

    The name is ``HostKeyAlias`` when set, else ``HostName``, else ``[HostName]:port`` for a port other than 22. ("", []) when ssh could not answer.
    Example: ``await resolve_lookup(SshDestination("hosta", 2201))`` -> ``("[hosta.local]:2201", ["/Users/a/.ssh/known_hosts"])``.
    """
    res = await ssh_exec.run_process([SSH_BINARY, "-G", *dest.port_args(), "--", dest.target], timeout=10, verb="add_resolve", host=dest.target)
    if not res.ok:
        return "", []
    values = ssh_exec.parse_effective_config(res.stdout_text)
    host, port, alias = values.get("hostname", ""), values.get("port", "22"), values.get("hostkeyalias", "")
    name = alias if alias and alias != "none" else (host if port == "22" else f"[{host}]:{port}")
    files = [os.path.expanduser(f) for key in ("userknownhostsfile", "globalknownhostsfile") for f in values.get(key, "").split() if f != "none"]
    return (name if host else ""), files


async def fingerprints(path: str, name: Optional[str] = None) -> List[Tuple[str, str]]:
    if not os.path.isfile(path):
        return []
    argv = [SSH_KEYGEN, "-l", "-f", path] if name is None else [SSH_KEYGEN, "-F", name, "-l", "-f", path]
    res = await ssh_exec.run_process(argv, timeout=10, verb="add_keygen")
    out: List[Tuple[str, str]] = []
    for line in res.stdout_text.splitlines():
        match = _FP_LINE.search(line)
        if match:
            out.append((match.group(1), match.group(2)))
            continue
        found = _FP_FOUND.match(line)
        if found:
            out.append((found.group(2), found.group(1)))
    return out


def failure_code(res: ssh_exec.ExecResult) -> Optional[str]:
    failure = res.failure
    if failure is None:
        return None
    return "auth_failed" if failure == ssh_exec.FAILURE_AUTH else "unreachable"


async def first_contact(dest: ssh_exec.SshDestination, jail: HostKeyJail) -> Tuple[ssh_exec.ExecResult, Optional[str]]:
    argv = ssh_exec.direct_argv(dest, "true", ssh_binary=SSH_BINARY, pre_options=jail.options("accept-new"))
    res = await ssh_exec.run_process(argv, timeout=25, verb="add_first_contact", host=dest.target)
    found = await fingerprints(jail.known_hosts)
    return res, (found[0][0] if found else None)


async def known_status(dest: ssh_exec.SshDestination, fp: str) -> str:
    name, files = await resolve_lookup(dest)
    if not name:
        return "new"
    found = [pair for path in files for pair in await fingerprints(path, name)]
    if any(f == fp for f, _ in found):
        return "same"
    return "changed" if found else "new"


def parse_probe(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        pattern = _PROBE_VALUES.get(key)
        if sep and pattern is not None and key not in out and pattern.match(value):
            out[key] = value
    return out


def assess(probe: Dict[str, str], *, paired: bool) -> Tuple[Dict[str, Any], List[str]]:
    version = probe.get("installed_version") or None
    status = probe.get("setup_status") or None
    joined = {"true": True, "false": False}.get(probe.get("joined", ""))
    target = {"console_user_ok": probe.get("console_user_ok") == "1", "brew": probe.get("brew") == "1", "installed_version": version,
              "setup_status": status, "joined": joined, "paired_with_us": paired, "installer_ok": probe.get("installer_protocol") == "1"}
    blockers: List[str] = []
    if not ssh_exec.is_posix_shell(probe.get("shell")):
        blockers.append("not_posix_shell")
    if not target["console_user_ok"]:
        blockers.append("no_console_login")
    if not target["brew"] and version is None:
        blockers.append("needs_homebrew")
    if not target["installer_ok"]:
        blockers.append("installer_too_old")
    if joined is True and not paired:
        blockers.append("joined_elsewhere")
    elif status == "complete" and joined is not True and not paired:
        blockers.append("needs_owner")
    return target, blockers


def probe_script(installer_script: Optional[str] = None) -> str:
    if installer_script is None:
        return PROBE_SCRIPT
    head, _, _ = PROBE_SCRIPT.rpartition("printf 'installer_protocol")
    return head + "printf 'installer_protocol=%s\\n' \"$(grep -c '^INSTALLER_PROTOCOL=2$' " + shlex.quote(installer_script) + " 2>/dev/null)\"\n"


async def preview(dest: ssh_exec.SshDestination, *, paired: bool, installer_script: Optional[str] = None) -> Dict[str, Any]:
    jail = HostKeyJail.create(secrets.token_hex(4))
    try:
        res, fp = await first_contact(dest, jail)
        code = failure_code(res)
        reachable = code != "unreachable" and fp is not None
        out: Dict[str, Any] = {"host_key_sha256": fp, "known": "new", "reachable": reachable,
                               "auth_ok": (code is None) if reachable else None, "posix_shell": None, "target": None, "blockers": []}
        if fp is not None:
            out["known"] = await known_status(dest, fp)
        if out["known"] == "changed":
            out["blockers"].append("host_key_changed")
        if not reachable:
            out["blockers"].append("unreachable")
        elif code == "auth_failed":
            out["blockers"].append("auth_failed")
        elif out["known"] != "changed":
            probe = await _probe(dest, jail, installer_script)
            out["posix_shell"] = ssh_exec.is_posix_shell(probe.get("shell"))
            out["target"], more = assess(probe, paired=paired)
            out["blockers"] += more
        log.info("computer_add_preview", known=out["known"], blockers=out["blockers"])
        return out
    finally:
        jail.remove()


async def _probe(dest: ssh_exec.SshDestination, jail: HostKeyJail, installer_script: Optional[str] = None) -> Dict[str, str]:
    argv = ssh_exec.direct_argv(dest, ssh_exec.sh_c(probe_script(installer_script)), ssh_binary=SSH_BINARY, pre_options=jail.options("yes"))
    res = await ssh_exec.run_process(argv, timeout=60, max_output=16384, verb="add_probe", host=dest.target)
    return parse_probe(res.stdout_text) if res.returncode == 0 else {}


_RECENT: Dict[Tuple[str, Optional[int]], Tuple[float, Dict[str, Any]]] = {}
RECENT_S = 600.0


def remember(dest: ssh_exec.SshDestination, doc: Dict[str, Any]) -> None:
    now = time.monotonic()
    for key in [k for k, (at, _) in _RECENT.items() if now - at > RECENT_S]:
        del _RECENT[key]
    _RECENT[(dest.target, dest.port)] = (now, doc)


def recall(target: str, port: Optional[int]) -> Optional[Dict[str, Any]]:
    held = _RECENT.get((target, port))
    return held[1] if held is not None and time.monotonic() - held[0] <= RECENT_S else None
