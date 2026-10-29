
from __future__ import annotations

from typing import Any, Dict, Optional

from src.cplugs.huddle import rules


MAX_TITLE = 120
FIELD = "title"


def clean_fields(value: Optional[object]) -> Dict[str, Optional[str]]:
    if value is None:
        return {}
    text = rules.clean_text(value, FIELD, MAX_TITLE, allow_blank=True)
    return {FIELD: text or None}


def display(item: Dict[str, Any]) -> str:
    text = (item.get("text") or "").strip()
    for value in (item.get("title"), text.splitlines()[0] if text else ""):
        if value and str(value).strip():
            return str(value).strip()[:200]
    return f"item {item['id']}"
