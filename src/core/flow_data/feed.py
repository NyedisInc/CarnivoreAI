
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SKEW_S = 5.0
MAX_ITEMS = 1500
WORK_CALLS_MAX = 40
RANK = {"crosstalk": 0, "spawn": 0, "launch": 0, "huddle": 1, "task": 1, "bubble": 2, "work": 3, "return": 4}
EDGE_CARDS = {"crosstalk": "crosstalk", "spawn": "spawn", "subagent_launch": "launch", "subagent_return": "return",
              "huddle_post": "huddle", "owner_reply": "huddle"}


def lanes_view(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id = {lane["id"]: lane for lane in run["lanes"]}
    out, color = [], 0
    for lane in run["lanes"]:
        depth, parent = 0, lane.get("parent")
        while parent and parent in by_id and depth < 8:
            depth, parent = depth + 1, by_id[parent].get("parent")
        view = {"id": lane["id"], "kind": lane["kind"], "label": lane["label"], "parent": lane.get("parent"), "depth": depth, "color": None}
        if lane["kind"] != "owner":
            view["color"], color = color, color + 1
        out.append(view)
    return out


def _work_cards(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    marks: Dict[str, List[Tuple[float, int, Optional[Dict[str, Any]]]]] = {}
    for say in run.get("says", []):
        marks.setdefault(say["lane"], []).append((say["t"], 0, None))
    for block in run["blocks"]:
        if block["kind"] == "turn":
            marks.setdefault(block["lane"], []).append((block["start"], 0, None))
    for call in run.get("calls", []):
        marks.setdefault(call["lane"], []).append((call["start"], 1, call))
    cards: List[Dict[str, Any]] = []
    for lane, seq in marks.items():
        group: List[Dict[str, Any]] = []
        for _, _, call in sorted(seq, key=lambda m: (m[0], m[1], (m[2] or {}).get("id", ""))):
            if call is None:
                if group:
                    cards.append(_work(lane, group))
                group = []
            else:
                group.append(call)
        if group:
            cards.append(_work(lane, group))
    return cards


def _work(lane: str, calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    tally: Dict[str, int] = {}
    for call in calls:
        tally[call["tool"]] = tally.get(call["tool"], 0) + 1
    end = max(call["end"] for call in calls)
    return {"id": f"work:{calls[0]['id']}", "kind": "work", "lane": lane, "t": calls[0]["start"], "u": end, "count": len(calls),
            "tools": dict(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))), "duration_s": round(end - calls[0]["start"], 1),
            "calls": [{"tool": c["tool"], "start": c["start"], "end": c["end"]} for c in calls[-WORK_CALLS_MAX:]]}


def _edge_card(edge: Dict[str, Any], runs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    kind = EDGE_CARDS[edge["kind"]]
    t_from, t_to = edge["from"]["t"], edge["to"]["t"]
    card = {"id": f"{kind}:{edge['id']}", "kind": kind, "lane": edge["from"]["lane"], "to": edge["to"]["lane"], "t": t_from,
            "u": max(t_from, t_to), "label": edge.get("label", ""), "inferred": bool(edge.get("inferred"))}
    if kind == "crosstalk":
        card.update(thread=edge.get("thread"), reply_to=edge.get("reply_to"), status=edge.get("status"), delivered=not edge.get("undelivered"),
                    landed=edge.get("located_by") in ("landed", "header", "column"), located_by=edge.get("located_by"),
                    delivery_path=edge.get("delivery_path"), t_to=t_to, message_id=edge["id"])
    elif kind == "spawn":
        card.update(basis=edge.get("basis"))
    elif kind == "return":
        block = runs.get(edge["from"]["lane"]) or {}
        card.update(t=t_to, status=edge.get("label"), duration_s=round(block["end"] - block["start"], 1) if block else None,
                    tool_count=sum((block.get("tools") or {}).values()) if block else None)
    elif kind == "huddle":
        source = edge.get("source") or {}
        card.update(item_id=source.get("item_id"), message_id=source.get("message_id"), owner=edge["kind"] == "owner_reply")
    return card


def _mark_card(mark: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": f"task:{mark['id']}", "kind": "task", "lane": mark["lane"], "t": mark["t"], "u": mark["t"], "label": mark.get("label", ""),
            "inferred": bool(mark.get("inferred")), "item_id": mark.get("item_id") or (mark.get("source") or {}).get("item_id"),
            "change": "filed" if mark["kind"] == "huddle_add" else "moved", "from_col": mark.get("from_col"), "to_col": mark.get("to_col")}


def items(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    runs = {b["lane"]: b for b in run["blocks"] if b["kind"] == "subagent"}
    out = [{"id": say["id"], "kind": "bubble", "lane": say["lane"], "t": say["t"], "u": say["t"], "role": say["role"], "text": say["text"]}
           for say in run.get("says", [])]
    out += _work_cards(run)
    out += [_edge_card(e, runs) for e in run["edges"] if e["kind"] in EDGE_CARDS]
    out += [_mark_card(m) for m in run["marks"]]
    out.sort(key=lambda i: (i["t"], RANK[i["kind"]], i["id"]))
    return out[-MAX_ITEMS:]


def page(run: Dict[str, Any], cursor: Optional[float]) -> Dict[str, Any]:
    every = items(run)
    newest = max((i["u"] for i in every), default=cursor or 0.0)
    sent = every if cursor is None else [i for i in every if i["u"] > cursor - SKEW_S]
    return {"seed": run["seed"], "window": run["window"], "lanes": lanes_view(run), "items": sent,
            "cursor": max(newest, cursor or 0.0), "total": len(every), "full": cursor is None, "warnings": run.get("warnings", [])}
