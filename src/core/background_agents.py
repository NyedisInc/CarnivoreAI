
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

QUERY_TIMEOUT_SECONDS: int = 10

QUERY_OK = "ok"
QUERY_UNAVAILABLE = "unavailable"
QUERY_UNPARSEABLE = "unparseable"

KIND_BACKGROUND = "background"


@dataclass(frozen=True)
class BackgroundAgent:

    session_id: str
    name: Optional[str]
    cwd: Optional[str]
    status: Optional[str]
    state: Optional[str]
    pid: Optional[int]
    started_at_ms: Optional[int]

    @property
    def short_id(self) -> str:
        return self.session_id[:8] if self.session_id else ""


@dataclass(frozen=True)
class AgentsResult:

    agents: List[BackgroundAgent] = field(default_factory=list)
    status: str = QUERY_OK
    detail: Optional[str] = None

    @property
    def measured(self) -> bool:
        return self.status == QUERY_OK


def _parse_agent(raw: Dict[str, Any]) -> Optional[BackgroundAgent]:
    session_id = raw.get("sessionId") or raw.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    pid = raw.get("pid")
    started = raw.get("startedAt")
    return BackgroundAgent(
        session_id=session_id,
        name=raw.get("name"),
        cwd=raw.get("cwd"),
        status=raw.get("status"),
        state=raw.get("state"),
        pid=pid if isinstance(pid, int) else None,
        started_at_ms=started if isinstance(started, int) else None,
    )


def list_background_agents(
    *, cwd: Optional[str] = None, claude_path: Optional[str] = None
) -> AgentsResult:
    """List Claude background sessions. Never raises.

    Description: runs ``claude agents --json`` and keeps only records
      whose ``kind`` is ``background`` - interactive ones are the tmux
      sessions CloudeCode already shows, and listing them twice would be
      worse than not listing them at all.

      Returns a NAMED failure rather than an empty list whenever the
      question could not be answered. See ``AgentsResult.measured``.
    Inputs: cwd (str | None) - restrict to sessions started under this
      path. claude_path (str | None) - resolved binary; looked up when
      omitted.
    Output: AgentsResult.
    Example: list_background_agents(cwd='/x').measured -> True
    """
    if not claude_path:
        try:
            from src.core.server_status import collect_claude_cli

            info = collect_claude_cli() or {}
            claude_path = info.get("path")
        except Exception as exc:  # noqa: BLE001
            return AgentsResult(
                status=QUERY_UNAVAILABLE, detail=f"claude cli lookup failed: {exc}"
            )
    if not claude_path:
        return AgentsResult(
            status=QUERY_UNAVAILABLE, detail="claude cli not found on any known path"
        )

    argv = [claude_path, "agents", "--json"]
    if cwd:
        argv += ["--cwd", cwd]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=QUERY_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return AgentsResult(
            status=QUERY_UNAVAILABLE,
            detail=f"claude agents did not answer within {QUERY_TIMEOUT_SECONDS}s",
        )
    except OSError as exc:
        return AgentsResult(status=QUERY_UNAVAILABLE, detail=str(exc))

    if proc.returncode != 0:
        return AgentsResult(
            status=QUERY_UNAVAILABLE,
            detail=f"claude agents exited {proc.returncode}",
        )
    try:
        parsed = json.loads(proc.stdout or "[]")
    except ValueError as exc:
        return AgentsResult(status=QUERY_UNPARSEABLE, detail=str(exc))
    if not isinstance(parsed, list):
        return AgentsResult(
            status=QUERY_UNPARSEABLE, detail="expected a JSON array"
        )

    agents = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") != KIND_BACKGROUND:
            continue
        agent = _parse_agent(raw)
        if agent is not None:
            agents.append(agent)
    return AgentsResult(agents=agents, status=QUERY_OK)
