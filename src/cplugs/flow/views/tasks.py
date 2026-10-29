
from __future__ import annotations

import re
from typing import Any, Dict, List

from src.cplugs.flow.views.text import clean_title, short

COLUMNS = ("created", "in_progress", "review", "done")
_COLUMN_OF = {"todo": "created", "created": "created", "": "created", "in_progress": "in_progress", "review": "review", "done": "done"}
LINK_BEFORE_S, LINK_AFTER_S = 5.0, 180.0


def column_of(card_col: str) -> str:
    return _COLUMN_OF.get(card_col or "", "in_progress")


def item_tasks(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    seed = run["seed"]
    seed_item = int(seed["id"]) if seed["kind"] == "huddle_item" and str(seed["id"]).isdigit() else None
    moves: Dict[int, List[Dict[str, Any]]] = {}
    for m in run["marks"]:
        if m["kind"] == "card" and m.get("item_id") is not None:
            moves.setdefault(m["item_id"], []).append({"t": m["t"], "col": column_of(m.get("to_col") or ""), "agent": m["lane"]})
    out = []
    for m in run["marks"]:
        if m["kind"] != "huddle_add":
            continue
        item = m["item_id"]
        ev = sorted(moves.get(item, []), key=lambda x: x["t"])
        title = clean_title(m.get("title") or "") or short(m["label"], 64)
        out.append({"id": f"#{item}", "kind": "item", "agent": m["lane"], "title": title, "status": ev[-1]["col"] if ev else "created",
                    "t": m["t"], "end": max([m["t"]] + [x["t"] for x in ev]), "root": item == seed_item,
                    "review": re.sub(r"[*_]", "", str(m.get("review") or "").split("\n")[0]), "events": ev})
    return out


def subagent_tasks(run: Dict[str, Any], lanes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    returned = {e["from"]["lane"]: e for e in run["edges"] if e["kind"] == "subagent_return"}
    spans: Dict[str, float] = {}
    for b in run["blocks"]:
        if b["kind"] == "subagent":
            spans[b["lane"]] = b["end"]
    out = []
    launches = sorted((e for e in run["edges"] if e["kind"] == "subagent_launch"), key=lambda e: e["from"]["t"])
    for n, e in enumerate(launches, 1):
        lane = e["to"]["lane"]
        ret = returned.get(lane)
        end = ret["from"]["t"] if ret else spans.get(lane, e["to"]["t"])
        out.append({"id": f"S{n}", "kind": "sub", "agent": lane, "title": lanes[lane]["label"].partition(": ")[2] or lanes[lane]["label"],
                    "status": "done" if ret else "in_progress", "t": e["from"]["t"], "end": max(end, e["from"]["t"]), "root": False,
                    "review": "", "events": [{"t": end, "col": "done", "agent": lane}] if ret else [], "launch": e["id"]})
    return out


def link_edges(tasks: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {t["launch"]: t["id"] for t in tasks if t["kind"] == "sub"}
    for e in edges:
        if e["kind"] != "crosstalk" or e["id"] in out:
            continue
        hit = next((t for t in tasks if t["kind"] == "item" and not t["root"] and t["agent"] == e["to"]["lane"]
                    and e["from"]["t"] - LINK_BEFORE_S <= t["t"] <= e["from"]["t"] + LINK_AFTER_S), None)
        if hit:
            out[e["id"]] = hit["id"]
    return out
