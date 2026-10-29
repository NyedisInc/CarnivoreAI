
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.swarm.cards.names import CARD_TOOLS, OWNER_ONLY_CARD_TOOLS

logger = structlog.get_logger()

OWNER = "owner"
DATA = "data"
REFUSAL = "refused: this turn came from agent data, not from the owner"
DATA_SAFE = frozenset({"swarm_ask", "swarm_answer", "swarm_pass", "swarm_remember", "swarm_suggest", "swarm_report",
                       "swarm_say", "swarm_conflict"}) | (CARD_TOOLS - OWNER_ONLY_CARD_TOOLS)


@dataclass
class _Turn:

    authority: str
    tmux_name: str
    newest_at: datetime
    opened_at: datetime
    last_busy_at: Optional[datetime] = None
    scan_from: Optional[datetime] = None
    edgeless: bool = False


_lock = threading.Lock()
_turns: Dict[int, _Turn] = {}
_last: Dict[int, tuple] = {}
_last_busy_at: Dict[str, datetime] = {}
_last_done_at: Dict[str, datetime] = {}
_carded: set = set()


def on_delivery(agent_id: int, authority: str, delivered_at: datetime, delivery_id: Optional[int] = None,
                tmux_name: str = "", wake_started_at: Optional[datetime] = None) -> None:
    authority = OWNER if authority == OWNER and tmux_name else DATA
    with _lock:
        prior = _turns.get(agent_id)
        _last[agent_id] = (delivery_id, None if prior is None else replace(prior))
        if prior is None:
            done, busy = _last_done_at.get(tmux_name), _last_busy_at.get(tmux_name)
            if wake_started_at is not None:
                idle, scan_from = busy is None or busy < wake_started_at, wake_started_at
            else:
                idle, scan_from = done is not None and (busy is None or busy < done), done
            edgeless = authority == OWNER and not idle and wake_started_at is None and done is None
            if authority == OWNER and not idle:
                authority = DATA
            _turns[agent_id] = _Turn(authority, tmux_name, delivered_at, delivered_at, scan_from=scan_from, edgeless=edgeless)
            return
        if authority == DATA:
            prior.authority = DATA
        prior.tmux_name = tmux_name or prior.tmux_name
        prior.newest_at = max(prior.newest_at, delivered_at)


def on_discard(delivery_id: int) -> None:
    with _lock:
        for agent_id, (last_id, prior) in list(_last.items()):
            if last_id != delivery_id:
                continue
            if prior is None:
                _turns.pop(agent_id, None)
            else:
                _turns[agent_id] = prior
            del _last[agent_id]


def on_turn_end(agent_id: int, observed_at: datetime) -> bool:
    with _lock:
        turn = _turns.get(agent_id)
        if turn is None or observed_at <= turn.newest_at:
            return False
        if turn.authority == DATA and (turn.last_busy_at is None or turn.last_busy_at <= turn.newest_at):
            return False
        del _turns[agent_id]
        _last.pop(agent_id, None)
        return True


def on_session_idle(session_key: str, observed_at: datetime) -> None:
    name = session_key.rsplit("@", 1)[0]
    with _lock:
        _last_done_at[name] = max(observed_at, _last_done_at.get(name, observed_at))
        ids = [a for a, t in _turns.items() if t.tmux_name == name]
    for agent_id in ids:
        on_turn_end(agent_id, observed_at)


def on_session_busy(session_key: str, observed_at: datetime) -> None:
    name = session_key.rsplit("@", 1)[0]
    with _lock:
        _last_busy_at[name] = max(observed_at, _last_busy_at.get(name, observed_at))
        for turn in _turns.values():
            if turn.tmux_name == name:
                turn.last_busy_at = max(observed_at, turn.last_busy_at or observed_at)


def turn_authority(agent_id: int) -> Optional[str]:
    with _lock:
        turn = _turns.get(agent_id)
        return turn.authority if turn else None


def reset() -> None:
    with _lock:
        _turns.clear()
        _last.clear()
        _last_busy_at.clear()
        _last_done_at.clear()
        _carded.clear()


