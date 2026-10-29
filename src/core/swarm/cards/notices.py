
from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from typing import Any, Dict, Mapping, Optional, Set, Tuple

import structlog

from src.core.swarm import body
from src.core.swarm.cards import dealer, deliver, port as card_port
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

NOTICE_S = 15.0

Snapshot = Tuple[str, Optional[int], bool]


@dataclasses.dataclass
class _Window:

    base: Snapshot
    agent_id: Optional[int]
    held_by_agent: bool
    list_key: str
    title: str
    note: str = ""
    handle: Optional[asyncio.TimerHandle] = None
    loop: Optional[asyncio.AbstractEventLoop] = None


_windows: Dict[int, _Window] = {}
_tasks: Set["asyncio.Task[Any]"] = set()


def snapshot(card: Optional[Mapping[str, Any]]) -> Snapshot:
    if card is None:
        return ("deleted", None, False)
    return (card["column"], (card.get("holder") or {}).get("agent_id"), card.get("archived_at") is not None)


def pending(card_id: int) -> bool:
    window = _windows.get(int(card_id))
    if window is not None and window.loop is not None and window.loop.is_closed():
        _windows.pop(int(card_id), None)
        return False
    return window is not None


def note(app_state: Any, before: Mapping[str, Any], after: Optional[Mapping[str, Any]], *, owner_note: str = "") -> None:
    card_id = int(before["id"])
    window = _windows.get(card_id) if pending(card_id) else None
    if window is None:
        holder = (before.get("holder") or {}).get("agent_id")
        agent = holder if holder is not None else (before.get("last_holder") if before["column"] == "review" else None)
        window = _Window(base=snapshot(before), agent_id=agent, held_by_agent=holder is not None, list_key=str(before["list_key"]),
                         title=str(before.get("title") or ""))
        _windows[card_id] = window
    if owner_note:
        window.note = owner_note
    if window.handle is not None:
        window.handle.cancel()
    loop = asyncio.get_running_loop()
    window.loop = loop
    window.handle = loop.call_later(NOTICE_S, _launch, app_state, card_id)
    logger.info("card_notice_armed", card_id=card_id, after=snapshot(after))


def _launch(app_state: Any, card_id: int) -> None:
    task = asyncio.get_running_loop().create_task(flush(app_state, card_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def notice_text(card_id: int, title: str, card: Optional[Mapping[str, Any]], note_text: str) -> str:
    name = f"card #{card_id} ({title})" if title else f"card #{card_id}"
    if card is None:
        text = f"The owner deleted {name}. Drop it: stop work on it and do not finish it."
    elif card.get("archived_at") is not None:
        text = f"The owner archived {name}: it is kept but off the board. Stop work on it."
    elif card["column"] == "todo":
        text = (f"The owner put {name} on hold: it is back in Todo. Stop after your current step, write your handoff with "
                "swarm_card_handoff, and do not finish it.")
    elif card["column"] == "done":
        text = f"The owner marked {name} done as it stands. No more work on it."
    elif card["column"] == "review":
        text = f"The owner moved {name} to Review. Stop work on it."
    else:
        text = f"The owner moved {name} back to In Progress, for the next deal. Stop work on it unless it is dealt to you again."
    return text + (f"\nThe owner's note: {note_text}" if note_text else "")


async def flush(app_state: Any, card_id: int) -> str:
    window = _windows.pop(int(card_id), None)
    if window is None:
        return "idle"
    try:
        port = card_port.get()
        card = await port.card(card_id)
        if (card is not None and window.held_by_agent and card.get("queued") and card.get("archived_at") is None
                and card.get("dealt_to") is None):
            try:
                card = (await port.act("deal", card_id, {"agent_id": window.agent_id, "slot_ok": True}, "owner"))["card"]
            except CardRefused as exc:
                logger.info("card_notice_rehold_refused", card_id=card_id, code=exc.code)
        if snapshot(card) == window.base:
            return "unchanged"
        if window.agent_id is None:
            return "no_agent"
        await deliver.tell(app_state, window.agent_id, notice_text(card_id, window.title, card, window.note), ref=f"card_notice:{card_id}", wake=False)
        return "told"
    except card_port.CardsOff:
        return "idle"
    except (body.BodyError, sqlite3.Error, OSError, RuntimeError, ValueError, KeyError) as exc:
        logger.warning("card_notice_failed", card_id=card_id, error_type=type(exc).__name__)
        return "idle"
    finally:
        dealer.kick(window.list_key)


def reset() -> None:
    for window in _windows.values():
        if window.handle is not None:
            window.handle.cancel()
    _windows.clear()
