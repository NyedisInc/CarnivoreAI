
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.flow.views import tree
from src.cplugs.flow.views.text import clock, short


def _agent(lane: str) -> Dict[str, str]:
    return {"a": lane}


def _edge_event(e: Dict[str, Any], cls: Optional[str], lanes: Dict[str, Dict[str, Any]], links: Dict[str, str], seed: str) -> Dict[str, Any]:
    f, t, kind = e["from"]["lane"], e["to"]["lane"], e["kind"]
    quote, task = short(e["label"]), links.get(e["id"])
    item = (e.get("source") or {}).get("item_id")
    if kind == "subagent_launch":
        what = "delegate", [_agent(f), " launched subagent ", _agent(t), ": ", short(lanes[t]["label"].partition(": ")[2])]
        acts = [{"a": "creates", "task": task, "to": t}]
    elif kind == "subagent_return":
        what = "return", [_agent(f), " returned its result to ", _agent(t), "."]
        acts = [{"a": "completes", "task": links.get("ret:" + e["id"])}, {"a": "returns", "to": t}]
        quote = ""
    elif kind == "huddle_post":
        what = "chat", [_agent(f), " posted to ", _agent(t), ": ", quote]
        acts = [{"a": "comments", "task": f"#{item}" if item is not None else None}]
    elif kind == "owner_reply":
        what = "chat", [_agent(f), " answered ", _agent(t), " on the huddle: ", quote.replace("answers to 1 question", "1 question")]
        acts = [{"a": "comments", "task": f"#{item}" if item is not None else None}]
    elif cls == "delegate":
        what = "delegate", [_agent(f), " delegated to ", _agent(t), ": ", quote]
        acts = [{"a": "delegates", "to": t, "task": task}]
    elif cls == "return":
        what = "return", [_agent(f), " returned findings to ", _agent(t), ": ", quote]
        acts = [{"a": "returns", "to": t}]
    else:
        what = "chat", [_agent(f), " shared context with ", _agent(t), ": ", quote]
        acts = [{"a": "returns", "to": t}]
    return {"id": e["id"], "t": e["from"]["t"], "t_to": e["to"]["t"], "kind": what[0], "from": f, "to": t, "text": what[1], "quote": quote,
            "task": task, "acts": acts, "cls": cls, "edge_kind": kind}


def _mark_events(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for task in tasks:
        if task["kind"] != "item":
            continue
        who, ref = task["agent"], task["id"]
        verb = " created by " if task["root"] else " filed by "
        out.append({"id": f"c:{ref}", "t": task["t"], "t_to": task["t"], "kind": "task_created", "from": who, "to": None,
                    "text": ["Task ", ref, verb, _agent(who), ": ", short(task["title"], 64)], "quote": "", "task": ref,
                    "acts": [{"a": "creates", "task": ref, "root": task["root"]}], "cls": None, "edge_kind": "mark"})
        for n, ev in enumerate(task["events"]):
            col, actor = ev["col"], ev["agent"]
            if col == "done":
                text, kind, act = [_agent(actor), " moved " if actor != tree.OWNER else " approved ", ref, " to done." if actor != tree.OWNER else " as done."], "task_done", "completes"
            elif col == "review":
                text, kind, act = [_agent(actor), " moved ", ref, " to review."], "task_updated", "completes"
            else:
                text, kind, act = [_agent(actor), " moved ", ref, " to " + col.replace("_", " ") + "."], "task_updated", "updates"
            out.append({"id": f"m:{ref}:{n}", "t": ev["t"], "t_to": ev["t"], "kind": kind, "from": actor, "to": None, "text": text, "quote": "",
                        "task": ref, "acts": [{"a": act, "task": ref, "col": col}], "cls": None, "edge_kind": "mark"})
    return out


def build_events(run: Dict[str, Any], parent: Dict[str, Optional[str]], tasks: List[Dict[str, Any]], links: Dict[str, str],
                 tz: Optional[dt.tzinfo]) -> Tuple[List[Dict[str, Any]], int]:
    lanes = {lane["id"]: lane for lane in run["lanes"]}
    ret_of = {t["events"][0]["agent"]: t["id"] for t in tasks if t["kind"] == "sub" and t["events"]}
    links = dict(links, **{"ret:" + e["id"]: ret_of[e["from"]["lane"]] for e in run["edges"] if e["kind"] == "subagent_return" and e["from"]["lane"] in ret_of})
    events, off = [], 0
    for e in run["edges"]:
        cls = tree.classify(e, parent)
        off += cls is None
        events.append(_edge_event(e, cls, lanes, links, str(run["seed"]["id"])))
    events += _mark_events(tasks)
    events.sort(key=lambda r: (r["t"], r["id"]))
    for r in events:
        r["time"] = clock(r["t"], tz)
    return events, off
