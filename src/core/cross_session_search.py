
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from src.core.product_identity import is_owned_session_name
from src.core.tmux_discovery import tmux_argv_prefix

logger = structlog.get_logger()

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 200
MAX_LINES_PER_SESSION = 10000
MAX_BYTES_PER_SESSION = 4 * 1024 * 1024
MAX_MATCHES_PER_SESSION = 20
MAX_TOTAL_MATCHES = 200
MAX_CONCURRENCY = 4
PER_CALL_TIMEOUT_S = 3.0
TOTAL_DEADLINE_S = 8.0
CONTEXT_BEFORE = 60
CONTEXT_AFTER = 80

_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[()*+\-./][ -~]"
    r"|\x1b[@-Z\\-_]"
    r"|[\x00-\x08\x0b-\x1f\x7f]"
)


_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="xsearch")


class QueryRejected(ValueError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SearchTarget:

    session_id: str
    tmux_session: str
    socket: str


@dataclass
class SessionHits:

    session_id: str
    tmux_session: str
    match_count: int = 0
    matches: List[Dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    alternate_screen: bool = False
    error: Optional[str] = None


def normalize_query(raw: Optional[str]) -> str:
    query = (raw or "").strip()
    if len(query) < MIN_QUERY_CHARS:
        raise QueryRejected("too_short", f"type at least {MIN_QUERY_CHARS} characters")
    if len(query) > MAX_QUERY_CHARS:
        raise QueryRejected("too_long", f"at most {MAX_QUERY_CHARS} characters")
    return query


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def collect_targets(session_manager: Any, socket: str) -> List[SearchTarget]:
    targets: List[SearchTarget] = []
    backends = dict(session_manager._registry.backends)
    for session_id, backend in backends.items():
        name = getattr(backend, "tmux_session", None)
        backend_socket = getattr(backend, "socket_name", None)
        if not isinstance(name, str) or not isinstance(backend_socket, str):
            continue
        if backend_socket != socket or not is_owned_session_name(name):
            continue
        if ":" in name or "." in name:
            continue
        targets.append(SearchTarget(session_id, name, backend_socket))
    return targets


def _run(argv: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, check=False, timeout=PER_CALL_TIMEOUT_S
    )


def capture_text(target: SearchTarget, lines: int) -> tuple[str, bool]:
    base = tmux_argv_prefix(target.socket)
    exact = f"={target.tmux_session}:"
    probe = _run(base + ["display-message", "-p", "-t", exact, "#{alternate_on}"])
    if probe.returncode != 0:
        raise RuntimeError("pane not readable")
    alternate = probe.stdout.strip() == b"1"
    cap = _run(base + ["capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", exact])
    if cap.returncode != 0:
        raise RuntimeError("capture failed")
    raw = cap.stdout[-MAX_BYTES_PER_SESSION:]
    return raw.decode("utf-8", errors="replace"), alternate


def _snippet(line: str, start: int, end: int) -> Dict[str, str]:
    lo = max(0, start - CONTEXT_BEFORE)
    hi = min(len(line), end + CONTEXT_AFTER)
    before = line[lo:start].lstrip()
    after = line[end:hi].rstrip()
    if lo > 0:
        before = "..." + before
    if hi < len(line):
        after = after + "..."
    return {"before": before, "match": line[start:end], "after": after}


def find_matches(text: str, query: str, keep: int) -> tuple[int, List[Dict[str, Any]]]:
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    rows = text.split("\n")
    total = 0
    found: List[Dict[str, Any]] = []
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        hits = list(pattern.finditer(row))
        for hit in reversed(hits):
            if len(found) < keep:
                entry = {"line": index, "occurrence_from_end": total}
                entry.update(_snippet(row, hit.start(), hit.end()))
                found.append(entry)
            total += 1
    return total, found


def _search_one(target: SearchTarget, query: str, lines: int) -> SessionHits:
    result = SessionHits(target.session_id, target.tmux_session)
    try:
        text, alternate = capture_text(target, lines)
    except subprocess.TimeoutExpired:
        logger.warning("cross_search_capture_timeout", session_id=target.session_id)
        result.error = "timeout"
        return result
    except (RuntimeError, OSError) as exc:
        logger.warning(
            "cross_search_capture_failed", session_id=target.session_id, error=str(exc)
        )
        result.error = "unreadable"
        return result
    result.alternate_screen = alternate
    total, found = find_matches(strip_ansi(text), query, MAX_MATCHES_PER_SESSION)
    result.match_count = total
    result.matches = found
    result.truncated = total > len(found)
    return result


async def search_targets(
    targets: List[SearchTarget],
    query: str,
    *,
    lines: int = MAX_LINES_PER_SESSION,
    deadline_s: float = TOTAL_DEADLINE_S,
) -> Dict[str, Any]:
    depth = max(1, min(int(lines or MAX_LINES_PER_SESSION), MAX_LINES_PER_SESSION))
    started = time.monotonic()
    loop = asyncio.get_running_loop()
    tasks = {
        asyncio.ensure_future(
            loop.run_in_executor(_EXECUTOR, _search_one, t, query, depth)
        ): t
        for t in targets
    }
    done, pending = (set(), set())
    if tasks:
        done, pending = await asyncio.wait(tasks.keys(), timeout=deadline_s)
    for task in pending:
        task.cancel()

    by_id: Dict[str, SessionHits] = {}
    for task in done:
        hits = task.result()
        by_id[hits.session_id] = hits
    for task in pending:
        target = tasks[task]
        by_id[target.session_id] = SessionHits(
            target.session_id, target.tmux_session, error="timeout"
        )

    sessions: List[Dict[str, Any]] = []
    budget = MAX_TOTAL_MATCHES
    truncated = False
    total = 0
    for target in targets:
        hits = by_id[target.session_id]
        total += hits.match_count
        if hits.match_count == 0 and hits.error is None:
            continue
        kept = hits.matches[:budget]
        budget -= len(kept)
        if len(kept) < len(hits.matches):
            truncated = True
        sessions.append(
            {
                "session_id": hits.session_id,
                "tmux_session": hits.tmux_session,
                "match_count": hits.match_count,
                "matches": kept,
                "truncated": hits.truncated or len(kept) < len(hits.matches),
                "alternate_screen": hits.alternate_screen,
                "error": hits.error,
            }
        )
    timed_out = sum(1 for h in by_id.values() if h.error == "timeout")
    logger.info(
        "cross_search_done",
        searched=len(targets),
        sessions_with_hits=len(sessions),
        total_matches=total,
        timed_out=timed_out,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "query": query,
        "sessions": sessions,
        "searched": len(targets),
        "total_matches": total,
        "truncated": truncated or any(s["truncated"] for s in sessions),
        "timed_out": timed_out,
    }
