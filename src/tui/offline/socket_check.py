
from __future__ import annotations

import ctypes
import ctypes.util
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import structlog

from src.core.product_identity import sockets_to_probe
from src.tui.offline.tmux_cmd import (
    SEP,
    OfflineTmuxError,
    TmuxCommandFailed,
    TmuxNotRunning,
    TmuxTarget,
    list_sessions_argv,
    run_query,
    server_info_argv,
)

logger = structlog.get_logger(__name__)

DEFAULT_TMPDIR = "/tmp"
PARENT_MODE = 0o700
PS_PATH = "/bin/ps"
SOURCE_SERVER = "server"
SOURCE_RESOLVED = "resolved"


class SocketRefused(OfflineTmuxError):

    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{reason}: {path}")
        self.reason = reason
        self.path = path


class TmuxMissing(OfflineTmuxError):
    pass


@dataclass(frozen=True)
class OfflineContext:

    target: TmuxTarget
    binary_source: str


def socket_dirs(env: Mapping[str, str], uid: int) -> list[Path]:
    roots = [DEFAULT_TMPDIR] + ([env["TMUX_TMPDIR"]] if env.get("TMUX_TMPDIR") else [])
    out: list[Path] = []
    for root in roots:
        path = Path(os.path.realpath(root)) / f"tmux-{uid}"
        if path not in out:
            out.append(path)
    return out


def check_socket(socket_path: Path, uid: int) -> None:
    parent = socket_path.parent
    try:
        pst = os.lstat(parent)
        sst = os.lstat(socket_path)
    except FileNotFoundError as err:
        raise SocketRefused("missing", str(err.filename)) from err
    if stat.S_ISLNK(pst.st_mode):
        raise SocketRefused("parent_symlink", str(parent))
    if not stat.S_ISDIR(pst.st_mode):
        raise SocketRefused("parent_not_dir", str(parent))
    if pst.st_uid != uid:
        raise SocketRefused("parent_owner", str(parent))
    if stat.S_IMODE(pst.st_mode) != PARENT_MODE:
        raise SocketRefused("parent_mode", str(parent))
    if stat.S_ISLNK(sst.st_mode):
        raise SocketRefused("socket_symlink", str(socket_path))
    if not stat.S_ISSOCK(sst.st_mode):
        raise SocketRefused("socket_not_socket", str(socket_path))
    if sst.st_uid != uid:
        raise SocketRefused("socket_owner", str(socket_path))


def socket_candidates(configured: Optional[str], env: Mapping[str, str], uid: int) -> list[Path]:
    return [
        directory / name
        for name in sockets_to_probe(configured)
        for directory in socket_dirs(env, uid)
        if os.path.lexists(directory / name)
    ]


def _proc_pidpath(pid: int) -> Optional[str]:
    if sys.platform == "darwin":
        lib_path = ctypes.util.find_library("proc")
        if not lib_path:
            return None
        try:
            lib = ctypes.CDLL(lib_path)
        except OSError:
            return None
        buf = ctypes.create_string_buffer(4096)
        length = lib.proc_pidpath(ctypes.c_int(pid), buf, ctypes.c_uint32(len(buf)))
        return buf.value.decode("utf-8", "replace") if length > 0 else None
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def _ps_field(pid: int, field: str) -> Optional[str]:
    try:
        done = subprocess.run([PS_PATH, "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = done.stdout.strip()
    return text if done.returncode == 0 and text else None


def pid_executable(pid: int) -> Optional[str]:
    path = _proc_pidpath(pid) or _ps_field(pid, "comm")
    if path and os.path.isabs(path) and os.path.basename(path) == "tmux" and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


def pid_uid(pid: int) -> Optional[int]:
    text = _ps_field(pid, "uid")
    return int(text) if text and text.isdigit() else None


def server_binary(
    target: TmuxTarget,
    uid: int,
    *,
    exe_of: Callable[[int], Optional[str]] = pid_executable,
    uid_of: Callable[[int], Optional[int]] = pid_uid,
) -> tuple[str, str]:
    try:
        first = run_query(server_info_argv(target)).strip().splitlines()
        pid_text = first[0].split(SEP, 1)[0] if first else ""
    except TmuxCommandFailed as err:
        logger.info("tui_offline_server_pid_unknown", detail=err.detail)
        return target.binary, SOURCE_RESOLVED
    if not pid_text.isdigit() or uid_of(int(pid_text)) != uid:
        return target.binary, SOURCE_RESOLVED
    exe = exe_of(int(pid_text))
    return (exe, SOURCE_SERVER) if exe else (target.binary, SOURCE_RESOLVED)


def has_sessions(target: TmuxTarget) -> bool:
    return bool(run_query(list_sessions_argv(target)).strip())


def resolve_offline(
    configured: Optional[str],
    env: Mapping[str, str],
    uid: int,
    probe_binary: Optional[str],
    *,
    exe_of: Callable[[int], Optional[str]] = pid_executable,
    uid_of: Callable[[int], Optional[int]] = pid_uid,
) -> OfflineContext:
    if not probe_binary:
        raise TmuxMissing("no tmux binary found")
    candidates: Sequence[Path] = socket_candidates(configured, env, uid)
    if not candidates:
        raise TmuxNotRunning("no tmux socket exists")
    chosen: Optional[TmuxTarget] = None
    live_but_empty: list[TmuxTarget] = []
    for path in candidates:
        check_socket(path, uid)
        target = TmuxTarget(probe_binary, str(path))
        try:
            found = has_sessions(target)
        except TmuxNotRunning:
            continue
        if found:
            chosen = target
            break
        live_but_empty.append(target)
    chosen = chosen or (live_but_empty[0] if live_but_empty else None)
    if chosen is None:
        raise TmuxNotRunning("no tmux server answers on any candidate socket")
    binary, source = server_binary(chosen, uid, exe_of=exe_of, uid_of=uid_of)
    return OfflineContext(TmuxTarget(binary, chosen.socket_path), source)
