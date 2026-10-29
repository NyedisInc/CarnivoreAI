
from __future__ import annotations

import sqlite3
from typing import Any, Awaitable, List, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from src.api.auth import require_auth
from src.core import db
from src.core.swarm import body
from src.core.swarm.cards import board as card_board, capacity, ops, port as card_port, validate
from src.cplugs.sdk import CplugSchemaError
from src.cplugs.sdk.cards import CardRefused
from src.models.swarm_cards import (CapacityReading, CardBoard, CardColumnMove, CardCreate, CardDeleted, CardFlag, CardQueue, CardGrant, CardGrantPut, CardDone, CardEventWindow, CardEvents, CardValidation, CardMove, CardPause,
                                   CardPauseResult, CardPinRequest, CardRelease, CardRules, CardRulesPatch, CardSendBack, CardSuggestionAction, CardSuggestionView, CardSwap, CardView)

logger = structlog.get_logger()

EVENT_WINDOW_MAX_S = 8 * 86400
EVENT_WINDOW_ROWS = 5000

_STATUS = {"not_a_card": 404, "no_suggestion": 404, "not_allowed": 403, "bad_card": 422, "bad_agent": 422, "bad_rules": 422, "bad_grant": 422, "secret": 422}


def _require_port() -> None:
    try:
        card_port.get()
    except card_port.CardsOff as exc:
        raise HTTPException(status_code=409, detail={"code": "cards_off", "message": str(exc)}) from exc


def _refuse(exc: CardRefused) -> NoReturn:
    raise HTTPException(status_code=_STATUS.get(exc.code, 409), detail={"code": exc.code, "message": str(exc)}) from exc


def _huddle_unavailable(exc: Exception) -> NoReturn:
    logger.warning("swarm_cards_huddle_unavailable", error_type=type(exc).__name__, error=str(exc)[:300])
    raise HTTPException(status_code=503, detail={"code": "huddle_unavailable", "message": str(exc)}) from exc


def _unreadable(exc: Exception) -> NoReturn:
    logger.warning("swarm_cards_unreadable", error_type=type(exc).__name__, error=str(exc)[:300])
    raise HTTPException(status_code=503, detail={"code": "datastore_unreadable", "message": "the datastore could not be read"}) from exc


router = APIRouter(prefix="/swarm/cards", tags=["swarm-cards"], dependencies=[Depends(require_auth), Depends(_require_port)])


async def _named(card: dict) -> dict:
    names = await body.run_db(lambda conn: card_board.holder_names(conn, [card["holder"]["agent_id"]] if card.get("holder") else []))
    card_board.name_holders([card], names)
    return card


async def _reading() -> dict:
    return (await body.run_db(capacity.reading)).as_dict()


async def _owner(work: Awaitable[Any]) -> Any:
    try:
        return await work
    except CardRefused as exc:
        _refuse(exc)
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        _huddle_unavailable(exc)
    except db.DatastoreUnreadableError as exc:
        _unreadable(exc)


@router.get("/board", response_model=CardBoard)
async def get_board(scope: str = Query("sysop", pattern=r"^(sysop|project:[1-9][0-9]{0,9}|company:[1-9][0-9]{0,9})$"),
                    filter: str = Query("all", pattern="^(all|mine)$"),
                    done_limit: int = Query(50, ge=1, le=500), archived: str = Query("hide", pattern="^(hide|only|all)$")) -> dict:
    """The board of one scope: lanes (a project's queue, or each project of a company or the install), win number, counts; archived cards only on ``archived=only|all``."""
    try:
        lanes = await card_board.board(scope, filter=filter, done_limit=done_limit, archived=archived)
        try:
            return {**lanes, "capacity": await _reading()}
        except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
            logger.warning("swarm_cards_capacity_unread", error_type=type(exc).__name__)
            return {**lanes, "capacity": None}
    except CplugSchemaError as exc:
        _huddle_unavailable(exc)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        _unreadable(exc)


