
from __future__ import annotations

import ctypes
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple

from src.core.attention.registry_record import format_version
from src.core.sessions.agent_update_warn import warn_once

DEFAULT_INSTALLED_CLAUDE_LINK = os.path.expanduser("~/.local/bin/claude")

CLAUDE_INSTALL_CANDIDATES = (
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

VersionTuple = Tuple[int, int, int]


def _parse_version(name: Optional[str]) -> Optional[VersionTuple]:
    if not name:
        return None
    match = _VERSION_RE.match(name)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def installed_claude_version(
    link_path: str = DEFAULT_INSTALLED_CLAUDE_LINK,
) -> Optional[str]:
    try:
        target = os.path.realpath(link_path)
    except OSError as exc:
        warn_once("agent_update_installed_unreadable", link_path, link=link_path, error=str(exc))
        return None
    target_name = os.path.basename(target)
    newest = _newest_version_in(os.path.dirname(target))
    if newest is not None:
        return newest
    if _parse_version(target_name) is not None:
        return target_name
    warn_once(
        "agent_update_installed_unparseable", link_path,
        link=link_path, target=target,
    )
    return None


_NEWEST_VERSION_CACHE: Dict[str, Tuple[int, Optional[str]]] = {}


def _newest_version_in(directory: str) -> Optional[str]:
    try:
        stamp = os.stat(directory).st_mtime_ns
    except OSError:
        stamp = None
    cached = _NEWEST_VERSION_CACHE.get(directory)
    if stamp is not None and cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        names = os.listdir(directory)
    except OSError as exc:
        _NEWEST_VERSION_CACHE.pop(directory, None)
        warn_once("agent_update_versions_dir_unreadable", directory, directory=directory, error=str(exc))
        return None
    best: Optional[Tuple[VersionTuple, str]] = None
    for name in names:
        parsed = _parse_version(name)
        if parsed is None or not os.path.isfile(os.path.join(directory, name)):
            continue
        if best is None or parsed > best[0]:
            best = (parsed, name)
    newest = best[1] if best else None
    if stamp is not None:
        _NEWEST_VERSION_CACHE[directory] = (stamp, newest)
    return newest


def version_text(version: Optional[Sequence[int]]) -> Optional[str]:
    if version is None or len(version) != 3:
        return None
    return format_version(version)


def _proc_pidpath(pid: int) -> Optional[str]:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError as exc:
        warn_once("agent_update_libproc_unavailable", "libproc", error=str(exc))
        return None
    buf = ctypes.create_string_buffer(4096)
    try:
        length = libproc.proc_pidpath(ctypes.c_int(pid), buf, ctypes.c_uint32(4096))
    except (OSError, ctypes.ArgumentError) as exc:
        warn_once("agent_update_pidpath_failed", str(pid), pid=pid, error=str(exc))
        return None
    if length <= 0:
        return None
    return buf.value.decode("utf-8", errors="replace")


_RUNNING_VERSION_CACHE: Dict[int, str] = {}


def running_claude_version(
    pid: int,
    *,
    path_reader: Callable[[int], Optional[str]] = _proc_pidpath,
) -> Optional[str]:
    path = path_reader(pid)
    name = os.path.basename(path) if path else None
    version = name if _parse_version(name) is not None else None
    if version is not None:
        _RUNNING_VERSION_CACHE[pid] = version
        return version
    if path:
        warn_once("agent_update_running_path_unversioned", path, pid=pid, path=path)
        _RUNNING_VERSION_CACHE.pop(pid, None)
        return None
    return _RUNNING_VERSION_CACHE.get(pid)


def forget_running_version(pid: int) -> None:
    _RUNNING_VERSION_CACHE.pop(pid, None)


@dataclass(frozen=True)
class AgentUpdate:

    running: str
    installed: str
    ready: bool


def agent_update_status(
    *,
    pid: Optional[int],
    registry_version: Optional[str] = None,
    running_reader: Callable[[int], Optional[str]] = running_claude_version,
    installed_reader: Callable[[], Optional[str]] = installed_claude_version,
) -> Optional[AgentUpdate]:
    if pid is None:
        return None
    running = registry_version or running_reader(pid)
    installed = installed_reader()
    if running is None or installed is None:
        warn_once("agent_update_unmeasured", f"{pid}:{running}:{installed}", pid=pid, running=running, installed=installed)
        return None
    running_parsed = _parse_version(running)
    installed_parsed = _parse_version(installed)
    if running_parsed is None or installed_parsed is None:
        return None
    return AgentUpdate(
        running=running,
        installed=installed,
        ready=running_parsed < installed_parsed,
    )
