
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from src.cplugs.reviewboard import document, layout, opener, ports, revisions, service, state, store, wire
from src.cplugs.reviewboard.errors import BoardError, TaskNotFound
from src.cplugs.reviewboard.requests import CreateBody, ReviseBody
from src.cplugs.reviewboard.schema import Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import AgentCaller, CplugContext
from src.cplugs.sdk import task_folders
from src.cplugs.sdk.computer import local_computer

logger = structlog.get_logger()

MAX_REVIEW_SUMMARY = 300
MAX_REVIEW_DESCRIPTION = 4000
Decorate = Callable[[Optional[Sidecar], Dict[str, Any], Dict[str, bytes]], None]


NO_CARD: Dict[str, Any] = {"posted": False, "reason": "no card was asked for"}


def _decorated(built: Tuple[Dict[str, Any], Any], current: Optional[Sidecar], decorate: Optional[Decorate]) -> Tuple[Dict[str, Any], Any]:
    if decorate is None:
        return built
    doc, files = built[0], dict(built[1])
    decorate(current, doc, files)
    return doc, files


def actor(caller: Optional[AgentCaller]) -> Dict[str, Any]:
    by: Dict[str, Any] = {"actor": "claude"}
    if caller is not None and not caller.external and caller.current_session_id:
        by["session"] = caller.current_session_id[:64]
    return by


def _review(sidecar: Sidecar) -> Dict[str, str]:
    rev, title = sidecar.revisions[-1], sidecar.board.title
    line = " ".join(f"{title} {rev.id}: {rev.summary}".split())
    asks = "".join(f"\n- {p.label}" for p in rev.prompts)
    body = f"{rev.summary}\n\nto answer on the board:{asks}" if asks else rev.summary
    return {"summary": line[:MAX_REVIEW_SUMMARY], "description": body[:MAX_REVIEW_DESCRIPTION], "where": f"review board: {title}"}


async def card(caller: Optional[AgentCaller], sidecar: Sidecar, request_review: bool, cross_project: bool) -> Dict[str, Any]:
    task = sidecar.task
    if task is None:
        return {"posted": False, "reason": "the board has no task"}
    here = local_computer()
    if task.computer and here and task.computer != here:
        return {"posted": False, "reason": f"the task is on {task.computer}"}
    try:
        port = ports.get()
        if await port.item_info(task.item_id) is None:
            return {"posted": False, "reason": f"item {task.item_id} no longer exists"}
        rev = sidecar.revisions[-1]
        review = _review(sidecar)
        posted = await port.post_card(caller, task.item_id, text=review["summary"], request_review=request_review, review=review,
                                      card={"slug": sidecar.board.slug, "revision": rev.id, "title": sidecar.board.title, "summary": rev.summary},
                                      cross_project=cross_project)
    except BoardError as exc:
        return {"posted": False, "reason": str(exc)}
    return {"posted": True, **posted}


def answer(root: Path, text: str, tag: str, sidecar: Sidecar, card: Dict[str, Any]) -> Dict[str, Any]:
    folder = layout.board_dir(root, sidecar.board.slug) or root / sidecar.board.slug
    return {"slug": sidecar.board.slug, "revision": sidecar.revisions[-1].id, "etag": tag, "state": state.board_state(sidecar),
            "revision_dir": str(folder), "card": card}


def boards_folder(root: Path, info: Dict[str, Any]) -> Optional[Path]:
    try:
        task_dir = task_folders.ensure_task(root, int(info["item_id"]), str(info.get("list") or ""), info.get("project"), info.get("title"))
        return task_folders.kind_dir(task_dir, task_folders.BOARDS)
    except OSError as exc:
        logger.warning("reviewboard_task_boards_folder_failed", item=info.get("item_id"), error=type(exc).__name__, detail=str(exc)[:200])
        return None


def today_slug(name: str) -> str:
    return f"{datetime.now().astimezone():%Y%m%d}-{name}"


async def guard(root: Path, slug: str, caller: Optional[AgentCaller], cross_project: bool) -> None:
    before = await asyncio.to_thread(service.board, root, slug)
    task = (before.get("sidecar") or {}).get("task") if isinstance(before.get("sidecar"), dict) else None
    if task and task.get("item_id"):
        await ports.get().check_caller(caller, int(task["item_id"]), cross_project)


async def create_board(ctx: CplugContext, body: CreateBody, caller: Optional[AgentCaller] = None, cross_project: bool = False,
                       decorate: Optional[Decorate] = None, *, post_card: bool = True, at: Optional[datetime] = None) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    port = ports.get()
    info = await port.item_info(body.task.item_id)
    if info is None:
        raise TaskNotFound(f"there is no huddle item {body.task.item_id} on this computer")
    await port.check_caller(caller, body.task.item_id, cross_project)
    now = at or revisions.utcnow()
    slug = today_slug(body.slug_name)
    by = actor(caller)
    task = {"item_id": body.task.item_id, "list": info.get("list"), "computer": local_computer(), "github_issue": info.get("github_issue"),
            "title_at_link": (info.get("title") or f"item {body.task.item_id}")[:200], "linked_at": revisions.stamp(now), "history": []}
    text, tag = await asyncio.to_thread(store.create, root, ctx.storage.path, slug,
                                        lambda _none: _decorated(revisions.first_document(body, slug, now, by, task), None, decorate),
                                        lambda: boards_folder(root, info))
    sidecar = document.parse_sidecar(json.loads(text))
    ctx.notify(TOPIC)
    opener.style_board(slug, body.color, body.icon)
    return answer(root, text, tag, sidecar, await card(caller, sidecar, body.request_review, cross_project) if post_card else NO_CARD)


async def add_revision(ctx: CplugContext, slug: str, body: ReviseBody, caller: Optional[AgentCaller] = None, cross_project: bool = False,
                       decorate: Optional[Decorate] = None, *, post_card: bool = True, at: Optional[datetime] = None) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    await guard(root, slug, caller, cross_project)
    now = at or revisions.utcnow()
    by = actor(caller)
    text, tag = await asyncio.to_thread(store.append, root, ctx.storage.path, slug, body.base_etag,
                                        lambda current: _decorated(revisions.next_document(current, body, now, by), current, decorate))
    sidecar = document.parse_sidecar(json.loads(text))
    ctx.notify(TOPIC)
    return answer(root, text, tag, sidecar, await card(caller, sidecar, body.request_review, cross_project) if post_card else NO_CARD)
