
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

import structlog

from src.cplugs.huddle import rules, sends
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden, TaskManagerInvalid, TaskManagerNotFound, TaskManagerStale
from src.cplugs.huddle.wire import item_dict

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()


ITEM_ORDER = "ORDER BY (SELECT g.position FROM work_item_groups g WHERE g.id = work_items.group_id), position, id"

MAX_GROUPS_PER_LIST = 50
MAX_NAME = 80

GROUP_COLS = "id, list_key, name, position, folded, created_by, seq, deleted"

UNSET = object()


def group_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "list": row["list_key"], "name": row["name"], "position": row["position"],
            "folded": bool(row["folded"]), "created_by": row["created_by"], "seq": row["seq"],
            "deleted": bool(row["deleted"])}


def live_groups(conn: sqlite3.Connection, list_key: str) -> List[dict]:
    return [group_dict(r) for r in conn.execute(
        f"SELECT {GROUP_COLS} FROM work_item_groups WHERE list_key = ? AND deleted = 0 ORDER BY position, id", (list_key,))]


def changed_groups(conn: sqlite3.Connection, since: int, list_key: Optional[str]) -> List[dict]:
    where, args = ("AND list_key = ?", [list_key]) if list_key else ("", [])
    return [group_dict(r) for r in conn.execute(
        f"SELECT {GROUP_COLS} FROM work_item_groups WHERE seq > ? {where} ORDER BY seq", [since, *args])]


def check_group(conn: sqlite3.Connection, list_key: str, group: object) -> Optional[int]:
    if group is None:
        return None
    if isinstance(group, bool) or not isinstance(group, int):
        raise TaskManagerInvalid("group must be a group id (or null for ungrouped)")
    found = conn.execute("SELECT 1 FROM work_item_groups WHERE id = ? AND list_key = ? AND deleted = 0",
                         (group, list_key)).fetchone()
    if found is None:
        raise TaskManagerNotFound(f"no group {group} in list {list_key}")
    return group


def clean_name(value: object) -> str:
    name = rules.clean_text(value, "name", MAX_NAME)
    if "\n" in name or "\t" in name:
        raise TaskManagerInvalid("a group name is one line")
    return name


def _ordered(conn: sqlite3.Connection, list_key: str) -> List[sqlite3.Row]:
    return conn.execute(f"SELECT id, group_id, position FROM work_items WHERE list_key = ? AND deleted = 0 {ITEM_ORDER}",
                        (list_key,)).fetchall()


def renumber(conn: sqlite3.Connection, order: Sequence[int], current: Dict[int, int], seq: int, now: float) -> None:
    conn.executemany("UPDATE work_items SET position = ?, seq = ?, updated_at = ? WHERE id = ?",
                     [(p, seq, now, i) for p, i in enumerate(order) if current.get(i) != p])


def place_in_section(rows: Sequence[sqlite3.Row], item_id: int, group: Optional[int],
                     group_order: Sequence[int], index: Optional[int]) -> List[int]:
    sections: Dict[Optional[int], List[int]] = {None: [], **{g: [] for g in group_order}}
    for row in rows:
        if row["id"] != item_id:
            sections.setdefault(row["group_id"], []).append(row["id"])
    target = sections.setdefault(group, [])
    at = len(target) if index is None else max(0, min(len(target), index))
    target.insert(at, item_id)
    return [i for key in [None, *group_order] for i in sections.get(key, [])]


