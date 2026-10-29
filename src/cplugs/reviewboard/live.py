
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.cplugs.reviewboard import document, layout, live_doc, opener, ports, publish, revisions, scratch_files, state, store, viewer, wire
from src.cplugs.reviewboard.errors import BadRequest, BoardError, NotLive, TaskNotFound
from src.cplugs.reviewboard.live_requests import LiveBody, LiveCreateBody, LiveEndBody, MilestoneBody
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import AgentCaller, CplugContext
from src.cplugs.sdk.computer import local_computer

logger = structlog.get_logger()


def _answer(root: Path, tag: str, sidecar: Sidecar, **fields: Any) -> Dict[str, Any]:
    folder = layout.board_dir(root, sidecar.board.slug) or root / sidecar.board.slug
    return {"slug": sidecar.board.slug, "etag": tag, "state": state.board_state(sidecar), "revision_dir": str(folder), **fields}


def _parsed(text: str) -> Sidecar:
    return document.parse_sidecar(json.loads(text))


async def _open_for_owner(root: Path, slug: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(opener.open_board, root, slug)
    except BoardError as exc:
        logger.info("reviewboard_live_open_refused", slug=slug, code=exc.code)
        return {"opened": False, "reason": str(exc)}


async def start_board(ctx: CplugContext, body: LiveCreateBody, caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    port = ports.get()
    info = await port.item_info(body.task.item_id)
    if info is None:
        raise TaskNotFound(f"there is no huddle item {body.task.item_id} on this computer")
    await port.check_caller(caller, body.task.item_id, cross_project)
    now = revisions.utcnow()
    slug = publish.today_slug(body.slug_name)
    by = publish.actor(caller)
    task = {"item_id": body.task.item_id, "list": info.get("list"), "computer": local_computer(), "github_issue": info.get("github_issue"),
            "title_at_link": (info.get("title") or f"item {body.task.item_id}")[:200], "linked_at": revisions.stamp(now), "history": []}
    text, tag = await asyncio.to_thread(store.create, root, ctx.storage.path, slug, lambda _none: live_doc.first_document(body, slug, now, by, task),
                                        lambda: publish.boards_folder(root, info))
    ctx.notify(TOPIC)
    opener.style_board(slug, body.color, body.icon)
    return _answer(root, tag, _parsed(text), live=True, seq=1, started=True, opened=await _open_for_owner(root, slug) if body.open else None)


async def set_draft(ctx: CplugContext, slug: str, body: LiveBody, caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    await publish.guard(root, slug, caller, cross_project)
    now, by = revisions.utcnow(), publish.actor(caller)
    outcome: Dict[str, bool] = {}

    def build(current: Optional[Sidecar]):
        assert current is not None
        if scratch_files.is_scratch(current):
            raise BadRequest("a scratch board is not live; start a review board")
        doc, files, outcome["started"], outcome["changed"] = live_doc.overwrite(current, body, now, by)
        if not outcome["changed"]:
            raise store.NoChange()
        return doc, files

    text, tag = await asyncio.to_thread(store.append, root, ctx.storage.path, slug, None, build)
    if outcome.get("changed"):
        await asyncio.to_thread(store.prune_draft_files, root, ctx.storage.path, slug)
        ctx.notify(TOPIC)
    sidecar = _parsed(text)
    started = bool(outcome.get("started"))
    assert sidecar.live is not None
    return _answer(root, tag, sidecar, live=True, seq=sidecar.live.draft.seq, started=started, changed=bool(outcome.get("changed")),
                   opened=await _open_for_owner(root, slug) if started and body.open else None)


def _draft_pages(folder: Path, current: Sidecar) -> Dict[str, bytes]:
    assert current.live is not None
    pages: Dict[str, bytes] = {}
    for view in current.live.draft.views:
        try:
            data = viewer.read_regular(folder / view.file, MAX_VIEW_BYTES)
        except BoardError as exc:
            raise BadRequest(f"the draft's {view.id} page cannot be read ({exc}); overwrite the draft again") from exc
        if hashlib.sha256(data).hexdigest() != view.sha256:
            raise BadRequest(f"the draft's {view.id} page is not the one recorded; overwrite the draft again")
        pages[view.file] = data
    return pages


async def milestone(ctx: CplugContext, slug: str, body: MilestoneBody, caller: Optional[AgentCaller] = None, cross_project: bool = False,
                    *, post_card: bool = True) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    await publish.guard(root, slug, caller, cross_project)
    now, by = revisions.utcnow(), publish.actor(caller)
    folder = await asyncio.to_thread(store.board_folder, root, slug)
    seen: Dict[str, bool] = {"unchanged": False}

    def build(current: Optional[Sidecar]):
        assert current is not None
        if current.live is None:
            raise NotLive("the board is not running live, so there is no draft to bookmark")
        if live_doc.draft_matches_newest(current):
            seen["unchanged"] = True
            raise store.NoChange()
        return live_doc.milestone(current, _draft_pages(folder, current), body.name, body.summary, now, by)

    text, tag = await asyncio.to_thread(store.append, root, ctx.storage.path, slug, body.base_etag, build)
    sidecar = _parsed(text)
    if not seen["unchanged"]:
        ctx.notify(TOPIC)
    newest = sidecar.revisions[-1] if sidecar.revisions else None
    card = publish.NO_CARD
    if seen["unchanged"]:
        card = {"posted": False, "reason": "nothing changed since the newest revision, so there is nothing new to review"}
    elif post_card and newest is not None:
        card = await publish.card(caller, sidecar, body.request_review, cross_project)
    return _answer(root, tag, sidecar, revision=newest.id if newest else None, milestone=newest.milestone if newest else None,
                   unchanged=seen["unchanged"], card=card)


async def end(ctx: CplugContext, slug: str, body: LiveEndBody, caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    await publish.guard(root, slug, caller, cross_project)
    made: Optional[Dict[str, Any]] = None
    if body.milestone is not None:
        made = await milestone(ctx, slug, MilestoneBody(name=body.milestone, request_review=False), caller, cross_project, post_card=False)

    def build(current: Optional[Sidecar]):
        assert current is not None
        return live_doc.ended(current), {}

    text, tag = await asyncio.to_thread(store.append, root, ctx.storage.path, slug, None, build)
    await asyncio.to_thread(store.prune_draft_files, root, ctx.storage.path, slug)
    ctx.notify(TOPIC)
    sidecar = _parsed(text)
    card = await publish.card(caller, sidecar, body.request_review, cross_project) if sidecar.revisions else publish.NO_CARD
    return _answer(root, tag, sidecar, ended=True, revision=made["revision"] if made and not made["unchanged"] else None,
                   milestone=made["milestone"] if made and not made["unchanged"] else None, revisions=len(sidecar.revisions), card=card)
