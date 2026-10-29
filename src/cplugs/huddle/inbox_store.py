
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import structlog

from src.cplugs.huddle import inbox, rules, triggers
from src.cplugs.huddle.rules import TaskManagerInvalid, TaskManagerNotFound

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()

_COLS = "id, list_key, raw_text, author, created_at, status, delivered_at, delivered_to, filed_at, item_ids, error"


def open_entries_in(conn: sqlite3.Connection, list_key: str) -> List[Dict[str, Any]]:
    rows = conn.execute(f"SELECT {_COLS} FROM work_inbox WHERE list_key = ? AND {inbox.OPEN_SQL} ORDER BY id", (list_key,)).fetchall()
    return [inbox.pending_dict(r) for r in rows]


class InboxStore:

    def __init__(self, store: "TaskManagerStore") -> None:
        self._store = store

    def prefs(self) -> Dict[str, bool]:
        with closing(self._store._read_connection()) as conn:
            return {r[0]: bool(r[1]) for r in conn.execute("SELECT list_key, inbox FROM work_list_prefs")}

    def pref(self, list_key: str) -> bool:
        return self.prefs().get(list_key, True)

    def set_pref(self, list_key: str, on: bool) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            conn.execute("INSERT INTO work_list_prefs (list_key, nudge, inbox, updated_at) VALUES (?, 0, ?, ?) "
                         "ON CONFLICT(list_key) DO UPDATE SET inbox = excluded.inbox, updated_at = excluded.updated_at",
                         (list_key, int(on), self._store._clock()))
        self._store._commit_notify(list_key)
        return on

    def add(self, list_key: str, text: str, author: str = inbox.OWNER) -> Dict[str, Any]:
        rules.check_list_key(list_key)
        clean = rules.clean_text(text, "text", rules.MAX_TEXT)
        with closing(self._store._connect(True)) as conn, conn:
            entry_id = conn.execute("INSERT INTO work_inbox (list_key, raw_text, author, created_at, status) VALUES (?, ?, ?, ?, ?)",
                                    (list_key, clean, author, self._store._clock(), inbox.QUEUED)).lastrowid
        self._store._commit_notify(list_key)
        triggers.nudge()
        logger.info("task_manager_inbox_queued", list=list_key, entry=entry_id)
        return self.get(entry_id)

    def get(self, entry_id: int) -> Dict[str, Any]:
        with closing(self._store._read_connection()) as conn:
            row = conn.execute(f"SELECT {_COLS} FROM work_inbox WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise TaskManagerNotFound(f"no inbox entry {entry_id}")
        return inbox.entry_dict(row)

    def open_entries(self, list_key: Optional[str] = None) -> List[Dict[str, Any]]:
        where, args = (" AND list_key = ?", (list_key,)) if list_key is not None else ("", ())
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute(f"SELECT {_COLS} FROM work_inbox WHERE {inbox.OPEN_SQL}{where} ORDER BY id", args).fetchall()
        entries = [inbox.entry_dict(r) for r in rows]
        now = self._store._clock()
        return [e for e in entries if e["status"] != inbox.STUCK or not self.adopt_promoted(e["id"], now)]

    def active_entries(self) -> List[Dict[str, Any]]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute(f"SELECT {_COLS} FROM work_inbox WHERE {inbox.ACTIVE_SQL} ORDER BY id").fetchall()
        return [inbox.entry_dict(r) for r in rows]

    def has_open(self) -> bool:
        with closing(self._store._read_connection()) as conn:
            return conn.execute(f"SELECT EXISTS(SELECT 1 FROM work_inbox WHERE {inbox.ACTIVE_SQL})").fetchone()[0] == 1

    def mark_stuck(self, entry_id: int) -> Optional[str]:
        with self._store._immediate() as conn:
            row = conn.execute(f"SELECT list_key, status FROM work_inbox WHERE id = ? AND {inbox.ACTIVE_SQL}", (entry_id,)).fetchone()
            if row is None or conn.execute(f"UPDATE work_inbox SET status = ? WHERE id = ? AND {inbox.ACTIVE_SQL}", (inbox.STUCK, entry_id)).rowcount == 0:
                return None
        self._store._commit_notify(row["list_key"])
        return row["status"]

    def rearm(self, entry_id: int, now: float, previous: str = inbox.QUEUED) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            row = conn.execute("SELECT list_key FROM work_inbox WHERE id = ? AND status = ?", (entry_id, inbox.STUCK)).fetchone()
            done = row is not None and conn.execute("UPDATE work_inbox SET status = ?, delivered_at = ?, delivered_to = NULL WHERE id = ? AND status = ?",
                                                    (previous, now, entry_id, inbox.STUCK)).rowcount
        if done:
            self._store._commit_notify(row["list_key"])
            triggers.nudge()
        return bool(done)

    def carriers(self, entry_id: int) -> List[int]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute("SELECT DISTINCT work_items.id FROM work_items JOIN work_messages ON work_messages.item_id = work_items.id "
                                "WHERE work_items.inbox_id = ? AND work_items.deleted = 0 AND work_items.created_key = ? AND work_items.state = ? "
                                "AND work_messages.kind = 'question' AND work_messages.category = ? "
                                "AND work_items.id NOT IN (SELECT j.value FROM work_inbox, json_each(work_inbox.item_ids) j WHERE work_inbox.id = ?)",
                                (entry_id, rules.CARNIVORE_KEY, rules.TODO, inbox.STUCK_CATEGORY, entry_id)).fetchall()
        return [r[0] for r in rows]

    def promoted(self, entry_id: int) -> List[int]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute("SELECT work_items.id FROM work_items WHERE work_items.inbox_id = ? AND work_items.deleted = 0 AND work_items.created_key = ? "
                                "AND work_items.state != ? AND work_items.id NOT IN (SELECT j.value FROM work_inbox, json_each(work_inbox.item_ids) j WHERE work_inbox.id = ?) "
                                "ORDER BY work_items.id", (entry_id, rules.CARNIVORE_KEY, rules.TODO, entry_id)).fetchall()
        return [r[0] for r in rows]

    def adopt_promoted(self, entry_id: int, now: float) -> List[int]:
        ids = self.promoted(entry_id)
        if not ids:
            return []
        try:
            self.claim(entry_id, inbox.FILED, now)
        except TaskManagerInvalid:
            return []
        for item_id in ids:
            self.link_item(entry_id, item_id)
        logger.info("task_manager_inbox_adopted_promoted", entry=entry_id, items=ids)
        return ids

    def retire_questions(self, entry_id: int) -> int:
        gone = 0
        for item_id in self.carriers(entry_id):
            try:
                self._store.delete(item_id, actor=rules.JOE)
                gone += 1
            except TaskManagerNotFound:
                continue
        return gone

    def mark_delivered(self, entry_id: int, target: str, now: float) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            row = conn.execute("SELECT list_key FROM work_inbox WHERE id = ? AND status = ?", (entry_id, inbox.QUEUED)).fetchone()
            done = conn.execute("UPDATE work_inbox SET status = ?, delivered_at = ?, delivered_to = ? WHERE id = ? AND status = ?",
                                (inbox.FILING, now, target, entry_id, inbox.QUEUED)).rowcount
        if done:
            self._store._commit_notify(row["list_key"])
        return bool(done)

    def claim(self, entry_id: int, final: str, now: float, error: Optional[str] = None) -> str:
        with self._store._immediate() as conn:
            row = conn.execute(f"SELECT {_COLS} FROM work_inbox WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                raise TaskManagerNotFound(f"no inbox entry {entry_id}")
            if conn.execute(f"UPDATE work_inbox SET status = ?, filed_at = ?, error = ? WHERE id = ? AND {inbox.OPEN_SQL}",
                            (final, now, error, entry_id)).rowcount == 0:
                ids = inbox.ids_of(row)
                raise TaskManagerInvalid(f"inbox entry {entry_id} is already {row['status']}" + (f" as item(s) {ids}" if ids else ""))
        self._store._commit_notify(row["list_key"])
        return row["status"]

    def release(self, entry_id: int, previous: str) -> None:
        with closing(self._store._connect(True)) as conn, conn:
            row = conn.execute("SELECT list_key FROM work_inbox WHERE id = ?", (entry_id,)).fetchone()
            conn.execute("UPDATE work_inbox SET status = ?, filed_at = NULL, error = NULL WHERE id = ?", (previous, entry_id))
        if row is not None:
            self._store._commit_notify(row["list_key"])

    def link_item(self, entry_id: int, item_id: int) -> None:
        with self._store._immediate() as conn:
            entry = conn.execute("SELECT list_key, item_ids FROM work_inbox WHERE id = ?", (entry_id,)).fetchone()
            if entry is None:
                raise TaskManagerNotFound(f"no inbox entry {entry_id}")
            found = json.loads(entry["item_ids"] or "[]")
            if item_id not in found:
                found.append(item_id)
            conn.execute("UPDATE work_inbox SET item_ids = ? WHERE id = ?", (json.dumps(found), entry_id))
            seq = self._store._next_seq(conn)
            conn.execute("UPDATE work_items SET inbox_id = ?, seq = ? WHERE id = ?", (entry_id, seq, item_id))
            list_key = conn.execute("SELECT list_key FROM work_items WHERE id = ?", (item_id,)).fetchone()[0]
        self._store._commit_notify(list_key)
        self.retire_questions(entry_id)

    def file_plain(self, entry_id: int, now: float, reason: str) -> Dict[str, Any]:
        entry = self.get(entry_id)
        previous = self.claim(entry_id, inbox.FALLBACK, now, reason)
        try:
            item = self._store.add(entry["list"], entry["text"], actor=rules.JOE)
            self.link_item(entry_id, item["id"])
        except (rules.TaskManagerError, sqlite3.Error):
            self.release(entry_id, previous)
            raise
        logger.info("task_manager_inbox_fallback", entry=entry_id, item=item["id"], reason=reason)
        return self._store.item(item["id"])
