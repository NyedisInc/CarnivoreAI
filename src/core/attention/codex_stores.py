"""Read Codex's on-disk stores into the reader's tier facts. IMPURE, fail-soft.

This is the file-touching half of the Codex reader: the sqlite turn record, the
rollout jsonl tail, the writer-lock liveness probe and the primary-conversation
pick. Everything here is READ-ONLY, opens databases ``mode=ro`` and NEVER raises
- a store it cannot read answers the tier's own "absent" sentinel, because a
reader that raises stops a watcher, and a session whose store could not be read
is a session whose status is unknown, never idle.

TWO NAMED TRAPS THIS FILE IS BUILT AGAINST:
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Set

import structlog

from src.core.attention.codex_reader import (
    CODEX_RECORD_ABSENT,
    CODEX_RECORD_BUSY,
    CODEX_RECORD_REST,
    CODEX_TURN_COMPLETED,
    CODEX_TURN_FAILED,
    CODEX_TURN_INTERRUPTED,
    CodexRecordFacts,
    CodexTranscriptFacts,
)
from src.core.attention.registry_pane import descends_from
from src.core.attention.usage_limit import KIND_OTHER, UsageLimit

logger = structlog.get_logger()

PROJECTION_STALE_MARGIN_BYTES: int = 65_536

ROLLOUT_TAIL_BYTES: int = 256 * 1024

MAX_DECISION_LINE_BYTES: int = 64 * 1024

WAIT_AGENT_MAX_AGE_SECONDS: float = 1800.0

_REST_STATUSES = {
    "completed": CODEX_TURN_COMPLETED,
    "interrupted": CODEX_TURN_INTERRUPTED,
    "failed": CODEX_TURN_FAILED,
}

_QUESTION_CALLS = frozenset({"request_user_input", "request_user_input_async"})

_WAIT_CALLS = frozenset({"wait_agent", "wait"})

_TURN_CLOSE_EVENTS = frozenset({"task_complete", "turn_aborted"})




def latest_history_db(codex_home: str) -> Optional[str]:
    matches = glob.glob(os.path.join(codex_home, "thread_history_*.sqlite"))
    if not matches:
        return None
    return sorted(matches)[-1]


def _connect_ro(path) -> Optional[sqlite3.Connection]:
    try:
        db_path = os.fspath(path)
        immutable = os.path.exists(db_path) and not os.path.exists(
            "%s-wal" % db_path
        )
        mode = "immutable=1" if immutable else "mode=ro"
        uri = "file:%s?%s" % (db_path, mode)
        return sqlite3.connect(uri, uri=True, timeout=0.5)
    except sqlite3.Error:
        return None


def read_codex_record(
    db_path,
    thread_uuid: str,
    *,
    lock_live: bool,
    rollout_size: Optional[int] = None,
) -> CodexRecordFacts:
    con = _connect_ro(db_path)
    if con is None:
        return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)
    try:
        cur = con.execute(
            "SELECT status FROM thread_turns WHERE thread_id = ? "
            "ORDER BY rollout_ordinal DESC LIMIT 1",
            (thread_uuid,),
        )
        row = cur.fetchone()
        if row is None:
            return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)
        status = row[0]
        next_offset = None
        try:
            off = con.execute(
                "SELECT next_rollout_byte_offset FROM "
                "thread_history_projection_state WHERE thread_id = ?",
                (thread_uuid,),
            ).fetchone()
            next_offset = off[0] if off is not None else None
        except sqlite3.Error:
            next_offset = None
    except sqlite3.Error as exc:
        logger.debug("codex_record_read_failed", error=str(exc))
        return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)
    finally:
        con.close()
    return codex_record_facts(status, next_offset, lock_live=lock_live,
                              rollout_size=rollout_size)


def codex_record_facts(
    status: Optional[str],
    next_offset: Optional[int],
    *,
    lock_live: bool,
    rollout_size: Optional[int] = None,
) -> CodexRecordFacts:
    if (
        rollout_size is not None
        and next_offset is not None
        and rollout_size - next_offset > PROJECTION_STALE_MARGIN_BYTES
    ):
        return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)

    if status in _REST_STATUSES:
        return CodexRecordFacts(
            verdict=CODEX_RECORD_REST, rest_kind=_REST_STATUSES[status]
        )
    if status == "inProgress":
        if lock_live:
            return CodexRecordFacts(verdict=CODEX_RECORD_BUSY)
        return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)
    return CodexRecordFacts(verdict=CODEX_RECORD_ABSENT)




def _read_tail_lines(path) -> Optional[List[str]]:
    """Read a bounded window from a file's EOF and return its complete lines.

    Description: seeks to at most :data:`ROLLOUT_TAIL_BYTES` before EOF,
      discards the first partial line unless the window began at offset 0,
      and returns the rest. None when the file cannot be opened.
    Inputs: path (str | os.PathLike).
    Output: list[str] | None.
    Example: _read_tail_lines("/x/rollout.jsonl")
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            start = max(0, size - ROLLOUT_TAIL_BYTES)
            fh.seek(start)
            data = fh.read()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if start > 0 and lines:
        lines = lines[1:]
    return [ln for ln in lines if ln.strip()]


