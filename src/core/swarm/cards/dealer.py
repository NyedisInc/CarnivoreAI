
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core import db
from src.core.swarm import body, store, switch, thread_port
from src.core.swarm.cards import capacity, deliver, port as card_port
from src.cplugs.sdk import chat_category

logger = structlog.get_logger()

DEAL_DEBOUNCE_S = 5.0
RETRY_S = 900.0
MAX_ATTEMPTS = 3
QUEUE_LINES = 8
PACE_TEXT = {"normal": "normal (one card per free agent)", "asap": "asap (use every free slot, split cards, spawn up to the grant)"}
FLOOR_TAIL = "deal only to awake agents or hold."
_ERRORS = (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError)

_timers: Dict[str, asyncio.TimerHandle] = {}
_tasks: Set["asyncio.Task[Any]"] = set()
_inflight: Set[str] = set()
_rerun: Set[str] = set()
_due: Set[str] = set()
_app_state: Optional[Any] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def bind(app_state: Any, loop: Optional[asyncio.AbstractEventLoop]) -> None:
    global _app_state, _loop
    _app_state, _loop = app_state, loop


def ensure_bound(app_state: Any) -> None:
    if _loop is None or _loop.is_closed():
        bind(app_state, asyncio.get_running_loop())
    elif _app_state is None:
        bind(app_state, _loop)


def unbind() -> None:
    global _app_state, _loop
    loop = _loop
    _app_state, _loop = None, None
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(_cancel_timers)
    else:
        _cancel_timers()


def _cancel_timers() -> None:
    for handle in _timers.values():
        handle.cancel()
    _timers.clear()
    _inflight.clear()
    _rerun.clear()
    _due.clear()


def armed(project_key: str) -> bool:
    return project_key in _timers or project_key in _inflight


def kick(list_key: str, due: bool = False) -> None:
    if not switch.is_on():
        return
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(_arm, list_key, due)
    except RuntimeError:
        logger.info("card_deal_kick_dropped", project=list_key)


def _arm(project_key: str, due: bool = False) -> None:
    """Start the project's debounce window unless one is already running (on the loop); a kick during a send is remembered and re-armed after it."""
    if _loop is None:
        return
    if due:
        _due.add(project_key)
    if project_key in _inflight:
        _rerun.add(project_key)
        return
    if project_key in _timers:
        return
    _timers[project_key] = _loop.call_later(DEAL_DEBOUNCE_S, _launch, project_key)


def _launch(project_key: str) -> None:
    _timers.pop(project_key, None)
    app_state = _app_state
    if app_state is None or _loop is None:
        return
    _inflight.add(project_key)
    task = _loop.create_task(_run(app_state, project_key))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(app_state: Any, project_key: str) -> None:
    try:
        outcome = await fire(app_state, project_key)
    finally:
        _inflight.discard(project_key)
        _due.discard(project_key)
    if project_key in _rerun:
        _rerun.discard(project_key)
        if outcome not in ("refused", switch.CODE):
            _arm(project_key)


async def _post_line(project_key: str, text: str, category: str) -> None:
    thread = thread_port.get()
    if thread is None:
        return
    try:
        await thread.post_traffic(project_key, text, chat_category.card_ref(category, f"deal-{project_key}"))
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        logger.warning("card_deal_post_failed", project=project_key, error_type=type(exc).__name__)


async def _settle(project_key: str, state: str, **kw: Any) -> bool:
    result = await card_port.get().policy("deal_state", {"project_key": project_key, "state": state, **kw}, "server")
    return bool(result["data"]["changed"])