@router.get("/events", response_model=CardEventWindow)
async def get_event_window(scope: str = Query("sysop", pattern=r"^(sysop|project:[1-9][0-9]{0,9}|company:[1-9][0-9]{0,9})$"),
                           filter: str = Query("all", pattern="^(all|mine)$"),
                           since: float = Query(..., ge=0), until: float = Query(..., gt=0)) -> dict:
    """Every card event of the board's scope in ``[since, until)`` (at most 8 days), oldest first, the newest 5000 kept; 422 ``bad_window``.

    The board's calendar view reads it (``docs/swarm-board.md``); ``filter=mine`` keeps the owner's own cards, as the board does.
    """
    if until <= since or until - since > EVENT_WINDOW_MAX_S:
        raise HTTPException(status_code=422, detail={"code": "bad_window", "message": "until must be after since, at most 8 days later"})
    head = {"scope": scope, "filter": filter, "since": since, "until": until}
    try:
        keys = await body.run_db(lambda conn: card_board.scope_list_keys(conn, scope))
    except CplugSchemaError as exc:
        _huddle_unavailable(exc)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        _unreadable(exc)
    list_keys = [key for _, key in keys]
    if not list_keys:
        return {**head, "events": [], "truncated": False}
    port = card_port.get()
    item_ids = None
    if filter == "mine":
        item_ids = [c["id"] for c in await _owner(port.cards(list_keys=list_keys)) if card_board.is_mine(c)]
    args = {"list_keys": list_keys, "since": since, "until": until, "limit": EVENT_WINDOW_ROWS, "item_ids": item_ids}
    return {**head, **await _owner(port.policy_read("events_window", args))}


@router.post("/", response_model=CardView, status_code=201)
async def create_card(request: Request, req: CardCreate) -> dict:
    """Make a card as the owner (a project's queue or a named list). 422 for a bad title, 404 for a parent that is no card."""
    return await _named(await _owner(ops.create(request.app.state, None, req.model_dump(), by="owner")))


@router.post("/suggestions/{suggestion_id}", response_model=CardSuggestionView)
async def settle_suggestion(request: Request, suggestion_id: int, req: CardSuggestionAction) -> dict:
    """Apply (move the card as suggested) or dismiss an agent's reorder suggestion; 404 for an unknown one, 409 for one already settled."""
    done = await _owner(ops.settle_suggestion(request.app.state, None, {"suggestion_id": suggestion_id, "action": req.action}, by="owner"))
    return {**done["suggestion"], "card": await _named(done["card"]) if done["card"] else None}


@router.get("/rules/{project_id}", response_model=CardRules)
async def get_rules(project_id: int) -> dict:
    """A project queue's card switches (the defaults when none were set)."""
    key = str(project_id)
    return (await _owner(card_port.get().policy_read("rules", {"list_keys": [key]})))["rules"][key]


@router.put("/rules/{project_id}", response_model=CardRules)
async def put_rules(request: Request, project_id: int, req: CardRulesPatch) -> dict:
    """Change the fields sent; turning dealing on asks for a deal. 422 for a value outside the allowed set."""
    return await _owner(ops.set_rules(request.app.state, None, {"list_key": str(project_id), "changes": req.model_dump(exclude_none=True)}, by="owner"))


@router.get("/capacity", response_model=CapacityReading)
async def get_capacity() -> dict:
    """The capacity governor's inputs: CPU busy and its floor, the highest fresh usage window and its floor, live bodies and the hard caps (null is not measured)."""
    return await _owner(_reading())


@router.get("/grants", response_model=List[CardGrant])
async def get_grants() -> list:
    """Every capacity grant that is set, by scope (a scope with none runs up to the Swarm-wide cap of 20, 5 under one parent; a company with none runs up to 20)."""
    return (await _owner(card_port.get().policy_read("grants", {})))["grants"]


@router.put("/grants/{scope}", response_model=CardGrant)
async def put_grant(req: CardGrantPut, scope: str = Path(..., pattern=r"^(company|project):[1-9][0-9]{0,9}$")) -> dict:
    """Set how many agents a company or project may run (0..20), or send null slots to remove the grant. 422 ``bad_grant`` for a bad scope or count."""
    async def work() -> Any:
        ops._no_secrets("grant reason", req.reason)
        return (await card_port.get().policy("set_grant", {"scope": scope, "slots": req.slots, "reason": req.reason}, "owner"))["data"]["grant"]

    return await _owner(work())


@router.get("/{card_id}", response_model=CardView)
async def get_card(card_id: int) -> dict:
    """One card with its lease, marks, roll-up counts and proof; 404 ``not_a_card`` for an id that is no live card."""
    try:
        card = await card_port.get().card(card_id)
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        _huddle_unavailable(exc)
    if card is None:
        _refuse(CardRefused("not_a_card", "that item is not a card"))
    try:
        return await _named(card)
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        _unreadable(exc)


@router.get("/{card_id}/events", response_model=CardEvents)
async def get_events(card_id: int) -> dict:
    """The card's history (``card_events``), oldest first: created, started, finished, sent back, done and the rest; 404 ``not_a_card``."""
    await get_card(card_id)
    return {"card_id": card_id, **await _owner(card_port.get().policy_read("events", {"card_id": card_id}))}


