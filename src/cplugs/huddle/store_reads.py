
from __future__ import annotations

import copy
import sqlite3
from contextlib import closing
from typing import Dict, List, Optional, Sequence

import structlog

from src.core.db_reuse.change_cache import CACHE
from src.cplugs.huddle import groups, inbox, inbox_store, kinds, lane, lifecycle, rules, sends
from src.cplugs.huddle.rules import QUESTION, TaskManagerInvalid
from src.cplugs.sdk.storage import CplugSchemaError
from src.cplugs.huddle.wire import ITEM_COLS, MSG_COLS, item_dict, message_dict, numbers_in_view

logger = structlog.get_logger()

_ID_CHUNK = 500

DONE_PAGE = 50
DONE_MAX = 200

def _not_approved(column: str = "state") -> str:
    return f"{column} NOT IN (" + ", ".join(f"'{s}'" for s in sorted(rules.APPROVED_STATES)) + ")"


def _counts_incomplete(column: str = "state") -> str:
    return f"({_not_approved(column)} AND {column} != '{rules.TODO}')"


def empty_summary() -> dict:
    return {"items": 0, "open": 0, "review": 0, "questions": 0, "claude_seq": 0, "unread": 0, "untold": False,
            "waiting_to_send": 0, "incomplete": 0, "needs_you": 0, "attention": 0, "status_counts": {}}


def thread_asks(thread: Sequence[dict]) -> bool:
    return any(m["kind"] == QUESTION and not m["answered"] for m in thread)


