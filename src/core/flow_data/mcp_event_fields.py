
from __future__ import annotations

import json
import re
from typing import Any, Dict, FrozenSet, List, Optional

ID_ARGS: FrozenSet[str] = frozenset({
    "target", "targets", "to", "item", "items", "message_id", "session", "session_id", "id", "ids", "list", "thread",
    "card", "parent", "project", "group", "group_id", "company", "open", "automation", "bookmark", "peer", "computer"})
MAX_IDS = 8
MAX_ID_LEN = 100
_ID_SHAPE = re.compile(r'^[A-Za-z0-9_:.@-]{1,%d}$' % MAX_ID_LEN)
DENIAL_MARKERS = ("denied", "declined", "refused", "read-only", "is off", "not approved", "owner rejected", "not allowed")


def _as_ids(value: Any) -> List[str]:
    values = value if isinstance(value, list) else [value]
    kept = []
    for item in values:
        if isinstance(item, bool):
            continue
        text = str(item) if isinstance(item, int) else item
        if isinstance(text, str) and _ID_SHAPE.match(text):
            kept.append(text)
    return kept


def target_ids(args: Any) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    found: Dict[str, List[str]] = {}
    budget = MAX_IDS
    for name in sorted(ID_ARGS & set(args)):
        ids = _as_ids(args[name])[:budget]
        if ids:
            found[name] = ids
            budget -= len(ids)
        if budget <= 0:
            break
    return json.dumps(found, sort_keys=True) if found else None


def outcome_of(result: Any, denied_by_gate: bool = False) -> str:
    if denied_by_gate:
        return 'denied'
    if not isinstance(result, dict) or not result.get('isError'):
        return 'ok'
    blocks = result.get('content')
    text = ' '.join(str(b.get('text') or '') for b in blocks if isinstance(b, dict)).lower() if isinstance(blocks, list) else ''
    return 'denied' if any(marker in text for marker in DENIAL_MARKERS) else 'error'


RESULT_ID_KEYS: FrozenSet[str] = frozenset({"id", "item_id", "message_id", "thread", "session_id", "parent", "to", "card_id", "task_message"})
MAX_RESULT_CHARS = 20000


def result_ids(result: Any) -> Optional[str]:
    blocks = result.get("content") if isinstance(result, dict) else None
    if not isinstance(blocks, list) or not blocks or not isinstance(blocks[0], dict):
        return None
    text = blocks[0].get("text")
    if not isinstance(text, str) or len(text) > MAX_RESULT_CHARS or not text.startswith("{"):
        return None
    try:
        body = json.loads(text)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    found: Dict[str, List[str]] = {}
    for key in sorted(RESULT_ID_KEYS & set(body)):
        value = body[key]
        if key == "task_message":
            value = value.get("id") if isinstance(value, dict) else None
        ids = _as_ids(value)[:MAX_IDS]
        if ids:
            found[key] = ids
    return json.dumps(found, sort_keys=True) if found else None
