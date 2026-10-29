
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime
from typing import Callable, ContextManager, Dict, List, Mapping, Optional, Sequence, Set

import structlog

from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.cards.flow import CardAct
from src.cplugs.huddle import actor_log, fork as forks, from_project, groups, github_issue, item_marker, kinds, lane, lifecycle, lineage, original_ask, perceived_ask as perceived_ask_mod, review, review_checks as review_checks_mod, rules, title as titles
from src.cplugs.huddle import status_lines, store_identity
from src.cplugs.huddle import blockers, child_hold, files as item_files, item_owner, moves, late_results, owner_guards, provisional, quotes, reopen_state, reply_return, review_lock, rich_ask, schedule_offer, sends, triggers, waits
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden, TaskManagerInvalid, TaskManagerNotFound, TaskManagerStale
from src.cplugs.huddle.wire import ITEM_COLS, MSG_COLS, item_dict, message_dict, numbers_in_view
from src.cplugs.huddle.store_claims import StoreClaims
from src.cplugs.huddle.store_files import StoreFiles
from src.cplugs.huddle.store_reads import StoreReads, thread_asks
from src.cplugs.huddle.store_triggers import StoreTriggers
from src.cplugs.sdk.change_cache import CACHE
from src.cplugs.sdk import CplugStorage, work
from src.cplugs.sdk.storage import CplugSchemaError

logger = structlog.get_logger()

OPTIONAL_COLUMNS = frozenset({*review.FIELDS, review_checks_mod.FIELD, titles.FIELD, item_marker.COLUMN, item_marker.LEGACY_REASON_COLUMN, github_issue.FIELD, perceived_ask_mod.FIELD})


