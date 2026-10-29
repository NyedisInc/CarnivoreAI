
from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from src.cplugs.huddle import files, rules
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import JOE, TaskManagerInvalid

CLIENT_ID = re.compile(r"^[0-9A-Za-z-]{8,64}$")
MAX_RETRY_AGE_S = 7 * 86400
SLACK_S = 30.0
KEEP = 2000
TTL_S = 86400.0

Answer = Dict[str, Any]
Ref = Dict[str, Any]


@dataclass(frozen=True)
class Done:

    scope: str
    ref: Ref
    at: float


_done: "OrderedDict[str, Done]" = OrderedDict()
_flight: Dict[str, "asyncio.Future[Answer]"] = {}


def check_id(client_id: Optional[str]) -> Optional[str]:
    if client_id is not None and not CLIENT_ID.match(client_id):
        raise TaskManagerInvalid("client_id must be 8 to 64 letters, digits or dashes")
    return client_id


def reset() -> None:
    _done.clear()
    _flight.clear()


def _remember(client_id: str, scope: str, ref: Ref) -> None:
    now = time.time()
    _done[client_id] = Done(scope, ref, now)
    _done.move_to_end(client_id)
    while _done and (len(_done) > KEEP or now - next(iter(_done.values())).at > TTL_S):
        _done.popitem(last=False)


async def once(scope: str, client_id: Optional[str], retry_age_s: Optional[float], *, run: Callable[[], Awaitable[Answer]],
               recover: Callable[[float], Awaitable[Optional[Answer]]], ref_of: Callable[[Answer], Ref],
               replay: Callable[[Ref], Awaitable[Answer]]) -> Answer:
    if not client_id:
        return await run()
    known = _done.get(client_id)
    if known is not None:
        if known.scope != scope:
            raise TaskManagerInvalid("client_id was used for another write")
        return {**await replay(known.ref), "duplicate": True}
    waiting = _flight.get(client_id)
    if waiting is not None:
        return {**await asyncio.shield(waiting), "duplicate": True}
    mine: "asyncio.Future[Answer]" = asyncio.get_running_loop().create_future()
    _flight[client_id] = mine
    try:
        found = await recover(time.time() - retry_age_s - SLACK_S) if retry_age_s is not None else None
        answer = found if found is not None else await run()
        _remember(client_id, scope, ref_of(answer))
        mine.set_result(answer)
        return {**answer, "duplicate": found is not None}
    except BaseException as exc:
        if not mine.done():
            mine.set_exception(exc)
            mine.exception()
        raise
    finally:
        _flight.pop(client_id, None)


def _message(store: Any, message_id: int) -> Answer:
    from src.cplugs.huddle.wire import MSG_COLS, message_dict
    with closing(store._read_connection()) as conn:
        return message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (message_id,)).fetchone())


def find_reply(store: Any, item_id: int, text: str, file_ids: Sequence[str], since: float, kind: str = rules.REPLY) -> Optional[Answer]:
    clean = rules.clean_text(text, "text", rules.MAX_MESSAGE, allow_blank=bool(file_ids))
    with closing(store._read_connection()) as conn:
        rows = conn.execute("SELECT id, parts FROM work_messages WHERE item_id = ? AND author = ? AND kind = ? AND text = ? AND created_at >= ? "
                            "ORDER BY id DESC", (item_id, JOE, kind, clean, since)).fetchall()
    wanted = set(file_ids)
    for row in rows:
        if {e.get("id") for e in files.entries_of(row["parts"] or "")} == wanted:
            return {"item": store.item(item_id), "message": _message(store, row["id"])}
    return None


def find_inbox(store: Any, list_key: str, text: str, since: float) -> Optional[Answer]:
    clean = rules.clean_text(text, "text", rules.MAX_TEXT)
    with closing(store._read_connection()) as conn:
        row = conn.execute("SELECT id FROM work_inbox WHERE list_key = ? AND author = ? AND raw_text = ? AND created_at >= ? ORDER BY id DESC LIMIT 1",
                           (list_key, "joe", clean, since)).fetchone()
    return {"queued": True, "entry": InboxStore(store).get(row["id"]), "item": None} if row else None


def find_added(store: Any, list_key: str, text: str, since: float) -> Optional[Answer]:
    clean = rules.clean_text(text, "text", rules.MAX_TEXT)
    with closing(store._read_connection()) as conn:
        row = conn.execute("SELECT id FROM work_items WHERE list_key = ? AND created_by = ? AND text = ? AND created_at >= ? AND deleted = 0 "
                           "ORDER BY id DESC LIMIT 1", (list_key, JOE, clean, since)).fetchone()
    return {"queued": False, "entry": None, "item": store.item(row["id"])} if row else None


def reply_ref(answer: Answer) -> Ref:
    return {"item": answer["item"]["id"], "message": answer["message"]["id"]}


def add_ref(answer: Answer) -> Ref:
    return {"entry": answer["entry"]["id"]} if answer.get("queued") else {"item": answer["item"]["id"]}


def replay_reply(store: Any, ref: Ref) -> Answer:
    return {"item": store.item(ref["item"]), "message": _message(store, ref["message"])}


def replay_add(store: Any, ref: Ref) -> Answer:
    if "entry" in ref:
        return {"queued": True, "entry": InboxStore(store).get(ref["entry"]), "item": None}
    return {"queued": False, "entry": None, "item": store.item(ref["item"])}
