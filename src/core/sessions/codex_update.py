
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Sequence, Tuple

import structlog

from src.core.claude_resume_argv import ProcessRow, find_rows_in_tree
from src.core.codex_process_infer import is_codex_command
from src.core.sessions.agent_update import AgentUpdate, _proc_pidpath
from src.core.sessions.agent_update_warn import warn_once

logger = structlog.get_logger(__name__)

CODEX_INSTALL_CANDIDATES = (
    "~/.local/bin/codex",
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
    "~/.npm-global/bin/codex",
    "~/.bun/bin/codex",
)

VERSION_PROBE_TIMEOUT_SECONDS = 3.0

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?")

_LSTART_FORMAT = "%a %b %d %H:%M:%S %Y"

_PROBE_CACHE: Dict[Tuple[str, int, int], Optional[str]] = {}

SortKey = Tuple


def parse_codex_version(text: Optional[str]) -> Optional[str]:
    match = _VERSION_RE.search(text or "")
    if match is None:
        return None
    return match.group(0)


def version_sort_key(version: str) -> Optional[SortKey]:
    match = _VERSION_RE.fullmatch(version or "")
    if match is None:
        return None
    core = tuple(int(part) for part in match.groups()[:3])
    tag = match.group(4)
    if tag is None:
        return core + (1,)
    ids = tuple((0, int(i), "") if i.isdigit() else (1, 0, i) for i in tag.split("."))
    return core + (0,) + ids


def _run_version(binary: str) -> Optional[str]:
    try:
        done = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=False,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS, close_fds=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warn_once("agent_update_codex_probe_failed", binary, binary=binary, error=str(exc))
        return None
    version = parse_codex_version(done.stdout) if done.returncode == 0 else None
    if version is None:
        warn_once("agent_update_codex_probe_unparseable", binary, binary=binary, returncode=done.returncode)
    return version


def probe_version(binary: str, runner: Callable[[str], Optional[str]] = _run_version) -> Optional[str]:
    try:
        real = os.path.realpath(binary)
        info = os.stat(real)
    except OSError as exc:
        warn_once("agent_update_codex_binary_unreadable", binary, binary=binary, error=str(exc))
        return None
    key = (real, info.st_mtime_ns, info.st_size)
    if key not in _PROBE_CACHE:
        _PROBE_CACHE[key] = runner(binary)
    return _PROBE_CACHE[key]


def find_installed_codex(which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    on_path = which("codex")
    if on_path:
        return on_path
    for candidate in CODEX_INSTALL_CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def installed_codex_version(finder: Callable[[], Optional[str]] = find_installed_codex) -> Optional[str]:
    binary = finder()
    if binary is None:
        warn_once("agent_update_codex_not_installed", "codex")
        return None
    return probe_version(binary)


def process_start_epochs(pids: Sequence[int]) -> Dict[int, float]:
    if not pids:
        return {}
    try:
        done = subprocess.run(
            ["/bin/ps", "-o", "pid=,lstart=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, check=False, timeout=2.0, close_fds=False,
            env={"LC_ALL": "C", "PATH": "/bin:/usr/bin"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warn_once("agent_update_codex_ps_failed", "lstart", error=str(exc))
        return {}
    out: Dict[int, float] = {}
    for line in done.stdout.splitlines():
        head, _, rest = line.strip().partition(" ")
        try:
            out[int(head)] = time.mktime(time.strptime(rest.strip(), _LSTART_FORMAT))
        except ValueError:
            warn_once("agent_update_codex_lstart_unparseable", head, line=line.strip())
    return out


def native_codex_row(pane_pid: int, table: Sequence[ProcessRow]) -> Optional[ProcessRow]:
    rows = find_rows_in_tree(pane_pid, table, is_codex_command)
    native = [r for r in rows if os.path.basename(r.command.split()[0]) == "codex"]
    return native[-1] if native else None


def rollout_cli_version(rollout_path: Optional[str], started_at: float) -> Optional[str]:
    if not rollout_path:
        return None
    try:
        with open(rollout_path, "r", encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        payload = record["payload"]
        written = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        warn_once("agent_update_codex_rollout_unreadable", str(rollout_path), path=str(rollout_path), error=str(exc))
        return None
    if record.get("type") != "session_meta" or written < started_at:
        return None
    return parse_codex_version(str(payload.get("cli_version") or ""))


def running_codex_version(
    row: ProcessRow,
    started_at: Optional[float],
    rollout_path: Optional[str],
    *,
    path_reader: Callable[[int], Optional[str]] = _proc_pidpath,
    prober: Callable[[str], Optional[str]] = probe_version,
) -> Optional[str]:
    if started_at is None:
        warn_once("agent_update_codex_start_unknown", str(row.pid), pid=row.pid)
        return None
    exe = path_reader(row.pid)
    if exe:
        try:
            unchanged = os.stat(exe).st_mtime <= started_at
        except OSError as exc:
            warn_once("agent_update_codex_exe_unreadable", exe, exe=exe, error=str(exc))
            unchanged = False
        if unchanged:
            return prober(exe)
    return rollout_cli_version(rollout_path, started_at)


def codex_update_status(
    *,
    pane_pid: Optional[int],
    table: Optional[Sequence[ProcessRow]],
    rollout_path: Optional[str] = None,
    start_reader: Callable[[Sequence[int]], Dict[int, float]] = process_start_epochs,
    installed_reader: Callable[[], Optional[str]] = installed_codex_version,
    running_reader: Callable[..., Optional[str]] = running_codex_version,
) -> Optional[AgentUpdate]:
    if pane_pid is None or table is None:
        return None
    row = native_codex_row(int(pane_pid), table)
    if row is None:
        warn_once("agent_update_codex_no_native_process", str(pane_pid), pane_pid=pane_pid)
        return None
    running = running_reader(row, start_reader([row.pid]).get(row.pid), rollout_path)
    installed = installed_reader()
    if running is None:
        warn_once("agent_update_codex_running_unproven", str(row.pid), pid=row.pid)
    if running is None or installed is None:
        return None
    running_key, installed_key = version_sort_key(running), version_sort_key(installed)
    if running_key is None or installed_key is None:
        return None
    return AgentUpdate(running=running, installed=installed, ready=running_key < installed_key)