class TaskManagerStore(StoreReads, StoreClaims, StoreFiles, StoreTriggers):

    def __init__(self, storage: CplugStorage, notify: Callable[[str], None],
                 clock: Callable[[], float] = time.time, view: str = lifecycle.VIEW_AREA,
                 acted: Optional[Callable[[int], None]] = None) -> None:
        self._acted = acted
        self._view = view
        self._storage = storage
        self._notify = notify
        self._clock = clock

    def _connect(self, write: bool) -> sqlite3.Connection:
        return self._storage.connect(write)

    def _immediate(self) -> ContextManager[sqlite3.Connection]:
        return work.write_tx(self._connect, set(), self._commit_notify)

    def _read_connection(self) -> sqlite3.Connection:
        return self._storage.connect_read()

    def read_scope(self) -> ContextManager[None]:
        return self._storage.read_scope()

    @staticmethod
    def _next_seq(conn: sqlite3.Connection) -> int:
        return work.next_seq(conn)

    @staticmethod
    def _cursor(conn: sqlite3.Connection) -> int:
        return work.cursor(conn)

    def _row(self, conn: sqlite3.Connection, item_id: int) -> sqlite3.Row:
        row = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
        if row is None:
            raise TaskManagerNotFound(f"no huddle item {item_id}")
        return row

    def _numbers(self, conn: sqlite3.Connection, list_keys: Sequence[str]) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for key in set(list_keys):
            rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 {groups.ITEM_ORDER}", (key,)).fetchall()
            asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
            out.update(numbers_in_view(rows, {r["id"]: lifecycle.status(r, r["id"] in asking) for r in rows}, self._view))
        return out

    def _numbers_cached(self, conn: sqlite3.Connection, list_keys: Sequence[str]) -> Dict[int, int]:
        try:
            path = self._storage.db_path
        except CplugSchemaError:
            return self._numbers(conn, list_keys)
        out: Dict[int, int] = {}
        for key in set(list_keys):
            out.update(CACHE.fetch(path, ("numbers", key, self._view), lambda key=key: self._numbers(conn, [key])))
        return out

    def _acted_on(self, item_id: int) -> None:
        if self._acted is None:
            return
        try:
            self._acted(item_id)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("task_manager_acted_hook_failed", item=item_id, error=str(exc))

    def _commit_notify(self, list_key: str) -> None:
        try:
            self._notify(list_key)
        except (RuntimeError, ValueError) as exc:
            logger.warning("task_manager_notify_failed", list=list_key, error=str(exc))
        triggers.wrote()

    @staticmethod
    def _mark(conn: sqlite3.Connection, item_id: int, actor: str, seq: int, *, eyes: bool = True) -> None:
        if actor == CLAUDE:
            if eyes or conn.execute("SELECT lane FROM work_items WHERE id = ?", (item_id,)).fetchone()[0] == lane.SWARM:
                conn.execute("UPDATE work_items SET attention_seq = ? WHERE id = ?", (seq, item_id))
        else:
            if conn.execute("SELECT lane FROM work_items WHERE id = ?", (item_id,)).fetchone()[0] == lane.SWARM:
                kinds.acknowledge(conn, item_id)
            sends.stamp_joe(conn, [item_id], seq)

    def mark_seen(self, item_id: int, message_id: Optional[int] = None, through: Optional[int] = None) -> dict:
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            if message_id is not None:
                changed = kinds.read_post(conn, item_id, message_id)
            else:
                changed = kinds.acknowledge(conn, item_id, through)
        if changed:
            self._commit_notify(row["list_key"])
        self._acted_on(item_id)
        return self.item(item_id)

    def mark_unread(self, list_key: str, ids: Sequence[int]) -> None:
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        with closing(self._connect(True)) as conn, conn:
            seq = self._next_seq(conn)
            conn.execute(f"UPDATE work_items SET attention_seq = ? WHERE list_key = ? AND deleted = 0 AND id IN ({marks})",
                         (seq, list_key, *ids))
        self._commit_notify(list_key)



    @staticmethod
    def _insert_item(conn: sqlite3.Connection, list_key: str, text: str, *, actor: str, seq: int, now: float, note: str = "",
                     kind: str = rules.NO_KIND, group_id: Optional[int] = None, created_key: str = "", swarm_ref: str = "",
                     reviewing: Optional[Mapping[str, Optional[str]]] = None, forked_from: Optional[int] = None, state: str = rules.OPEN) -> int:
        live = conn.execute("SELECT COUNT(*), MAX(position) FROM work_items WHERE list_key = ? AND deleted = 0", (list_key,)).fetchone()
        born_lane = lane.for_new(list_key=list_key, created_key=created_key, swarm_ref=swarm_ref)
        born_unread = actor == CLAUDE and born_lane == lane.SWARM
        cur = conn.execute(
            "INSERT INTO work_items (list_key, text, note, position, created_by, state, created_at, updated_at, "
            "created_seq, seq, kind, attention_seq, joe_seq, group_id, created_key, swarm_ref, forked_from, lane) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (list_key, text, note, (live[1] if live[1] is not None else -1) + 1, actor, state, now, now, seq, seq, kind,
             seq if born_unread else 0, seq if actor == JOE else 0, group_id,
             created_key or (rules.OWNER_KEY if actor == JOE else ""), swarm_ref, forked_from,
             born_lane))
        if reviewing:
            TaskManagerStore._set_optional(conn, cur.lastrowid, reviewing)
        lineage.record_birth(conn, cur.lastrowid, list_key, state, actor, now, created_key)
        flow.on_inserted(conn, cur.lastrowid, now)
        return cur.lastrowid

    def add(self, list_key: str, text: str, *, actor: str, note: str = "", kind: str = rules.NO_KIND,
            group: Optional[int] = None, review_fields: Optional[Mapping[str, object]] = None,
            title: Optional[str] = None, created_key: str = "", swarm_ref: str = "",
            fire_at: Optional[str] = None, repeat: object = None, marker: Optional[str] = None,
            github_issue_url: Optional[str] = None,
            perceived_ask: Optional[str] = None, state: Optional[str] = None) -> dict:
        rules.check_actor(actor)
        rules.check_list_key(list_key)
        text = rules.clean_text(text, "text", rules.MAX_TEXT)
        note = rules.clean_text(note, "note", rules.MAX_NOTE, allow_blank=True)
        kind = rules.check_kind(kind)
        born = moves.born_state(state)
        reviewing = {**review.clean_fields(review_fields or {}), **titles.clean_fields(title), **item_marker.clean_fields(marker),
                     **github_issue.clean_field(github_issue_url), **perceived_ask_mod.clean_fields(perceived_ask)}
        if note and actor != JOE:
            raise TaskManagerForbidden("only joe writes an item's note")
        now = self._clock()
        with self._immediate() as conn:
            group_id = groups.check_group(conn, list_key, group)
            seq = self._next_seq(conn)
            item_id = self._insert_item(conn, list_key, text, actor=actor, seq=seq, now=now, note=note, kind=kind, group_id=group_id,
                                        created_key=created_key, swarm_ref=swarm_ref, reviewing=reviewing, state=born)
            if actor == CLAUDE:
                original_ask.inherit_from_claim(conn, item_id, created_key)
            trigger_change = triggers.plan(conn, item_id, born, fire_at, repeat, None, now)
            if trigger_change is not None:
                triggers.apply(conn, item_id, trigger_change, self._clock())
        self._commit_notify(list_key)
        if trigger_change is not None:
            triggers.nudge()
        logger.info("task_manager_item_added", list=list_key, item=item_id, actor=actor)
        return self.item(item_id)

    def fork(self, item_id: int, *, actor: str, claimed_by: str = "", title: Optional[str] = None, text: Optional[str] = None,
             list_key: Optional[str] = None, group: object = groups.UNSET, fork_state: Optional[str] = None,
             parent_state: Optional[str] = None, review_fields: Optional[Mapping[str, object]] = None, parent_waits: bool = False) -> dict:
        rules.check_actor(actor)
        target = rules.check_list_key(list_key) if list_key is not None else None
        now = self._clock()
        with self._immediate() as conn:
            parent = self._row(conn, item_id)
            forks.check_parent(actor, parent, parent_state)
            fork_change = forks.plan_state(actor, forks.NEW_ITEM, fork_state)
            if parent_waits:
                child_hold.check_fork(conn, parent, parent_state)
            parent_change = forks.plan_state(actor, parent, rules.WAITING if parent_waits else parent_state)
            parent_change, parent_decided = forks.gate(conn, parent, parent_change, actor, now)
            target = target or parent["list_key"]
            reviewing = {**review.clean_fields(review_fields or {}), **titles.clean_fields(title if title is not None else parent["title"]),
                         **perceived_ask_mod.clean_fields(parent[perceived_ask_mod.FIELD])}
            group_id = forks.default_group(parent, target) if group is groups.UNSET else groups.check_group(conn, target, group)
            seq = self._next_seq(conn)
            fork_id = self._insert_item(
                conn, target, rules.clean_text(text if text is not None else parent["text"], "text", rules.MAX_TEXT), actor=actor,
                seq=seq, now=now, group_id=group_id, created_key=claimed_by, reviewing=reviewing, forked_from=item_id)
            if parent_change is not None:
                review_lock.check_tick(conn, parent, parent_change.state, actor, decided=parent_decided, now=now, before_id=fork_id)
            original_ask.copy_link(conn, fork_id, parent["inbox_id"])
            owner_guards.check_fork_parent(conn, parent, parent_change.state if parent_change else None, actor, decided=parent_decided, seq=seq, now=now)
            owner_guards.check_review(conn, self._row(conn, fork_id), fork_change.state if fork_change else None, actor)
            if fork_change is not None:
                flow.on_state_write(conn, self._row(conn, fork_id), fork_change.state, actor, now, None, working=fork_change.working)
                forks.write_state(conn, fork_id, fork_change, seq=seq, now=now, claimant=claimed_by)
            if parent_change is not None:
                flow.on_state_write(conn, parent, parent_change.state, actor, now, None, working=parent_change.working, decided=parent_decided)
                forks.write_state(conn, item_id, parent_change, seq=seq, now=now, claimant=claimed_by)
            if parent_waits:
                blockers.set_hold(conn, item_id, by=claimed_by or (rules.OWNER_KEY if actor == JOE else ""), now=now)
            fork_row = self._row(conn, fork_id)
            forks.post_info(conn, fork_id, f"forked from {forks.name_of(parent)}", seq=seq, now=now)
            forks.post_info(conn, item_id, f"forked into {forks.name_of(fork_row)}", seq=seq, now=now)
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
            changed = [(item_id, parent_change), (fork_id, fork_change)]
            triggered = False
            for side, change in changed:
                self._mark(conn, side, actor, seq, eyes=kinds.needs_eyes(None, change.state if change else None))
                if change is not None:
                    cancel = triggers.plan(conn, side, change.state, None, None, None, now)
                    if cancel is not None:
                        triggers.apply(conn, side, cancel, now)
                        triggered = True
        for key in {parent["list_key"], target}:
            self._commit_notify(key)
        if triggered:
            triggers.nudge()
        if actor == JOE:
            self._acted_on(item_id)
        logger.info("task_manager_item_forked", parent=item_id, fork=fork_id, actor=actor, fork_state=fork_state, parent_state=parent_state)
        return {"fork": self.item(fork_id), "parent": self.item(item_id)}

    def update(self, item_id: int, *, actor: str, expected_revision: Optional[int] = None,
               text: Optional[str] = None, note: Optional[str] = None,
               approve: Optional[bool] = None, state: Optional[str] = None,
               kind: Optional[str] = None, review_fields: Optional[Mapping[str, object]] = None,
               title: Optional[str] = None, fire_at: Optional[str] = None, repeat: object = None,
               paused: Optional[bool] = None, marker: Optional[str] = None,
               github_issue_url: Optional[str] = None, act: Optional[CardAct] = None,
               perceived_ask: Optional[str] = None, decided: Optional[lineage.Decided] = None,
               wait: Optional[Mapping[str, object]] = None, wait_by: str = "", review_checks: Optional[Sequence[str]] = None) -> dict:
        rules.check_actor(actor)
        state = rules.canonical_state(state)
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            rules.check_not_swarm_card(actor, row["swarm_ref"])
            if expected_revision is not None and expected_revision != row["revision"]:
                raise TaskManagerStale("the item changed since you read it", current=item_dict(row))
            new_text = row["text"]
            if text is not None:
                if actor == CLAUDE and row["created_by"] != CLAUDE:
                    raise TaskManagerForbidden("claude edits only the text of items claude added")
                new_text = rules.clean_text(text, "text", rules.MAX_TEXT)
            new_kind = row["kind"]
            if kind is not None:
                if actor == CLAUDE and row["created_by"] != CLAUDE:
                    raise TaskManagerForbidden("claude sets the kind of items claude added")
                new_kind = rules.check_kind(kind)
            new_note = row["note"]
            if note is not None:
                if actor != JOE:
                    raise TaskManagerForbidden("only joe writes an item's note")
                new_note = rules.clean_text(note, "note", rules.MAX_NOTE, allow_blank=True)
            flagging = item_marker.clean_fields(marker)
            reviewing = {**review.clean_fields(review_fields or {}), **review_checks_mod.build(review_checks), **titles.clean_fields(title), **flagging, **github_issue.clean_field(github_issue_url), **perceived_ask_mod.clean_fields(perceived_ask)}
            claude_done = bool(row["claude_done"])
            if actor == CLAUDE and state is not None:
                claude_done = state == rules.REVIEW
            elif actor == JOE and state == rules.OPEN:
                claude_done = False
            restored = reply_return.restore_to_done(conn, row, actor, state, act, decided)
            reopened = None if moves.is_swarm_lane(row) or not reopen_state.is_reopen(actor, row["state"], approve) else reopen_state.state_after_reopen(conn, row)
            if restored is not None:
                new_state, decided = rules.DONE, restored
            elif reopened is not None:
                new_state, claude_done = reopened, reopened == rules.REVIEW
            else:
                new_state = rules.next_state(actor, row["state"], approve=approve, state=state, note=new_note, claude_done=claude_done, swarm_lane=moves.is_swarm_lane(row))
            review_lock.check_tick(conn, row, new_state, actor, act=act, decided=decided, now=self._clock())
            new_state, decided = moves.repeat_tick(row, actor, new_state, decided, act)
            new_state, decided = moves.checkpoint(conn, row, new_state, actor, act, decided, self._clock())
            moves.record_stop(conn, row, new_state, decided, self._clock())
            owner_guards.check_review(conn, row, new_state, actor, act=act, decided=decided, review_fields=reviewing)
            decided = reply_return.answered_review(conn, row, actor, new_state, act, decided) or decided
            if new_state != row["state"] and decided is not None:
                claude_done = new_state == rules.REVIEW
            if new_state in rules.APPROVED_STATES:
                if flagging.get(item_marker.COLUMN):
                    raise TaskManagerInvalid("an approved item takes no marker")
                if row[item_marker.COLUMN]:
                    reviewing = {**reviewing, **item_marker.CLEAR}
            review_changed = any(row[k] != v for k, v in reviewing.items())
            trigger_change = triggers.plan(conn, item_id, new_state, fire_at, repeat, paused, self._clock())
            holding = child_hold.plan(conn, row, wait, new_state, actor, act)
            parking = (waits.prepare_park(conn, row, wait, wait_by, self._clock())
                       if not holding and wait is not None and actor == CLAUDE and new_state == rules.WAITING and act is None and not moves.is_swarm_lane(row) else None)
            ends_claim = actor == CLAUDE and state == rules.OPEN
            if not review_changed and trigger_change is None and parking is None and not holding and not (ends_claim and row["claude_working"]) and (
                    new_text, new_note, new_state, claude_done, new_kind) == (
                    row["text"], row["note"], row["state"], bool(row["claude_done"]), row["kind"]):
                thread = self._thread(conn, item_id)
                return {**item_dict(row, thread_asks(thread)), "number": self._numbers(conn, [row["list_key"]]).get(item_id),
                        "thread": thread}
            flow.on_state_write(conn, row, new_state, actor, self._clock(), act, kind_changed=new_kind != row["kind"],
                                working=bool(row["claude_working"]) and new_state == rules.OPEN and not ends_claim, decided=decided)
            seq = self._next_seq(conn)
            conn.execute(
                "UPDATE work_items SET text = ?, note = ?, state = ?, claude_done = ?, kind = ?, updated_at = ?, "
                "revision = revision + 1, seq = ?, claude_working = claude_working * (? = 'open' AND ? = 0), "
                "claude_working_by = CASE WHEN ? = 'open' AND ? = 0 THEN claude_working_by ELSE '' END WHERE id = ?",
                (new_text, new_note, new_state, int(claude_done), new_kind, self._clock(), seq, new_state, int(ends_claim),
                 new_state, int(ends_claim), item_id))
            if actor == JOE and new_state in rules.APPROVED_STATES:
                item_owner.keep_for_tell(conn, row)
            if reviewing:
                self._set_optional(conn, item_id, reviewing)
            if trigger_change is not None:
                triggers.apply(conn, item_id, trigger_change, self._clock())
            wait_token = parking.commit(conn, item_id, self._clock()) if parking is not None else None
            if holding:
                blockers.set_hold(conn, item_id, by=wait_by, now=self._clock())
            self._mark(conn, item_id, actor, seq, eyes=kinds.needs_eyes(row["state"], new_state))
            if actor == JOE and (new_state in rules.APPROVED_STATES or (decided is not None and decided.detail == moves.REPEAT_TICK)):
                kinds.acknowledge(conn, item_id)
            list_key = row["list_key"]
        self._commit_notify(list_key)
        if trigger_change is not None:
            triggers.nudge()
        if actor == JOE:
            self._acted_on(item_id)
        logger.info("task_manager_item_updated", item=item_id, actor=actor, state=new_state)
        updated = self.item(item_id)
        return {**updated, waits.TOKEN_KEY: wait_token} if wait_token else updated

    def tick_review_check(self, item_id: int, check_id: str, checked: bool, *, actor: str) -> dict:
        rules.check_actor(actor)
        if actor != JOE:
            raise TaskManagerForbidden("only the owner ticks a review check")
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            stored = review_checks_mod.tick(row[review_checks_mod.FIELD], check_id, checked, actor, self._clock())
            before = review_checks_mod.parse(row[review_checks_mod.FIELD])
            unchanged = next((c.get("checked") for c in before if c.get("id") == check_id), None) == checked
            if not unchanged:
                seq = self._next_seq(conn)
                conn.execute("UPDATE work_items SET review_checks = ?, updated_at = ?, revision = revision + 1, seq = ? WHERE id = ?",
                             (stored, self._clock(), seq, item_id))
            list_key = row["list_key"]
        if not unchanged:
            self._commit_notify(list_key)
            logger.info("task_manager_review_check_ticked", item=item_id, check=check_id, checked=checked)
        return self.item(item_id)

    def awaiting_answer(self, item_ids: Sequence[int]) -> List[int]:
        with closing(self._read_connection()) as conn:
            rows = (conn.execute("SELECT * FROM work_items WHERE id = ?", (i,)).fetchone() for i in item_ids)
            return [r["id"] for r in rows if r is not None and reply_return.awaiting_answer(conn, r)]

    def retire_swarm_ref(self, item_id: int) -> None:
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            ref = row["swarm_ref"]
            if ref in rules.NOT_A_CARD_REFS or ref.startswith(rules.CLOSED_REF_PREFIX):
                return
            seq = self._next_seq(conn)
            conn.execute("UPDATE work_items SET swarm_ref = ?, revision = revision + 1, seq = ?, updated_at = ? WHERE id = ?",
                         (rules.CLOSED_REF_PREFIX + ref, seq, self._clock(), item_id))
            list_key = row["list_key"]
        self._commit_notify(list_key)

    @staticmethod
    def _set_optional(conn: sqlite3.Connection, item_id: int, fields: Mapping[str, Optional[str]]) -> None:
        unknown = set(fields) - OPTIONAL_COLUMNS
        if unknown:
            raise ValueError(f"not an optional item column: {sorted(unknown)[0]}")
        sets = ", ".join(f"{name} = ?" for name in fields)
        conn.execute(f"UPDATE work_items SET {sets} WHERE id = ?", (*fields.values(), item_id))

    @staticmethod
    def _thread(conn: sqlite3.Connection, item_id: int) -> List[dict]:
        return [message_dict(m) for m in conn.execute(
            f"SELECT {MSG_COLS} FROM work_messages WHERE item_id = ? ORDER BY id", (item_id,))]

    def deleted_item(self, item_id: int) -> dict:
        with closing(self._read_connection()) as conn:
            row = conn.execute("SELECT list_key, revision FROM work_items WHERE id = ? AND deleted = 1", (item_id,)).fetchone()
        if row is None:
            raise TaskManagerNotFound(f"no deleted huddle item {item_id}")
        return {"id": item_id, "list": row["list_key"], "deleted": True, "revision": row["revision"]}

    def delete(self, item_id: int, *, actor: str, expected_revision: Optional[int] = None, reason: str = "") -> dict:
        if rules.check_actor(actor) != JOE:
            raise TaskManagerForbidden("only joe deletes an item")
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            if expected_revision is not None and expected_revision != row["revision"]:
                raise TaskManagerStale("the item changed since you read it", current=item_dict(row))
            flow.on_tombstone(conn, [row], self._clock(), actor_log.by_for(actor), detail=reason)
            seq = self._next_seq(conn)
            conn.execute("UPDATE work_items SET deleted = 1, flag_color = NULL, flag_reason = NULL, seq = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                         (seq, self._clock(), item_id))
            sends.stamp_joe(conn, [item_id], seq)
            triggers.cancel(conn, item_id)
            named = moves.thread_file_names(conn, item_id)
            moves.purge(conn, item_id)
        moves.remove_folder(item_files.item_dir(self._storage, item_id))
        moves.remove_task_files(item_id, store_identity.of(self._storage), named)
        self._commit_notify(row["list_key"])
        triggers.nudge()
        logger.info("task_manager_item_deleted", item=item_id)
        return {"id": item_id, "list": row["list_key"], "deleted": True, "revision": row["revision"] + 1}

    def move(self, item_id: int, list_key: str, *, actor: str, group: object = groups.UNSET) -> dict:
        rules.check_actor(actor)
        rules.check_list_key(list_key)
        with closing(self._read_connection()) as conn:
            moving = self._row(conn, item_id)
            rules.check_not_swarm_card(actor, moving["swarm_ref"])
            here = moving["list_key"]
        if here == list_key:
            return self.item(item_id) if group is groups.UNSET else groups.GroupWriter(self).set_group(item_id, group, actor=actor)
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            source = row["list_key"]
            target_group = groups.check_group(conn, list_key, None if group is groups.UNSET else group)
            live = conn.execute("SELECT COUNT(*), MAX(position) FROM work_items WHERE list_key = ? AND deleted = 0",
                                (list_key,)).fetchone()
            flow.on_list_move(conn, row, list_key, self._clock(), actor_log.by_for(actor))
            seq = self._next_seq(conn)
            conn.execute("UPDATE work_items SET list_key = ?, group_id = ?, position = ?, seq = ?, updated_at = ?, "
                         "revision = revision + 1 WHERE id = ?",
                         (list_key, target_group, (live[1] if live[1] is not None else -1) + 1, seq, self._clock(), item_id))
            conn.execute("UPDATE work_messages SET seq = ? WHERE item_id = ?", (seq, item_id))
            if actor == JOE:
                sends.stamp_joe(conn, [item_id], seq)
        self._commit_notify(source)
        self._commit_notify(list_key)
        logger.info("task_manager_item_moved", item=item_id, source=source, target=list_key, actor=actor)
        return self.item(item_id)

    def remove_completed(self, list_key: str, *, actor: str) -> dict:
        if rules.check_actor(actor) != JOE:
            raise TaskManagerForbidden("only joe removes items")
        rules.check_list_key(list_key)
        marks = ",".join("?" for _ in rules.APPROVED_STATES)
        with self._immediate() as conn:
            gone = conn.execute(
                f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 AND state IN ({marks}) ORDER BY position, id",
                (list_key, *sorted(rules.APPROVED_STATES))).fetchall()
            ids = [r["id"] for r in gone]
            if ids:
                flow.on_tombstone(conn, gone, self._clock())
                seq = self._next_seq(conn)
                conn.executemany("UPDATE work_items SET deleted = 1, seq = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                                 [(seq, self._clock(), item_id) for item_id in ids])
                sends.stamp_joe(conn, ids, seq)
        if ids:
            self._commit_notify(list_key)
        logger.info("task_manager_completed_removed", list=list_key, count=len(ids))
        return {"list": list_key, "removed": ids}

    def reorder(self, list_key: str, ids: Sequence[int], *, actor: str, expected_revision: int) -> dict:
        if rules.check_actor(actor) != JOE:
            raise TaskManagerForbidden("only joe reorders a list")
        rules.check_list_key(list_key)
        if not isinstance(ids, (list, tuple)) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise TaskManagerInvalid("ids must be a list of item ids")
        with self._immediate() as conn:
            revision = self._list_revision(conn, list_key)
            stored = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 {groups.ITEM_ORDER}", (list_key,)).fetchall()
            rows = [(r["id"], r["lane"]) for r in stored]
            live = [i for i, _ in rows]
            settled = {r["id"] for r in stored if lifecycle.status(r, False) == lifecycle.DONE}
            full = lane.merge_order(rows, list(ids), settled) if len(set(ids)) == len(ids) else None
            if expected_revision != revision or full is None:
                raise TaskManagerStale("the list changed since you read it", current={"revision": revision})
            ids = full
            if list(ids) != live:
                seq = self._next_seq(conn)
                now = self._clock()
                for position, item_id in enumerate(ids):
                    conn.execute("UPDATE work_items SET position = ?, seq = ?, updated_at = ? WHERE id = ? AND position != ?",
                                 (position, seq, now, item_id, position))
        self._commit_notify(list_key)
        return self.list_items(list_key)

    def note_system(self, item_id: int, text: str) -> None:
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            seq = self._next_seq(conn)
            forks.post_info(conn, item_id, text, seq=seq, now=self._clock())
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
        self._commit_notify(row["list_key"])

    def stamp_from_project(self, item_id: int, project_id: str, project_name: str) -> bool:
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            if not from_project.is_unset(row):
                return False
            seq = self._next_seq(conn)
            conn.execute(from_project.stamp_sql(), (project_id, project_name, item_id))
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
        self._commit_notify(row["list_key"])
        return True

    def mark_answered(self, item_id: int, *, actor: str) -> dict:
        rules.check_actor(actor)
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            rules.check_not_swarm_card(actor, row["swarm_ref"])
            wait_asked = conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND kind = 'question' AND answered = 0 AND category = ?",
                                      (item_id, "wait_stuck")).fetchone() is not None
            if wait_asked and actor != JOE:
                raise TaskManagerForbidden("the owner answers a stuck-wait question (push, drop or wait longer); it cannot be closed for him")
            if conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND kind = 'question' AND answered = 0",
                            (item_id,)).fetchone():
                seq = self._next_seq(conn)
                conn.execute("UPDATE work_messages SET answered = 1, seq = ? WHERE item_id = ? AND kind = 'question' "
                             "AND answered = 0", (seq, item_id))
                conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
                status_lines.post(conn, item_id, lifecycle.QUESTION, lifecycle.OPEN, by=actor_log.by_for(actor), now=self._clock())
                changed = True
            elif row["kind"] == rules.QUESTION and row["created_by"] == CLAUDE and not row["joe_seq"]:
                seq = self._next_seq(conn)
                conn.execute("UPDATE work_items SET joe_seq = ?, claude_read_seq = ?, seq = ?, revision = revision + 1 WHERE id = ?",
                             (seq, seq, seq, item_id))
                changed = True
            else:
                changed = False
        if changed:
            self._commit_notify(row["list_key"])
            logger.info("task_manager_question_answered_elsewhere", item=item_id, actor=actor)
        if wait_asked and row["state"] == rules.WAITING:
            self.update(item_id, actor=JOE, state=rules.OPEN, decided=lineage.Decided(lineage.CARNIVORE, "wait_closed"))
        self._acted_on(item_id)
        return self.item(item_id)

    def post(self, item_id: int, text: str, *, actor: str, kind: Optional[str] = None, author_key: str = "", parts: str = "", allow_blank: bool = False,
             quote: Optional[int] = None, quote_text: str = "", category: str = "", act: Optional[CardAct] = None, notify: bool = False,
             offer: Optional[Mapping[str, str]] = None, ack_through: Optional[int] = None) -> dict:
        text = rules.clean_text(text, "text", rules.MAX_MESSAGE, allow_blank=allow_blank)
        kinds.resolve(kind, actor, lifecycle.OPEN)
        with self._immediate() as conn:
            row = self._row(conn, item_id)
            kind = kinds.resolve(kind, actor, lifecycle.status(row, item_id in lifecycle.asking_ids(conn, [item_id])))
            if kind == kinds.ANSWER:
                parts = quotes.build(conn, item_id, quote, quote_text, parts)
            elif quote is not None or quote_text:
                raise TaskManagerInvalid("quote goes only on an answer post (kind answer)")
            if offer:
                if actor != CLAUDE:
                    raise TaskManagerInvalid("only the agent offers a schedule")
                parts = schedule_offer.attach(parts, dict(offer))
            seq = self._next_seq(conn)
            asker = ""
            quiet = kind == kinds.COMMENT
            if actor == JOE and not quiet:
                kinds.acknowledge(conn, item_id, None if moves.is_swarm_lane(row) else ack_through)
                triggers.resume_skipped(conn, item_id, self._clock(), (triggers.SKIP_JOE,))
                conn.execute(
                    "UPDATE work_messages SET answered = 1, seq = ? WHERE item_id = ? AND kind = 'question' "
                    f"AND answered = 0 AND NOT ({rich_ask.TYPED_SQL})", (seq, item_id))
                if kind == rules.REPLY and author_key in ("", rules.OWNER_KEY):
                    parts, asker = provisional.answer(conn, item_id, seq, parts)
            cur = conn.execute(
                "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, actor, kind, text, self._clock(), seq, author_key or (rules.OWNER_KEY if actor == JOE else ""), parts, category))
            message_id = cur.lastrowid
            item_files.require_present(self._storage, parts)
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
            if actor == CLAUDE:
                owner_guards.after_agent_post(conn, row, kind, text, author_key, seq=seq, now=self._clock())
            if actor == JOE and not quiet and moves.reply_reopens(row, wait_on_owner=row["state"] == rules.WAITING and waits.on_owner(conn, item_id)):
                said = lineage.Decided(actor_log.by_for(JOE), reply_return.REPLIED) if row["state"] in (rules.REVIEW, *rules.APPROVED_STATES) and not moves.is_swarm_lane(row) else None
                flow.on_state_write(conn, row, rules.OPEN, JOE, self._clock(), act, working=False, decided=said)
                conn.execute("UPDATE work_items SET state = ?, claude_done = 0, claude_working = 0, claude_working_by = '', "
                             "revision = revision + 1 WHERE id = ?", (rules.OPEN, item_id))
            if asker:
                lifecycle.claim(conn, item_id, asker)
            if actor == CLAUDE and kind == rules.QUESTION:
                moves.supersede_questions(conn, item_id, message_id, seq)
            if actor == CLAUDE and kind in (rules.QUESTION, kinds.ATTENTION):
                lifecycle.end_claim(conn, item_id)
            if actor == CLAUDE and kind == rules.QUESTION:
                item_owner.adopt_asker(conn, item_id, author_key)
            if actor == CLAUDE:
                kinds.stamp_claude(conn, row, kind, seq, late_results.lands_unread(conn, row, notify))
            elif not quiet:
                self._mark(conn, item_id, actor, seq)
            message = message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (message_id,)).fetchone())
        self._commit_notify(row["list_key"])
        if actor == JOE and not quiet:
            self._acted_on(item_id)
        logger.info("task_manager_message_posted", item=item_id, actor=actor, kind=kind)
        return {"item": self.item(item_id), "message": message}

    def accept_schedule(self, item_id: int, message_id: int) -> dict:
        touched: Set[str] = set()
        with work.write_tx(self._connect, touched, self._commit_notify) as conn:
            row = self._row(conn, item_id)
            touched.add(row["list_key"])
            found = conn.execute("SELECT parts FROM work_messages WHERE id = ? AND item_id = ? AND author = ?", (message_id, item_id, CLAUDE)).fetchone()
            offer = schedule_offer.read(found["parts"]) if found else None
            if found is None or offer is None:
                raise TaskManagerNotFound(f"message {message_id} on item {item_id} holds no schedule offer")
            if offer["state"] == schedule_offer.ACCEPTED:
                raise TaskManagerInvalid("that schedule offer was already accepted")
            triggers.parse_fire_at(offer["when"], self._clock())
            seq = self._next_seq(conn)
            stamp = datetime.fromtimestamp(self._clock()).astimezone().isoformat(timespec="seconds")
            conn.execute("UPDATE work_messages SET parts = ?, seq = ? WHERE id = ?", (schedule_offer.accept(found["parts"], stamp), seq, message_id))
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
            message = message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (message_id,)).fetchone())
        logger.info("task_manager_schedule_accepted", item=item_id, message=message_id)
        return {"offer": message["schedule"], "message": message}
