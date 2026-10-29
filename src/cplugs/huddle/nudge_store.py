
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.cplugs.huddle import groups, lifecycle, nudges, rules, sends, triggers
from src.cplugs.huddle.roles import ask, route
from src.cplugs.huddle.wire import ITEM_COLS

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()


class NudgeStore:

    def __init__(self, store: "TaskManagerStore") -> None:
        self._store = store

    def prefs(self) -> Dict[str, bool]:
        with closing(self._store._read_connection()) as conn:
            return {r[0]: bool(r[1]) for r in conn.execute("SELECT list_key, nudge FROM work_list_prefs")}

    def nudge_lists(self) -> List[str]:
        with closing(self._store._read_connection()) as conn:
            return [r[0] for r in conn.execute(
                "SELECT list_key FROM (SELECT list_key FROM work_items WHERE deleted = 0 AND state = ? UNION SELECT list_key FROM work_list_prefs WHERE nudge = 1) "
                "WHERE list_key GLOB '[0-9]*' AND list_key NOT GLOB '*[^0-9]*' "
                "AND list_key NOT IN (SELECT list_key FROM work_list_prefs WHERE nudge = 0) ORDER BY list_key", (rules.OPEN,))]

    def session_prefs(self) -> Dict[str, bool]:
        with closing(self._store._read_connection()) as conn:
            return {r[0]: bool(r[1]) for r in conn.execute("SELECT session_uuid, nudge FROM work_session_prefs WHERE nudge IS NOT NULL")}

    def set_session_pref(self, session_uuid: str, on: Optional[bool]) -> Optional[bool]:
        with closing(self._store._connect(True)) as conn, conn:
            conn.execute("INSERT INTO work_session_prefs (session_uuid, nudge, updated_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(session_uuid) DO UPDATE SET nudge = excluded.nudge, updated_at = excluded.updated_at",
                         (session_uuid, None if on is None else int(on), self._store._clock()))
        triggers.nudge()
        return on

    def enabled(self) -> bool:
        with closing(self._store._read_connection()) as conn:
            if conn.execute("SELECT EXISTS(SELECT 1 FROM work_session_prefs WHERE nudge = 1)").fetchone()[0]:
                return True
        return bool(self.nudge_lists())

    def set_pref(self, list_key: str, on: bool) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            conn.execute("INSERT INTO work_list_prefs (list_key, nudge, updated_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(list_key) DO UPDATE SET nudge = excluded.nudge, updated_at = excluded.updated_at",
                         (list_key, int(on), self._store._clock()))
        self._store._commit_notify(list_key)
        triggers.nudge()
        return on

    def candidates(self, list_key: str) -> List[Tuple[Any, str, float, str]]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute(
                f"SELECT {ITEM_COLS}, {nudges.BASIS_SQL} AS basis_now, {nudges.LAST_ACTIVITY_SQL} AS last_activity, "
                f"claude_working_by AS claimant, {nudges.CLAIM_OP_SQL} AS claim_op FROM work_items WHERE list_key = ? AND deleted = 0 AND state = ? AND {sends.sendable_sql()} {groups.ITEM_ORDER}",
                (list_key, rules.OPEN)).fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
        return [(r, lifecycle.status(r, r["id"] in asking), r["last_activity"], r["basis_now"]) for r in rows]

    def record_nudges(self, list_key: str, sent: Sequence[Any], tries: int, now: float) -> int:
        done = 0
        with self._store._immediate() as conn:
            for cand in sent:
                if conn.execute(f"SELECT {nudges.BASIS_SQL} FROM work_items WHERE id = ?", (cand.id,)).fetchone()[0] != cand.basis:
                    continue
                count = (cand.row["nudge_count"] or 0) + 1
                conn.execute("INSERT INTO work_item_nudges (item_id, count, last_at, basis, stalled_at) VALUES (?, ?, ?, ?, NULL) "
                             "ON CONFLICT(item_id) DO UPDATE SET count = excluded.count, last_at = excluded.last_at, "
                             "basis = excluded.basis, stalled_at = NULL", (cand.id, count, now, cand.basis))
                seq = self._store._next_seq(conn)
                conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts, category, seen) "
                             "VALUES (?, ?, 'info', ?, ?, ?, ?, '', 'nudge', 1)",
                             (cand.id, rules.CLAUDE, f"nudged {count} of {tries}", now, seq, rules.NUDGE_KEY))
                conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, cand.id))
                done += 1
        if done:
            self._store._commit_notify(list_key)
        return done

    def raise_stall(self, list_key: str, stalled: Sequence[Any], now: float, contexts: Mapping[int, str]) -> List[int]:
        raised: List[int] = []
        for cand in stalled:
            with closing(self._store._read_connection()) as conn:
                if conn.execute(f"SELECT {nudges.BASIS_SQL} FROM work_items WHERE id = ?", (cand.id,)).fetchone()[0] != cand.basis:
                    continue
            ask.carnivore_ask(self._store, cand.id, category=ask.STALL, context=contexts[cand.id], options=ask.STALL_OPTIONS)
            with closing(self._store._connect(True)) as conn, conn:
                conn.execute("INSERT INTO work_item_nudges (item_id, count, last_at, basis, stalled_at) "
                             f"SELECT id, ?, ?, {nudges.BASIS_SQL}, ? FROM work_items WHERE id = ? "
                             "ON CONFLICT(item_id) DO UPDATE SET basis = excluded.basis, stalled_at = excluded.stalled_at",
                             (cand.row["nudge_count"] or 0, cand.row["nudge_last_at"] or now, now, cand.id))
            raised.append(cand.id)
        if raised:
            self._store._commit_notify(list_key)
        return raised

    def session_keys(self, list_key: str, rows: Sequence[Any]) -> Dict[int, str]:
        return route.session_keys(self._store, list_key, rows)