@router.post("/{card_id}/done", response_model=CardView)
async def post_done(request: Request, card_id: int, req: CardDone) -> dict:
    """Move a Review card to Done as the owner; its agent-accepted children are approved with it. 409 ``not_in_review`` / ``stale``."""
    return await _named(await _owner(ops.done(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/send-back", response_model=CardView)
async def post_send_back(request: Request, card_id: int, req: CardSendBack) -> dict:
    """Send a Review card back with a note: the last holder (when live) gets it again, the note becomes a project fact."""
    return await _named(await _owner(ops.send_back(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/move", response_model=CardView)
async def post_move(request: Request, card_id: int, req: CardMove) -> dict:
    """Move a waiting card above ``before_id`` (null = the bottom); the owner's move always lands."""
    return await _named(await _owner(ops.move(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/release", response_model=CardView)
async def post_release(request: Request, card_id: int, req: CardRelease) -> dict:
    """Take a held card from its agent back to the queue (the agent is told to stop); a pending swap hands it on instead."""
    return await _named(await _owner(ops.release(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/pause", response_model=CardPauseResult)
async def post_pause(request: Request, card_id: int, req: CardPause) -> dict:
    """Pause a card and every card under it; ``now`` also sends Escape to each holder."""
    done = await _owner(ops.pause(request.app.state, card_id, req.model_dump(), by="owner"))
    return {**done, "card": await _named(done["card"])}


@router.post("/{card_id}/resume", response_model=CardPauseResult)
async def post_resume(request: Request, card_id: int) -> dict:
    """Resume a paused card and what its pause reached (409 ``paused_with_parent`` names the card to resume instead)."""
    done = await _owner(ops.resume(request.app.state, card_id, {}, by="owner"))
    return {**done, "card": await _named(done["card"])}


@router.post("/{card_id}/swap", response_model=CardView)
async def post_swap(request: Request, card_id: int, req: CardSwap) -> dict:
    """Move a held card to another agent: the holder is told to hand off and release, and the release hands it over."""
    return await _named(await _owner(ops.swap(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/pin", response_model=CardView)
async def post_pin(request: Request, card_id: int, req: CardPinRequest) -> dict:
    """Limit dealing of the card to one agent (null clears) and/or freeze its queue place against agent moves."""
    return await _named(await _owner(ops.pin(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/column", response_model=CardView)
async def post_column(request: Request, card_id: int, req: CardColumnMove) -> dict:
    """Move a card to any column as the owner: pause (in progress to todo), mark done (review to done, as it stands), reclassify (any), with a note
    for the agent that picks it up next. Saved at once; the agent hears the final state about 15 s after the last move, or nothing when it ends where it began."""
    return await _named(await _owner(ops.set_column(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/archive", response_model=CardView)
async def post_archive(request: Request, card_id: int, req: CardFlag) -> dict:
    """Archive a card (kept, hidden from the board and the deal; a card in the work is paused to todo first) or bring it back (``on`` false)."""
    return await _named(await _owner(ops.archive(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/auto-promote", response_model=CardView)
async def post_auto_promote(request: Request, card_id: int, req: CardFlag) -> dict:
    """Flag a todo card for auto-promote (or clear it): when the project has no queued card left the dealer promotes the top flagged one. 409 ``not_todo``."""
    return await _named(await _owner(ops.auto_promote(request.app.state, card_id, req.model_dump(), by="owner")))


@router.post("/{card_id}/queue", response_model=CardView)
async def post_queue(request: Request, card_id: int, req: CardQueue) -> dict:
    """Pull a todo card into in progress as queued (the dealer offers it next); ``reason`` is written to its history. 409 ``not_todo``, ``paused``, ``archived``."""
    return await _named(await _owner(ops.queue(request.app.state, card_id, req.model_dump(), by="owner")))


@router.delete("/{card_id}", response_model=CardDeleted)
async def delete_card(request: Request, card_id: int) -> dict:
    """Delete a card for good (its history stays); its agent is told to drop it, about 15 s later. 404 ``not_a_card``."""
    return await _owner(ops.delete(request.app.state, card_id, {}, by="owner"))


@router.get("/{card_id}/validation", response_model=CardValidation)
async def get_validation(card_id: int) -> dict:
    """The card's validation: state, proof (null reads "no proof yet"), what would validate it now and whether a start would be accepted."""
    return await _owner(validate.reading(await get_card(card_id)))


@router.post("/{card_id}/validate", response_model=CardValidation)
async def post_validate(request: Request, card_id: int) -> dict:
    """Validate a Review card now: the project agent's task child runs its how-to-validate steps. 409 ``no_capability`` (no proof yet), ``not_in_review``, ``no_project_agent``, ``already_validating``, ``cannot_validate``."""
    card = await _owner(validate.start(request.app.state, card_id, by="owner"))
    return await _owner(validate.reading(card))
