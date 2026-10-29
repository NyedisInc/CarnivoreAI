
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from src.cplugs.huddle.rules import TaskManagerInvalid

KEY = "quote"
MAX_QUOTE = 1000
PREFIX = '{"quote"'


def build(conn: sqlite3.Connection, item_id: int, quote: Optional[int], quote_text: str, base: str = "") -> str:
    given = quote_text.strip() if isinstance(quote_text, str) else ""
    if (quote is None) == (not given):
        raise TaskManagerInvalid("an answer quotes the question it answers: pass quote (a message id on this item) or quote_text, not both")
    message_id: Optional[int] = None
    if quote is not None:
        if isinstance(quote, bool) or not isinstance(quote, int):
            raise TaskManagerInvalid("quote must be a message id")
        found = conn.execute("SELECT text FROM work_messages WHERE id = ? AND item_id = ?", (quote, item_id)).fetchone()
        if found is None:
            raise TaskManagerInvalid(f"quote: message {quote} is not on item {item_id}")
        message_id, given = quote, str(found[0]).strip()
    if not given:
        raise TaskManagerInvalid("the quoted question is empty")
    kept = json.loads(base) if base else {}
    return json.dumps({KEY: {"id": message_id, "text": given[:MAX_QUOTE]}, **{k: v for k, v in kept.items() if k != KEY}}, ensure_ascii=False)


def wire(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or not raw.startswith(PREFIX):
        return None
    try:
        data = json.loads(raw)[KEY]
        return {"id": data.get("id"), "text": str(data["text"])}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


__all__ = ["KEY", "MAX_QUOTE", "build", "wire"]
