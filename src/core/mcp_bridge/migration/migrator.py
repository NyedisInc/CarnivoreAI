
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.account_switch.auto_restart import SessionEvidence
from src.core.conversation_writers import MeasureError, ProcessTable, read_process_table
from src.core.mcp_bridge.migration import detect, idle
from src.core.session_respawn import LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION
from src.core.session_resume_target import CONVERSATION_NONE_RECORDED, CONVERSATION_RESUMED

logger = structlog.get_logger()

BOOT_SETTLE_SECONDS: float = 30.0
PASS_SECONDS: float = 60.0
MAX_ATTEMPTS: int = 3
BACKOFF_SECONDS: float = 300.0
MAX_RESTARTS_PER_PASS: int = 1

STATE_PENDING = "pending"
STATE_RESTARTED = "restarted"
STATE_MIGRATED = "migrated"
STATE_SKIPPED = "skipped"
STATE_GAVE_UP = "gave_up"
OPEN_STATES = frozenset({STATE_PENDING, STATE_RESTARTED})

PASS_RAN = "ran"
PASS_DISABLED = "disabled"
PASS_BRIDGE_MISSING = "bridge_missing"
PASS_PS_FAILED = "ps_failed"

REASON_NO_CONVERSATION = "no_conversation"
REASON_CONVERSATION_UNKNOWN = "conversation_unknown"
REASON_BACKOFF = "backoff"
REASON_ONE_AT_A_TIME = "one_at_a_time"
REASON_RECHECK = "recheck_"

RESPAWN_ERRORS = (ValueError, LookupError, RuntimeError, OSError, HTTPException)


@dataclass
class Entry:

    session_id: str
    tmux_session: str
    state: str = STATE_PENDING
    reason: Optional[str] = None
    transport: Optional[str] = None
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    last_outcome: Optional[str] = None


def _default_enabled() -> bool:
    from src.config import settings

    try:
        mcp = settings.load_auth_config().mcp
    except (ValueError, OSError) as exc:
        logger.warning("mcp_bridge_migration_config_unreadable", error=type(exc).__name__)
        return False
    return bool(mcp.enabled and mcp.bridge_migration)


def _default_bridge_ready() -> bool:
    from src.config.mcp_launch import BRIDGE_SCRIPT

    return BRIDGE_SCRIPT.is_file()


def _registry_pid(observation: Any) -> Optional[int]:
    registry = getattr(getattr(observation, "evidence", None), "registry", None)
    return getattr(registry, "pid", None) if registry is not None and getattr(registry, "known", False) else None


