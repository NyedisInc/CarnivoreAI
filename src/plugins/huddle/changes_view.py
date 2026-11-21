
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

MAX_SESSIONS = 64

MAX_ITEMS = 5000

THIN_FIELDS = ("status", "section", "revision")

_SENT: "OrderedDict[str, Dict[int, Tuple[Any, Any]]]" = OrderedDict()


def remember(session_id: Optional[str], items: Iterable[Mapping[str, Any]]) -> None:
    if not session_id:
        return
    held = _SENT.setdefault(session_id, {})
    _SENT.move_to_end(session_id)
    for item in items:
        if item.get("deleted"):
            held.pop(item["id"], None)
        else:
            held[item["id"]] = (item.get("revision"), item.get("group"))
    while len(held) > MAX_ITEMS:
        held.pop(next(iter(held)))
    while len(_SENT) > MAX_SESSIONS:
        _SENT.popitem(last=False)


def is_thin(session_id: Optional[str], item: Mapping[str, Any]) -> bool:
    if not session_id or item.get("deleted"):
        return False
    return _SENT.get(session_id, {}).get(item["id"]) == (item.get("revision"), item.get("group"))


def slim(session_id: Optional[str], items: List[dict], reset: bool) -> List[dict]:
    out: List[dict] = []
    full: List[dict] = []
    for item in items:
        if not reset and is_thin(session_id, item):
            out.append({"id": item["id"], **{k: item[k] for k in THIN_FIELDS if k in item}})
        else:
            out.append(item)
            full.append(item)
    remember(session_id, full)
    return out
