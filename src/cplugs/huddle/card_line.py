
from __future__ import annotations

import json
from typing import Optional

from src.cplugs.sdk import chat_category

KEY = "card_line"


def parts_for(swarm_ref: str) -> str:
    if not swarm_ref.startswith(chat_category.CARD_REF_PREFIX):
        return ""
    tail = swarm_ref[len(chat_category.CARD_REF_PREFIX):].split(":", 1)
    if len(tail) != 2 or not tail[1].isdigit() or int(tail[1]) < 1:
        return ""
    return json.dumps({KEY: int(tail[1])})


def read(raw: str) -> Optional[int]:
    if not raw or KEY not in raw:
        return None
    try:
        value = json.loads(raw)[KEY]
    except (ValueError, KeyError, TypeError):
        return None
    return value if type(value) is int and value > 0 else None
