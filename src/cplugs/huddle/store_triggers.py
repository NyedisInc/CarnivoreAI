
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import List, Optional

import structlog

from src.cplugs.huddle import fire_line, item_owner, lifecycle, lineage, rules, status_lines, triggers
from src.cplugs.huddle.rules import JOE
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.wire import ITEM_COLS

logger = structlog.get_logger()


class StoreTriggers:

    def next_trigger_due(self) -> Optional[float]:
        with closing(self._read_connection()) as conn:
            return triggers.next_due(conn)

    def scheduled_items(self) -> List[dict]:
        tag = item_owner.TAG_COLUMN
        with closing(self._read_connection()) as conn:
            rows = conn.execute(f"SELECT i.id AS id, i.list_key AS list_key, i.title AS title, i.text AS text, i.{tag} AS {tag}, {triggers.JOINED_COLS} "
                                "FROM work_item_triggers t CROSS JOIN work_items i ON i.id = t.item_id WHERE i.deleted = 0").fetchall()
        return [{"id": r["id"], "list": r["list_key"], "title": r["title"], "text": r["text"], item_owner.TAG_COLUMN: r[item_owner.TAG_COLUMN],
                 triggers.FIELD: triggers.wire(r)} for r in rows]

    def claim_due_triggers(self) -> List[dict]:
        now = self._clock()
        due: List[dict] = []
        touched = set()
        with closing(self._connect(True)) as conn, conn:
            ids = triggers.due_ids(conn, now)
            seq = self._next_seq(conn) if ids else 0
            for item_id in ids:
                row = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ?", (item_id,)).fetchone()
                repeats = bool(conn.execute("SELECT repeat_rule FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()[0])
                parked = row["state"] == rules.TODO and repeats
                on_joe = not parked and lifecycle.blocks_schedule(row, lifecycle.status(row, bool(lifecycle.asking_ids(conn, [item_id]))))
                if not triggers.claim(conn, item_id, now, deliver=not (parked or on_joe)):
                    continue
                conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
                touched.add(row["list_key"])
                if row["state"] == rules.TODO and not parked:
                    self._unpark_for_reminder(conn, row, now)
                if parked or on_joe:
                    if not repeats:
                        why = triggers.SKIP_PARKED if parked else triggers.SKIP_JOE
                        triggers.record_error(conn, item_id, why, now)
                        status_lines.note(conn, item_id, triggers.refusal_line(why), now)
                    continue
                due.append({"id": row["id"], "list": row["list_key"], "title": row["title"], "text": row["text"]})
        for key in sorted(touched):
            self._commit_notify(key)
        return due

    def _unpark_for_reminder(self, conn: sqlite3.Connection, row: sqlite3.Row, now: float) -> None:
        flow.on_state_write(conn, row, rules.OPEN, JOE, now, None, working=False, decided=lineage.Decided(lineage.CARNIVORE, triggers.REMINDER_DUE))
        conn.execute("UPDATE work_items SET state = ?, claude_done = 0, claude_working = 0, claude_working_by = '', updated_at = ?, "
                     "revision = revision + 1 WHERE id = ?", (rules.OPEN, now, row["id"]))

    def claim_now(self, item_id: int) -> dict:
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            if row["state"] in rules.APPROVED_STATES or row["state"] == rules.TODO:
                raise rules.TaskManagerInvalid("an approved or back-burner item is not sent; reopen it first")
            triggers.claim_now(conn, item_id, self._clock())
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (self._next_seq(conn), item_id))
        self._commit_notify(row["list_key"])
        triggers.nudge()
        return {"id": row["id"], "list": row["list_key"], "title": row["title"], "text": row["text"]}

    def record_trigger_error(self, item_id: int, message: str) -> None:
        with self._immediate() as conn:
            row = conn.execute("SELECT list_key FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
            if row is None:
                return
            now = self._clock()
            triggers.record_error(conn, item_id, message, now)
            status_lines.note(conn, item_id, triggers.refusal_line(message), now)
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (self._next_seq(conn), item_id))
        self._commit_notify(row["list_key"])
        logger.warning("task_manager_trigger_failed", item=item_id, error=message[:200])

    def record_wake_target(self, item_id: int, label: str, is_lead: bool, fell_back: bool = False) -> None:
        with self._immediate() as conn:
            row = conn.execute("SELECT list_key FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
            if row is None or not fire_line.record(conn, item_id, label, is_lead, self._clock(), fell_back):
                return
        self._commit_notify(row["list_key"])
