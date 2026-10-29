
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Sequence

from src.cplugs.huddle import service
from src.cplugs.huddle.rules import ALL_LIST, TaskManagerInvalid, TaskManagerNotFound, check_list_key
from src.cplugs.sdk import CplugContext

MAX_FOCUS_ITEMS = 50

_lock = threading.Lock()
_focus: Dict[str, dict] = {}


def _key(ctx: CplugContext) -> str:
    return str(ctx.storage.path)


def current(ctx: CplugContext) -> Optional[dict]:
    with _lock:
        found = _focus.get(_key(ctx))
        return dict(found) if found else None


def _publish(ctx: CplugContext) -> None:
    try:
        ctx.notify("focus")
    except (RuntimeError, ValueError) as exc:
        ctx.log.warning("task_manager_focus_notify_failed", error=str(exc))


def clear(ctx: CplugContext) -> dict:
    with _lock:
        had = _focus.pop(_key(ctx), None)
    if had is not None:
        _publish(ctx)
    return {"focus": None}


def live_items(store: "service.TaskManagerStore", list_key: str) -> Dict[int, dict]:
    if list_key == ALL_LIST:
        lists = store.aggregate()["groups"]
    else:
        lists = [store.list_items(list_key)]
    return {i["id"]: i for body in lists for i in body["items"]}


def set_focus(ctx: CplugContext, list_key: str, items: Sequence[int], open_id: Optional[int], *,
              mark_unread: bool = False) -> dict:
    check_list_key(list_key)
    wanted: List[int] = []
    for value in list(items) + ([open_id] if open_id is not None else []):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TaskManagerInvalid("items and open are item ids (integers)")
        if value not in wanted:
            wanted.append(value)
    if not wanted:
        raise TaskManagerInvalid("name at least one item to focus (or pass clear)")
    if len(wanted) > MAX_FOCUS_ITEMS:
        raise TaskManagerInvalid(f"at most {MAX_FOCUS_ITEMS} items in one focus")
    store = service.store(ctx)
    live = live_items(store, list_key)
    stray = [i for i in wanted if i not in live]
    if stray:
        raise TaskManagerNotFound(f"not live items of list {list_key}: {', '.join(map(str, stray))}")
    if mark_unread:
        for key in sorted({live[i]["list"] for i in wanted}):
            store.mark_unread(key, [i for i in wanted if live[i]["list"] == key])
    focus = {"seq": time.time_ns() // 1000, "list": list_key, "items": wanted, "open": open_id, "at": time.time()}
    with _lock:
        _focus[_key(ctx)] = focus
    _publish(ctx)
    return {"focus": dict(focus)}