def _parse_ts(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def read_codex_transcript(
    rollout_path, *, now: datetime
) -> CodexTranscriptFacts:
    lines = _read_tail_lines(rollout_path)
    if lines is None:
        return CodexTranscriptFacts(
            readable=False, detail="codex rollout could not be read"
        )
    return codex_transcript_facts(lines, now=now)


def _codex_usage_limit(payload: Dict, ts: Optional[datetime]) -> Optional[UsageLimit]:
    error = payload.get("error")
    if not isinstance(error, dict) or error.get("codex_error_info") != "usage_limit_exceeded":
        return None
    message = error.get("message")
    return UsageLimit(KIND_OTHER, None, message.strip() if isinstance(message, str) else "", ts)


def codex_transcript_facts(lines: List[str], *, now: datetime) -> CodexTranscriptFacts:
    open_questions: Set[str] = set()
    open_waits: Dict[str, Optional[datetime]] = {}
    last_append_at: Optional[datetime] = None
    newest_user_prompt_at: Optional[datetime] = None
    limit_hit: Optional[UsageLimit] = None

    for line in lines:
        if len(line.encode("utf-8")) > MAX_DECISION_LINE_BYTES:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        ts = _parse_ts(record.get("timestamp"))
        if ts is not None:
            last_append_at = ts
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        ptype = payload.get("type")
        if (ts is not None and record.get("type") == "event_msg"
                and ptype == "user_message"):
            newest_user_prompt_at = max(newest_user_prompt_at or ts, ts)
        if record.get("type") == "event_msg" and ptype in _TURN_CLOSE_EVENTS:
            open_waits.clear()
            if ptype == "task_complete":
                limit_hit = _codex_usage_limit(payload, ts)
            continue
        if ptype == "function_call":
            name = payload.get("name")
            call_id = payload.get("call_id")
            if not isinstance(call_id, str):
                continue
            if name in _QUESTION_CALLS:
                open_questions.add(call_id)
            elif name in _WAIT_CALLS:
                open_waits[call_id] = ts
        elif ptype == "function_call_output":
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                open_questions.discard(call_id)
                open_waits.pop(call_id, None)

    subagents_waiting = _waits_are_live(open_waits, last_append_at, now)
    return CodexTranscriptFacts(
        question_open=bool(open_questions),
        subagents_waiting=subagents_waiting,
        last_append_at=last_append_at,
        newest_user_prompt_at=newest_user_prompt_at,
        usage_limit=limit_hit,
        readable=True,
        detail=(
            "codex rollout tail: %d open question(s), %s"
            % (
                len(open_questions),
                "sub-agents running" if subagents_waiting else "no live waits",
            )
        ),
    )


def _waits_are_live(
    open_waits: Dict[str, Optional[datetime]],
    last_append_at: Optional[datetime],
    now: datetime,
) -> bool:
    if not open_waits:
        return False
    if last_append_at is None:
        return False
    try:
        age = (now - last_append_at).total_seconds()
    except TypeError:
        return False
    return age <= WAIT_AGENT_MAX_AGE_SECONDS




def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError, ValueError, OverflowError, TypeError):
        return False


def writer_lock_live(
    codex_home: str,
    thread_uuid: str,
    *,
    holder_pids: Optional[Set[int]] = None,
) -> bool:
    lock_path = os.path.join(
        codex_home, "thread-writer-locks", "%s.lock" % thread_uuid
    )
    if not os.path.exists(lock_path):
        return False
    pids = holder_pids if holder_pids is not None else _lsof_holders(lock_path)
    return any(_pid_is_alive(pid) for pid in pids)


