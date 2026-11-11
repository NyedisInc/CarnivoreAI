
from __future__ import annotations

import json
from typing import Any, Dict, List

SYSTEM = (
    "You decide which work item a coding session is working on. You get a list of candidate work items (id, kind, title, parent), the id of the "
    "item the session is on now, and three signals: the git branch, the files changed, and the last prompt the owner typed. Score EVERY candidate "
    "from 0 to 1 for how well it fits the signals. Only if no candidate fits at 0.5 or better, you may propose one new feature title (short, plain, "
    "lowercase, no ticket numbers) with your own confidence from 0 to 1. Never invent an id. Reply with ONLY a JSON object: "
    '{"scores": {"<candidate id>": <0 to 1>}, "new_feature": {"title": "<name>", "confidence": <0 to 1>} or null}.'
)


def build(signals: Dict[str, Any], candidates: List[Dict[str, str]], current_id: str) -> str:
    return json.dumps({"current_item_id": current_id, "candidates": candidates, "signals": signals}, sort_keys=True)
