
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from src.api.subagent_listing import _fresh_claude_observation
from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_for
from src.core.attention.evidence import FAMILY_CODEX
from src.core.claude_resume_argv import ProcessRow, list_process_table
from src.core.sessions.agent_update import AgentUpdate, agent_update_status, version_text
from src.core.sessions.codex_update import codex_update_status
from src.models import AgentUpdateInfo, SessionInfo

CODEX_ANSWER_TTL_SECONDS = 30.0

_CODEX_ANSWERS: Dict[Tuple[int, str], Tuple[float, Optional[AgentUpdate]]] = {}


def agent_update_for(
    watcher: Any, info: Any, now: datetime, table: Optional[Sequence[ProcessRow]] = None,
) -> Optional[AgentUpdate]:
    family = getattr(info, "agent_family", None)
    if family == FAMILY_CODEX:
        return _codex_update_for(info, table)
    if family is not None and family != DEFAULT_FAMILY:
        return None
    observation = _fresh_claude_observation(watcher, info, now)
    if observation is None:
        return None
    registry = getattr(observation.evidence, "registry", None)
    if registry is None or not getattr(registry, "known", False):
        return None
    pid = getattr(registry, "pid", None)
    return agent_update_status(pid=pid, registry_version=version_text(getattr(registry, "version", None)))


def _codex_update_for(info: Any, table: Optional[Sequence[ProcessRow]]) -> Optional[AgentUpdate]:
    session = getattr(info, "session", None)
    pane_pid = getattr(session, "pty_pid", None)
    if pane_pid is None:
        return None
    uuid = getattr(info, "claude_session_uuid", None) or ""
    key = (int(pane_pid), uuid)
    cached = _CODEX_ANSWERS.get(key)
    if cached is not None and time.monotonic() - cached[0] < CODEX_ANSWER_TTL_SECONDS:
        return cached[1]
    if table is None:
        return None
    rollout = rollout_path_for(DEFAULT_CODEX_HOME, uuid) if uuid else None
    answer = codex_update_status(pane_pid=int(pane_pid), table=table, rollout_path=rollout)
    _CODEX_ANSWERS[key] = (time.monotonic(), answer)
    return answer


def mark_agent_update(session_manager: Any, infos: Iterable[Any]) -> None:
    watcher = getattr(session_manager, "_attention_watcher", None)
    now = datetime.now(timezone.utc)
    rows = [info for info in infos if isinstance(info, SessionInfo)]
    table = list_process_table() if any(r.agent_family == FAMILY_CODEX for r in rows) else None
    for info in rows:
        update = agent_update_for(watcher, info, now, table)
        info.agent_update = (
            AgentUpdateInfo(running=update.running, installed=update.installed, ready=update.ready)
            if update is not None
            else None
        )
