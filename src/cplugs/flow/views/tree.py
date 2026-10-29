
from __future__ import annotations

from typing import Any, Dict, List, Optional

OWNER = "owner"
_DOWN_KINDS = {"subagent_launch", "owner_reply"}
_UP_KINDS = {"subagent_return", "huddle_post"}


def assign_parents(lanes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    ids = [lane["id"] for lane in lanes]
    root = OWNER if OWNER in ids else ids[0]
    parent: Dict[str, Optional[str]] = {root: None}
    explicit = {lane["id"]: lane.get("parent") or (lane.get("spawned_by") or {}).get("lane") for lane in lanes}
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    for e in sorted(edges, key=lambda e: e["from"]["t"]):
        if e["kind"] in ("crosstalk", "owner_reply"):
            incoming.setdefault(e["to"]["lane"], []).append(e)
    pending = [i for i in ids if i != root]
    while pending:
        placed = False
        for lid in list(pending):
            cand = explicit.get(lid) if explicit.get(lid) in ids else None
            if cand is None:
                cand = next((e["from"]["lane"] for e in incoming.get(lid, []) if e["from"]["lane"] in parent), None)
            if cand is not None and cand in parent:
                parent[lid] = cand
                pending.remove(lid)
                placed = True
        if not placed:
            for lid in pending:
                parent[lid] = root
            break
    return parent


def classify(edge: Dict[str, Any], parent: Dict[str, Optional[str]]) -> Optional[str]:
    src, dst = edge["from"]["lane"], edge["to"]["lane"]
    down, up = parent.get(dst) == src, parent.get(src) == dst
    if not (down or up):
        return None
    kind = edge["kind"]
    if kind in _DOWN_KINDS:
        return "delegate"
    if kind in _UP_KINDS:
        return "return"
    if up:
        return "return"
    return "context" if edge.get("reply_to") else "delegate"
