
from __future__ import annotations

import subprocess
from typing import Callable, Dict, Iterable, Mapping, Optional, Tuple

import structlog

from src.core.agent_manifests.engine import cli_name, manifests
from src.core.attention.parent_map import descends_from
from src.core.attention.record_identity import read_lstarts
from src.core.attention.registry_pane import falls_back_to_pane, registry_for_pane
from src.core.attention.registry_record import RegistryRecord
from src.core.attention.registry_index import read_registry_index, registry_for_session
from src.core.session_status import KNOWN_SHELL_COMMANDS

logger = structlog.get_logger()

ForegroundReader = Callable[[int], Optional[Tuple[int, int]]]

ParentsReader = Callable[[], Optional[Mapping[int, int]]]


def read_process_group(pid: int) -> Optional[Tuple[int, int]]:
    from src.core.claude_resume_argv import PS_PATH, PS_TIMEOUT_SECONDS

    try:
        done = subprocess.run(
            [PS_PATH, "-o", "pgid=,tpgid=", "-p", str(int(pid))],
            capture_output=True, timeout=PS_TIMEOUT_SECONDS, check=False, close_fds=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("pane_agent_proof_ps_failed", pid=pid, error=str(exc))
        return None
    if done.returncode != 0:
        return None
    parts = done.stdout.decode("utf-8", "replace").split()
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def read_process_parents() -> Optional[Mapping[int, int]]:
    from src.core.claude_resume_argv import list_process_table

    rows = list_process_table()
    if rows is None:
        return None
    return {row.pid: row.ppid for row in rows}


CommandsReader = Callable[[], Optional[Mapping[int, str]]]

StartsReader = Callable[[Iterable[int]], Optional[Dict[int, str]]]


def read_process_commands() -> Optional[Mapping[int, str]]:
    from src.core.claude_resume_argv import list_process_table

    rows = list_process_table()
    return None if rows is None else {row.pid: row.command for row in rows}


def _profile_agent_block(wanted: str) -> Optional[object]:
    from src.config import settings  # noqa: PLC0415

    for profile in settings.get_launch_profiles():
        pid = profile.get("id") if isinstance(profile, dict) else getattr(profile, "id", None)
        if str(pid or "").lower() == wanted:
            return profile.get("agent") if isinstance(profile, dict) else getattr(profile, "agent", None)
    return None


def _manifest_names(agent_type: Optional[str]) -> frozenset[str]:
    wanted = (agent_type or "").strip().lower()
    if not wanted:
        return frozenset()
    table = {name: m for m in manifests() for name in m.names}
    agent = _profile_agent_block(wanted)
    if agent is not None:
        get = agent.get if isinstance(agent, dict) else lambda key: getattr(agent, key, None)
        process, rules = str(get("process") or "").lower(), str(get("rules") or "").lower()
        manifest = table.get(process) or table.get(rules)
        names = set(manifest.names) if manifest else set()
        if process:
            names.add(process)
        return frozenset(names) - KNOWN_SHELL_COMMANDS
    manifest = table.get(wanted)
    return (frozenset(manifest.names) if manifest else frozenset()) - KNOWN_SHELL_COMMANDS


def _started_at_or_after(pid: int, floor: int, starts: StartsReader) -> bool:
    from src.core.mcp_health.agent_process import lstart_to_datetime

    text = (starts([pid]) or {}).get(pid)
    began = lstart_to_datetime(text) if text else None
    return began is not None and int(began.timestamp()) >= floor


def _known_cli_in_foreground(
    *, agent_type: Optional[str], pane_pid: int, floor: Optional[int], parents: Mapping[int, int],
    commands: CommandsReader, foreground: ForegroundReader, starts: StartsReader,
) -> bool:
    names = _manifest_names(agent_type)
    argv = commands() if names and floor is not None else None
    if not argv:
        return False
    for pid, command in argv.items():
        if cli_name(command) not in names or not descends_from(pid, pane_pid, parents):
            continue
        groups = foreground(pid)
        if groups is not None and groups[1] > 0 and groups[0] == groups[1] \
                and _started_at_or_after(pid, floor, starts):
            return True
    return False


def _registered_record(
    *, index: Mapping[str, RegistryRecord], tmux_name: Optional[str], pane_id: Optional[str],
    pane_pid: int, parents: ParentsReader, session_started_epoch: Optional[int],
    claude_session_uuid: Optional[str],
) -> RegistryRecord:
    record = registry_for_session(
        tmux_name=tmux_name, index=index,
        session_started_epoch=session_started_epoch, claude_session_uuid=claude_session_uuid,
    )
    if falls_back_to_pane(record):
        by_pane = registry_for_pane(
            index=index, pane_id=pane_id, pane_pid=pane_pid, process_parents=parents,
            session_started_epoch=session_started_epoch, claude_session_uuid=claude_session_uuid,
        )
        if by_pane is not None:
            return by_pane
    return record


def registered_agent_in_foreground(
    *,
    tmux_name: Optional[str],
    pane_id: Optional[str],
    pane_pid: Optional[int],
    session_started_epoch: Optional[int] = None,
    claude_session_uuid: Optional[str] = None,
    index: Optional[Mapping[str, RegistryRecord]] = None,
    parents: ParentsReader = read_process_parents,
    foreground: ForegroundReader = read_process_group,
    agent_type: Optional[str] = None,
    commands: CommandsReader = read_process_commands,
    starts: StartsReader = read_lstarts,
) -> bool:
    if pane_pid is None or not tmux_name:
        return False
    table = index if index is not None else read_registry_index()
    snapshot: dict = {}

    def cached_parents() -> Optional[Mapping[int, int]]:
        if "parents" not in snapshot:
            snapshot["parents"] = parents()
        return snapshot["parents"]

    if _claude_in_foreground(
        table=table, tmux_name=tmux_name, pane_id=pane_id, pane_pid=pane_pid, parents=cached_parents,
        floor=session_started_epoch, claude_session_uuid=claude_session_uuid, foreground=foreground,
    ):
        return True
    table_parents = cached_parents()
    return table_parents is not None and _known_cli_in_foreground(
        agent_type=agent_type, pane_pid=pane_pid, floor=session_started_epoch, parents=table_parents,
        commands=commands, foreground=foreground, starts=starts,
    )


def _claude_in_foreground(
    *, table: Mapping[str, RegistryRecord], tmux_name: Optional[str], pane_id: Optional[str], pane_pid: int,
    parents: ParentsReader, floor: Optional[int], claude_session_uuid: Optional[str], foreground: ForegroundReader,
) -> bool:
    record = _registered_record(
        index=table, tmux_name=tmux_name, pane_id=pane_id, pane_pid=pane_pid,
        parents=parents, session_started_epoch=floor,
        claude_session_uuid=claude_session_uuid,
    )
    if not record.known or record.pid is None:
        return False
    table_parents = parents()
    if table_parents is None or not descends_from(record.pid, pane_pid, table_parents):
        return False
    groups = foreground(record.pid)
    if groups is None:
        return False
    pgid, tpgid = groups
    return tpgid > 0 and pgid == tpgid
