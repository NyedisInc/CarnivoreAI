
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.cplugs.flow.views import events as ev, tasks as tk, tree
from src.cplugs.flow.views.text import clock, display_name, monogram, short

SEGMENT_GAP_S = 90.0


def _agents(run: Dict[str, Any], parent: Dict[str, Optional[str]], sent: Dict[str, int]) -> List[Dict[str, Any]]:
    out = []
    for lane in run["lanes"]:
        mine = [b for b in run["blocks"] if b["lane"] == lane["id"]]
        turns = sum(1 for b in mine if b["kind"] == "turn")
        a: Dict[str, Any] = {"id": lane["id"], "parent": parent.get(lane["id"]), "full": lane["label"], "kind": lane["kind"]}
        if lane["kind"] == "owner":
            a.update(name="Joe", role="Owner", desc="Answers questions and approves the result.", mono="J")
        elif lane["kind"] == "subagent":
            kind, _, title = lane["label"].partition(": ")
            a.update(name=kind, role="Subagent", desc=title, mono=kind[:1].upper())
        else:
            parts = Path(lane.get("working_dir") or "").parts
            where = parts[-1] if parts else ""
            name = display_name(lane["label"])
            a.update(name=name, role="Session" + (", " + where if where else ""), mono=monogram(name),
                     desc=f"{turns} turns in window, {sent.get(lane['id'], 0)} messages sent.")
        out.append(a)
    return out


def _segments(run: Dict[str, Any]) -> Dict[str, List[List[float]]]:
    out: Dict[str, List[List[float]]] = {}
    for b in sorted((b for b in run["blocks"] if b["kind"] in ("turn", "subagent")), key=lambda b: b["start"]):
        segs = out.setdefault(b["lane"], [])
        if segs and b["start"] - segs[-1][1] <= SEGMENT_GAP_S:
            segs[-1][1] = max(segs[-1][1], b["end"])
        else:
            segs.append([b["start"], b["end"]])
    return out


def _graph(events: List[Dict[str, Any]], parent: Dict[str, Optional[str]], tasks_by_id: Dict[str, Dict[str, Any]], seed: str) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for r in events:
        if r["cls"] is None or r["to"] is None:
            continue
        key = f"{r['from']}|{r['to']}|{r['cls']}"
        g = agg.setdefault(key, {"id": f"e{len(agg)}", "from": r["from"], "to": r["to"], "cls": r["cls"], "n": 0, "kinds": set(), "tip": r["quote"],
                                 "t": r["t"], "task": r["task"] if r["cls"] == "delegate" else None})
        g["n"] += 1
        g["kinds"].add(r["edge_kind"])
        r["edge"] = g["id"]
    for g in agg.values():
        g["kinds"] = sorted(g["kinds"])
        more = f" x{g['n']}" if g["n"] > 1 else ""
        if g["cls"] == "delegate":
            g["label"] = ("Delegates " + g["task"] if g["task"] else ("Answers question" if "owner_reply" in g["kinds"] else "Delegates")) + more
        elif g["cls"] == "context":
            g["label"] = "Shares context" + more
        else:
            root = next((t["id"] for t in tasks_by_id.values() if t["root"]), "the item")
            g["label"] = ("Reports on " + root if "huddle_post" in g["kinds"] else ("Returns result" if "subagent_return" in g["kinds"] else "Returns findings")) + more
    return list(agg.values())


def build_view(run: Dict[str, Any], tz: Optional[dt.tzinfo] = None) -> Dict[str, Any]:
    tz = tz or dt.datetime.now().astimezone().tzinfo
    parent = tree.assign_parents(run["lanes"], run["edges"])
    lanes = {lane["id"]: lane for lane in run["lanes"]}
    all_tasks = tk.item_tasks(run) + tk.subagent_tasks(run, lanes)
    links = tk.link_edges(all_tasks, run["edges"])
    events, off = ev.build_events(run, parent, all_tasks, links, tz)
    sent: Dict[str, int] = {}
    for r in events:
        if r["edge_kind"] == "crosstalk":
            sent[r["from"]] = sent.get(r["from"], 0) + 1
    graph = _graph(events, parent, {t["id"]: t for t in all_tasks}, str(run["seed"]["id"]))
    root = next((t for t in all_tasks if t["root"]), None)
    final = None
    if root and root["review"]:
        final = {"title": "Final result", "text": short(root["review"], 80), "time": clock(root["end"], tz), "task": root["id"]}
    start = dt.datetime.fromtimestamp(run["window"]["start"], tz)
    for t in all_tasks:
        t["time"] = clock(t["t"], tz)
        t.pop("review", None)
        t.pop("launch", None)
    seed = run["seed"]
    title = f"Item #{seed['id']}" if seed["kind"] == "huddle_item" else f"Session {seed['id']}"
    return {"title": title, "date": start.strftime("%Y-%m-%d"), "tz": start.strftime("%Z") or "local",
            "tz_offset": int((start.utcoffset() or dt.timedelta(0)).total_seconds()), "window": run["window"],
            "agents": _agents(run, parent, sent), "tasks": all_tasks, "events": events, "edges": graph, "segments": _segments(run),
            "idle_gaps": run["idle_gaps"], "final": final, "stats": run["stats"], "offtree": off}
