
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional, Set

import structlog

from src.core.argent import notices, work_items
from src.core.argent.classifier import normalize
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unauthorized, Unreachable
from src.core.argent.store import open_db
from src.plugins.sdk.cards import CardRefused

logger = structlog.get_logger()

ORIGIN_KIND = "argent"
SYNC_SECONDS = 300.0
MAX_TITLE, MAX_SUMMARY = 120, 200
ACTIVE, BACKLOG, CLOSED = "active", "backlog", "closed"
_BACKLOG_STATUSES = frozenset({"backlog", "backlogged", "icebox", "parked", "deferred", "on_hold"})
_CLOSED_STATUSES = frozenset({"done", "closed", "resolved", "complete", "completed", "cancelled", "canceled", "merged", "wont_fix", "wontfix", "rejected"})

_task: Optional["asyncio.Task[None]"] = None
_wake: Optional[asyncio.Event] = None
_app_state: Any = None


def origin_of(row: Mapping[str, Any]) -> str:
    source = row.get("source") if isinstance(row.get("source"), str) and row.get("source") else "argent"
    return f"{ORIGIN_KIND}:{source}:{row['id']}"


def classify(status: Any) -> str:
    key = "".join(ch if ch.isalnum() else "_" for ch in str(status or "").lower().replace("'", "")).strip("_")
    return BACKLOG if key in _BACKLOG_STATUSES else CLOSED if key in _CLOSED_STATUSES else ACTIVE


def bind(app_state: Any) -> None:
    global _app_state
    _app_state = app_state


async def _pages(client: ArgentClient, path: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(work_items.MAX_PAGES):
        page: Dict[str, Any] = {**params, "limit": work_items.PAGE_LIMIT, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(path, params=page)).body
        rows += [r for r in body.get("items", []) if isinstance(r, dict)] if isinstance(body.get("items"), list) else []
        cursor = body.get("next_cursor") if isinstance(body.get("next_cursor"), str) else None
        if not cursor:
            break
    return rows


async def _unhealthy_sources(client: ArgentClient) -> Set[str]:
    try:
        rows = await _pages(client, "/v1/my/trackers", {})
    except NotFound:
        return set()
    return {str(r.get("type")) for r in rows if r.get("healthy") is False and r.get("type")}


async def _projects() -> Dict[str, Optional[int]]:
    from src.core.swarm import body

    rows = await body.run_db(lambda c: c.execute("SELECT id, display_name FROM projects WHERE archived_at IS NULL").fetchall())
    out: Dict[str, Optional[int]] = {}
    for row in rows:
        name = normalize(str(row["display_name"]))
        out[name] = None if name in out else int(row["id"])
    return out


def _seen(tenant: str) -> Set[str]:
    with closing(open_db()) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (f"cards_synced:{tenant}",)).fetchone()
    try:
        data = json.loads(row[0]) if row else []
    except ValueError:
        data = []
    return {s for s in data if isinstance(s, str)}


def _remember(tenant: str, origins: Set[str]) -> None:
    with closing(open_db()) as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (f"cards_synced:{tenant}", json.dumps(sorted(origins))))
        conn.commit()


async def _make(app_state: Any, ops: Any, row: Mapping[str, Any], project_id: int, *, level: str, parent: Optional[int]) -> Optional[Dict[str, Any]]:
    summary = f"from {row.get('source') or 'argent'}: {row.get('external_key') or row['id']}"[:MAX_SUMMARY]
    args = {"title": (str(row.get("title") or "").strip() or str(row["id"]))[:MAX_TITLE], "summary": summary, "project_id": project_id, "parent": parent, "level": level}
    try:
        return await ops.create(app_state, None, args, by="owner", origin=origin_of(row))
    except CardRefused as exc:
        logger.info("argent_card_create_refused", code=exc.code)
        return None


