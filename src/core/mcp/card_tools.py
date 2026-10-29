
from __future__ import annotations

import asyncio
import json
import sqlite3

import structlog
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.core import db
from src.core.crosstalk import bus as crosstalk_bus, store as crosstalk_store
from src.core.mcp import lean_answers, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.swarm import facts, spawn
from src.core.swarm.cards import board as card_board, ops, port as card_port
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

DEFAULT_LIMIT = 50
_COLUMNS = ["todo", "in_progress", "review", "done"]


def _int(args: dict, key: str, *, required: bool = False, minimum: int = 1) -> Any:
    value = args.get(key)
    if value is None and not required:
        return None
    if type(value) is not int or value < minimum:
        raise ToolError(f"{key} is required and must be a whole number" if required else f"{key} must be a whole number")
    return value


def _text(args: dict, key: str, *, required: bool = False, limit: int = 8000) -> Any:
    value = args.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ToolError(f"{key} must be text of at most {limit} characters" + (" and is required" if required else ""))
    return value.strip()


async def _caller(manager: Any, caller: AgentCaller) -> Dict[str, Any]:
    try:
        return await spawn.parent_agent(manager, caller)
    except spawn.SpawnRefused:
        raise CardRefused("not_a_swarm_agent", "swarm tools are for Swarm agents") from None


async def _guard(work: Awaitable[Any], *, wrap: bool = True) -> Any:
    try:
        value = await work
        return _ok(value) if wrap else value
    except CardRefused as exc:
        raise ToolError(f"{exc.code}: {exc}") from None
    except card_port.CardsOff:
        raise ToolError("cards_off: the huddle plugin is off, so there are no cards") from None
    except (db.DatastoreUnreadableError, sqlite3.Error):
        raise ToolError("the Swarm datastore could not be read") from None


_QUIET = frozenset({"revision", "updated_at"})
MAX_REMEMBER = 5
MAX_CREATE = 20
_LIST_KEYS = ("id", "title", "summary", "column", "project_id", "queue_index", "parent", "progress", "children", "stranded", "revision", "updated_at")


def _holder_id(card: Optional[dict]) -> Any:
    holder = (card or {}).get("holder")
    return holder.get("agent_id") if isinstance(holder, dict) else None


def lean_card(card: dict, before: Optional[dict] = None) -> dict:
    out = {"id": card.get("id"), "column": card.get("column"), "title": card.get("title"), "revision": card.get("revision")}
    if before is not None:
        out["changed"] = [k for k in card if k not in _QUIET and (_holder_id(card) != _holder_id(before) if k == "holder" else card[k] != before.get(k))]
    return out


def _detail(args: dict) -> bool:
    return lean_answers.detail_flag(args)


async def _before(card_id: Optional[int]) -> Optional[dict]:
    return await card_port.get().card(card_id) if card_id is not None else None


def _writer(op: Callable[..., Awaitable[Any]], build: Callable[[dict], dict], *, wrap: bool = True) -> Callable[..., Awaitable[Any]]:
    async def handler(manager: Any, caller: AgentCaller, args: dict) -> Any:
        async def work() -> Any:
            full = _detail(args)
            agent = await _caller(manager, caller)
            card_id = _int(args, "card_id", required=op is not ops.create and op is not ops.deal)
            sent = build(args)
            before = None if full or op is ops.create else await _before(card_id)
            card = await op(manager.app.state, card_id, sent, by=f"agent:{agent['id']}")
            return {"card": card if full else lean_card(card, before)}

        return await _guard(work(), wrap=wrap)

    return handler


async def swarm_card_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        agent = await _caller(manager, caller)
        full = _detail(args)
        project, column, limit = _int(args, "project_id"), args.get("column"), _int(args, "limit") or DEFAULT_LIMIT
        offset = _int(args, "offset", minimum=0) or 0
        if column is not None and column not in _COLUMNS or limit > 200:
            raise ToolError("column must be todo, in_progress, review or done; limit at most 200")
        holder = agent["id"] if args.get("mine") else _int(args, "holder")
        cards = await card_port.get().cards(list_keys=[str(project)] if project else (), holder=holder, columns=[column] if column else ())
        page = cards[offset:offset + limit]
        more = offset + limit < len(cards)
        rows = page if full else [{**{k: c[k] for k in _LIST_KEYS if k in c}, "holder": _holder_id(c)} for c in page]
        return {"cards": rows, "has_more": more, "next": offset + limit if more else None}

    return await _guard(work())


