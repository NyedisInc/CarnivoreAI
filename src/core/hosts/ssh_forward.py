
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import stat
from typing import List, Tuple

from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import HARDENING_OPTIONS, SSH_BINARY, SshDestination

FORWARD_PATH_MAX = 103
_PATH_RE = re.compile(r"/[A-Za-z0-9._/+-]+")
_REMOTE_REFUSED = "remote port forwarding failed"


class ForwardError(Exception):
    pass


def _path(path: str) -> str:
    if not isinstance(path, str) or _PATH_RE.fullmatch(path) is None or len(path) > FORWARD_PATH_MAX:
        raise ForwardError(f"socket path {str(path)[:64]!r} is not usable in a forward")
    return path


def forward_argv(dest: SshDestination, control_path: str, flag: str, spec: str, *,
                 ssh_binary: str = SSH_BINARY, verb: str = "forward") -> List[str]:
    if verb not in ("forward", "cancel"):
        raise ForwardError(f"mux verb {verb!r} is not used here")
    if flag not in ("-L", "-R"):
        raise ForwardError(f"forward flag {flag!r} is not used here")
    options = tuple((k, "no" if k == "ClearAllForwardings" else v) for k, v in HARDENING_OPTIONS)
    control = (("ControlPath", ssh_exec.validate_control_path(control_path)),)
    return [ssh_binary, *ssh_exec._options(options), *ssh_exec._options(control),
            *dest.port_args(), "-O", verb, flag, spec, "--", dest.target]


async def _exec(dest: SshDestination, control_path: str, command: str, *, ssh_binary: str,
                timeout: float = 10.0) -> ssh_exec.ExecResult:
    return await ssh_exec.run_process(
        ssh_exec.mux_argv(dest, control_path, command, ssh_binary=ssh_binary),
        timeout=timeout, verb="forward-exec", host=dest.target)


async def _add(dest: SshDestination, control_path: str, flag: str, spec: str, *, ssh_binary: str
               ) -> ssh_exec.ExecResult:
    result = await ssh_exec.run_process(
        forward_argv(dest, control_path, flag, spec, ssh_binary=ssh_binary),
        timeout=10.0, verb="forward", host=dest.target)
    if result.ok:
        return result
    if _REMOTE_REFUSED in result.stderr_text:
        raise ForwardError("the far side refused the socket path (it already exists)")
    raise ForwardError(f"ssh -O forward failed: {ssh_exec.first_line(result.stderr_text) or result.returncode}")


async def _add_local(dest: SshDestination, control_path: str, local_path: str, target: str,
                     *, ssh_binary: str) -> str:
    spec = f"{local_path}:{target}"
    await ssh_exec.run_process(forward_argv(dest, control_path, "-L", spec, ssh_binary=ssh_binary, verb="cancel"),
                               timeout=10.0, verb="forward-cancel", host=dest.target)
    with contextlib.suppress(FileNotFoundError):
        if stat.S_ISSOCK(os.lstat(local_path).st_mode):
            os.unlink(local_path)
    await _add(dest, control_path, "-L", spec, ssh_binary=ssh_binary)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_unix_connection(local_path), timeout=3)
    except (OSError, asyncio.TimeoutError) as exc:
        raise ForwardError(f"the -L socket did not accept a connect ({type(exc).__name__})") from None
    writer.close()
    return local_path


async def forward_local(dest: SshDestination, control_path: str, local_path: str, host: str, port: int,
                        *, ssh_binary: str = SSH_BINARY) -> str:
    local_path = _path(local_path)
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,63}", host) or not 1 <= int(port) <= 65535:
        raise ForwardError("the forward target is not usable")
    return await _add_local(dest, control_path, local_path, f"{host}:{int(port)}", ssh_binary=ssh_binary)


async def forward_local_unix(dest: SshDestination, control_path: str, local_path: str, remote_path: str,
                             *, ssh_binary: str = SSH_BINARY) -> str:
    local_path, remote_path = _path(local_path), _path(remote_path)
    return await _add_local(dest, control_path, local_path, remote_path, ssh_binary=ssh_binary)


async def glob_remote(dest: SshDestination, control_path: str, pattern: str,
                      *, ssh_binary: str = SSH_BINARY) -> List[str]:
    if re.fullmatch(r'\$HOME/[A-Za-z0-9._/+*-]+', pattern) is None:
        raise ForwardError("that glob is not usable")
    result = await _exec(dest, control_path, f"ls -1 {pattern} 2>/dev/null", ssh_binary=ssh_binary)
    return [line for line in result.stdout_text.splitlines() if _PATH_RE.fullmatch(line)]


async def forward_remote_unix(dest: SshDestination, control_path: str, remote_path: str, local_path: str,
                              *, ssh_binary: str = SSH_BINARY) -> str:
    remote_path, local_path = _path(remote_path), _path(local_path)
    await _exec(dest, control_path, f"rm -f -- {remote_path}", ssh_binary=ssh_binary)
    await _add(dest, control_path, "-R", f"{remote_path}:{local_path}", ssh_binary=ssh_binary)
    seen = await _exec(dest, control_path, f"test -S {remote_path}", ssh_binary=ssh_binary)
    if not seen.ok:
        raise ForwardError("the -R socket did not appear on the far side")
    return remote_path


async def forward_remote_tcp(dest: SshDestination, control_path: str, local_path: str,
                             *, ssh_binary: str = SSH_BINARY) -> int:
    result = await _add(dest, control_path, "-R", f"127.0.0.1:0:{_path(local_path)}", ssh_binary=ssh_binary)
    text = result.stdout_text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ForwardError("ssh did not report the allocated port")
    return int(text)


async def remote_home(dest: SshDestination, control_path: str, *, ssh_binary: str = SSH_BINARY) -> str:
    result = await _exec(dest, control_path, 'printf %s "$HOME"', ssh_binary=ssh_binary)
    home = result.stdout_text.strip()
    if not result.ok or _PATH_RE.fullmatch(home) is None:
        raise ForwardError("the far home directory is not a plain path")
    return home


async def ensure_remote_dir(dest: SshDestination, control_path: str, directory: str,
                            *, ssh_binary: str = SSH_BINARY) -> None:
    directory = _path(directory)
    result = await _exec(dest, control_path, f"mkdir -p -m 700 {directory} && chmod 700 {directory}",
                         ssh_binary=ssh_binary)
    if not result.ok:
        raise ForwardError("the far directory could not be made")
