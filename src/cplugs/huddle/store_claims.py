
from __future__ import annotations

from contextlib import closing
from typing import Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.cplugs.huddle.cards import flow
from src.cplugs.huddle import actor_log, item_owner, lifecycle, status_lines, reply_send, rules, send_pick, sends, unread_sweep
from src.cplugs.huddle.roles import claims
from src.cplugs.huddle.rules import CLAUDE, TaskManagerForbidden
from src.cplugs.huddle.wire import ITEM_COLS

logger = structlog.get_logger()


class StoreClaims:

    def note_read(self, key: str, list_key: str, cursor: int, legacy_id: Optional[str] = None) -> None:
        with closing(self._connect(True)) as conn, conn:
            if legacy_id and legacy_id != key:
                conn.execute("UPDATE OR IGNORE work_reads SET session_id = ? WHERE session_id = ?", (key, legacy_id))
                conn.execute("DELETE FROM work_reads WHERE session_id = ?", (legacy_id,))
            conn.execute("INSERT OR REPLACE INTO work_reads VALUES (?, ?, ?)", (key, list_key, cursor))

    def last_read(self, key: str, list_key: str, legacy_id: Optional[str] = None) -> Optional[int]:
        with closing(self._read_connection()) as conn:
            row = conn.execute("SELECT cursor FROM work_reads WHERE session_id = ? AND list_key = ?", (key, list_key)).fetchone()
            if row is None and legacy_id and legacy_id != key:
                row = conn.execute("SELECT cursor FROM work_reads WHERE session_id = ? AND list_key = ?",
                                   (legacy_id, list_key)).fetchone()
        return None if row is None else int(row[0])

    def current_cursor(self) -> int:
        with closing(self._read_connection()) as conn:
            return self._cursor(conn)

    def record_send(self, list_keys: Sequence[str], cursor: int, target: str = "") -> None:
        with closing(self._connect(True)) as conn, conn:
            sends.record_send(conn, list_keys, cursor, target)
            item_owner.release_told(conn, list_keys, cursor)
        for key in list_keys:
            self._commit_notify(key)

    def send_pick(self, list_key: str) -> Optional[str]:
        with closing(self._read_connection()) as conn:
            return send_pick.picked(conn, list_key)

    def set_send_pick(self, list_key: str, target_key: Optional[str]) -> None:
        with closing(self._connect(True)) as conn, conn:
            send_pick.set_pick(conn, list_key, target_key)
        self._commit_notify(list_key)

    def send_targets(self, list_keys: Sequence[str]) -> Dict[str, str]:
        with closing(self._read_connection()) as conn:
            return sends.targets(conn, list_keys)

    def owner_replies(self, list_key: str, since: int, items: Optional[Sequence[int]] = None) -> List[Tuple[int, int]]:
        with closing(self._read_connection()) as conn:
            return reply_send.newest_replies(conn, list_key, since, items)

    def untold_owners(self, list_key: str) -> List[Tuple[int, str]]:
        with closing(self._read_connection()) as conn:
            return item_owner.untold_items(conn, list_key)

    def working_claims(self) -> List[tuple]:
        with closing(self._read_connection()) as conn:
            rows = conn.execute("SELECT id, list_key, claude_working_by FROM work_items "
                                "WHERE deleted = 0 AND claude_working = 1 AND claude_working_by != ''").fetchall()
        return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    def record_claude_read(self, seen: Sequence[tuple]) -> Dict[int, str]:
        if not seen:
            return {}
        moved: Set[str] = set()
        with closing(self._read_connection()) as conn:
            behind = lifecycle.any_behind(conn, seen)
        if behind:
            with self._immediate() as conn:
                moved = lifecycle.record_read(conn, seen)
        ids = [item_id for item_id, _seq in seen]
        marks = ",".join("?" * len(ids))
        with closing(self._read_connection()) as conn:
            rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE deleted = 0 AND id IN ({marks})", ids).fetchall()
            asking = lifecycle.asking_ids(conn, ids)
            statuses = {r["id"]: lifecycle.status(r, r["id"] in asking) for r in rows}
        for key in sorted(moved):
            self._commit_notify(key)
        return statuses

    def sweep_read_claims(self) -> List[int]:
        with self._immediate() as conn:
            ids, keys = lifecycle.sweep_read_claims(conn)
        for key in sorted(keys):
            self._commit_notify(key)
        return ids

    def sweep_stale_dots(self) -> List[int]:
        with self._immediate() as conn:
            ids, keys = unread_sweep.sweep_stale_dots(conn)
        for key in sorted(keys):
            self._commit_notify(key)
        return ids

    def sweep_read_owners(self) -> List[int]:
        with self._immediate() as conn:
            ids, keys, owners = lifecycle.sweep_read_owners(conn)
        for item_id, owner in owners.items():
            logger.info("task_manager_read_owner_cleared", item_id=item_id, owner_prefix=owner[:8])
        for key in sorted(keys):
            self._commit_notify(key)
        return ids

    def release_conversation_claims(self, claimant: str) -> List[str]:
        with self._immediate() as conn:
            released = lifecycle.end_claims_of(conn, claimant)
        for key in sorted(released):
            self._commit_notify(key)
        return sorted(released)

    def mark_working(self, item_id: int, claimed_by: Optional[str] = None, *, swarm_caller: bool = False) -> dict:
        with closing(self._read_connection()) as conn:
            row = self._row(conn, item_id)
            flow.refuse_claim_on_held(row)
            claims.refuse_swarm_lane(row, swarm_caller)
        current = self.item(item_id)
        ticked = f"the owner ticked this item; its state is his. To ask him to reopen it, call {rules.STATE_REQUEST_TOOL}"
        approved = sorted(rules.APPROVED_STATES)
        if current["state"] in rules.APPROVED_STATES:
            raise TaskManagerForbidden(ticked)
        if current["state"] in (rules.REVIEW, rules.WAITING):
            current = self.update(item_id, actor=CLAUDE, state=rules.OPEN)
        with closing(self._connect(True)) as conn, conn:
            changed = conn.execute(
                "UPDATE work_items SET claude_working = 1, claude_working_by = ?, claude_read_seq = MAX(claude_read_seq, joe_seq) "
                f"WHERE id = ? AND deleted = 0 AND {flow.UNHELD_SQL}{'' if swarm_caller else ' AND ' + claims.NOT_SWARM_LANE_SQL} "
                f"AND state NOT IN ({','.join('?' * len(approved))}) "
                "AND (claude_working = 0 OR claude_working_by != ? OR claude_read_seq < joe_seq)",
                (claimed_by or "", item_id, *approved, claimed_by or "")).rowcount
            if not changed:
                row = self._row(conn, item_id)
                if row["state"] in rules.APPROVED_STATES:
                    raise TaskManagerForbidden(ticked)
                flow.refuse_claim_on_held(row)
                claims.refuse_swarm_lane(row, swarm_caller)
            else:
                status_lines.post(conn, item_id, current["status"], lifecycle.WORKING, by=actor_log.by_for(CLAUDE), now=self._clock())
        if changed:
            self._commit_notify(current["list"])
        return self.item(item_id)

    def mark_sent_by_swarm_ref(self, swarm_ref: str, *, prefix: bool = False) -> List[int]:
        like = swarm_ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" if prefix else None
        where = "swarm_ref LIKE ? ESCAPE '\\'" if prefix else "swarm_ref = ?"
        with self._immediate() as conn:
            rows = conn.execute(f"SELECT id, list_key FROM work_items WHERE deleted = 0 AND {where}", (like or swarm_ref,)).fetchall()
            conn.execute(f"UPDATE work_items SET claude_read_seq = MAX(claude_read_seq, joe_seq) WHERE deleted = 0 AND {where} "
                         "AND claude_read_seq < joe_seq", (like or swarm_ref,))
        for key in sorted({r["list_key"] for r in rows}):
            self._commit_notify(key)
        return [int(r["id"]) for r in rows]

    def open_swarm_cards(self) -> List[dict]:
        with closing(self._read_connection()) as conn:
            rows = conn.execute(
                "SELECT id, list_key, kind, swarm_ref, title, text FROM work_items WHERE deleted = 0 AND swarm_ref NOT IN ('', 'chat') "
                "AND state != ? ORDER BY id", (rules.DONE,)).fetchall()
        return [{"id": r["id"], "thread_key": r["list_key"], "kind": r["kind"], "swarm_ref": r["swarm_ref"], "title": r["title"] or "", "text": r["text"]}
                for r in rows]