async def _tracker_wins(app_state: Any, ops: Any, card: Mapping[str, Any], row: Mapping[str, Any], verdict: str) -> bool:
    column = card.get("column")
    if column == "done" or (verdict == BACKLOG and column == "todo"):
        return False
    mid_work = column in ("in_progress", "review")
    word = "backlogged" if verdict == BACKLOG else "closed"
    note = f"the tracker {word} this story ({row.get('source') or 'argent'} {row.get('external_key') or row['id']}). finish your turn and stop; the tracker decides."
    for target in (("todo",) if verdict == BACKLOG else ("done", "todo")):
        try:
            await ops.set_column(app_state, int(card["id"]), {"column": target, "note": note if mid_work else ""}, by="owner")
        except CardRefused as exc:
            logger.info("argent_card_tracker_move_refused", code=exc.code, target=target)
            continue
        if mid_work:
            notices.tracker_wins(str(row["id"]), str(card.get("title") or row.get("title") or ""), word)
        return True
    return False


async def sync_once(app_state: Any = None) -> Dict[str, int]:
    from src.core.swarm.cards import ops, port as card_port

    counts = {"created": 0, "moved": 0, "unmapped": 0, "skipped": 0}
    state = app_state if app_state is not None else _app_state
    if state is None:
        return counts
    try:
        client, tenant = await work_items.client_for_call()
        stories = await _pages(client, "/v1/my/work-items", {"scope": "mine", "kind": "story"})
        unhealthy = await _unhealthy_sources(client)
        live = await card_port.get().cards()
    except (Unauthorized, NotFound, Unreachable, ArgentError, card_port.CardsOff) as exc:
        logger.info("argent_cards_sync_skipped", error_type=type(exc).__name__)
        return counts
    cards = {f"{c['origin']['kind']}:{c['origin']['ref']}": c for c in live if (c.get("origin") or {}).get("kind") == ORIGIN_KIND}
    seen = await asyncio.to_thread(_seen, tenant)
    projects = await _projects()
    before = set(seen)
    for story in stories:
        if not isinstance(story.get("id"), str) or story.get("source") in unhealthy:
            counts["skipped"] += 1
            continue
        verdict, origin = classify(story.get("status")), origin_of(story)
        card = cards.get(origin)
        if card is not None:
            if verdict != ACTIVE and await _tracker_wins(state, ops, card, story, verdict):
                counts["moved"] += 1
            continue
        if verdict != ACTIVE or origin in seen:
            continue
        made = await _carded(state, ops, story, cards, projects, tenant)
        counts["created" if made else "unmapped"] += 1
        if made:
            seen.add(origin)
    if seen != before:
        await asyncio.to_thread(_remember, tenant, seen)
    return counts


async def _carded(app_state: Any, ops: Any, story: Mapping[str, Any], cards: Dict[str, Dict[str, Any]], projects: Mapping[str, Optional[int]], tenant: str) -> bool:
    parent_row = await asyncio.to_thread(work_items.resolve, tenant, str(story.get("parent_id") or ""))
    feature = parent_row if parent_row and parent_row.get("kind") == "feature" else None
    project_row = parent_row
    if feature is not None:
        project_row = await asyncio.to_thread(work_items.resolve, tenant, str(feature.get("parent_id") or ""))
    project_id = projects.get(normalize(str(project_row.get("title") or ""))) if project_row and project_row.get("kind") == "project" else None
    if project_id is None:
        return False
    parent_id: Optional[int] = None
    if feature is not None:
        parent_card = cards.get(origin_of(feature)) or await _make(app_state, ops, feature, project_id, level="feature", parent=None)
        if parent_card is None:
            return False
        cards[origin_of(feature)] = parent_card
        parent_id = int(parent_card["id"])
    made = await _make(app_state, ops, story, project_id, level="task", parent=parent_id)
    if made is not None:
        cards[origin_of(story)] = made
    return made is not None


async def _run() -> None:
    assert _wake is not None
    while True:
        await sync_once()
        try:
            await asyncio.wait_for(_wake.wait(), SYNC_SECONDS)
        except asyncio.TimeoutError:
            pass
        _wake.clear()


def start() -> None:
    global _task, _wake
    if is_running():
        return
    _wake = asyncio.Event()
    _task = asyncio.get_running_loop().create_task(_run())


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def is_running() -> bool:
    return _task is not None and not _task.done()


def poke() -> None:
    if _wake is not None:
        _wake.set()