class StoreReads:

    def list_items(self, list_key: str, *, hide_swarm: bool = False, live_only: bool = False) -> dict:
        rules.check_list_key(list_key)
        with closing(self._read_connection()) as conn:
            rows = conn.execute(
                f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 {groups.ITEM_ORDER}",
                (list_key,)).fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in rows if r["state"] not in rules.APPROVED_STATES])
            statuses = {r["id"]: lifecycle.status(r, r["id"] in asking) for r in rows}
            numbers = numbers_in_view(rows, statuses, self._view)
            settled = {i for i, st in statuses.items() if st == lifecycle.DONE} if live_only else set()
            sent = [r for r in rows if r["id"] not in settled]
            threads = self._threads(conn, [r["id"] for r in sent])
            revision = self._list_revision(conn, list_key)
            cursor = self._cursor(conn)
            sections = groups.live_groups(conn, list_key)
            pending = inbox_store.open_entries_in(conn, list_key)
        if hide_swarm:
            sent = [r for r in sent if r["lane"] == lane.TASK_MANAGER]
        extra = {"done_count": sum(1 for r in rows if r["id"] in settled and (not hide_swarm or r["lane"] == lane.TASK_MANAGER)),
                 "done_swarm": 0 if hide_swarm else sum(1 for r in rows if r["id"] in settled and r["lane"] != lane.TASK_MANAGER)} if live_only else {}
        return {"list": list_key, "revision": revision, "cursor": cursor, "groups": sections, **({"inbox": pending} if pending else {}), **extra,
                "items": [{**item_dict(r, r["id"] in asking), "number": numbers.get(r["id"]), "thread": threads[r["id"]]} for r in sent]}

    @staticmethod
    def _threads(conn: sqlite3.Connection, ids: Sequence[int]) -> Dict[int, List[dict]]:
        threads: Dict[int, List[dict]] = {i: [] for i in ids}
        for start in range(0, len(ids), _ID_CHUNK):
            chunk = list(ids[start:start + _ID_CHUNK])
            marks = ",".join("?" * len(chunk))
            for m in conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE item_id IN ({marks}) ORDER BY id", chunk):
                threads[m["item_id"]].append(message_dict(m))
        return threads

    def done_page(self, list_key: str, *, hide_swarm: bool = False, limit: int = DONE_PAGE, offset: int = 0) -> dict:
        rules.check_list_key(list_key)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= DONE_MAX:
            raise TaskManagerInvalid(f"limit must be 1 to {DONE_MAX}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise TaskManagerInvalid("offset must be an integer >= 0")
        approved = ", ".join(f"'{s}'" for s in sorted(rules.APPROVED_STATES))
        only = f" AND {lane.visible_sql()}" if hide_swarm else ""
        with closing(self._read_connection()) as conn:
            rows = [r for r in conn.execute(
                f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 AND state IN ({approved}){only} ORDER BY position, id",
                (list_key,)) if lifecycle.status(r, False) == lifecycle.DONE]
            page = rows[offset:offset + limit]
            threads = self._threads(conn, [r["id"] for r in page])
            revision = self._list_revision(conn, list_key)
            cursor = self._cursor(conn)
        more = offset + limit if offset + limit < len(rows) else None
        return {"list": list_key, "revision": revision, "cursor": cursor, "total": len(rows), "offset": offset, "next_offset": more,
                "items": [{**item_dict(r, False), "number": None, "thread": threads[r["id"]]} for r in page]}

    def aggregate(self, *, hide_swarm: bool = False, live_only: bool = False) -> dict:
        built = self._cached(("aggregate", hide_swarm, live_only, self._view), lambda: self._build_aggregate(hide_swarm, live_only))
        return {"cursor": built["cursor"], "groups": [{**g, "items": [dict(i) for i in g["items"]]} for g in built["groups"]]}

    def _cached(self, key: tuple, load):
        try:
            path = self._storage.db_path
        except CplugSchemaError:
            return load()
        return CACHE.fetch(path, key, load)

    def _build_aggregate(self, hide_swarm: bool, live_only: bool = False) -> dict:
        with closing(self._read_connection()) as conn:
            where = f" AND {lane.visible_sql()}" if hide_swarm else ""
            keys = [r[0] for r in conn.execute(f"SELECT list_key FROM work_items WHERE deleted = 0{where} UNION "
                                                "SELECT list_key FROM work_item_groups WHERE deleted = 0 UNION "
                                                f"SELECT list_key FROM work_inbox WHERE {inbox.OPEN_SQL}")]
        lists = [self.list_items(k, hide_swarm=hide_swarm and lane.hides_swarm(k, False), live_only=live_only) for k in keys]
        return {"cursor": max([g["cursor"] for g in lists], default=self.summary()["cursor"]), "groups": [
            {"list": g["list"], "revision": g["revision"], "groups": g["groups"], **({"inbox": g["inbox"]} if "inbox" in g else {}),
             **{k: g[k] for k in ("done_count", "done_swarm") if k in g}, "items": g["items"]} for g in lists]}

    @staticmethod
    def _list_revision(conn: sqlite3.Connection, list_key: str) -> int:
        row = conn.execute("SELECT MAX(COALESCE((SELECT MAX(seq) FROM work_items WHERE list_key = ?), 0), "
                           "COALESCE((SELECT MAX(seq) FROM work_item_groups WHERE list_key = ?), 0))", (list_key, list_key)).fetchone()
        return int(row[0] or 0)

    def summary(self, *, hide_swarm: bool = False) -> dict:
        return copy.deepcopy(self._cached(("summary", hide_swarm, self._view), lambda: self._build_summary(hide_swarm)))

    def _build_summary(self, hide_swarm: bool) -> dict:
        only, only_i = (f" AND {lane.visible_sql()}", f" AND {lane.visible_sql('i')}") if hide_swarm else ("", "")
        with closing(self._read_connection()) as conn:
            out: Dict[str, dict] = {}
            for r in conn.execute(
                "SELECT list_key, COUNT(*) n, SUM(state = 'open') o, SUM(state = 'review') d, "
                "MAX(CASE WHEN created_by = 'claude' THEN created_seq END) c, "
                f"SUM(attention_seq > seen_seq AND {_not_approved()}) u, SUM({_counts_incomplete()}) x "
                f"FROM work_items WHERE deleted = 0{only} GROUP BY list_key"):
                out[r["list_key"]] = {**empty_summary(), "items": r["n"], "open": r["o"] or 0, "review": r["d"] or 0,
                                      "claude_seq": r["c"] or 0, "unread": r["u"] or 0, "incomplete": r["x"] or 0}
            for r in conn.execute(
                f"SELECT i.list_key k, SUM(m.answered = 0 AND {_not_approved('i.state')}) q, MAX(m.seq) s "
                f"FROM work_messages m JOIN work_items i ON i.id = m.item_id WHERE m.kind = 'question' AND i.deleted = 0{only_i} GROUP BY i.list_key"):
                entry = out.setdefault(r["k"], empty_summary())
                entry["questions"] = r["q"] or 0
                entry["claude_seq"] = max(entry["claude_seq"], r["s"] or 0)
            for r in conn.execute(
                "SELECT i.list_key k, MAX(m.seq) s FROM work_messages m JOIN work_items i ON i.id = m.item_id "
                f"WHERE m.kind = ? AND i.deleted = 0{only_i} GROUP BY i.list_key", (kinds.ATTENTION,)):
                if r["k"] in out:
                    out[r["k"]]["claude_seq"] = max(out[r["k"]]["claude_seq"], r["s"] or 0)
            for key in sends.untold_lists(conn):
                entry = out.setdefault(key, empty_summary())
                entry["untold"] = True
            live = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE deleted = 0{only} "
                                f"AND ({_not_approved()} OR joe_seq > claude_read_seq)").fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in live])
            for key, count in lifecycle.waiting_counts(live, asking).items():
                if key in out:
                    out[key]["waiting_to_send"] = count
            for key, count in lifecycle.needs_you_counts(live, asking).items():
                if key in out:
                    out[key]["needs_you"] = count
            for key, count in lifecycle.attention_counts(live, asking).items():
                if key in out:
                    out[key]["attention"] = count
            for key, counts in lifecycle.status_counts(live, asking).items():
                if key in out:
                    out[key]["status_counts"] = counts
            cursor = self._cursor(conn)
        return {"cursor": cursor, "lists": out}

    def changes(self, since: int, list_key: Optional[str] = None, *, all_live_groups: bool = True, hide_swarm: bool = False) -> dict:
        if isinstance(since, bool) or not isinstance(since, int) or since < 0:
            raise TaskManagerInvalid("since must be a cursor (an integer >= 0)")
        if list_key is not None:
            rules.check_list_key(list_key)
        with closing(self._read_connection()) as conn:
            cursor = self._cursor(conn)
            reset = since > cursor
            floor = 0 if reset else since
            where, args = ("AND list_key = ?", [list_key]) if list_key else ("", [])
            hidden = (f"AND ({lane.visible_sql()} OR list_key LIKE '{lane.AGENT_LIST_PREFIX}%')" if hide_swarm else "")
            rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE seq > ? {where} {hidden} ORDER BY seq", [floor, *args]).fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
            items = [item_dict(r, r["id"] in asking) for r in rows]
            numbers = self._numbers_cached(conn, [i["list"] for i in items])
            for entry in items:
                entry["number"] = None if entry["deleted"] else numbers.get(entry["id"])
            mwhere = ("AND i.list_key = ?" if list_key else "") + (f" AND ({lane.visible_sql('i')} OR i.list_key LIKE '{lane.AGENT_LIST_PREFIX}%')" if hide_swarm else "")
            messages = [message_dict(r) for r in conn.execute(
                f"SELECT m.id, m.item_id, m.author, m.author_key, m.kind, m.text, m.answered, m.created_at, m.seq, m.seen, m.parts, m.category "
                f"FROM work_messages m JOIN work_items i ON i.id = m.item_id WHERE m.seq > ? {mwhere} ORDER BY m.seq",
                [floor, *args])]
            changed_groups = groups.changed_groups(conn, floor, list_key)
            known = {g["id"] for g in changed_groups}
            for key in sorted({i["list"] for i in items}) if (all_live_groups or reset) else []:
                changed_groups += [g for g in groups.live_groups(conn, key) if g["id"] not in known]
        return {"cursor": cursor, "reset": reset, "items": items, "messages": messages, "groups": changed_groups}

    def list_heads(self) -> Dict[str, int]:
        with closing(self._read_connection()) as conn:
            heads = {r[0]: int(r[1]) for r in conn.execute("SELECT list_key, MAX(seq) FROM work_items GROUP BY list_key")}
            for key, seq in conn.execute(
                    "SELECT i.list_key, MAX(m.seq) FROM work_messages m JOIN work_items i ON i.id = m.item_id GROUP BY i.list_key"):
                heads[key] = max(heads.get(key, 0), int(seq))
            for key, seq in conn.execute("SELECT list_key, MAX(seq) FROM work_item_groups GROUP BY list_key"):
                heads[key] = max(heads.get(key, 0), int(seq))
        return heads

    def item(self, item_id: int) -> dict:
        with closing(self._read_connection()) as conn:
            row = self._row(conn, item_id)
            thread = [message_dict(m) for m in conn.execute(
                f"SELECT {MSG_COLS} FROM work_messages WHERE item_id = ? ORDER BY id", (item_id,))]
            number = self._numbers_cached(conn, [row["list_key"]]).get(item_id)
        return {**item_dict(row, thread_asks(thread)), "number": number, "thread": thread}

    def forks_of(self, item_id: int) -> List[dict]:
        with closing(self._connect(False)) as conn:
            rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE forked_from = ? AND deleted = 0 ORDER BY id", (item_id,)).fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
            return [item_dict(r, r["id"] in asking) for r in rows]

    def items_by_id(self, item_ids: Sequence[int]) -> Dict[int, dict]:
        ids = sorted({int(i) for i in item_ids})
        out: Dict[int, dict] = {}
        with closing(self._read_connection()) as conn:
            for start in range(0, len(ids), _ID_CHUNK):
                chunk = ids[start:start + _ID_CHUNK]
                marks = ",".join("?" * len(chunk))
                rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE deleted = 0 AND id IN ({marks})", chunk).fetchall()
                asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
                out.update({r["id"]: item_dict(r, r["id"] in asking) for r in rows})
        return out