def _lsof_holders(lock_path: str) -> Set[int]:
    import subprocess

    try:
        out = subprocess.run(
            ["lsof", "-t", lock_path],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    pids: Set[int] = set()
    for token in out.stdout.split():
        try:
            pids.add(int(token))
        except ValueError:
            continue
    return pids


def pick_primary_conversation(
    threads: List[Dict],
    *,
    pane_current_path: str,
    pane_title: str,
    live_lock_uuids: Set[str],
) -> Optional[str]:
    candidates = [
        t
        for t in threads
        if (t.get("thread_source") == "user")
        and not t.get("archived")
        and t.get("cwd") == pane_current_path
    ]
    if not candidates:
        return None

    held = [t for t in candidates if t.get("id") in live_lock_uuids]
    if len(held) == 1:
        return held[0].get("id")

    pool = held or candidates
    wanted_name = (pane_title or "").split(" | ", 1)[0].strip()
    if wanted_name:
        named = [t for t in pool if (t.get("name") or "").strip() == wanted_name]
        if len(named) == 1:
            return named[0].get("id")

    if len(pool) == 1:
        return pool[0].get("id")
    return None


def latest_state_db(codex_home: str) -> Optional[str]:
    matches = glob.glob(os.path.join(codex_home, "state_*.sqlite"))
    return sorted(matches)[-1] if matches else None


def _read_user_threads_at(codex_home: str, cwd: str) -> List[Dict]:
    state_db = latest_state_db(codex_home)
    if state_db is None:
        return []
    con = _connect_ro(state_db)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, thread_source, cwd, name, archived FROM threads "
            "WHERE thread_source = 'user' AND cwd = ?",
            (cwd,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [
        {
            "id": r[0],
            "thread_source": r[1],
            "cwd": r[2],
            "name": r[3],
            "archived": r[4],
        }
        for r in rows
    ]


def resolve_primary_uuid(
    codex_home: str, *, pane_current_path: str, pane_title: str,
    pane_pid: Optional[int] = None,
    process_parents: Optional[Mapping[int, int]] = None,
) -> Optional[str]:
    """The pane's primary Codex conversation uuid, end to end. NEVER RAISES.

    Description: the glue the listing calls to turn a pane into a
      conversation id: it reads the user ``threads`` rows at the pane's cwd,
      probes each one's writer lock for a LIVE holder (the pick leads with
      the lock, kernel truth), and hands both to
      :func:`pick_primary_conversation`. Returns None - which the caller
      resolves to unknown, never idle - when no user thread matches this
      pane or two remain ambiguous. It writes nothing; the bind is a
      separate step through the one identity writer.
    Inputs:
      codex_home (str): Codex's store root, usually ``~/.codex``.
      pane_current_path (str): the pane's cwd, matched against ``threads.cwd``.
      pane_title (str): the tmux pane title, used only to corroborate a named
        thread; the pick never relies on it.
      pane_pid (int | None): when supplied, require the writer to descend
        from this pane; cwd and title alone cannot authorize a rebind.
      process_parents (mapping | None): measured pid to parent pid snapshot.
    Output: str | None - the primary conversation uuid.
    Example: resolve_primary_uuid("~/.codex", pane_current_path="/p",
      pane_title="") -> "01a0..."
    """
    if not pane_current_path:
        return None
    candidates = _read_user_threads_at(codex_home, pane_current_path)
    if not candidates:
        return None
    if pane_pid is not None:
        descendants = {pid for pid in (process_parents or {})
                       if descends_from(pid, pane_pid, process_parents or {})}
        descendants.add(pane_pid)
        held = _owned_writer_uuids(codex_home, descendants)
        owned = {str(candidate["id"]) for candidate in candidates
                 if candidate.get("id") in held and not candidate.get("archived")}
        return next(iter(owned)) if len(owned) == 1 else None
    live_lock_uuids = {
        str(t["id"])
        for t in candidates
        if t.get("id") and writer_lock_live(codex_home, str(t["id"]))
    }
    return pick_primary_conversation(
        candidates,
        pane_current_path=pane_current_path,
        pane_title=pane_title,
        live_lock_uuids=live_lock_uuids,
    )


def _owned_writer_uuids(codex_home: str, pids: Set[int]) -> Set[str]:
    import subprocess

    if not pids:
        return set()
    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", ",".join(str(pid) for pid in sorted(pids)), "-Fn"],
            capture_output=True, text=True, timeout=1.0, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if len(result.stdout) > 1024 * 1024:
        return set()
    lock_dir = os.path.join(codex_home, "thread-writer-locks") + os.sep
    prefixes = {"n" + lock_dir, "n" + os.path.realpath(lock_dir.rstrip(os.sep)) + os.sep}
    owned = set()
    for line in result.stdout.splitlines():
        if not line.endswith(".lock"):
            continue
        for prefix in prefixes:
            if line.startswith(prefix):
                uuid = line[len(prefix):-len(".lock")]
                if uuid and os.sep not in uuid:
                    owned.add(uuid)
                break
    return owned
