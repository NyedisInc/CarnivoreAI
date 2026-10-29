
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.stats.plugin import extract, rollup, usage_revision
from src.core.stats.pricing import PRICE_SOURCE, PRICE_SOURCE_DATE, PRICE_VERSION, RATES_JSON, estimate

logger = structlog.get_logger()

AccountResolver = Callable[[str, str], Optional[str]]
_resolver: Optional[AccountResolver] = None
OPEN_RESPONSES = 4
LIVE_WINDOW_SECONDS = 3600
TRIM_PER_WRITE = 64
_moved_lock = threading.Lock()
_moved = 0


def set_account_resolver(resolver: Optional[AccountResolver]) -> None:
    global _resolver
    _resolver = resolver


def take_moved() -> int:
    global _moved
    with _moved_lock:
        moved, _moved = _moved, 0
    return moved


def _note_moved() -> None:
    global _moved
    with _moved_lock:
        _moved += 1


def _account(provider: str, conversation_id: str) -> Optional[str]:
    if _resolver is None:
        return None
    try:
        return _resolver(provider, conversation_id.split(":", 1)[0])
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("stats_plugin_account_resolve_failed", error_type=type(exc).__name__)
        return None


def _source(conn: sqlite3.Connection, event: C.Appended) -> Tuple[int, Optional[str]]:
    key = extract.path_key(event.path)
    row = conn.execute("SELECT id, account_id FROM dim_source WHERE path_key = ?", (key,)).fetchone()
    if row is not None:
        src, account = row
        if account is None:
            account = _account(event.family, event.conversation_id)
            if account:
                conn.execute("UPDATE dim_source SET account_id = ? WHERE id = ?", (account, src))
                usage_revision.bump(conn)
        return src, account
    if event.file_kind == "subagent":
        conversation, kind, parent = f"{event.conversation_id}:{Path(event.path).stem}", "subagent", event.conversation_id
        subagent_type = extract.sidecar_subagent_type(event.path) if event.family == "claude" else None
    else:
        conversation, kind, parent, subagent_type = event.conversation_id, "session", None, None
    account = _account(event.family, event.conversation_id)
    cur = conn.execute("INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, parent_conversation_id, "
                       "account_id, subagent_type) VALUES (?,?,?,?,?,?,?)",
                       (key, conversation, event.family, kind, parent, account, subagent_type))
    return cur.lastrowid, account


def _spans(conn: sqlite3.Connection) -> List[Tuple[int, Optional[int]]]:
    try:
        return [tuple(r) for r in conn.execute("SELECT start_ts, end_ts FROM stats_disabled_spans")]
    except sqlite3.OperationalError:
        return []


def _disabled(t: int, spans: List[Tuple[int, Optional[int]]]) -> bool:
    return any(start <= t < (end if end is not None else 2 ** 63 - 1) for start, end in spans)


def _priced(model: str, counts: Tuple[int, ...]) -> Tuple[Optional[int], str]:
    cost, version = estimate(model, counts)  # type: ignore[arg-type]
    return cost, version or ""


def _add_response(batch: rollup.Batch, new: extract.Response, old: Optional[extract.Response]) -> None:
    base = old or new
    old_counts = old.counts if old else (0, 0, 0, 0)
    old_extras = old.extras if old else (0,) * len(extract.EXTRAS)
    delta = tuple(a - b for a, b in zip(new.counts, old_counts))
    new_cost, version = _priced(new.model, new.counts)
    old_cost = _priced(new.model, old_counts)[0] if old else 0
    cost = None if new_cost is None else new_cost - (old_cost or 0)
    if any(delta) or old is None:
        batch.add_usage(base.t, new.model, base.project, version, delta, cost, 0 if old else 1)
    for counter, value in zip(extract.EXTRAS, (a - b for a, b in zip(new.extras, old_extras))):
        batch.add_counter(base.t, new.model, base.project, counter, "", value)
    if new.stop != (old.stop if old else None):
        if old and old.stop:
            batch.add_counter(base.t, new.model, base.project, "stop_reasons", old.stop, -1)
        if new.stop:
            batch.add_counter(base.t, new.model, base.project, "stop_reasons", new.stop, 1)


def _note_models(conn: sqlite3.Connection, models: Set[str]) -> None:
    from src.core.stats.events import note_models

    note_models(conn, models)


def _source_meta(conn: sqlite3.Connection, src: int) -> Optional[tuple]:
    row = conn.execute("SELECT first_minute, last_minute, cli_version, branch_hash, subagent_type, parent_conversation_id "
                       "FROM dim_source WHERE id = ?", (src,)).fetchone()
    return tuple(row) if row is not None else None


def _apply_meta(conn: sqlite3.Connection, src: int, first: Optional[int], last: Optional[int],
                meta: Dict[str, Any]) -> bool:
    before = _source_meta(conn, src)
    conn.execute("UPDATE dim_source SET first_minute = CASE WHEN first_minute IS NULL OR ? < first_minute THEN ? "
                 "ELSE first_minute END, last_minute = CASE WHEN last_minute IS NULL OR ? > last_minute THEN ? "
                 "ELSE last_minute END, cli_version = COALESCE(?, cli_version), "
                 "branch_hash = COALESCE(?, branch_hash), subagent_type = COALESCE(subagent_type, ?), "
                 "parent_conversation_id = COALESCE(parent_conversation_id, ?) WHERE id = ?",
                 (first, first, last, last, meta.get("cli_version"), meta.get("branch_hash"),
                  meta.get("subagent_type"), meta.get("parent_conversation_id"), src))
    return _source_meta(conn, src) != before


