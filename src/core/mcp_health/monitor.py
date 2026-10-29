
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

import structlog

from src.core.mcp_health import process_match
from src.core.mcp_health.client_log import READER, ClientLogReader, LinkState
from src.core.mcp_health.config_claude import claude_servers, not_started
from src.core.mcp_health.config_codex import codex_servers
from src.core.mcp_health.probe import ProbeTable
from src.core.account_switch.pane_account import read_pane_profile
from src.core.claude_resume_argv import SHARED_TABLE_MAX_AGE_SECONDS
from src.core.conversation_writers import MeasureError, ProcessTable, read_process_table
from src.core.mcp_health.agent_process import FAMILY_CLAUDE, find_agent, lstart_to_datetime
from src.core.mcp_health.servers import REMOTE_TRANSPORTS, TRANSPORT_STDIO, ServerSpec
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS

log = structlog.get_logger()

CYCLE: float = 10.0
CYCLE_TIMEOUT: float = 30.0


@dataclass(frozen=True)
class Target:

    session_id: str
    tmux_name: str
    family: str
    epoch: Optional[int] = None
    pane_pid: Optional[int] = None
    agent_pid: Optional[int] = None
    agent_started_at: Optional[datetime] = None
    agent_cwd: Optional[str] = None
    working_dir: Optional[str] = None


@dataclass(frozen=True)
class Measure:

    specs: Tuple[ServerSpec, ...]
    excluded: FrozenSet[str]
    links: Optional[Dict[str, LinkState]]
    alive: Dict[str, Optional[bool]]
    agent_started_at: Optional[datetime]
    at: datetime

    def signature(self) -> Tuple[Any, ...]:
        links = tuple(sorted((k, v.state, v.reason) for k, v in (self.links or {}).items()))
        return (tuple(s.key for s in self.specs), links, tuple(sorted(self.alive.items())))


def measure_target(
    target: Target, table: ProcessTable, profile: Optional[str], now: datetime, reader: ClientLogReader,
    commands: Optional[Dict[int, str]] = None,
) -> Optional[Measure]:
    pid = target.agent_pid if target.agent_pid in table.rows else find_agent(table, target.pane_pid, target.family)
    if pid is None:
        return None
    proc = table.rows[pid]
    started = target.agent_started_at if pid == target.agent_pid else None
    started = started or lstart_to_datetime(proc.lstart)
    cwd = target.agent_cwd or target.working_dir
    links: Optional[Dict[str, LinkState]] = None
    if target.family == FAMILY_CLAUDE:
        config = claude_servers(proc.command, cwd, profile)
        specs, excluded = config.servers, config.excluded
        if pid == target.agent_pid:
            links = reader.session_links(cwd, target.agent_started_at, now)
            never = not_started(specs, reader.session_servers(cwd, target.agent_started_at))
            specs, excluded = tuple(s for s in specs if s.key not in never), excluded | never
    else:
        specs, excluded = codex_servers(proc.command, cwd, profile), frozenset()
    commands = commands if commands is not None else {p: r.command for p, r in table.rows.items()}
    alive = {s.key: process_match.alive(s, pid, commands, table.children)
             for s in specs if s.transport == TRANSPORT_STDIO}
    return Measure(specs, excluded, links, alive, started, now)


@dataclass
class McpMonitor:

    probes: ProbeTable = field(default_factory=ProbeTable)
    reader: ClientLogReader = field(default_factory=lambda: READER)
    cycle: float = CYCLE
    _targets: Dict[str, Target] = field(default_factory=dict)
    _profiles: Dict[Tuple[str, Optional[int]], Optional[str]] = field(default_factory=dict)
    _measures: Dict[str, Measure] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, targets: Iterable[Target]) -> None:
        fresh = {t.session_id: t for t in targets}
        with self._lock:
            self._targets = fresh
            self._measures = {k: v for k, v in self._measures.items() if k in fresh}

    def measure_for(self, session_id: str) -> Optional[Measure]:
        with self._lock:
            return self._measures.get(session_id)

    def _cycle_sync(self, targets: List[Target], profiles: Dict[Tuple[str, Optional[int]], Optional[str]]) -> bool:
        now = datetime.now(timezone.utc)
        try:
            table = read_process_table(max_age=SHARED_TABLE_MAX_AGE_SECONDS)
        except MeasureError as exc:
            log.warning("mcp_monitor_ps_failed", error=str(exc))
            return False
        measured: Dict[str, Measure] = {}
        commands = {p: r.command for p, r in table.rows.items()}
        for target in targets:
            profile = profiles.get((target.tmux_name, target.epoch))
            found = measure_target(target, table, profile, now, self.reader, commands)
            if found is not None:
                measured[target.session_id] = found
        wanted = {(s.transport, s.url) for m in measured.values() for s in m.specs
                  if s.transport in REMOTE_TRANSPORTS and s.url}
        probe_moved = self.probes.refresh(wanted, now)
        with self._lock:
            before = {k: v.signature() for k, v in self._measures.items()}
            live = set(self._targets)
            self._measures = {k: v for k, v in measured.items() if k in live}
            after = {k: v.signature() for k, v in self._measures.items()}
        return probe_moved or before != after

    async def _profiles_for(self, targets: List[Target], socket: str) -> Dict[Tuple[str, Optional[int]], Optional[str]]:
        missing = [t for t in targets if (t.tmux_name, t.epoch) not in self._profiles]
        for target in missing:
            variable = PROFILE_ENV_VARS.get(target.family)
            if variable is None:
                continue
            profile = await read_pane_profile(socket, target.tmux_name, variable)
            self._profiles[(target.tmux_name, target.epoch)] = profile.value if profile.readable else None
        live = {(t.tmux_name, t.epoch) for t in targets}
        self._profiles = {k: v for k, v in self._profiles.items() if k in live}
        return dict(self._profiles)

    async def run(self, socket: Callable[[], str], wake: Callable[[], None]) -> None:
        while True:
            with self._lock:
                targets = list(self._targets.values())
            if targets:
                try:
                    profiles = await self._profiles_for(targets, socket())
                    moved = await asyncio.wait_for(asyncio.to_thread(self._cycle_sync, targets, profiles), CYCLE_TIMEOUT)
                    if moved:
                        wake()
                except asyncio.TimeoutError:
                    log.warning("mcp_monitor_cycle_timeout", seconds=CYCLE_TIMEOUT)
                except (OSError, RuntimeError) as exc:
                    log.warning("mcp_monitor_cycle_failed", error=type(exc).__name__, detail=str(exc))
            await asyncio.sleep(self.cycle)

    def close(self) -> None:
        self.probes.close()
