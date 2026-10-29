
from __future__ import annotations

from typing import Any, Dict, List

from src.cplugs.huddle import status_lines

NUDGE_CATEGORY = "nudge"
SYSTEM_CATEGORIES = (NUDGE_CATEGORY, status_lines.CATEGORY)


def slim_thread(thread: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep = {m["id"] for m in thread if m.get("unread") or (m.get("kind") == "question" and not m.get("answered"))}
    questions = [m for m in thread if m.get("kind") == "question"]
    if questions:
        keep.add(questions[-1]["id"])
    preview = [m for m in thread if m.get("category") not in SYSTEM_CATEGORIES]
    if preview:
        keep.add(preview[-1]["id"])
    own = [m for m in thread if m.get("author") == "joe" and m.get("kind") == "reply"]
    if own:
        keep.add(own[-1]["id"])
    answers = [m for m in thread if m.get("author") == "claude" and m.get("kind") == "answer" and (m.get("quote") or {}).get("id") is not None]
    if answers:
        keep.update((answers[-1]["id"], answers[-1]["quote"]["id"]))
    keep.update(m["answers_to"] for m in thread if m["id"] in keep and m.get("answers_to"))
    kept_questions = {m["id"] for m in questions if m["id"] in keep}
    keep.update(m["id"] for m in thread if m.get("answers_to") in kept_questions)
    return [m for m in thread if m["id"] in keep]


def slim_item(item: Dict[str, Any]) -> Dict[str, Any]:
    thread = item.get("thread", [])
    return {**item, "thread": slim_thread(thread), "thread_count": len(thread), "thread_slim": True}


def slim_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**g, "items": [slim_item(i) for i in g["items"]]} for g in groups]