def appended(conn: sqlite3.Connection, event: C.Appended, now: Optional[float] = None) -> int:
    lines = event.own_lines
    if not lines:
        return 0
    src, _ = _source(conn, event)
    row = conn.execute("SELECT state FROM file_state WHERE src = ?", (src,)).fetchone()
    state: Dict[str, Any] = json.loads(row[0]) if row else {}
    recent = [extract.Response.load(r) for r in state.get("open") or []]
    spans = _spans(conn)
    batch = rollup.Batch(src)
    first = last = None
    meta: Dict[str, Any] = {}
    models: Set[str] = set()
    used = 0
    for line in lines:
        raw = line.parsed.raw
        if not isinstance(raw, dict):
            continue
        if event.family == "codex":
            facts = extract.codex_line(raw, state)
        else:
            facts = extract.claude_line(raw, line.offset, state)
        if facts is None:
            continue
        meta.update({k: v for k, v in facts.meta.items() if v})
        first = facts.t if first is None else min(first, facts.t)
        last = facts.t if last is None else max(last, facts.t)
        if _disabled(facts.t, spans):
            continue
        model = state.get("model", "")
        if facts.response is not None:
            new = facts.response
            old = next((r for r in recent if r.key == new.key), None)
            _add_response(batch, new, old)
            kept = new if old is None else extract.Response(new.key, old.t, new.model, old.project, new.counts,
                                                            new.extras, new.stop)
            recent = [kept] + [r for r in recent if r.key != new.key][:OPEN_RESPONSES - 1]
            models.add(facts.response.model)
            used += 1
        if facts.codex_delta is not None:
            cost, version = _priced(model, facts.codex_delta)
            batch.add_usage(facts.t, model, facts.project, version, facts.codex_delta, cost, 1)
            models.add(model)
            used += 1
        for counter, key, value in facts.counters:
            batch.add_counter(facts.t, model, facts.project, counter, key, value)
            used += 1
    clock = time.time() if now is None else now
    newest = max(last or 0, max((r.t for r in recent), default=0))
    wide = len(recent) > 1 and newest >= clock - LIVE_WINDOW_SECONDS
    if recent:
        state["open"] = [r.dump() for r in (recent if wide else recent[:1])]
    conn.execute("INSERT INTO file_state VALUES (?, ?, ?, ?) ON CONFLICT(src) DO UPDATE SET last_t = excluded.last_t, "
                 "wide = excluded.wide, state = excluded.state",
                 (src, newest, int(wide), json.dumps(state, separators=(",", ":"))))
    trim_idle(conn, clock)
    meta_moved = _apply_meta(conn, src, first, last, meta) if first is not None else False
    if meta_moved and batch.empty:
        usage_revision.bump(conn)
    if not batch.empty:
        rollup.advance_floor(conn, now)
        batch.flush(conn, {})
        _note_models(conn, {m for m in models if m})
        conn.execute("INSERT OR IGNORE INTO price_versions VALUES (?,?,?,?)",
                     (PRICE_VERSION, PRICE_SOURCE, PRICE_SOURCE_DATE, RATES_JSON))
        conn.execute("UPDATE stats_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
        usage_revision.bump(conn)
        _note_moved()
    return used


def trim_idle(conn: sqlite3.Connection, now: float) -> int:
    rows = conn.execute("SELECT src, state FROM file_state WHERE wide = 1 AND last_t < ? LIMIT ?",
                        (int(now - LIVE_WINDOW_SECONDS), TRIM_PER_WRITE)).fetchall()
    for src, text in rows:
        state = json.loads(text)
        state["open"] = (state.get("open") or [])[:1]
        conn.execute("UPDATE file_state SET wide = 0, state = ? WHERE src = ?",
                     (json.dumps(state, separators=(",", ":")), src))
    return len(rows)


def drop_paths(conn: sqlite3.Connection, paths: Tuple[str, ...]) -> int:
    dropped = 0
    for path in paths:
        row = conn.execute("SELECT id FROM dim_source WHERE path_key = ?", (extract.path_key(path),)).fetchone()
        if row is not None:
            rollup.drop_source(conn, row[0])
            dropped += 1
    if dropped:
        conn.execute("UPDATE stats_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
        usage_revision.bump(conn)
        _note_moved()
    return dropped


def on_event(conn: sqlite3.Connection, event: C.Event) -> None:
    if event.name == C.EV_APPENDED:
        appended(conn, event)
    elif event.name in (C.EV_FILE_REWRITTEN, C.EV_TRUNCATED):
        drop_paths(conn, (event.path,))
    elif event.name == C.EV_CONVERSATION_REMOVED:
        drop_paths(conn, event.paths)