def queued_cards(cards: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    from src.core.swarm.cards import notices

    return [c for c in cards if c.get("queued") and c["state"] == "open" and not c["paused"] and c["dealt_to"] is None
            and c.get("archived_at") is None and (c["mark"] or {}).get("name") != "waiting_for_slot" and not notices.pending(c["id"])]


def promotable(card: Mapping[str, Any]) -> bool:
    return (card["column"] == "todo" and bool(card.get("auto_promote")) and card["state"] == "open" and not card["paused"]
            and card.get("archived_at") is None)


def request_text(project: str, reasons: Sequence[str], queue: Sequence[Mapping[str, Any]], free: Sequence[str], *,
                 slots: Optional[Tuple[int, int]] = None, waiting: int = 0, pace: Optional[str] = None, floor: Optional[str] = None) -> str:
    lines = [f"#{c.get('queue_index') or i + 1} card #{c['id']}: {c['title']}"
             + (f" (pinned: agent {c['pin']['agent_id']})" if (c.get("pin") or {}).get("agent_id") is not None else "")
             for i, c in enumerate(queue[:QUEUE_LINES])]
    more = f" and {len(queue) - QUEUE_LINES} more" if len(queue) > QUEUE_LINES else ""
    queued = f"; {waiting} {'card' if waiting == 1 else 'cards'} waiting for a slot" if waiting else ""
    if slots is None:
        slot_line = ""
    elif slots[1] is not None:
        slot_line = f"Slots: {slots[0]} of {slots[1]} free{queued}. "
    else:
        slot_line = f"Slots: {'0 free' if slots[0] == 0 else 'no fixed limit, a new agent waits only while the computer is pegged'}{queued}. "
    pace_line = f"Pace: {PACE_TEXT.get(pace, pace)}. " if pace else ""
    floor_line = f"Floor: {floor}; {FLOOR_TAIL} " if floor else ""
    return (f"Deal request for {project}: {', '.join(r.replace('_', ' ') for r in reasons) or 'the queue changed'}. "
            f"Queued in progress, top first: {'; '.join(lines)}{more}. Free agents: {', '.join(free) or 'none'}. {slot_line}{pace_line}{floor_line}"
            "Deal only these queued cards, in this order; Todo is the owner's backlog and is never started. "
            "Deal with swarm_card_deal (agent_id; with no card_id the server deals the top queued card, a lower one needs a reason), spawn with swarm_spawn and card, or answer swarm_card_deal with hold "
            "when nothing should start. This request stays open until you answer.")


def _facts(conn: sqlite3.Connection, project_id: int, busy: Set[int], grants: Mapping[str, int]) -> Dict[str, Any]:
    agent = store.get_project_agent(conn, project_id)
    row = conn.execute("SELECT display_name FROM projects WHERE id = ?", (project_id,)).fetchone()
    below: Set[int] = {agent["id"]} if agent else set()
    free = []
    for a in store.list_agents(conn):
        if a["parent_id"] in below:
            below.add(a["id"])
            if a["id"] not in busy:
                free.append(f"{a['display_name']} (agent {a['id']})")
    return {"agent": agent, "project": row["display_name"] if row else f"project {project_id}", "free": free,
            "slots": capacity.slots(conn, project_id, grants)}


async def _give_up(project_key: str, project: str) -> str:
    await _settle(project_key, "gave_up", only_from=("waiting", "delivered"))
    await _post_line(project_key, f"the deal request for {project} went unanswered {MAX_ATTEMPTS} times; cards wait for you or for the next request", "important")
    return "gave_up"


async def fire(app_state: Any, project_key: str) -> str:
    if not switch.is_on():
        return switch.CODE
    try:
        port = card_port.get()
        seen = await port.policy_read("dealing", {"project_key": project_key})
        row = seen["deal"]
        if row is None or row["state"] != "waiting":
            return "idle"
        if not seen["dealing"]:
            await _settle(project_key, "dealing_off", only_from=("waiting",))
            return "dealing_off"
        cards = await port.cards(list_keys=[project_key], columns=["todo", "in_progress"])
        todo = queued_cards(cards)
        if not todo:
            flagged = next((c for c in cards if promotable(c)), None)
            if flagged is not None:
                await port.act("promote", flagged["id"], {}, "server")
                cards = await port.cards(list_keys=[project_key], columns=["todo", "in_progress"])
                todo = queued_cards(cards)
        busy = {c["holder"]["agent_id"] for c in cards if c["holder"]} | {c["dealt_to"] for c in cards if c["dealt_to"] is not None}
        grants = await capacity.grants_by_scope()
        facts = await body.run_db(lambda conn: _facts(conn, int(project_key), busy, grants))
        if facts["agent"] is None:
            await _settle(project_key, "no_dealer", only_from=("waiting",))
            return "no_dealer"
        if not todo:
            await _settle(project_key, "answered", only_from=("waiting",))
            return "idle"
        if row["attempts"] and project_key not in _due and time.time() - (row["delivered_at"] or 0.0) < RETRY_S:
            return "held"
        if row["attempts"] >= MAX_ATTEMPTS:
            return await _give_up(project_key, facts["project"])
        if not await _settle(project_key, "waiting", attempt=True, only_from=("waiting",)):
            return "idle"
        waiting = sum(1 for c in cards if (c["mark"] or {}).get("name") == "waiting_for_slot")
        pace = (await port.policy_read("rules", {"list_keys": [project_key]}))["rules"][project_key]["pace"]
        code = await asyncio.to_thread(capacity.floor_refusal)
        floor = await asyncio.to_thread(capacity.refusal_text, code) if code else None
        slots = (0, facts["slots"][1]) if floor else facts["slots"]
        text = request_text(facts["project"], row["reasons"], todo, facts["free"], slots=slots, waiting=waiting, pace=pace, floor=floor)
        outcome = await deliver.tell(app_state, facts["agent"]["id"], text, ref=f"deal:{project_key}")
        if outcome.startswith("refused"):
            return "refused"
        await _settle(project_key, "delivered", offered=[c["id"] for c in todo[:QUEUE_LINES]], only_from=("waiting",))
        return "held" if outcome == "held" else "delivered"
    except card_port.CardsOff:
        return "idle"
    except (*_ERRORS, ValueError, KeyError) as exc:
        logger.warning("card_deal_fire_failed", project=project_key, error_type=type(exc).__name__)
        return "idle"


async def answered(card: Optional[Mapping[str, Any]], dealer: Optional[Mapping[str, Any]]) -> None:
    if dealer is None:
        return
    key = str(card["list_key"]) if card else (str(dealer["thread_key"]) if dealer.get("rank") == "project" else "")
    if not key.isdigit():
        return
    try:
        await _settle(key, "answered", only_from=("waiting", "delivered"))
    except (card_port.CardsOff, *_ERRORS, ValueError, KeyError) as exc:
        logger.warning("card_deal_answer_failed", project=key, error_type=type(exc).__name__)
