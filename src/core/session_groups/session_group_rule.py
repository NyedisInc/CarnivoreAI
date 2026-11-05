
from __future__ import annotations

import json
import sqlite3
from typing import Dict, Optional, Tuple

from src.core.db import table_exists
from src.core.session_group_errors import SessionGroupError
from src.core.trail_entry import utc_now

RULE_TABLE = "session_group_rules"

FLAGS: Tuple[str, ...] = (
    "running", "sleeping", "coffee", "sharing", "pinned", "remote", "swarm", "unread", "waiting",
)

TEXT_MAX = 64

DDL_V101: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {RULE_TABLE} (
        group_id   INTEGER PRIMARY KEY REFERENCES session_groups(id) ON DELETE CASCADE,
        rule_json  TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
)


class GroupRuleInvalid(SessionGroupError):
    pass


def apply_v101(conn: sqlite3.Connection) -> None:
    for statement in DDL_V101:
        conn.execute(statement)


def normalize(flags: object, prefix: object, suffix: object) -> Optional[Dict[str, object]]:
    raw = list(flags) if isinstance(flags, (list, tuple)) else []
    unknown = [f for f in raw if f not in FLAGS]
    if unknown:
        raise GroupRuleInvalid(f"unknown rule flag: {unknown[0]!r}")
    texts = []
    for value in (prefix, suffix):
        if value is not None and not isinstance(value, str):
            raise GroupRuleInvalid("prefix and suffix must be text")
        clean = (value or "").strip()
        if len(clean) > TEXT_MAX:
            raise GroupRuleInvalid(f"prefix and suffix are at most {TEXT_MAX} characters")
        texts.append(clean)
    kept = [f for f in FLAGS if f in raw]
    if not kept and not texts[0] and not texts[1]:
        return None
    return {"flags": kept, "prefix": texts[0], "suffix": texts[1]}


def rules_by_group(conn: sqlite3.Connection) -> Dict[int, Dict[str, object]]:
    if not table_exists(conn, RULE_TABLE):
        return {}
    out: Dict[int, Dict[str, object]] = {}
    for gid, blob in conn.execute(f"SELECT group_id, rule_json FROM {RULE_TABLE}").fetchall():
        try:
            rule = normalize(*(lambda d: (d.get("flags"), d.get("prefix"), d.get("suffix")))(json.loads(blob)))
        except (ValueError, AttributeError, GroupRuleInvalid):
            continue
        if rule:
            out[int(gid)] = rule
    return out


def write(conn: sqlite3.Connection, group_id: int, rule: Optional[Dict[str, object]], *, now: Optional[str] = None) -> None:
    if rule is None:
        conn.execute(f"DELETE FROM {RULE_TABLE} WHERE group_id = ?", (group_id,))
        return
    conn.execute(
        f"INSERT INTO {RULE_TABLE} (group_id, rule_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(group_id) DO UPDATE SET rule_json = excluded.rule_json, updated_at = excluded.updated_at",
        (group_id, json.dumps(rule, sort_keys=True), now or utc_now()),
    )
