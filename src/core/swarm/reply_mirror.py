
from __future__ import annotations

import asyncio
import copy
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core import db
from src.core.swarm import body, memory, push, reply_turns, say, store

logger = structlog.get_logger()

EXPIRE_S = 6 * 3600
WAKE_SKEW_S = 5
RETRIES = 3
MAX_TURNS_KEPT = 200
SOURCES = ("owner_chat", "wake_prompt")
MAX_DRAFTS_KEPT = 20
LIVE_STATES = ("awake", "waking")
PANE_DEAD = "pane_dead"

_pending: Set[int] = set()
_tried: Dict[int, Any] = {}
_again: Dict[int, int] = {}
_uuids: Dict[int, str] = {}
_locks: Dict[int, asyncio.Lock] = {}
_inflight: Set[int] = set()
_dead: Set[int] = set()
_tasks: set = set()
_RETRY = object()
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def reset() -> None:
    for held in (_pending, _tried, _again, _uuids, _locks, _inflight, _dead):
        held.clear()


def note_owner_delivery(agent_id: int) -> None:
    _pending.add(agent_id)
    _tried.pop(agent_id, None)


def ledger_path(state_dir: Path, agent_id: int) -> Path:
    return Path(state_dir) / "swarm" / "replies" / f"{agent_id}.json"


def _state_dir() -> Path:
    """The app's state directory (late import: settings reads the environment)."""
    from src.config import settings

    return Path(settings.get_state_dir())


def _load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        logger.warning("swarm_reply_ledger_unreadable", path=str(path), error_type=type(exc).__name__)
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"done": dict(data.get("done") or {}), "turns": list(data.get("turns") or []), "held": dict(data.get("held") or {}),
            "drafts": dict(data.get("drafts") or {})}


def _save(path: Path, ledger: Dict[str, Any], now: datetime) -> None:
    cutoff = (now - timedelta(seconds=2 * EXPIRE_S)).isoformat()
    ledger["done"] = {ref: row for ref, row in ledger["done"].items() if str(row.get("at", "")) >= cutoff}
    ledger["held"] = {ref: texts for ref, texts in ledger["held"].items() if ref not in ledger["done"]}
    ledger["turns"] = ledger["turns"][-MAX_TURNS_KEPT:]
    newest = sorted(ledger["drafts"].items(), key=lambda kv: float(kv[1].get("at") or 0))[-MAX_DRAFTS_KEPT:]
    ledger["drafts"] = dict(newest)
    memory.atomic_write(path, json.dumps(ledger, indent=1) + "\n")


