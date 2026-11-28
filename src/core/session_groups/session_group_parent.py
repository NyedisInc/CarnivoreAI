
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from src.core.db import column_exists
from src.core.session_group_errors import GroupNotFound, SessionGroupError

PARENT_COLUMN = "parent_key"

SECTION_PARENTS = frozenset({"pinned", "layouts", "rogue", "terminals", "browsers", "files"})

_COMPANY_RE = re.compile(r"^c:(?:\d{1,18}|orphaned)$")
_PROJECT_RE = re.compile(r"^p:\d{1,18}$")
_GROUP_RE = re.compile(r"^g:[A-Za-z0-9_-]{1,120}$")
_LAYOUT_RE = re.compile(r"^layout:[A-Za-z0-9_-]{1,120}$")


class GroupParentInvalid(SessionGroupError):
    pass


def apply_v111(conn: sqlite3.Connection) -> None:
    if not column_exists(conn, "session_groups", PARENT_COLUMN):
        conn.execute(f"ALTER TABLE session_groups ADD COLUMN {PARENT_COLUMN} TEXT")
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS ix_session_groups_parent "
        f"ON session_groups ({PARENT_COLUMN}, position)"
    )


def normalize_parent_key(raw: object) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise GroupParentInvalid("parent_key must be a string or null")
    key = raw.strip()
    if not key:
        return None
    if (
        key in SECTION_PARENTS
        or _COMPANY_RE.match(key)
        or _PROJECT_RE.match(key)
        or _GROUP_RE.match(key)
        or _LAYOUT_RE.match(key)
    ):
        return key
    raise GroupParentInvalid(f"invalid parent_key: {key!r}")


def validate_parent_target(
    conn: sqlite3.Connection,
    raw: object,
    *,
    group_uuid: Optional[str] = None,
) -> Optional[str]:
    key = normalize_parent_key(raw)
    if key is None or not key.startswith("g:"):
        return key
    target_uuid = key[2:]
    if group_uuid is not None and target_uuid == group_uuid:
        raise GroupParentInvalid("a group cannot be nested inside itself")
    has_col = column_exists(conn, "session_groups", PARENT_COLUMN)
    seen = {group_uuid} if group_uuid else set()
    cur: Optional[str] = target_uuid
    while cur is not None:
        if cur in seen:
            raise GroupParentInvalid("nesting this group here would create a cycle")
        seen.add(cur)
        if has_col:
            row = conn.execute(
                f"SELECT {PARENT_COLUMN} FROM session_groups WHERE group_uuid = ?",
                (cur,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT NULL FROM session_groups WHERE group_uuid = ?",
                (cur,),
            ).fetchone()
        if row is None:
            if cur == target_uuid:
                raise GroupNotFound(f"no parent group with uuid {target_uuid!r}")
            break
        parent = row[0]
        cur = parent[2:] if isinstance(parent, str) and parent.startswith("g:") else None
    return key
