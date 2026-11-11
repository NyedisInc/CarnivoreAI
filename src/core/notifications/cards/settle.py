
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.approvals.deliver import SOURCE_AUTO, SOURCE_BEAST, SOURCE_OWNER_PHONE, answered_by
from src.core.approvals.inbox import item_id
from src.core.notifications import card_contract as cc
from src.core.notifications.cards.model import say
from src.core.notify_caps.store import get_store

logger = structlog.get_logger()

_MAX_OPEN = 256


@dataclass(frozen=True)
class Sent:

    device_row_id: str
    type_id: str
    instance: str
    kind: str
    agent: str
    path: str
    thread: str
    cap: str
    item: str = ""


_OPEN: Dict[str, List[Sent]] = {}
_TASKS: Set["asyncio.Task[Any]"] = set()


def remember(session_id: str, fingerprint: str, sent: Sent) -> None:
    key = item_id(session_id, fingerprint)
    _OPEN.setdefault(key, []).append(replace(sent, item=key))
    while len(_OPEN) > _MAX_OPEN:
        _OPEN.pop(next(iter(_OPEN)))


def on_lost(lost: List[Tuple[str, str]]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for _source, ident in lost:
        sends = _OPEN.pop(ident, None)
        if sends:
            task = loop.create_task(settle(sends))
            _TASKS.add(task)
            task.add_done_callback(_TASKS.discard)


def _answered_by_phone(sends: List[Sent]) -> Set[str]:
    store, used = get_store(), set()
    for s in sends:
        rec = store.find(s.cap)
        if rec is not None and rec.used_at is not None:
            used.add(s.device_row_id)
    return used


def where_answered(sends: List[Sent], used: Set[str]) -> str:
    if used:
        return "phone"
    source = answered_by(sends[0].item) if sends else None
    if source is None:
        return "elsewhere"
    return "phone" if source == SOURCE_OWNER_PHONE else "auto" if source in (SOURCE_AUTO, SOURCE_BEAST) else "computer"


async def settle(sends: List[Sent]) -> int:
    from src.core.notifications.kinds import apns  # noqa: PLC0415

    sender = apns.current_sender()
    if sender is None:
        return 0
    used = await asyncio.to_thread(_answered_by_phone, sends)
    where = where_answered(sends, used)
    sent = 0
    for s in sends:
        if s.device_row_id in used:
            continue
        payload = cc.build_payload(
            kind=s.kind, type_id=s.type_id, title=s.agent, body=say("native.notify.settled"), path=s.path, thread=s.thread,
            lv="p", snd="none", settle={"where": where, "agent": s.agent, "working": False})
        status: Optional[int] = await sender.send_typed(s.device_row_id, s.type_id, payload, s.instance, settle=True)
        sent += 1 if status is not None and 200 <= status < 300 else 0
    logger.info("notify_settle_sent", devices=sent, where=where)
    return sent