def _parse(stamp: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def open_messages(conn: sqlite3.Connection, agent_id: int, now: datetime) -> List[Tuple[str, datetime, Set[str]]]:
    since = (now - timedelta(seconds=EXPIRE_S)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute("SELECT owner_message_ref, delivered_at, source FROM swarm_deliveries WHERE agent_id = ? AND authority = 'owner' "
                        "AND owner_message_ref IS NOT NULL AND source IN (?, ?) AND delivered_at >= ? ORDER BY id",
                        (agent_id, *SOURCES, since)).fetchall()
    out: Dict[str, Tuple[datetime, Set[str]]] = {}
    for ref, stamp, source in rows:
        at = _parse(stamp) or now
        first, sources = out.get(str(ref), (at, set()))
        out[str(ref)] = (min(first, at), sources | {str(source)})
    return [(ref, at, sources) for ref, (at, sources) in out.items()]


def matcher(ref: str, delivered_at: datetime, sources: Set[str], pointer: str) -> reply_turns.Matcher:
    marker = re.compile(re.escape(f"owner_message_ref={ref}") + r"(?!\d)")
    floor = delivered_at - timedelta(seconds=WAKE_SKEW_S)

    def matches(text: str, at: Optional[datetime]) -> bool:
        if marker.search(text):
            return True
        return "wake_prompt" in sources and bool(pointer) and text.strip() == pointer and at is not None and at >= floor

    return matches


def _locate(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    row = conn.execute("SELECT claude_session_uuid, working_dir FROM sessions WHERE id = ?", (agent.get("session_row_id"),)).fetchone()
    uuid = _uuids.get(agent["id"]) or (row[0] if row else None)
    if not uuid:
        return None
    family = str(agent.get("harness") or "claude")
    if family == "codex":
        from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_in_sessions

        if not _UUID.match(str(uuid)):
            return None

        path = rollout_path_in_sessions(DEFAULT_CODEX_HOME, str(uuid))
        return (path, family) if path else None
    from src.core.session_token_usage.claude_reader import locate_transcript

    found = locate_transcript(str(uuid), working_dir=row[1] if row else None).path
    return (str(found), family) if found else None


def _turns(conn: sqlite3.Connection, agent: Dict[str, Any], refs: List[Tuple[str, datetime, Set[str]]]) -> List[Optional[reply_turns.Turn]]:
    from src.core.swarm import wake_prompt

    located = _locate(conn, agent)
    if located is None:
        return [None] * len(refs)
    pointer = wake_prompt.fresh_message(wake_prompt.desk_file(_state_dir(), agent["id"]))
    out: List[Optional[reply_turns.Turn]] = []
    for ref, at, sources in refs:
        try:
            out.append(reply_turns.find_turn(located[0], located[1], matcher(ref, at, sources, pointer)))
        except OSError as exc:
            logger.warning("swarm_reply_transcript_unreadable", agent_id=agent["id"], error_type=type(exc).__name__)
            out.append(None)
    return out


def _gather(conn: sqlite3.Connection, agent_id: int, now: datetime) -> Optional[Tuple[Dict[str, Any], Path, Dict[str, Any], list, list]]:
    agent = store.get_agent(conn, agent_id)
    if agent is None or agent["torn_down_at"] is not None:
        return None
    path = ledger_path(_state_dir(), agent_id)
    ledger = _load(path)
    refs = [r for r in open_messages(conn, agent_id, now) if r[0] not in ledger["done"]]
    if not refs:
        return None
    return agent, path, ledger, refs, _turns(conn, agent, refs)


def _close(ledger: Dict[str, Any], ref: str, now: datetime, why: str, turn: Optional[str]) -> None:
    ledger["done"][ref] = {"at": now.isoformat(), "why": why, "turn": turn}
    if turn and turn not in ledger["turns"]:
        ledger["turns"].append(turn)
    if why in ("answer", "held_say", "same_turn"):
        ledger["drafts"].pop(ref, None)
    elif ref in ledger["drafts"]:
        ledger["drafts"][ref]["state"] = "stopped"


async def run(agent_id: int) -> bool:
    now = datetime.now(timezone.utc)
    async with _locks.setdefault(agent_id, asyncio.Lock()):
        try:
            found = await body.run_db(lambda c: _gather(c, agent_id, now))
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
            logger.warning("swarm_reply_pass_unreadable", agent_id=agent_id, error_type=type(exc).__name__)
            return False
        if found is None:
            _pending.discard(agent_id)
            return False
        agent, path, ledger, refs, turns = found
        waiting = False
        for (ref, at, _sources), turn in zip(refs, turns):
            if turn is None or not turn.complete:
                if (now - at).total_seconds() <= EXPIRE_S:
                    waiting = waiting or turn is not None
                    continue
                text, why, key = "\n\n".join(ledger["held"].get(ref, [])), "expired", None
            elif turn.key in ledger["turns"]:
                text, why, key = "", "same_turn", turn.key
            else:
                text = turn.text or "\n\n".join(ledger["held"].get(ref, []))
                why, key = ("answer" if turn.text else "held_say" if text else "no_answer"), turn.key
            before = copy.deepcopy(ledger)
            _close(ledger, ref, now, why, key)
            await asyncio.to_thread(_save, path, ledger, now)
            if text.strip():
                try:
                    await say.post_as_agent(agent, text)
                except Exception:
                    ledger.clear()
                    ledger.update(before)
                    await asyncio.to_thread(_save, path, ledger, now)
                    raise
            logger.info("swarm_reply_mirrored", agent_id=agent_id, owner_message_ref=ref, why=why)
        if await _keep_draft(agent, path, ledger, refs, turns, now):
            push.notify_agent_draft(agent_id)
        return waiting


async def _keep_draft(agent: Dict[str, Any], path: Path, ledger: Dict[str, Any], refs: list, turns: list, now: datetime) -> bool:
    stopped = agent["id"] in _dead or agent.get("state") not in LIVE_STATES
    changed = False
    running = next(((ref, turn) for (ref, _at, _sources), turn in zip(refs, turns)
                    if ref not in ledger["done"] and turn is not None and not turn.complete and turn.so_far), None)
    if running is not None:
        ref, turn = running
        text = say.clean_text(turn.so_far or "")
        state = "stopped" if stopped else "writing"
        old = ledger["drafts"].get(ref) or {}
        if text and (old.get("turn"), old.get("text"), old.get("state")) != (turn.key, text, state):
            ledger["drafts"][ref] = {"turn": turn.key, "text": text, "state": state, "at": now.timestamp()}
            changed = True
    if stopped:
        for draft in ledger["drafts"].values():
            if draft.get("state") == "writing":
                draft["state"] = "stopped"
                changed = True
    if changed:
        await asyncio.to_thread(_save, path, ledger, now)
    return changed


def draft_entries(agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    ledger = _load(ledger_path(_state_dir(), agent["id"]))
    live = agent.get("state") in LIVE_STATES and agent.get("torn_down_at") is None
    out = [{"kind": "agent", "id": f"draft:{agent['id']}:{ref}", "at": float(d.get("at") or 0), "text": str(d["text"]),
            "draft": "writing" if live and d.get("state") == "writing" else "stopped"}
           for ref, d in ledger["drafts"].items() if isinstance(d, dict) and d.get("text")]
    return sorted(out, key=lambda e: e["at"])


async def hold_say(agent: Dict[str, Any], text: str) -> bool:
    now = datetime.now(timezone.utc)
    async with _locks.setdefault(agent["id"], asyncio.Lock()):
        try:
            found = await body.run_db(lambda c: _gather(c, agent["id"], now))
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError):
            return False
        if found is None:
            return False
        _agent, path, ledger, refs, turns = found
        for (ref, _at, _sources), turn in reversed(list(zip(refs, turns))):
            if turn is not None and not turn.complete:
                ledger["held"].setdefault(ref, []).append(text)
                await asyncio.to_thread(_save, path, ledger, now)
                _pending.add(agent["id"])
                logger.info("swarm_say_held", agent_id=agent["id"], owner_message_ref=ref)
                return True
        return False


def on_reading(agent_id: int, observation: Any) -> bool:
    if agent_id not in _pending:
        return False
    evidence = getattr(observation, "evidence", None)
    identity = getattr(evidence, "identity", None)
    if isinstance(identity, tuple) and len(identity) >= 5 and identity[4]:
        _uuids[agent_id] = str(identity[4])
    verdict = getattr(observation, "verdict", None)
    (_dead.add if getattr(verdict, "reason", None) == PANE_DEAD else _dead.discard)(agent_id)
    transcript = getattr(evidence, "transcript", None)
    signature = (getattr(verdict, "state", None), getattr(verdict, "reason", None), getattr(transcript, "turn_end_at", None),
                 getattr(transcript, "newest_assistant_at", None) or getattr(transcript, "last_append_at", None))
    last = _tried.get(agent_id)
    if last == signature:
        return False
    if last is not _RETRY:
        _again[agent_id] = RETRIES
    _tried[agent_id] = signature
    return True


def schedule(agent_id: int) -> None:
    if agent_id in _inflight:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def guarded() -> None:
        try:
            if await run(agent_id) and _again.get(agent_id, 0) > 0:
                _again[agent_id] -= 1
                _tried[agent_id] = _RETRY
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_reply_pass_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:300])
            _tried.pop(agent_id, None)
        finally:
            _inflight.discard(agent_id)

    _inflight.add(agent_id)
    task = loop.create_task(guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def boot() -> int:
    since = (datetime.now(timezone.utc) - timedelta(seconds=EXPIRE_S)).strftime("%Y-%m-%dT%H:%M:%S")

    def read(conn: sqlite3.Connection) -> List[int]:
        return [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT d.agent_id FROM swarm_deliveries d JOIN swarm_agents a ON a.id = d.agent_id WHERE d.authority = 'owner' "
            "AND d.source IN (?, ?) AND d.delivered_at >= ? AND a.torn_down_at IS NULL", (*SOURCES, since)).fetchall()]

    try:
        found = await body.run_db(read)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_reply_boot_unreadable", error_type=type(exc).__name__)
        return 0
    _pending.update(found)
    return len(found)
