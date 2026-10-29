
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional

from src.cplugs.huddle import answers, board, corrections, inbox, sends, told_log

TEXT_CHARS = 160
MAX_LIMIT = 200
ENTRY_SEND_WINDOW_S = 30.0

WAITING, TOLD, READ, QUEUED, SWARM = "waiting", "told", "read", "queued", "swarm"
FILING, FILED, STUCK = "filing", "filed", "stuck"


def one_line(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= TEXT_CHARS else flat[: TEXT_CHARS - 1] + "…"


def _send(state: str, label: Optional[str] = None, at: Optional[float] = None, due_at: Optional[float] = None,
          reason: Optional[str] = None) -> Dict[str, Any]:
    return {"state": state, "label": label, "at": at, "due_at": due_at, "reason": reason}


def send_state(list_key: str, item_id: int, seq: int, *, swarm: bool, cursor: int, read_seq: int,
               queue: Mapping[str, Any], holds: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    if swarm:
        return _send(SWARM)
    if seq <= cursor:
        found = told_log.find(list_key, seq, item_id)
        return _send(TOLD, found.label or None, found.at, None) if found else _send(TOLD)
    if read_seq >= seq:
        return _send(READ)
    if list_key in queue:
        return _send(QUEUED, due_at=queue[list_key].get("due_at"))
    hold = holds.get(list_key)
    if hold is not None:
        return _send(hold["state"], hold.get("label"), hold.get("since"), hold.get("deadline"), hold.get("reason"))
    return _send(WAITING)


def _kind(parts: str) -> tuple:
    ref = board.round_wire(parts or "")
    if ref is not None:
        return "round", {"slug": ref["slug"], "round": ref["round"]}
    if corrections.wire(parts or "") is not None:
        return corrections.KIND, None
    return ("answer" if answers.wire(parts or "") is not None else "reply"), None


def _entry_send(entry: Mapping[str, Any], queue: Mapping[str, Any]) -> Dict[str, Any]:
    status, at = entry["status"], entry["delivered_at"]
    if status == inbox.FILING:
        found = told_log.near(entry["list_key"], at, ENTRY_SEND_WINDOW_S) if at else None
        return _send(FILING, found.label if found else None, at)
    if status in inbox.FINAL_STATUSES:
        return _send(FILED, None, entry["filed_at"])
    if status == inbox.STUCK:
        return _send(STUCK, None, at)
    if entry["list_key"] in queue:
        return _send(QUEUED, due_at=queue[entry["list_key"]].get("due_at"))
    return _send(WAITING)


def gather(store: Any, *, limit: int, names: Mapping[str, str], queue: Mapping[str, Any], holds: Mapping[str, Mapping[str, Any]],
           labels: Optional[Mapping[str, str]] = None) -> List[Dict[str, Any]]:
    sends: List[Dict[str, Any]] = []
    with closing(store._read_connection()) as conn:
        cursors = {r[0]: r[1] for r in conn.execute("SELECT list_key, cursor FROM work_sends")}
        for m in conn.execute(
                "SELECT m.id, m.item_id, m.text, m.created_at, m.seq, m.parts, i.list_key, i.title, i.text AS item_text, i.swarm_ref, i.claude_read_seq "
                "FROM work_messages m JOIN work_items i ON i.id = m.item_id WHERE m.author = 'joe' AND m.kind IN ('reply', 'correction') AND i.deleted = 0 "
                "ORDER BY m.id DESC LIMIT ?", (limit,)):
            kind, on_board = _kind(m["parts"])
            sends.append(_row(f"m:{m['id']}", kind, m["created_at"], m["text"], m["list_key"], names, m["item_id"], m["title"] or m["item_text"], on_board,
                              send_state(m["list_key"], m["item_id"], m["seq"], swarm=bool(m["swarm_ref"]), cursor=cursors.get(m["list_key"], 0),
                                         read_seq=m["claude_read_seq"] or 0, queue=queue, holds=holds)))
        for e in conn.execute("SELECT id, list_key, raw_text, created_at, status, delivered_at, delivered_to, filed_at FROM work_inbox WHERE author = 'joe' ORDER BY id DESC LIMIT ?", (limit,)):
            sends.append(_row(f"e:{e['id']}", "add", e["created_at"], e["raw_text"], e["list_key"], names, None, None, None, _entry_send(e, queue),
                              session=(labels or {}).get(e["delivered_to"] or "")))
        for i in conn.execute(
                "SELECT id, list_key, text, title, created_at, created_seq, swarm_ref, claude_read_seq FROM work_items WHERE created_by = 'joe' AND inbox_id IS NULL "
                "AND swarm_ref = '' AND deleted = 0 ORDER BY id DESC LIMIT ?", (limit,)):
            sends.append(_row(f"i:{i['id']}", "add", i["created_at"], i["text"], i["list_key"], names, i["id"], i["title"] or i["text"], None,
                              send_state(i["list_key"], i["id"], i["created_seq"], swarm=False, cursor=cursors.get(i["list_key"], 0),
                                         read_seq=i["claude_read_seq"] or 0, queue=queue, holds=holds)))
    return sorted(sends, key=lambda s: s["at"], reverse=True)[:limit]


def tell_of_message(store: Any, message_id: int, *, queue: Mapping[str, Any], holds: Mapping[str, Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    with closing(store._read_connection()) as conn:
        m = conn.execute("SELECT m.seq, m.item_id, i.list_key, i.swarm_ref, i.claude_read_seq FROM work_messages m JOIN work_items i ON i.id = m.item_id WHERE m.id = ?",
                         (message_id,)).fetchone()
        if m is None:
            return None
        found = conn.execute("SELECT cursor FROM work_sends WHERE list_key = ?", (m["list_key"],)).fetchone()
    return send_state(m["list_key"], m["item_id"], m["seq"], swarm=bool(m["swarm_ref"]), cursor=found[0] if found else 0, read_seq=m["claude_read_seq"] or 0,
                      queue=queue, holds=holds)


def _row(key: str, kind: str, at: float, text: str, list_key: str, names: Mapping[str, str], item_id: Optional[int], title: Optional[str],
         on_board: Optional[Dict[str, str]], tell: Dict[str, Any], session: Optional[str] = None) -> Dict[str, Any]:
    return {"key": key, "kind": kind, "at": at, "text": one_line(text), "list": list_key, "list_name": names.get(list_key),
            "session": tell.get("label") or session or None,
            "item": {"id": item_id, "title": one_line(title or "")} if item_id is not None else None, "board": on_board, "tell": tell}
