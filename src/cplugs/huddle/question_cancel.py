
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.huddle import rules

CANCEL_NOTE = "cancelled this question. you decide what happens next."


def cancel(store: Any, item_id: int) -> Dict[str, Any]:
    item = store.item(item_id)
    if not any(m["kind"] == rules.QUESTION and not m["answered"] for m in item["thread"]):
        raise rules.TaskManagerInvalid(f"item {item_id} has no open question to cancel")
    store.mark_answered(item_id, actor=rules.JOE)
    store.post(item_id, CANCEL_NOTE, actor=rules.JOE, kind=rules.REPLY)
    if item["state"] in (rules.REVIEW, rules.WAITING):
        store.update(item_id, actor=rules.JOE, state=rules.OPEN)
    return store.item(item_id)