async def swarm_card_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        await _caller(manager, caller)
        card = await card_port.get().card(_int(args, "card_id", required=True))
        if card is None:
            raise CardRefused("not_a_card", "no such card")
        return {"card": card}

    return await _guard(work())


async def swarm_card_board(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        agent = await _caller(manager, caller)
        scope = _text(args, "scope", limit=40) or (f"project:{agent['project_id']}" if agent.get("project_id") else "sysop")
        if not card_board.valid_scope(scope):
            raise ToolError("scope must be sysop, project:<id> or company:<id>")
        return await card_board.board(scope, filter="all", done_limit=20)

    return await _guard(work())


def _create_args(a: dict) -> dict:
    return {
        "title": _text(a, "title", required=True, limit=ops.MAX_TITLE_CHARS), "summary": _text(a, "summary", required=True, limit=ops.MAX_SUMMARY_CHARS),
        "text": _text(a, "text", limit=2000) or "",
        "project_id": _int(a, "project_id"), "parent": _int(a, "parent"), "how_to_validate": _text(a, "how_to_validate", limit=4000) or "",
        "before_id": _int(a, "before_id"), "queued": a.get("queued") is True}


async def swarm_card_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    items = args.get("cards")
    if items is None:
        return _ok(await _create_card(manager, caller, args))
    if any(k in args for k in ("title", "summary")):
        raise ToolError("pass either cards or one card's own arguments, not both")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CREATE or not all(isinstance(i, dict) for i in items):
        raise ToolError(f"cards must be a list of 1 to {MAX_CREATE} card objects")
    created: List[dict] = []
    errors: List[dict] = []
    for index, item in enumerate(items):
        try:
            answer = await _create_card(manager, caller, {**{k: v for k, v in args.items() if k in ("project_id", "parent", "queued", "detail")}, **item})
        except ToolError as exc:
            errors.append({"index": index, "error": str(exc)})
        else:
            created.append(answer["card"])
    return _ok({"created": created, "errors": errors})


_create_card = _writer(ops.create, _create_args, wrap=False)


async def _unread_peer_messages(manager: Any, caller: AgentCaller) -> Optional[int]:
    try:
        identity = await crosstalk_bus.caller_identity(manager, caller)
        return await asyncio.to_thread(crosstalk_store.pending_count, identity["key"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("card_start_unread_count_failed", error_type=type(exc).__name__)
        return None


async def swarm_card_start(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        agent = await _caller(manager, caller)
        card_id = _int(args, "card_id", required=True)
        started = await ops.start(manager.app.state, card_id, {}, by=f"agent:{agent['id']}")
        answer: Dict[str, Any] = {"card": await card_port.get().card(card_id) or started}
        unread = await _unread_peer_messages(manager, caller)
        if unread is not None:
            answer["unread_peer_messages"] = unread
        return answer

    return await _guard(work())


def _remember_list(args: dict) -> List[dict]:
    value = args.get("remember")
    if value is None:
        return []
    items = [value] if isinstance(value, dict) else value
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_REMEMBER or not all(isinstance(i, dict) for i in items):
        raise ToolError(f"remember must be a fact object or a list of 1 to {MAX_REMEMBER} of them (title, scope, text)")
    return items


async def swarm_card_finish(manager: Any, caller: AgentCaller, args: dict) -> dict:
    facts_in = _remember_list(args)
    _text(args, "result", limit=ops.MAX_FINISH_CHARS)
    _text(args, "how_to_validate", limit=ops.MAX_FINISH_CHARS)
    if type(args.get("needs_owner")) is not bool:
        raise ToolError("needs_owner is required: false when the work is checked and complete (straight to Done), "
                        "true with owner_ask when the owner must answer, pick or do something before it closes")
    remembered: List[dict] = []
    for index, fact in enumerate(facts_in):
        try:
            remembered.append(await facts.remember(manager, caller, fact))
        except facts.FactRefused as exc:
            done = f"{len(remembered)} fact(s) written ({', '.join(str(r['fact_id']) for r in remembered)}); " if remembered else ""
            raise ToolError(f"remember failed on fact {index + 1}, the card is NOT finished: {exc}. {done}fix it and call swarm_card_finish again sending only the facts not yet written") from None
    try:
        answer = await _finish_card(manager, caller, args)
    except ToolError as exc:
        if remembered:
            raise ToolError(f"{exc} (the {len(remembered)} fact(s) in remember were written: {', '.join(str(r['fact_id']) for r in remembered)}; "
                            "call again without remember)") from None
        raise
    return _ok({**answer, "remembered": remembered} if remembered else answer)


_finish_card = _writer(ops.finish, lambda a: {
    "result": _text(a, "result", limit=ops.MAX_FINISH_CHARS), "how_to_validate": _text(a, "how_to_validate", limit=ops.MAX_FINISH_CHARS),
    "validate_link": _text(a, "validate_link", limit=500), "needs_owner": a.get("needs_owner"),
    "owner_ask": _text(a, "owner_ask", limit=ops.MAX_ASK_CHARS)}, wrap=False)
swarm_card_close = _writer(ops.close, lambda a: {"reason": _text(a, "reason", required=True, limit=ops.MAX_ASK_CHARS)})
swarm_card_handoff = _writer(ops.handoff, lambda a: {"handoff": _text(a, "handoff"), "progress": _int(a, "progress", minimum=0)})
swarm_card_release = _writer(ops.release, lambda a: {"reason": _text(a, "reason", required=True, limit=500)})
swarm_card_reorder = _writer(ops.reorder, lambda a: {"before_id": _int(a, "before_id"), "reason": _text(a, "reason", required=True, limit=500)})
swarm_card_deal = _writer(ops.deal, lambda a: {"agent_id": _int(a, "agent_id"), "hold": bool(a.get("hold")), "reason": _text(a, "reason", limit=500) or ""})
swarm_card_queue = _writer(ops.queue, lambda a: {"reason": _text(a, "reason", limit=500) or ""})
swarm_card_auto_promote = _writer(ops.auto_promote, lambda a: {"on": bool(a.get("on"))})
swarm_card_archive = _writer(ops.agent_archive, lambda a: {"reason": _text(a, "reason", required=True, limit=ops.MAX_ASK_CHARS)})


async def swarm_card_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def check() -> Any:
        agent = await _caller(manager, caller)
        card_id = _int(args, "card_id", required=True)
        sent = {"reason": _text(args, "reason", required=True, limit=ops.MAX_ASK_CHARS)}
        checked = await ops.curate_check(card_id, sent, by=f"agent:{agent['id']}", op="agent_delete")
        return agent, card_id, checked

    agent, card_id, checked = await _guard(check(), wrap=False)

    async def run(_approved: bool) -> dict:
        return await _guard(ops.agent_delete(manager.app.state, card_id, {"reason": checked["reason"]}, by=f"agent:{agent['id']}"))

    summary = (f"DELETE card #{card_id} {json.dumps(checked['card'].get('title') or '')} for good (its history stays; "
               f"its agent is told to drop it). Reason: {checked['reason']}")
    return await write_tools.park(manager, caller, "", "", "swarm_card_delete", summary, {"card_id": card_id, "reason": checked["reason"]},
                                  run, dedupe_key=f"swarm_card_delete:{card_id}", beast_eligible=False)


_CARD = {"card_id": {"type": "integer", "minimum": 1}}
_DETAIL = {"detail": {"type": "boolean", "description": "answer the full card instead of {id, column, title, revision, changed}"}}
_CARD_PROPS = {
    "title": {"type": "string", "minLength": 1, "maxLength": 120},
    "summary": {"type": "string", "minLength": 1, "maxLength": 200,
                "description": "one plain-English line saying what the card is for and what it changes for the owner: no file names, line numbers or code"},
    "text": {"type": "string", "maxLength": 2000},
    "project_id": {"type": "integer", "minimum": 1}, "parent": {"type": "integer", "minimum": 1},
    "how_to_validate": {"type": "string", "maxLength": 4000}, "before_id": {"type": "integer", "minimum": 1},
    "queued": {"type": "boolean", "description": "true: start in In Progress, queued for the deal (the project agent, its own project only)"}}

WRITE_TOOLS: frozenset = frozenset({"swarm_card_create", "swarm_card_start", "swarm_card_handoff", "swarm_card_finish", "swarm_card_close", "swarm_card_release",
                                    "swarm_card_reorder", "swarm_card_deal", "swarm_card_auto_promote", "swarm_card_queue",
                                    "swarm_card_archive", "swarm_card_delete"})

TOOLS: Dict[str, Any] = {
    "swarm_card_list": ("Cards in queue order, lean rows, one page: filter by project_id, column, holder, or mine (cards you hold). has_more and next (the offset to pass) page on; detail true keeps every field.",
                        {"project_id": {"type": "integer", "minimum": 1}, "column": {"type": "string", "enum": _COLUMNS},
                         "holder": {"type": "integer", "minimum": 1}, "mine": {"type": "boolean"},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "offset": {"type": "integer", "minimum": 0},
                         **_DETAIL}, [], swarm_card_list),
    "swarm_card_get": ("One card in full: its handoff, how to validate, proof, children and who holds it.", _CARD, ["card_id"], swarm_card_get),
    "swarm_card_board": ("The board of a scope (project:<id>, company:<id>, sysop; default your project).",
                         {"scope": {"type": "string"}}, [], swarm_card_board),
    "swarm_card_create": (
        "Make a card in Todo (the owner's backlog), or several with cards:[...]. Project and company agents and Alpha make cards where they deal; a task or feature agent makes only child cards of the card it holds. "
        "A project agent making a card for work to start now passes queued=true (its own project only): the card goes straight to In Progress, queued for the deal.",
        {**_CARD_PROPS, **_DETAIL,
         "cards": {"type": "array", "maxItems": MAX_CREATE, "items": {"type": "object", "properties": _CARD_PROPS, "required": ["title", "summary"]},
                   "description": f"make up to {MAX_CREATE} cards in one call instead of the single-card arguments; each is gated alone and a refused one is listed in errors"}},
        [], swarm_card_create),
    "swarm_card_start": ("Start the card you were dealt: the clock begins and the card is yours in progress. Answers the full card (no swarm_card_get first) and unread_peer_messages, a count of waiting crosstalk messages (read them with crosstalk_inbox).", _CARD, ["card_id"], swarm_card_start),
    "swarm_card_handoff": (
        "Write your handoff on a card you hold (what is done, what is left, the next step) and your progress 0..100. This is your heartbeat: keep it current.",
        {**_CARD, "handoff": {"type": "string", "maxLength": 8000}, "progress": {"type": "integer", "minimum": 0, "maximum": 100}, **_DETAIL},
        ["card_id"], swarm_card_handoff),
    "swarm_card_finish": (
        "Finish a card you hold with your result and the steps to validate it; the report to your parent is filed for you. "
        "needs_owner false (the work is checked and complete): the card goes straight to Done (a child card waits for its parent's accept). "
        "needs_owner true, only when the owner must answer a question, pick between options (such as mockups) or do something before it can close: "
        "the card goes to Review showing owner_ask. "
        "remember (a swarm_remember fact or a list of up to 5, only a lasting rule that meets the memory bar, usually none) is written first; "
        "if it fails the card is not finished.",
        {**_CARD, "result": {"type": "string", "minLength": 1, "maxLength": 4000},
         "needs_owner": {"type": "boolean", "description": "true only when the owner must answer, pick or do something before the card closes"},
         "owner_ask": {"type": "string", "maxLength": 500, "description": "required with needs_owner true: what the owner must answer, pick or do"},
         "how_to_validate": {"type": "string", "minLength": 1, "maxLength": 4000}, "validate_link": {"type": "string", "maxLength": 500},
         "remember": {"oneOf": [{"type": "object"}, {"type": "array", "maxItems": MAX_REMEMBER, "items": {"type": "object"}}], "description": "facts as swarm_remember takes them: title, scope, text, kind; leave out unless it is a rule needed again"},
         **_DETAIL},
        ["card_id", "result", "how_to_validate", "needs_owner"], swarm_card_finish),
    "swarm_card_close": (
        "Close a card in Review: it moves to Done, with your reason kept in its history. A project agent closes its own project's cards, "
        "a company agent its company's projects' cards. Close only work that is checked and complete; leave a card that waits on the owner's answer, pick or hands.",
        {**_CARD, "reason": {"type": "string", "minLength": 1, "maxLength": 500}, **_DETAIL}, ["card_id", "reason"], swarm_card_close),
    "swarm_card_release": ("Give a card you hold back to the queue (or on to the agent it was swapped to), with a reason.",
                           {**_CARD, "reason": {"type": "string", "minLength": 1, "maxLength": 500}, **_DETAIL}, ["card_id", "reason"], swarm_card_release),
    "swarm_card_reorder": (
        "Move a waiting card above before_id (null = the bottom). Where the list's reorder rule is suggest the owner decides; where it is auto the card moves at once.",
        {**_CARD, "before_id": {"type": ["integer", "null"], "minimum": 1}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}, **_DETAIL},
        ["card_id", "reason"], swarm_card_reorder),
    "swarm_card_deal": (
        "Deal a queued card (In Progress, unheld) to an agent (project agent, its company agent, Alpha); a Todo card is never dealt. "
        "Without card_id the top queued card of your project goes. A lower card, or one naming a live feature agent's specialty "
        "sent elsewhere, needs a reason (kept in the card's history). A held card is swapped; hold=true answers a deal request by leaving it.",
        {"card_id": {"type": "integer", "minimum": 1}, "agent_id": {"type": "integer", "minimum": 1}, "hold": {"type": "boolean"},
         "reason": {"type": "string", "maxLength": 500, "description": "why this card goes out of order, or to this agent rather than the specialist"}, **_DETAIL},
        [], swarm_card_deal),
    "swarm_card_queue": (
        "Pull one of your own project's Todo cards into In Progress, queued for the deal (project agent only). The server keeps the board order: "
        "the top Todo card goes first; queuing a lower one needs a reason, written to the card's history. Use it for a card meant for work now, "
        "such as one flagged stranded (an agent's work card the owner never touched); leave the owner's own backlog cards in Todo.",
        {**_CARD, "reason": {"type": "string", "maxLength": 500,
                             "description": "why this card goes ahead of the top todo card; required unless it is the top one"}, **_DETAIL},
        ["card_id"], swarm_card_queue),
    "swarm_card_auto_promote": (
        "Flag a Todo card for auto-promote (on=true) or clear it: when the project has no queued in-progress card left, the dealer moves the top flagged Todo card into In Progress and deals it. Todo cards without the flag are never started on their own.",
        {**_CARD, "on": {"type": "boolean"}, **_DETAIL}, ["card_id", "on"], swarm_card_auto_promote),
    "swarm_card_archive": (
        "Archive a card: kept, off the board and the deal, at once; your reason goes in its history. "
        "A project agent archives its own project's cards, a company agent its company's projects' cards.",
        {**_CARD, "reason": {"type": "string", "minLength": 1, "maxLength": 500}, **_DETAIL}, ["card_id", "reason"], swarm_card_archive),
    "swarm_card_delete": (
        "Delete a card for good; its history stays and its agent is told to drop it. Same scope as swarm_card_archive. "
        "Always waits for the owner's approval, even in Beast Mode.",
        {**_CARD, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ["card_id", "reason"], swarm_card_delete),
}
