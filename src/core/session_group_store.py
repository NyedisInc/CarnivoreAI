
from __future__ import annotations

import sqlite3
import uuid as _uuid
from dataclasses import dataclass
from typing import List, Optional

from src.core import session_group_style as style_store
from src.core.db import column_exists, table_exists, transaction
from src.core.session_group_style_ddl import SESSION_GROUP_STYLES_TABLE
from src.core.session_group_icon_ddl import ICON_COLUMN
from src.core.db_models import SESSION_GROUP_MAX, SESSION_GROUP_NAME_MAX
from src.core.trail_entry import utc_now
from src.core.session_group_errors import (  # noqa: F401
    GroupLimitReached,
    GroupNameInvalid,
    GroupNotFound,
    GroupsUnavailable,
    SessionGroupError,
    SessionNotStored,
)
from src.core.session_group_membership import (  # noqa: F401
    assign,
    assign_layout,
    assign_session,
    clear_group,
    group_id_for as _group_id,
    group_of,
    group_of_session,
    members_by_group,
    prune_missing,
    require_tables as _require_tables,
    session_uuid_for_name,
    set_member_order,
)


@dataclass(frozen=True)
class SessionGroup:

    group_uuid: str
    name: str
    position: int
    created_at: str
    updated_at: Optional[str]
    members: tuple
    member_session_uuids: tuple = ()
    style: Optional[style_store.GroupStyle] = None


def normalize_name(raw: str) -> str:
    if not isinstance(raw, str):
        raise GroupNameInvalid("group name must be a string")
    name = " ".join(raw.split())
    if not name:
        raise GroupNameInvalid("group name is empty")
    if len(name) > SESSION_GROUP_NAME_MAX:
        raise GroupNameInvalid(
            f"group name is {len(name)} characters, the limit is "
            f"{SESSION_GROUP_NAME_MAX}"
        )
    return name


def list_groups(conn: sqlite3.Connection) -> List[SessionGroup]:
    _require_tables(conn)
    members = members_by_group(conn)
    styles = style_store.styles_by_group(conn)
    rows = conn.execute(
        "SELECT id, group_uuid, name, position, created_at, updated_at "
        "FROM session_groups ORDER BY position ASC, group_uuid ASC"
    ).fetchall()
    out: List[SessionGroup] = []
    for r in rows:
        filed = members.get(int(r[0]), [])
        out.append(
            SessionGroup(
                group_uuid=str(r[1]),
                name=str(r[2]),
                position=int(r[3]),
                created_at=str(r[4]),
                updated_at=(str(r[5]) if r[5] is not None else None),
                members=tuple(name for _, name in filed if name),
                member_session_uuids=tuple(uuid for uuid, _ in filed),
                style=style_store.resolve(styles.get(int(r[0])), str(r[1])),
            )
        )
    return out


def create_group(
    conn: sqlite3.Connection, name: str, *, now: Optional[str] = None
) -> SessionGroup:
    _require_tables(conn)
    clean = normalize_name(name)
    stamp = now or utc_now()
    with transaction(conn):
        count = int(
            conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0]
        )
        if count >= SESSION_GROUP_MAX:
            raise GroupLimitReached(
                f"this install already holds {count} groups, the limit is "
                f"{SESSION_GROUP_MAX}"
            )
        top = conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM session_groups"
        ).fetchone()[0]
        group_uuid = str(_uuid.uuid4())
        conn.execute(
            "INSERT INTO session_groups "
            "(group_uuid, name, position, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (group_uuid, clean, int(top) + 1, stamp, stamp),
        )
        gid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        style = style_store.resolve(None, group_uuid)
        if table_exists(conn, SESSION_GROUP_STYLES_TABLE):
            style = style_store.GroupStyle(
                colour=style_store.random_colour(), gradient=None,
                animation="none", source=style_store.SOURCE_STORED,
            )
            style_store.write(conn, gid, style.colour, now=stamp)
    return SessionGroup(
        group_uuid=group_uuid,
        name=clean,
        position=int(top) + 1,
        created_at=stamp,
        updated_at=stamp,
        members=(),
        style=style,
    )


def set_group_style(
    conn: sqlite3.Connection,
    group_uuid: str,
    colour: str,
    gradient: Optional[str] = None,
    animation: str = "none",
    *,
    now: Optional[str] = None,
) -> None:
    _require_tables(conn)
    style_store.validate(colour, gradient, animation)
    with transaction(conn):
        gid = _group_id(conn, group_uuid)
        style_store.write(conn, gid, colour, gradient, animation, now=now)


def set_group_icon(
    conn: sqlite3.Connection,
    group_uuid: str,
    icon: Optional[str],
    *,
    now: Optional[str] = None,
) -> None:
    _require_tables(conn)
    if not column_exists(conn, SESSION_GROUP_STYLES_TABLE, ICON_COLUMN):
        raise GroupsUnavailable("the group icon column is not present (schema before v39)")
    style_store.validate_icon(icon)
    with transaction(conn):
        gid = _group_id(conn, group_uuid)
        style_store.write_icon(conn, gid, group_uuid, icon, now=now)

def rename_group(
    conn: sqlite3.Connection,
    group_uuid: str,
    name: str,
    *,
    now: Optional[str] = None,
) -> None:
    _require_tables(conn)
    clean = normalize_name(name)
    with transaction(conn):
        gid = _group_id(conn, group_uuid)
        conn.execute(
            "UPDATE session_groups SET name = ?, updated_at = ? WHERE id = ?",
            (clean, now or utc_now(), gid),
        )


def delete_group(conn: sqlite3.Connection, group_uuid: str) -> int:
    _require_tables(conn)
    with transaction(conn):
        gid = _group_id(conn, group_uuid)
        freed = clear_group(conn, gid)
        conn.execute("DELETE FROM session_groups WHERE id = ?", (gid,))
    return freed


def set_group_order(conn: sqlite3.Connection, group_uuids: List[str]) -> None:
    _require_tables(conn)
    with transaction(conn):
        known = {
            str(r[1]): int(r[0])
            for r in conn.execute("SELECT id, group_uuid FROM session_groups")
        }
        seen = []
        for group_uuid in group_uuids:
            if group_uuid not in known:
                raise GroupNotFound(f"no group with uuid {group_uuid!r}")
            if group_uuid in seen:
                continue
            seen.append(group_uuid)
        rest = [
            r[0]
            for r in conn.execute(
                "SELECT group_uuid FROM session_groups "
                "ORDER BY position ASC, group_uuid ASC"
            )
            if str(r[0]) not in seen
        ]
        for index, group_uuid in enumerate(seen + [str(x) for x in rest]):
            conn.execute(
                "UPDATE session_groups SET position = ? WHERE id = ?",
                (index, known[group_uuid]),
            )