def _alpha(tmux_name: str) -> Optional[tuple]:
    from src.config import settings

    path = db.db_path_for(settings.get_state_dir())
    if not os.path.exists(path):
        return None
    with closing(db.connect(path, create=False)) as conn:
        row = conn.execute(
            "SELECT a.id, s.claude_session_uuid, s.working_dir, a.thread_key, a.display_name FROM swarm_agents a "
            "JOIN sessions s ON s.id = a.session_row_id WHERE a.rank = 'alpha' AND a.torn_down_at IS NULL AND s.tmux_name = ?",
            (tmux_name,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT a.id, s.claude_session_uuid, s.working_dir, a.thread_key, a.display_name FROM swarm_agents a "
                "JOIN sessions s ON s.working_dir = a.repo_dir WHERE a.rank = 'alpha' AND a.torn_down_at IS NULL "
                "AND a.session_row_id IS NULL AND s.tmux_name = ?", (tmux_name,)).fetchone()
    return None if row is None else (int(row[0]), row[1], row[2], row[3], row[4])


def _peer_text_since(path: Any, opened_at: datetime) -> bool:
    with open(path, "rb") as stream:
        stream.seek(max(0, os.fstat(stream.fileno()).st_size - 1024 * 1024))
        if stream.tell():
            stream.readline()
        for line in stream:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(row, dict) or row.get("type") != "user":
                continue
            origin = row.get("origin")
            if not ((isinstance(origin, dict) and origin.get("kind") == "peer") or row.get("turnOrigin") == "peer"
                    or b"<cross-session-message" in line):
                continue
            try:
                at = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                return True
            if at.tzinfo is None or at > opened_at:
                return True
    return False


def _owner_turn_holds(agent_id: int, claude_uuid: Optional[str], working_dir: Optional[str]) -> bool:
    from src.core.session_transcript_presence import conversation_presence

    with _lock:
        turn = _turns.get(agent_id)
        opened_at = (turn.scan_from or turn.opened_at) if turn else None
    if opened_at is None:
        return False
    try:
        path = conversation_presence(claude_uuid, working_dir=working_dir).path
        if path is None:
            logger.warning("swarm_guard_transcript_unreadable", agent_id=agent_id)
            return False
        if not _peer_text_since(path, opened_at):
            return True
    except OSError as exc:
        logger.warning("swarm_guard_transcript_unreadable", agent_id=agent_id, error_type=type(exc).__name__)
        return False
    with _lock:
        if agent_id in _turns:
            _turns[agent_id].authority = DATA
    logger.warning("swarm_guard_peer_text_in_owner_turn", agent_id=agent_id)
    return False


def _wants_resend_card(agent_id: int) -> bool:
    with _lock:
        turn = _turns.get(agent_id)
        if turn is None or turn.authority != DATA or not turn.edgeless or agent_id in _carded:
            return False
        _carded.add(agent_id)
        return True


async def _post_resend_card(agent_id: int, thread_key: str, display_name: str) -> None:
    from src.cplugs.sdk.swarm import SwarmError
    from src.core.swarm import alerts, push, thread_port

    port = thread_port.get()
    if port is None:
        with _lock:
            _carded.discard(agent_id)
        return
    who = " ".join(str(display_name).lower().split())
    try:
        await port.post_card(thread_key, "info", "resend your last order",
                             f"carnivore restarted while {who} was awake, so your last order to {who} ran read only. "
                             f"send it again after {who}'s next reply.", f"{alerts.ALERT_PREFIX}resend:{agent_id}:{secrets.token_hex(4)}")
        await asyncio.to_thread(push.notify_thread, thread_key)
    except (SwarmError, sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        with _lock:
            _carded.discard(agent_id)
        logger.warning("swarm_guard_resend_card_failed", agent_id=agent_id, error_type=type(exc).__name__)


_CREATOR_BARRED_RANKS = ("company", "alpha")
CREATE_REFUSAL = "refused: a company agent or SysOp never creates anything; ask the agent below you or the owner"


def _creator_barred(tmux_name: str) -> bool:
    from src.config import settings

    path = db.db_path_for(settings.get_state_dir())
    if not os.path.exists(path):
        return False
    marks = ",".join("?" for _ in _CREATOR_BARRED_RANKS)
    with closing(db.connect(path, create=False)) as conn:
        return conn.execute(
            f"SELECT 1 FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
            f"WHERE a.rank IN ({marks}) AND a.torn_down_at IS NULL AND s.tmux_name = ?",
            (*_CREATOR_BARRED_RANKS, tmux_name)).fetchone() is not None


async def create_refusal(caller: Any, name: str) -> Optional[str]:
    from src.core.swarm import definition

    if getattr(caller, "external", False) or f"{definition.MCP_PREFIX}{name}" not in definition.CREATE_TOOLS:
        return None
    try:
        barred = await asyncio.to_thread(_creator_barred, caller.tmux_name)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_create_guard_lookup_failed", tool=name, error_type=type(exc).__name__)
        return CREATE_REFUSAL
    if barred:
        logger.info("swarm_create_refused", tool=name)
        return CREATE_REFUSAL
    return None


async def refusal(caller: Any, name: str) -> Optional[str]:
    from src.core.mcp import tools

    if (why := await create_refusal(caller, name)):
        return why
    if not tools.is_write(name) or name in DATA_SAFE or getattr(caller, "external", False):
        return None
    try:
        alpha = await asyncio.to_thread(_alpha, caller.tmux_name)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_guard_lookup_failed", tool=name, error_type=type(exc).__name__)
        return REFUSAL
    if alpha is None:
        return None
    if turn_authority(alpha[0]) == OWNER and await asyncio.to_thread(_owner_turn_holds, *alpha[:3]):
        return None
    logger.info("swarm_guard_refused", tool=name, agent_id=alpha[0], turn=turn_authority(alpha[0]))
    if _wants_resend_card(alpha[0]):
        await _post_resend_card(alpha[0], alpha[3], alpha[4])
    return REFUSAL