class GroupWriter:

    def __init__(self, store: "TaskManagerStore") -> None:
        self._store = store

    def _group(self, conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
        if isinstance(group_id, bool) or not isinstance(group_id, int):
            raise TaskManagerInvalid("group must be a group id")
        row = conn.execute(f"SELECT {GROUP_COLS} FROM work_item_groups WHERE id = ? AND deleted = 0", (group_id,)).fetchone()
        if row is None:
            raise TaskManagerNotFound(f"no huddle group {group_id}")
        return row

    def list_of(self, group_id: int) -> str:
        with closing(self._store._read_connection()) as conn:
            return self._group(conn, group_id)["list_key"]

    def create(self, list_key: str, name: str, *, actor: str) -> dict:
        rules.check_actor(actor)
        rules.check_list_key(list_key)
        name = clean_name(name)
        s = self._store
        with closing(s._connect(True)) as conn, conn:
            groups = live_groups(conn, list_key)
            same = next((g for g in groups if g["name"].casefold() == name.casefold()), None)
            if same is not None:
                return {**same, "created": False}
            if len(groups) >= MAX_GROUPS_PER_LIST:
                raise TaskManagerInvalid(f"a list holds at most {MAX_GROUPS_PER_LIST} groups")
            seq = s._next_seq(conn)
            now = s._clock()
            cur = conn.execute(
                "INSERT INTO work_item_groups (list_key, name, position, created_by, created_at, updated_at, seq) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (list_key, name, max([g["position"] for g in groups], default=-1) + 1, actor, now, now, seq))
            row = conn.execute(f"SELECT {GROUP_COLS} FROM work_item_groups WHERE id = ?", (cur.lastrowid,)).fetchone()
        s._commit_notify(list_key)
        logger.info("task_manager_group_created", list=list_key, group=row["id"], actor=actor)
        return {**group_dict(row), "created": True}

    def update(self, group_id: int, *, actor: str, name: Optional[str] = None, position: Optional[int] = None,
               folded: Optional[bool] = None) -> dict:
        rules.check_actor(actor)
        if folded is not None and actor != JOE:
            raise TaskManagerForbidden("the fold is the owner's view")
        if position is not None and (isinstance(position, bool) or not isinstance(position, int)):
            raise TaskManagerInvalid("position must be an integer (0 is the first group)")
        s = self._store
        with closing(s._connect(True)) as conn, conn:
            row = self._group(conn, group_id)
            key = row["list_key"]
            groups = live_groups(conn, key)
            content = False
            seq = 0
            if name is not None:
                new = clean_name(name)
                if any(g["id"] != group_id and g["name"].casefold() == new.casefold() for g in groups):
                    raise TaskManagerInvalid(f"a group named {new!r} is already in this list")
                if new != row["name"]:
                    seq = s._next_seq(conn)
                    conn.execute("UPDATE work_item_groups SET name = ?, seq = ?, updated_at = ? WHERE id = ?",
                                 (new, seq, s._clock(), group_id))
                    content = True
            if position is not None:
                order = [g["id"] for g in groups if g["id"] != group_id]
                order.insert(max(0, min(len(order), position)), group_id)
                stored = {g["id"]: g["position"] for g in groups}
                moved = [(p, gid) for p, gid in enumerate(order) if stored.get(gid) != p]
                if moved:
                    seq = seq or s._next_seq(conn)
                    conn.executemany("UPDATE work_item_groups SET position = ?, seq = ?, updated_at = ? WHERE id = ?",
                                     [(p, seq, s._clock(), gid) for p, gid in moved])
                    content = True
            fold_moved = folded is not None and bool(folded) != bool(row["folded"])
            if fold_moved:
                conn.execute("UPDATE work_item_groups SET folded = ? WHERE id = ?", (int(bool(folded)), group_id))
            after = group_dict(conn.execute(f"SELECT {GROUP_COLS} FROM work_item_groups WHERE id = ?", (group_id,)).fetchone())
        if content or fold_moved:
            s._commit_notify(key)
        if content:
            logger.info("task_manager_group_updated", group=group_id, actor=actor)
        return after

    def fold_many(self, group_ids: Sequence[int], folded: bool, *, actor: str) -> dict:
        rules.check_actor(actor)
        if actor != JOE:
            raise TaskManagerForbidden("the fold is the owner's view")
        if not isinstance(folded, bool):
            raise TaskManagerInvalid("folded must be true or false")
        if any(isinstance(g, bool) or not isinstance(g, int) for g in group_ids):
            raise TaskManagerInvalid("groups must be group ids")
        s = self._store
        updated: List[int] = []
        missing: List[int] = []
        touched: List[str] = []
        with closing(s._connect(True)) as conn, conn:
            for group_id in dict.fromkeys(group_ids):
                row = conn.execute(f"SELECT {GROUP_COLS} FROM work_item_groups WHERE id = ? AND deleted = 0", (group_id,)).fetchone()
                if row is None:
                    missing.append(group_id)
                    continue
                updated.append(group_id)
                if bool(row["folded"]) != folded:
                    conn.execute("UPDATE work_item_groups SET folded = ? WHERE id = ?", (int(folded), group_id))
                    if row["list_key"] not in touched:
                        touched.append(row["list_key"])
        for list_key in touched:
            s._commit_notify(list_key)
        logger.info("task_manager_groups_folded", groups=len(updated), missing=len(missing), folded=folded, actor=actor)
        return {"folded": folded, "updated": updated, "missing": missing}

    def remove(self, group_id: int, *, actor: str) -> dict:
        rules.check_actor(actor)
        s = self._store
        with closing(s._connect(True)) as conn, conn:
            row = self._group(conn, group_id)
            key = row["list_key"]
            rows = _ordered(conn, key)
            freed = [r["id"] for r in rows if r["group_id"] == group_id]
            seq = s._next_seq(conn)
            now = s._clock()
            conn.execute("UPDATE work_item_groups SET deleted = 1, seq = ?, updated_at = ? WHERE id = ?", (seq, now, group_id))
            others = [g["id"] for g in live_groups(conn, key)]
            loose = [r["id"] for r in rows if r["group_id"] is None]
            order = loose + freed + [r["id"] for g in others for r in rows if r["group_id"] == g]
            conn.executemany("UPDATE work_items SET group_id = NULL, revision = revision + 1 WHERE id = ?", [(i,) for i in freed])
            renumber(conn, order, {r["id"]: r["position"] for r in rows}, seq, now)
            conn.executemany("UPDATE work_items SET seq = ? WHERE id = ?", [(seq, i) for i in freed])
            if actor == JOE:
                sends.stamp_joe(conn, freed, seq)
        s._commit_notify(key)
        logger.info("task_manager_group_removed", group=group_id, list=key, ungrouped=len(freed), actor=actor)
        return {"group": group_id, "list": key, "ungrouped": freed}

    def set_group(self, item_id: int, group: object, *, actor: str, index: Optional[int] = None,
                  expected_revision: Optional[int] = None) -> dict:
        rules.check_actor(actor)
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise TaskManagerInvalid("index must be an integer (0 is the top of the group)")
        if index is not None and actor == CLAUDE:
            raise TaskManagerForbidden("only the owner orders a list; claude files an item at the bottom of a group")
        s = self._store
        with closing(s._connect(True)) as conn, conn:
            row = s._row(conn, item_id)
            if expected_revision is not None and expected_revision != row["revision"]:
                raise TaskManagerStale("the item changed since you read it", current=item_dict(row))
            key = row["list_key"]
            target = check_group(conn, key, group)
            rows = _ordered(conn, key)
            group_order = [g["id"] for g in live_groups(conn, key)]
            if target == row["group_id"] and index is None:
                return s.item(item_id)
            order = place_in_section(rows, item_id, target, group_order, index)
            if order == [r["id"] for r in rows] and target == row["group_id"]:
                return s.item(item_id)
            seq = s._next_seq(conn)
            now = s._clock()
            renumber(conn, order, {r["id"]: r["position"] for r in rows}, seq, now)
            conn.execute("UPDATE work_items SET group_id = ?, seq = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                         (target, seq, now, item_id))
            if actor == JOE:
                sends.stamp_joe(conn, [item_id], seq)
        s._commit_notify(key)
        logger.info("task_manager_item_grouped", item=item_id, group=target, actor=actor)
        return s.item(item_id)

    def find_or_create(self, list_key: str, group: object, *, actor: str) -> Optional[int]:
        if group is None:
            return None
        if isinstance(group, str):
            return int(self.create(list_key, group, actor=actor)["id"])
        with closing(self._store._read_connection()) as conn:
            return check_group(conn, list_key, group)
