
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response

from src.cplugs.reviewboard import drafts, opener, payload_draft, publish, relink, root, rounds, saves, service, ticket, viewer, wire
from src.cplugs.reviewboard import state as board_states
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.requests import CreateBody, DraftBody, OpenBody, PayloadDraftBody, RelinkBody, ResendBody, ReviseBody, RoundBody, SaveBody, TicketBody
from src.cplugs.sdk import OWN_POLICY_HEADER, CplugContext, add_public_get, cplug_context, cplug_router
from src.cplugs.sdk.sandboxed_html import view_headers

router = cplug_router("reviewboard")
Ctx = Depends(cplug_context("reviewboard"))
VIEW_PATH = f"/api/v1{router.prefix}/view"


@router.get("/root")
async def root_check(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Whether the boards folder can be used: the ``boardsRoot`` setting, or the plugin's default folder while it is blank.

    Output: {ok, path, default[, warnings]} or {ok: false, reason, message}; ``default`` is true when the path is the plugin's own default folder.

    ``warnings`` is a list of {code, message} (``no_commits``, ``no_remote``): the folder works, but its checkout cannot restore the boards.
    """
    state = await asyncio.to_thread(root.root_status, ctx.settings_now().get(root.SETTING), root.state_dir_of(ctx.storage.path))
    if not state.ok:
        return {"ok": False, "reason": state.reason, "message": state.message}
    warned = {"warnings": [{"code": w.code, "message": w.message} for w in state.warnings]} if state.warnings else {}
    return {"ok": True, "path": state.path, "default": state.is_default, **warned}


STATE_FILTER = "^(" + "|".join(board_states.STATES) + ")$"


@router.get("/boards")
async def list_boards(task: Optional[int] = Query(None, ge=1), state: Optional[str] = Query(None, pattern=STATE_FILTER),
                      project: Optional[str] = Query(None, min_length=1, max_length=service.MAX_PROJECT_KEY),
                      ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Every board, newest activity first (newest closed first for ``state=closed``).

    Inputs: task (an item id filter); state (one of ``state.STATES``); project (a list key). Output: see the module docstring.
    """
    try:
        return await service.listing(await asyncio.to_thread(wire.board_root, ctx), task, state, project)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.get("/boards/{slug}")
async def get_board(slug: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One board in full. Input: slug. Output: see the module docstring."""
    try:
        return await asyncio.to_thread(service.board, wire.board_root(ctx), slug)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/rescan")
async def rescan(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Read the folder again and tell every open board to do the same. Output: GET /boards's answer."""
    try:
        answer = await service.listing(await asyncio.to_thread(wire.board_root, ctx))
    except BoardError as exc:
        raise wire.http_error(exc) from exc
    ctx.notify(TOPIC)
    return answer


@router.post("/boards")
async def create_board(body: CreateBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Create a board with its first revision and post the card on its task. Output: see the module docstring."""
    try:
        return await publish.create_board(ctx, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/revisions")
async def revise_board(slug: str, body: ReviseBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Append a revision and post the card on the board's task. Inputs: slug. Output: see the module docstring."""
    try:
        return await publish.add_revision(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/revisions/{revision}/ticket")
async def view_ticket(slug: str, revision: str, body: Optional[TicketBody] = None, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """A signed viewer path for one page of one revision. Inputs: slug; revision; body {view?}. Output: {url, expires_in, view}."""
    view = (body or TicketBody()).view
    try:
        sidecar = await asyncio.to_thread(lambda: viewer.load_sidecar(wire.board_root(ctx), slug))
        viewer.find_view(sidecar, revision, view)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
    return {"url": f"{VIEW_PATH}/{ticket.mint(slug, revision, view)}", "expires_in": ticket.TTL_S, "view": view}


@router.post("/boards/{slug}/open")
async def open_board(slug: str, body: Optional[OpenBody] = None, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Open a board on the owner's screen. Inputs: slug; body {revision?}. Output: {page, select} as ``POST /browsers/open`` answers."""
    try:
        return await asyncio.to_thread(lambda: opener.open_board(wire.board_root(ctx), slug, (opened := body or OpenBody()).revision, opened.color, opened.icon))
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.get("/boards/{slug}/draft")
async def get_draft(slug: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Joe's draft of the next round. Input: slug. Output: {draft: {...} | null}."""
    try:
        wire.board_root(ctx)
        return {"draft": await asyncio.to_thread(drafts.read, ctx.storage.path, slug)}
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.put("/boards/{slug}/draft")
async def put_draft(slug: str, body: DraftBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Save the draft (409 when another device changed it first). Inputs: slug; body. Output: {draft}."""
    try:
        wire.board_root(ctx)
        draft = await asyncio.to_thread(drafts.write, ctx.storage.path, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
    ctx.notify(drafts.TOPIC)
    return {"draft": draft}


@router.delete("/boards/{slug}/draft", status_code=204)
async def delete_draft(slug: str, ctx: CplugContext = Ctx) -> Response:
    """Clear the draft. Input: slug. Output: 204."""
    try:
        wire.board_root(ctx)
        removed = await asyncio.to_thread(drafts.clear, ctx.storage.path, slug)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
    if removed:
        ctx.notify(drafts.TOPIC)
    return Response(status_code=204)


@router.post("/boards/{slug}/rounds")
async def send_round(slug: str, body: RoundBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Send Joe's round: write it, post it on the task as his reply. Output: see the module docstring."""
    try:
        return await rounds.send_round(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/saves")
async def save_payload(slug: str, body: SaveBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Save a payload page's state as the next numbered save. Inputs: slug; body. Output: {revision, save, etag}."""
    try:
        return await saves.save_payload(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.put("/boards/{slug}/payload-draft")
async def put_payload_draft(slug: str, body: PayloadDraftBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Autosave a payload page's state as the revision's one draft. Inputs: slug; body. Output: {revision, draft, etag, changed}."""
    try:
        return await payload_draft.save_draft(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/rounds/{round_id}/resend")
async def resend_round(slug: str, round_id: str, body: Optional[ResendBody] = None, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Retry an undelivered round on the board's current task. Inputs: slug; round_id. Output: as the send."""
    try:
        return await rounds.resend(ctx, slug, round_id)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.patch("/boards/{slug}/task")
async def relink_task(slug: str, body: RelinkBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Link the board to another task on this computer. Inputs: slug; body. Output: {task, etag, state}."""
    try:
        return await relink.relink(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


async def view_page(ticket_text: str, ctx: CplugContext = Ctx) -> Response:
    named = ticket.verify(ticket_text)
    if named is None:
        raise HTTPException(status_code=404, detail={"code": "reviewboard_not_found", "detail": "no such page"})
    try:
        data, name = await asyncio.to_thread(lambda: viewer.page(wire.board_root(ctx), *named))
    except BoardError as exc:
        raise wire.http_error(exc) from exc
    return Response(content=data, media_type="text/html; charset=utf-8", headers={**view_headers(name), OWN_POLICY_HEADER: "1"})


add_public_get(router, "reviewboard", "/view/{ticket_text}", view_page,
               "the review board page viewer: an iframe cannot send a bearer, so a signed ticket naming one board revision page is the credential "
               "(reviewboard ticket.verify; bad, tampered or expired answers 404), behind the plugin-enabled gate and its sandbox headers (docs/reviewboard.md)")

from src.cplugs.reviewboard import routes_posted, routes_scratch  # noqa: E402,F401  pylint
from src.cplugs.reviewboard import routes_attachments  # noqa: E402,F401  pylint
from src.cplugs.reviewboard import routes_live  # noqa: E402,F401  pylint
