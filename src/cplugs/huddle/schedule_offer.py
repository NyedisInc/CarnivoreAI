
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.cplugs.huddle import triggers
from src.cplugs.huddle.rules import TaskManagerInvalid

KEY = "schedule"
OFFERED, ACCEPTED = "offered", "accepted"
MAX_TITLE = 80


def clean(offer: Any, now: Optional[float] = None) -> Dict[str, str]:
    if not isinstance(offer, dict) or set(offer) - {"when", "title"}:
        raise TaskManagerInvalid("offer_schedule must be {when, title}")
    stamp = triggers.parse_fire_at(offer.get("when"), time.time() if now is None else now)
    if stamp is None:
        raise TaskManagerInvalid("offer_schedule.when must be an ISO 8601 time with a UTC offset")
    title = offer.get("title")
    if not isinstance(title, str) or not title.strip():
        raise TaskManagerInvalid("offer_schedule.title is required: a few words naming the follow-up")
    return {"when": datetime.fromisoformat(offer["when"].strip()).isoformat(), "title": title.strip()[:MAX_TITLE], "state": OFFERED}


def attach(parts: str, offer: Dict[str, str]) -> str:
    base = json.loads(parts) if parts else {}
    return json.dumps({**base, KEY: offer}, ensure_ascii=False)


def read(raw: str) -> Optional[Dict[str, str]]:
    if not raw or KEY not in raw:
        return None
    try:
        data = json.loads(raw)[KEY]
        return {k: str(data[k]) for k in ("when", "title", "state") if k in data} | ({"accepted_at": str(data["accepted_at"])} if "accepted_at" in data else {})
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def accept(raw: str, stamp: str) -> str:
    data = json.loads(raw)
    data[KEY] = {**data[KEY], "state": ACCEPTED, "accepted_at": stamp}
    return json.dumps(data, ensure_ascii=False)


def instruction(offer: Dict[str, str], message_id: int) -> str:
    return (f"schedule this (your offer in message {message_id}): file a scheduled item now with task_manager_add fire_at={offer['when']}, "
            f"titled \"{offer['title']}\", then reply here with the date.")
