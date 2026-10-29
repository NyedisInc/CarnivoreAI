
from __future__ import annotations

import json
from typing import Any, Dict, Optional

KEY = "board"
FIELDS = ("slug", "revision", "title", "summary")


def parts_of(card: Dict[str, Any]) -> str:
    return json.dumps({KEY: {k: str(card[k]) for k in FIELDS}}, ensure_ascii=False)


def wire(raw: str) -> Optional[Dict[str, str]]:
    if not raw or not raw.startswith(f'{{"{KEY}"'):
        return None
    try:
        card = json.loads(raw)[KEY]
        return {k: str(card[k]) for k in FIELDS} if isinstance(card, dict) else None
    except (ValueError, KeyError, TypeError):
        return None


ROUND_KEY = "board_round"
ROUND_FIELDS = ("slug", "round", "revision")


def round_parts_of(ref: Dict[str, Any]) -> str:
    return json.dumps({ROUND_KEY: {k: str(ref[k]) for k in ROUND_FIELDS}}, ensure_ascii=False)


def round_wire(raw: str) -> Optional[Dict[str, str]]:
    if not raw or not raw.startswith(f'{{"{ROUND_KEY}"'):
        return None
    try:
        ref = json.loads(raw)[ROUND_KEY]
        return {k: str(ref[k]) for k in ROUND_FIELDS} if isinstance(ref, dict) else None
    except (ValueError, KeyError, TypeError):
        return None
