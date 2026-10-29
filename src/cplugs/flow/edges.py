
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.cplugs.flow import participants
from src.cplugs.flow.transcript import ENVELOPE_RE, Scan, parse_ts

OWNER_LANE = "owner"
CARD_MATCH_S = 3.0
CHANNEL_MATCH_S = 15.0
LABEL_MAX = 100
MAX_ITEMS = 12
SPAWN_RANK = {"spawn_link": 0, "lineage": 1, "parent_session_id": 2, "transcript": 3, "contact": 4}
_INFERRED_SPAWN = frozenset({"transcript", "contact"})


def source_ref(scan: Scan, line: int, line_to: int = 0, uuid: Any = None) -> Dict[str, Any]:
    return {"conversation_id": scan.conversation_id, "path": scan.path, "line": line, "line_to": line_to or line, "uuid": uuid}


def edge(edge_id: str, kind: str, lane_from: str, t_from: float, lane_to: str, t_to: float, label: str = "", *,
         inferred: bool = False, source: Optional[Dict[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
    return {"id": edge_id, "kind": kind, "from": {"lane": lane_from, "t": t_from}, "to": {"lane": lane_to, "t": max(t_to, t_from)},
            "label": label[:LABEL_MAX], "inferred": inferred, "source": source or {}, **extra}


def first_line(text: Any) -> str:
    for line in str(text or "").splitlines():
        if line.strip() and not ENVELOPE_RE.search(line):
            return line.strip()
    return ""


def _index(scans: Dict[str, List[Scan]], attr: str, key: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for items in scans.values():
        for scan in items:
            for fact in getattr(scan, attr):
                out.setdefault(fact[key], (scan, fact))
    return out


def _landed_ref(m: Dict[str, Any]) -> Dict[str, Any]:
    anchor = str(m.get("landed_anchor") or "")
    parts = anchor.split(":", 2)
    return {"conversation_id": parts[2] if len(parts) == 3 and parts[0] == "native" else None, "line": None, "anchor": anchor or None,
            "header": m.get("landed_header")}


def crosstalk_edges(out: Dict[str, Any], messages: List[Dict[str, Any]], lane_of: Dict[str, str], scans: Dict[str, List[Scan]]) -> None:
    sends, receipts = _index(scans, "sends", "msg_id"), _index(scans, "receipts", "msg_id")
    for m in messages:
        a, b = lane_of.get(m.get("sender_uuid") or ""), lane_of.get(m.get("receiver_uuid") or "")
        if not a or not b:
            continue
        source: Dict[str, Any] = {"message_id": m["id"], "thread": m["thread"]}
        if m["id"] in sends:
            scan, fact = sends[m["id"]]
            source["send"] = source_ref(scan, fact["line"], uuid=fact["uuid"])
        t_to, located = m.get("delivered_at"), "delivered_at"
        if m.get("landed_at") is not None:
            t_to, located = m["landed_at"], "landed"
            source["receive"] = _landed_ref(m)
        if m["id"] in receipts:
            scan, fact = receipts[m["id"]]
            prior = source.get("receive") or {}
            source["receive"], t_to, located = source_ref(scan, fact["line"], uuid=fact["uuid"]), fact["t"], "header"
            source["receive"]["anchor"] = prior.get("anchor")
        elif m.get("receiver_record_uuid"):
            source["receive"] = {"conversation_id": m.get("receiver_conversation_id"), "uuid": m["receiver_record_uuid"], "line": None}
            located = "column"
        out["edges"].append(edge(m["id"], "crosstalk", a, m["created_at"], b, t_to if t_to is not None else m["created_at"], first_line(m["text"]),
                                 source=source, thread=m["thread"], reply_to=m.get("in_reply_to"), status=m["status"],
                                 located_by=located if t_to is not None else "none", undelivered=t_to is None,
                                 delivery_path=m.get("delivery_path"), spawn_task=bool(m.get("spawn_task"))))


def _spawn_candidates(activity: Any, rows: Dict[str, Dict[str, Any]], scans: Dict[str, List[Scan]]) -> Dict[str, Dict[str, Any]]:
    by_id = {r["id"]: u for u, r in rows.items() if "id" in r}
    app_to_uuid = {r["app_id"]: u for u, r in rows.items() if r.get("app_id")}
    found: Dict[str, Dict[str, Any]] = {}

    def offer(child: str, parent: str, t: Optional[float], basis: str, source: Dict[str, Any]) -> None:
        if t is None or child == parent or child not in rows or parent not in rows:
            return
        if child not in found or SPAWN_RANK[basis] < SPAWN_RANK[found[child]["basis"]]:
            found[child] = {"parent": parent, "t": t, "basis": basis, "source": source}

    def when(text: Any) -> Optional[float]:
        try:
            return parse_ts(str(text))
        except ValueError:
            return None

    for uuid, row in rows.items():
        parent = by_id.get(row.get("parent_session_id"))
        if parent and row.get("fork_kind") in (None, "", "spawn"):
            offer(uuid, parent, when(row.get("created_at")), "parent_session_id", {"session_id": row.get("id")})
    for link in activity.spawn_links(list(rows)):
        offer(link["child_uuid"] or "", link["parent_uuid"] or "", link["spawned_at"], "spawn_link",
              {"child_id": link["child_id"], "parent_id": link["parent_id"], "task_message_id": link["task_message_id"]})
    for e in activity.lineage(list(rows)):
        if e["edge_kind"] == "spawned_by":
            offer(e["child_id"], e["parent_id"], when(e["created_at"]), "lineage", {"lineage": [e["parent_id"], e["child_id"]]})
    for parent, items in scans.items():
        for scan in items:
            for spawn in scan.spawns:
                offer(app_to_uuid.get(spawn["child_app_id"], ""), parent, spawn["t"], "transcript",
                      {"send": source_ref(scan, spawn["line"], uuid=spawn["uuid"]), "task_message_id": spawn["task_msg_id"]})
    for pair in activity.spawn_contacts(list(rows)):
        ends = {pair["left_key"], pair["right_key"]}
        near = [m for m in activity.crosstalk(pair["granted_at"] - 30, pair["granted_at"] + 30, list(ends))
                if {m["sender_uuid"], m["receiver_uuid"]} == ends]
        if near:
            offer(near[0]["receiver_uuid"], near[0]["sender_uuid"], pair["granted_at"], "contact", {"task_message_id": near[0]["id"]})
    return found


def spawn_edges(out: Dict[str, Any], activity: Any, rows: Dict[str, Dict[str, Any]], lane_of: Dict[str, str],
                scans: Dict[str, List[Scan]], found: participants.Participants) -> None:
    lanes = {lane["id"]: lane for lane in out["lanes"]}
    for child, c in _spawn_candidates(activity, rows, scans).items():
        info = {"lane": lane_of[c["parent"]], "t": c["t"], "basis": c["basis"]}
        if found.start <= c["t"] <= found.end:
            out["edges"].append(edge(f"spawn:{child}", "spawn", lane_of[c["parent"]], c["t"], lane_of[child], c["t"],
                                     "spawned", inferred=c["basis"] in _INFERRED_SPAWN, source=c["source"], basis=c["basis"]))
        lanes[lane_of[child]]["spawned_by"] = info


def _card_actor(calls: List[Dict[str, Any]], at: float, item_id: int) -> Optional[str]:
    for lane, call in calls:
        if item_id in call["item_ids"] and call["tool"] in ("huddle_update", "huddle_move", "task_manager_update", "task_manager_move") and \
                min(abs(call["t"] - at), abs(call["t_result"] - at)) <= CARD_MATCH_S:
            return lane
    return None


def task_manager_events(out: Dict[str, Any], activity: Any, found: participants.Participants, lane_of: Dict[str, str],
                  scans: Dict[str, List[Scan]], logged: Optional[List[Any]] = None) -> None:
    mirrors = activity.task_manager_items_by_creator(list(lane_of), found.start, found.end)
    item_ids = list(dict.fromkeys([*found.item_ids, *(i["id"] for i in mirrors)]))[:MAX_ITEMS]
    calls = [(f"s:{u}", c) for u, items in scans.items() for s in items for c in s.huddle] + list(logged or [])
    channel_turns = [(f"s:{u}", t) for u, items in scans.items() for s in items for t in s.turns if t["origin"] == "channel"]
    unattributed = 0
    for item_id in item_ids:
        data = activity.huddle_item(item_id)
        if data is None:
            continue
        item = data["item"]
        creator = lane_of.get(item["created_by"])
        if creator is None:
            creator = next((lane_of[ev["by"]] for ev in data["card_events"] if ev["kind"] == "created" and ev["by"] in lane_of), None)
        guessed = creator is None
        if guessed:
            creator = next((lane_of[m["author_key"]] for m in data["messages"] if m["author_key"] in lane_of), None)
        if creator and found.start <= item["created_at"] <= found.end:
            out["marks"].append({"id": f"item:{item_id}", "lane": creator, "t": item["created_at"], "kind": "huddle_add",
                                 "label": str(item["text"])[:80], "inferred": guessed, "item_id": item_id,
                                 "source": {"item_id": item_id, "source_item_id": item.get("source_item_id")},
                                 "title": str(item.get("title") or "")[:LABEL_MAX], "review": str(item.get("review_description") or "")[:400]})
        for m in data["messages"]:
            if not found.start <= m["created_at"] <= found.end:
                continue
            source: Dict[str, Any] = {"item_id": item_id, "message_id": m["id"]}
            label = f"item {item_id}: {first_line(m['text'])}"
            if m["author_key"] in lane_of:
                lane = lane_of[m["author_key"]]
                for call_lane, call in calls:
                    if call_lane == lane and m["id"] in call.get("message_ids", ()):
                        source["send"] = {"tool_use_id": call.get("tool_use_id"), "line": call.get("line"), "uuid": call.get("uuid")}
                out["edges"].append(edge(f"hmsg:{m['id']}", "huddle_post", lane, m["created_at"], OWNER_LANE, m["created_at"], label, source=source))
            elif m["author_key"] == "owner" and creator:
                turn = next((t for lane, t in channel_turns if lane == creator and 0 <= t["start"] - m["created_at"] <= CHANNEL_MATCH_S), None)
                out["edges"].append(edge(f"hmsg:{m['id']}", "owner_reply", OWNER_LANE, m["created_at"], creator,
                                         turn["start"] if turn else m["created_at"], label, inferred=turn is None, source=source,
                                         located_by="channel" if turn else "item_creator"))
        for ev in data["card_events"]:
            if ev["kind"] == "created" or not found.start <= ev["at"] <= found.end:
                continue
            lane = lane_of.get(ev["by"]) or (OWNER_LANE if ev["by"] == "owner" else None)
            inferred = False
            if lane is None and ev["by"] == "claude":
                lane, inferred = _card_actor(calls, ev["at"], item_id), True
            if lane is None:
                unattributed += 1
                continue
            out["marks"].append({"id": f"card:{ev['id']}", "lane": lane, "t": ev["at"], "kind": "card", "inferred": inferred,
                                 "label": f"item {item_id}: {ev['from_col']} to {ev['to_col']}".replace(" to ", " -> ", 1)[:LABEL_MAX],
                                 "source": {"item_id": item_id, "card_event_id": ev["id"]},
                                 "item_id": item_id, "from_col": ev["from_col"], "to_col": ev["to_col"]})
    if unattributed:
        out["warnings"].append(f"{unattributed} card move(s) could not be credited to a session")
