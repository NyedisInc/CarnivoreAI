
from __future__ import annotations

from typing import Any, Dict, List

from src.cplugs.huddle import lifecycle, rules
from src.cplugs.sdk import chat_category

CHAT_REF = "chat"


def card_kind(item: Dict[str, Any]) -> str:
    status, kind = item.get("status"), item.get("kind")
    if status == lifecycle.QUESTION or kind == rules.QUESTION:
        return "question"
    if status == lifecycle.REVIEW or kind == "waiting":
        return "review"
    return "done" if kind == "done" else "info"


def entries(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in body["items"]:
        if item["swarm_ref"] != CHAT_REF:
            entry = {"kind": "card", "id": f"item:{item['id']}", "at": item["created_at"], "card": card_kind(item),
                     "item": item}
            out.append({**entry, "category": chat_category.derive(entry)})
            continue
        for msg in item["thread"]:
            if msg["author_key"] == rules.SWARM_KEY:
                if msg.get("category"):
                    out.append({"kind": "event", "id": f"msg:{msg['id']}", "at": msg["created_at"], "event": "card",
                                "ref": "", "text": msg["text"], "category": msg["category"]})
                continue
            owner = msg["author_key"] == rules.OWNER_KEY
            entry = {"kind": "owner" if owner else "agent", "id": f"msg:{msg['id']}", "at": msg["created_at"],
                     "text": msg["text"]}
            out.append({**entry, "category": chat_category.derive(entry)})
    return sorted(out, key=lambda e: (e["at"], e["id"]))
