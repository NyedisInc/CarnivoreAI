
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.argent import store, writeback

logger = structlog.get_logger()

READ_BYTES = 4 * 1024 * 1024
GIT_TIMEOUT = 10.0
MAX_HEAD_COMMITS = 20
MAX_FILES = 50
MAX_SUBJECT = 200
RETAIN_DAYS = 30
MAX_PENDING = 50

SOURCE_TRANSCRIPT, SOURCE_HEAD = "transcript", "head"

_COMMIT_CMD = re.compile(r"(?:^|[\s;&|(])git\s+(?:(?:-C|-c)\s+\S+\s+)*commit(?:\s|$)")
_COMMIT_LINE = re.compile(r"^\[[^\]\n]*?\s([0-9a-f]{7,40})\]", re.MULTILINE)
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_UNIT = "\x1f"


@dataclass(frozen=True)
class Commit:

    sha: str
    subject: str
    files: Tuple[str, ...]
    file_count: int
    sub_agent_id: str
    source: str


@dataclass
class _Call:

    agent_id: str
    cwd: str


_pending: Dict[str, Dict[str, _Call]] = {}
_since: float = 0.0


def is_commit_command(command: str) -> bool:
    return bool(_COMMIT_CMD.search(command or ""))


def _result_text(block: Dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def _epoch(stamp: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def scan_lines(lines: Iterable[bytes], agent_id: str, pending: Dict[str, _Call], since: float = 0.0) -> List[Tuple[str, str, str]]:
    found: List[Tuple[str, str, str]] = []
    for line in lines:
        if b"git" not in line and b"tool_result" not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = (block.get("input") or {}).get("command", "")
                moment = _epoch(record.get("timestamp"))
                if isinstance(command, str) and is_commit_command(command) and (moment is None or moment >= since):
                    pending[str(block.get("id"))] = _Call(agent_id, str(record.get("cwd") or ""))
            elif block.get("type") == "tool_result":
                call = pending.pop(str(block.get("tool_use_id")), None)
                if call is None or block.get("is_error"):
                    continue
                hit = _COMMIT_LINE.search(_result_text(block))
                if hit:
                    found.append((hit.group(1), call.agent_id, call.cwd))
    while len(pending) > MAX_PENDING:
        pending.pop(next(iter(pending)))
    return found


def _git(cwd: str, *args: str) -> Optional[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("argent_commits_git_failed", error_type=type(exc).__name__)
        return None
    return done.stdout if done.returncode == 0 else None


def _parse_show(out: str, sub_agent_id: str, source: str) -> Optional[Commit]:
    head, _, rest = out.partition("\n")
    sha, _, subject = head.partition(_UNIT)
    if not _SHA.match(sha):
        return None
    files = [p for p in rest.split("\n") if p.strip()]
    return Commit(sha, subject[:MAX_SUBJECT], tuple(files[:MAX_FILES]), len(files), sub_agent_id, source)


def show(cwd: str, sha: str, sub_agent_id: str, source: str) -> Optional[Commit]:
    if not _SHA.match(sha) or not os.path.isdir(cwd):
        return None
    out = _git(cwd, "show", "--no-color", "--name-only", f"--format=%H{_UNIT}%s", sha, "--")
    return _parse_show(out, sub_agent_id, source) if out else None


def _inside(cwd: str, root: str) -> bool:
    try:
        return bool(cwd) and os.path.commonpath([os.path.realpath(cwd), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False



def _cursor(conn: sqlite3.Connection, tenant: str, ref: str, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM commit_cursor WHERE tenant_id = ? AND session_ref = ? AND key = ?", (tenant, ref, key)).fetchone()
    return str(row[0]) if row else None


def _set_cursor(conn: sqlite3.Connection, tenant: str, ref: str, key: str, value: str) -> None:
    conn.execute("INSERT INTO commit_cursor (tenant_id, session_ref, key, value) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(tenant_id, session_ref, key) DO UPDATE SET value = excluded.value", (tenant, ref, key, value))


def _record(conn: sqlite3.Connection, tenant: str, ref: str, commit: Commit, now: float) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO commits (tenant_id, session_ref, sha, sub_agent_id, source, subject, files, file_count, detected_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (tenant, ref, commit.sha, commit.sub_agent_id, commit.source, commit.subject,
                                                              json.dumps(list(commit.files)), commit.file_count, now))
    return cur.rowcount > 0


def recorded(tenant: str, ref: str, *, after_seq: int = 0, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(store.open_db(state_dir)) as conn:
        rows = conn.execute("SELECT seq, sha, sub_agent_id, source, subject, files, file_count FROM commits WHERE tenant_id = ? AND session_ref = ? "
                            "AND seq > ? ORDER BY seq", (tenant, ref, after_seq)).fetchall()
    return [{**dict(r), "files": json.loads(r["files"])} for r in rows]



def _read_new(path: Path, offset: Optional[int]) -> Tuple[List[bytes], int]:
    cut = False
    try:
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            start = 0 if offset is None or size < offset else offset
            if size - start > READ_BYTES:
                start, cut = size - READ_BYTES, True
            handle.seek(start)
            data = handle.read(size - start)
    except OSError as exc:
        logger.debug("argent_commits_file_unreadable", error_type=type(exc).__name__)
        return [], offset or 0
    lines = data.split(b"\n")
    tail = lines.pop()
    return (lines[1:] if cut else lines), start + len(data) - len(tail)


def process_turn_end(tenant: str, ref: str, *, working_dir: str, transcript: Optional[Path], state_dir: Optional[Path] = None,
                     since: Optional[float] = None, clock: Callable[[], float] = time.time) -> List[Commit]:
    from src.core.session_token_usage.per_request import _files as conversation_files

    now = float(clock())
    floor = _since if since is None else since
    pending = _pending.setdefault(f"{tenant}/{ref}", {})
    found: List[Tuple[str, str, str]] = []
    offsets: Dict[str, int] = {}
    with closing(store.open_db(state_dir)) as conn:
        if transcript is not None:
            for path, agent_id, _workflow in conversation_files(transcript):
                key = f"offset:{path}"
                have = _cursor(conn, tenant, ref, key)
                lines, end = _read_new(path, int(have) if have is not None else None)
                offsets[key] = end
                found += scan_lines(lines, agent_id, pending, 0.0 if have is not None else floor)
        head_before = _cursor(conn, tenant, ref, "head")
    made: List[Commit] = []
    with closing(store.open_db(state_dir)) as conn:
        for sha, agent_id, cwd in found:
            where = cwd if _inside(cwd, working_dir) else working_dir
            commit = show(where, sha, agent_id, SOURCE_TRANSCRIPT) if where else None
            if commit is None:
                logger.info("argent_commits_sha_unknown_here")
                continue
            if _record(conn, tenant, ref, commit, now):
                made.append(commit)
        head = _git(working_dir, "rev-parse", "HEAD") if working_dir and os.path.isdir(working_dir) else None
        head = (head or "").strip()
        if head and _SHA.match(head):
            if head_before and head_before != head:
                made += _human_commits(conn, tenant, ref, working_dir, head_before, head, now)
            _set_cursor(conn, tenant, ref, "head", head)
        for key, value in offsets.items():
            _set_cursor(conn, tenant, ref, key, str(value))
        conn.execute("DELETE FROM commits WHERE detected_at < ?", (now - RETAIN_DAYS * 86400,))
        conn.commit()
    return made


def _human_commits(conn: sqlite3.Connection, tenant: str, ref: str, cwd: str, old: str, new: str, now: float) -> List[Commit]:
    who = (_git(cwd, "config", "user.email") or "").strip()
    listing = _git(cwd, "log", f"--max-count={MAX_HEAD_COMMITS}", f"--format=%H{_UNIT}%ae", f"{old}..{new}", "--") if who else None
    made: List[Commit] = []
    for entry in (listing or "").splitlines():
        sha, _, email = entry.partition(_UNIT)
        if email.strip().lower() != who.lower() or not _SHA.match(sha):
            continue
        if conn.execute("SELECT 1 FROM commits WHERE tenant_id = ? AND session_ref = ? AND sha = ?", (tenant, ref, sha)).fetchone():
            continue
        commit = show(cwd, sha, "", SOURCE_HEAD)
        if commit is not None and _record(conn, tenant, ref, commit, now):
            made.append(commit)
    return made



class _State:

    unsubscribe: Optional[Callable[[], None]] = None
    loop: Optional["asyncio.AbstractEventLoop"] = None
    busy: set = set()


_state = _State()


async def handle_turn_end(session_id: str) -> List[Commit]:
    from src.core.argent import classifier_auto, fallback_spend, session_ref, work_items
    from src.core.session_token_usage import claude_reader
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    manager = fallback_spend.session_manager()
    if manager is None or session_id in _state.busy:
        return []
    _state.busy.add(session_id)
    try:
        info = await manager.get_session_info(session_id)
        if info is None or info.session is None or not info.tmux_session or str(info.session.id).startswith("remote:"):
            return []
        tenant = await asyncio.to_thread(work_items.current_tenant)
        if not tenant:
            return []
        working_dir = info.session.working_dir or ""
        transcript: Optional[Path] = None
        if (info.agent_family or "claude") == "claude":
            uuid = await asyncio.to_thread(manager.claude_uuid_for_tmux_name, info.tmux_session)
            found = await asyncio.to_thread(claude_reader.locate_transcript, uuid, working_dir=working_dir) if uuid else None
            transcript = found.path if found is not None and found.outcome == CONVERSATION_PRESENT else None
        ref = await asyncio.to_thread(session_ref.ref_for_name, tenant, info.tmux_session)
        made = await asyncio.to_thread(process_turn_end, tenant, ref, working_dir=working_dir, transcript=transcript)
        if made:
            logger.info("argent_commits_detected", count=len(made))
            await asyncio.to_thread(writeback.on_commits, tenant, ref, info.tmux_session, info.label or info.tmux_session, made)
        await classifier_auto.run(info.tmux_session, info.label or info.tmux_session, working_dir, transcript, made)
        return made
    except (OSError, ValueError, sqlite3.Error) as exc:
        logger.warning("argent_commits_turn_end_failed", error_type=type(exc).__name__)
        return []
    finally:
        _state.busy.discard(session_id)


def _on_turn_end(session_id: Optional[str]) -> None:
    if session_id and _state.loop is not None and not _state.loop.is_closed():
        _state.loop.create_task(handle_turn_end(session_id))


def start() -> None:
    global _since
    if _state.unsubscribe is not None:
        return
    from src.plugins.sdk import turn_events

    _since = time.time()
    _state.loop = asyncio.get_running_loop()
    _state.unsubscribe = turn_events.subscribe(_on_turn_end)


def stop() -> None:
    unsubscribe, _state.unsubscribe = _state.unsubscribe, None
    if unsubscribe is not None:
        unsubscribe()
    _state.loop = None
    _pending.clear()


def is_running() -> bool:
    return _state.unsubscribe is not None