class BridgeMigrator:

    def __init__(self, manager: Any, *, enabled: Callable[[], bool] = _default_enabled,
                 bridge_ready: Callable[[], bool] = _default_bridge_ready,
                 process_table: Callable[[], ProcessTable] = read_process_table,
                 monotonic: Callable[[], float] = time.monotonic, evidence: Any = None) -> None:
        self._manager = manager
        self._enabled = enabled
        self._bridge_ready = bridge_ready
        self._process_table = process_table
        self._monotonic = monotonic
        self._evidence = evidence or SessionEvidence(manager)
        self._lock = asyncio.Lock()
        self._next_at: Dict[str, float] = {}
        self.entries: Dict[str, Entry] = {}
        self.last_pass: Optional[str] = None
        self.last_pass_at: Optional[str] = None
        self.looping = False

    def status(self) -> Dict[str, Any]:
        return {"enabled": self._enabled(), "bridge_ready": self._bridge_ready(), "looping": self.looping,
                "last_pass": self.last_pass, "last_pass_at": self.last_pass_at,
                "sessions": [asdict(e) for e in self.entries.values()]}

    def remaining(self) -> int:
        return sum(1 for e in self.entries.values() if e.state in OPEN_STATES)

    def _observation(self, session_id: str) -> Any:
        watcher = getattr(self._manager, "_attention_watcher", None)
        return watcher.observation_for(session_id) if watcher is not None else None

    async def _transport(self, info: Any, table: ProcessTable) -> Optional[str]:
        return detect.session_transport(table, getattr(info.session, "pty_pid", None),
                                        _registry_pid(self._observation(str(info.session.id))))

    async def _refusal(self, info: Any) -> Optional[str]:
        observation = self._observation(str(info.session.id))
        early = idle.refusal(info, observation, float("inf"))
        if early is not None:
            return early
        return idle.refusal(info, observation, await self._evidence.quiet_seconds(info.tmux_session))

    async def _conversation_refusal(self, name: str) -> Optional[str]:
        socket = self._manager._tmux_socket_name()
        target = await asyncio.to_thread(self._manager._resume_target_for_tmux_name, name, socket)
        if target.outcome == CONVERSATION_RESUMED:
            return None
        return REASON_NO_CONVERSATION if target.outcome == CONVERSATION_NONE_RECORDED else REASON_CONVERSATION_UNKNOWN

    def _observe(self, info: Any, transport: Optional[str]) -> Optional[Entry]:
        name = info.tmux_session
        entry = self.entries.get(name)
        if detect.on_bridge(transport):
            if entry is not None and entry.state != STATE_MIGRATED:
                entry.state, entry.reason, entry.transport = STATE_MIGRATED, None, transport
                logger.info("mcp_bridge_migration_verified", session_id=entry.session_id, tmux_session=name,
                            attempts=entry.attempts)
            return None
        if not detect.needs_bridge(transport):
            return None
        if entry is None:
            entry = self.entries[name] = Entry(session_id=str(info.session.id), tmux_session=name)
        entry.transport = transport
        if entry.state == STATE_GAVE_UP:
            return None
        if entry.attempts >= MAX_ATTEMPTS:
            entry.state, entry.reason = STATE_GAVE_UP, "still_http_after_attempts"
            logger.warning("mcp_bridge_migration_gave_up", session_id=entry.session_id, tmux_session=name,
                           attempts=entry.attempts)
            return None
        entry.state = STATE_PENDING
        return entry

    async def run_pass(self) -> Dict[str, Any]:
        async with self._lock:
            self.last_pass = await self._pass()
            self.last_pass_at = datetime.now(timezone.utc).isoformat()
        return self.status()

    async def _pass(self) -> str:
        if not self._enabled():
            return PASS_DISABLED
        if not self._bridge_ready():
            return PASS_BRIDGE_MISSING
        try:
            table = await asyncio.to_thread(self._process_table)
        except MeasureError as exc:
            logger.warning("mcp_bridge_migration_ps_failed", error=str(exc))
            return PASS_PS_FAILED
        seen: set = set()
        candidates: List[Any] = []
        for info in await self._manager.list_session_infos():
            if idle.scope_refusal(info) is not None:
                continue
            seen.add(info.tmux_session)
            if self._observe(info, await self._transport(info, table)) is not None:
                candidates.append(info)
        for gone in [n for n, e in self.entries.items() if n not in seen and e.state in OPEN_STATES]:
            del self.entries[gone]
        restarts = 0
        for info in candidates:
            entry = self.entries[info.tmux_session]
            if restarts >= MAX_RESTARTS_PER_PASS:
                entry.reason = REASON_ONE_AT_A_TIME
                continue
            if self._monotonic() < self._next_at.get(info.tmux_session, 0.0):
                entry.reason = REASON_BACKOFF
                continue
            entry.reason = await self._refusal(info) or await self._conversation_refusal(info.tmux_session)
            if entry.reason in (REASON_NO_CONVERSATION, REASON_CONVERSATION_UNKNOWN):
                entry.state = STATE_SKIPPED
            if entry.reason is not None:
                continue
            restarts += await self._restart(info, entry)
        return PASS_RAN

    async def _recheck(self, info: Any) -> Optional[str]:
        fresh = await self._manager.get_session_info(str(info.session.id))
        if fresh is None or fresh.tmux_session != info.tmux_session:
            return REASON_RECHECK + "row_changed"
        why = await self._refusal(fresh)
        if why is None:
            try:
                table = await asyncio.to_thread(self._process_table)
            except MeasureError:
                return REASON_RECHECK + "ps_failed"
            why = None if detect.needs_bridge(await self._transport(fresh, table)) else "not_http"
        return None if why is None else REASON_RECHECK + why

    async def _restart(self, info: Any, entry: Entry) -> int:
        name = info.tmux_session
        entry.reason = await self._recheck(info)
        if entry.reason is not None or not self._enabled():
            entry.reason = entry.reason or REASON_RECHECK + "disabled"
            return 0
        entry.attempts += 1
        entry.last_attempt_at = datetime.now(timezone.utc).isoformat()
        self._next_at[name] = self._monotonic() + BACKOFF_SECONDS * (2 ** (entry.attempts - 1))
        result: Any = None
        try:
            result = await self._manager.respawn_session(
                name, live_restart_confirmed=True, require_agent_resume=True,
                live_restart_reason=LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION)
            ok = (isinstance(result, dict) and result.get("ok") is True and result.get("kind") == "agent"
                  and result.get("conversation") == CONVERSATION_RESUMED)
            outcome = "restarted" if ok else f"refused_{result.get('kind') if isinstance(result, dict) else 'none'}"
        except RESPAWN_ERRORS as exc:
            ok, outcome = False, f"error_{type(exc).__name__}"
        entry.state = STATE_RESTARTED if ok else STATE_PENDING
        entry.last_outcome = outcome
        logger.info("mcp_bridge_migration_restart", session_id=entry.session_id, tmux_session=name,
                    reason=LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION, outcome=outcome, attempts=entry.attempts,
                    identity_status=result.get("identity_status") if isinstance(result, dict) else None,
                    killed_live_pane=result.get("killed_live_pane") if isinstance(result, dict) else None)
        return 1

    async def run(self, boot_task: Optional["asyncio.Future[Any]"] = None) -> None:
        self.looping = True
        try:
            if boot_task is not None and not boot_task.done():
                await asyncio.wait({boot_task})
            await asyncio.sleep(BOOT_SETTLE_SECONDS)
            while True:
                await self.run_pass()
                if self.last_pass == PASS_RAN and self.remaining() == 0:
                    logger.info("mcp_bridge_migration_done", migrated=sum(
                        1 for e in self.entries.values() if e.state == STATE_MIGRATED))
                    return
                await asyncio.sleep(PASS_SECONDS)
        finally:
            self.looping = False
