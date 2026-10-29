
from __future__ import annotations

import json
import sqlite3
import unicodedata
import uuid as uuid_lib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from src.core.layouts import style as style_store
from src.core.layouts import shape as shape_rules
from src.core.db import table_exists, transaction
from src.core.layouts.style_ddl import LAYOUT_STYLES_TABLE
from src.core.layouts.broadcast_ddl import LAYOUT_BROADCAST_OFF_TABLE
from src.core.layouts.ddl import LAYOUT_MEMBERS_TABLE, LAYOUTS_TABLE
from src.core.trail_entry import utc_now

NAME_MAX = 60

LAYOUT_MAX = 100

SOURCE_KEY_MAX = 200


class LayoutError(Exception):
    pass


class LayoutsUnavailable(LayoutError):
    pass


class LayoutNotFound(LayoutError):
    pass


class LayoutNameInvalid(LayoutError):
    pass


class LayoutNameTaken(LayoutError):
    pass


class LayoutLimitReached(LayoutError):
    pass


class LayoutShapeInvalid(LayoutError):
    pass


class LayoutTooFewMembers(LayoutError):
    pass


class MemberUnresolved(LayoutError):

    def __init__(self, unresolved: List[str]) -> None:
        super().__init__("members that name no stored session: " + ", ".join(unresolved))
        self.unresolved = unresolved


class LayoutStale(LayoutError):

    def __init__(self, current: "SavedLayout") -> None:
        super().__init__(f"the layout is at revision {current.revision}")
        self.current = current


@dataclass(frozen=True)
class LayoutMember:

    session_row_id: int
    session_uuid: str
    position: int
    broadcast: bool = True


@dataclass(frozen=True)
class SavedLayout:

    layout_uuid: str
    name: str
    position: int
    shape: Dict[str, Any]
    revision: int
    source_key: Optional[str]
    created_at: str
    updated_at: str
    members: tuple = field(default_factory=tuple)
    colour: str = style_store.DEFAULT_COLOUR
    gradient: Optional[str] = None
    animation: str = "none"
    style_source: str = style_store.SOURCE_DERIVED


@dataclass(frozen=True)
class WriteResult:

    layout: Optional[SavedLayout]
    deleted: bool = False
    survivor: Optional[LayoutMember] = None
    created: bool = False


def normalize_name(raw: Any) -> str:
    if not isinstance(raw, str):
        raise LayoutNameInvalid("layout name must be a string")
    name = raw.strip()
    if not name:
        raise LayoutNameInvalid("layout name is empty")
    if len(name) > NAME_MAX:
        raise LayoutNameInvalid(f"layout name is {len(name)} characters, the limit is {NAME_MAX}")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise LayoutNameInvalid("layout name holds a control character")
    return name


def fold_name(name: str) -> str:
    return name.casefold()


def _check_source_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw or len(raw) > SOURCE_KEY_MAX or any(
        unicodedata.category(ch) == "Cc" for ch in raw
    ):
        raise LayoutShapeInvalid(f"source_key is 1 to {SOURCE_KEY_MAX} printable characters")
    return raw


def require_tables(conn: sqlite3.Connection) -> None:
    if not (table_exists(conn, LAYOUTS_TABLE) and table_exists(conn, LAYOUT_MEMBERS_TABLE)):
        raise LayoutsUnavailable("the layouts tables are not present (schema before v34)")


def _members(conn: sqlite3.Connection, layout_id: int) -> tuple:
    if table_exists(conn, LAYOUT_BROADCAST_OFF_TABLE):
        rows = conn.execute(
            "SELECT m.session_row_id, s.session_uuid, m.position, o.session_row_id "
            "FROM layout_members m JOIN sessions s ON s.id = m.session_row_id "
            "LEFT JOIN layout_broadcast_off o ON o.layout_id = m.layout_id "
            "AND o.session_row_id = m.session_row_id WHERE m.layout_id = ? "
            "ORDER BY m.position ASC, m.session_row_id ASC",
            (layout_id,),
        ).fetchall()
        return tuple(LayoutMember(int(r[0]), str(r[1]), int(r[2]), r[3] is None) for r in rows)
    rows = conn.execute(
        "SELECT m.session_row_id, s.session_uuid, m.position FROM layout_members m "
        "JOIN sessions s ON s.id = m.session_row_id WHERE m.layout_id = ? "
        "ORDER BY m.position ASC, m.session_row_id ASC",
        (layout_id,),
    ).fetchall()
    return tuple(LayoutMember(int(r[0]), str(r[1]), int(r[2])) for r in rows)


_COLUMNS = ("id, layout_uuid, name, position, shape, revision, source_key, "
            "created_at, updated_at")


def _style_for(conn: sqlite3.Connection, layout_uuid: str) -> style_store.LayoutStyle:
    try:
        row = conn.execute(
            "SELECT colour, gradient, animation FROM layout_styles WHERE layout_uuid = ?",
            (layout_uuid,),
        ).fetchone()
    except sqlite3.OperationalError:
        return style_store.resolve(None)
    if row is None or not style_store.valid_colour(row[0]):
        return style_store.resolve(None)
    gradient = row[1] if row[1] in style_store.GRADIENTS else None
    animation = row[2] if row[2] in style_store.ANIMATIONS else "none"
    return style_store.resolve(
        style_store.LayoutStyle(colour=str(row[0]), gradient=gradient,
                                animation=animation, source=style_store.SOURCE_STORED)
    )


def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> SavedLayout:
    layout_uuid = str(row[1])
    style = _style_for(conn, layout_uuid)
    return SavedLayout(
        layout_uuid=layout_uuid, name=str(row[2]), position=int(row[3]),
        shape=json.loads(row[4]), revision=int(row[5]),
        source_key=(str(row[6]) if row[6] is not None else None),
        created_at=str(row[7]), updated_at=str(row[8]),
        members=_members(conn, int(row[0])),
        colour=style.colour, gradient=style.gradient, animation=style.animation,
        style_source=style.source,
    )


def _row_for(conn: sqlite3.Connection, layout_uuid: str) -> sqlite3.Row:
    found = conn.execute(
        f"SELECT {_COLUMNS} FROM layouts WHERE layout_uuid = ?", (str(layout_uuid),)
    ).fetchone()
    if found is None:
        raise LayoutNotFound(f"no layout {layout_uuid}")
    return found


def list_layouts(conn: sqlite3.Connection) -> List[SavedLayout]:
    require_tables(conn)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM layouts ORDER BY position ASC, layout_uuid ASC"
    ).fetchall()
    return [_hydrate(conn, r) for r in rows]


def get_layout(conn: sqlite3.Connection, layout_uuid: str) -> SavedLayout:
    require_tables(conn)
    return _hydrate(conn, _row_for(conn, layout_uuid))


def _resolve_rows(conn: sqlite3.Connection, row_ids: List[int]) -> None:
    if not row_ids:
        return
    marks = ",".join("?" for _ in row_ids)
    present = {int(r[0]) for r in conn.execute(
        f"SELECT id FROM sessions WHERE id IN ({marks})", tuple(row_ids)).fetchall()}
    missing = [shape_rules.row_slot(r) for r in row_ids if r not in present]
    if missing:
        raise MemberUnresolved(missing)


def _derive(conn: sqlite3.Connection, shape: Any) -> tuple:
    try:
        canonical = shape_rules.validate(shape)
        rows = shape_rules.member_row_ids(canonical)
    except shape_rules.ShapeUnresolved as exc:
        raise MemberUnresolved(exc.slots) from None
    except shape_rules.ShapeInvalid as exc:
        raise LayoutShapeInvalid(str(exc)) from None
    _resolve_rows(conn, rows)
    return canonical, rows


def _write_members(conn: sqlite3.Connection, layout_id: int, rows: List[int]) -> None:
    marks = ",".join("?" for _ in rows)
    conn.execute(
        f"DELETE FROM layout_members WHERE layout_id = ? AND session_row_id NOT IN ({marks})",
        (layout_id, *rows),
    )
    for position, row_id in enumerate(rows):
        conn.execute(
            "INSERT INTO layout_members (layout_id, session_row_id, position) VALUES (?, ?, ?) "
            "ON CONFLICT(layout_id, session_row_id) DO UPDATE SET position = excluded.position",
            (layout_id, row_id, position),
        )


def _check_name_free(conn: sqlite3.Connection, name: str, except_id: Optional[int]) -> None:
    found = conn.execute("SELECT id FROM layouts WHERE name_fold = ?", (fold_name(name),)).fetchone()
    if found is not None and int(found[0]) != except_id:
        raise LayoutNameTaken(f"a layout called '{name}' already exists")


def create_layout(conn: sqlite3.Connection, name: Any, shape: Any, *,
                  source_key: Optional[str] = None, now: Optional[str] = None) -> WriteResult:
    require_tables(conn)
    key = _check_source_key(source_key)
    clean = normalize_name(name)
    stamp = now or utc_now()
    with transaction(conn):
        if key is not None:
            prior = conn.execute(
                f"SELECT {_COLUMNS} FROM layouts WHERE source_key = ?", (key,)).fetchone()
            if prior is not None:
                return WriteResult(layout=_hydrate(conn, prior))
        count = int(conn.execute("SELECT COUNT(*) FROM layouts").fetchone()[0])
        if count >= LAYOUT_MAX:
            raise LayoutLimitReached(f"at most {LAYOUT_MAX} layouts")
        _check_name_free(conn, clean, None)
        canonical, rows = _derive(conn, shape)
        if not shape_rules.has_enough_members(rows, canonical):
            raise LayoutTooFewMembers(
                f"a layout shows at least {shape_rules.MIN_MEMBERS} terminal sessions")
        position = int(conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM layouts").fetchone()[0])
        public = str(uuid_lib.uuid4())
        cur = conn.execute(
            "INSERT INTO layouts (layout_uuid, name, name_fold, position, shape, revision, "
            "source_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (public, clean, fold_name(clean), position, json.dumps(canonical), key, stamp, stamp),
        )
        _write_members(conn, int(cur.lastrowid), rows)
        if table_exists(conn, LAYOUT_STYLES_TABLE):
            style_store.write(conn, public, style_store.random_colour(), now=stamp)
        return WriteResult(layout=_hydrate(conn, _row_for(conn, public)), created=True)


def rename_layout(conn: sqlite3.Connection, layout_uuid: str, name: Any, *,
                  now: Optional[str] = None) -> WriteResult:
    require_tables(conn)
    clean = normalize_name(name)
    with transaction(conn):
        row = _row_for(conn, layout_uuid)
        _check_name_free(conn, clean, int(row[0]))
        conn.execute("UPDATE layouts SET name = ?, name_fold = ?, updated_at = ? WHERE id = ?",
                     (clean, fold_name(clean), now or utc_now(), int(row[0])))
        return WriteResult(layout=_hydrate(conn, _row_for(conn, layout_uuid)))


def set_layout_style(
    conn: sqlite3.Connection,
    layout_uuid: str,
    colour: str,
    gradient: Optional[str] = None,
    animation: str = "none",
    *,
    now: Optional[str] = None,
) -> WriteResult:
    require_tables(conn)
    style_store.validate(colour, gradient, animation)
    with transaction(conn):
        row = _row_for(conn, layout_uuid)
        style_store.write(conn, layout_uuid, colour, gradient, animation, now=now)
        return WriteResult(layout=_hydrate(conn, row))


def _clear_group_membership(conn: sqlite3.Connection, layout_uuid: str) -> None:
    if not table_exists(conn, "session_group_membership"):
        return
    conn.execute(
        "DELETE FROM session_group_membership WHERE session_uuid = ?",
        (f"layout:{layout_uuid}",),
    )


def _store_shape(conn: sqlite3.Connection, row: sqlite3.Row, shape: Any,
                 expected_revision: Optional[int], now: Optional[str]) -> WriteResult:
    layout_id = int(row[0])
    if expected_revision is not None and int(expected_revision) != int(row[5]):
        raise LayoutStale(_hydrate(conn, row))
    canonical, rows = _derive(conn, shape)
    if not shape_rules.has_enough_members(rows, canonical):
        survivor = None
        if rows:
            uuid_row = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?",
                                    (rows[0],)).fetchone()
            survivor = LayoutMember(rows[0], str(uuid_row[0]), 0)
        conn.execute("DELETE FROM layouts WHERE id = ?", (layout_id,))
        _clear_group_membership(conn, str(row[1]))
        return WriteResult(layout=None, deleted=True, survivor=survivor)
    conn.execute(
        "UPDATE layouts SET shape = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
        (json.dumps(canonical), now or utc_now(), layout_id),
    )
    _write_members(conn, layout_id, rows)
    return WriteResult(layout=_hydrate(conn, _row_for(conn, str(row[1]))))


def set_shape(conn: sqlite3.Connection, layout_uuid: str, shape: Any,
              expected_revision: int, *, now: Optional[str] = None) -> WriteResult:
    require_tables(conn)
    with transaction(conn):
        return _store_shape(conn, _row_for(conn, layout_uuid), shape, expected_revision, now)


def _row_id_for_uuid(conn: sqlite3.Connection, session_uuid: str) -> int:
    found = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?",
                         (str(session_uuid),)).fetchone()
    if found is None:
        raise MemberUnresolved([str(session_uuid)])
    return int(found[0])


def add_member(conn: sqlite3.Connection, layout_uuid: str, *,
               session_uuid: Optional[str] = None, session_row_id: Optional[int] = None,
               expected_revision: Optional[int] = None, now: Optional[str] = None) -> WriteResult:
    require_tables(conn)
    with transaction(conn):
        row = _row_for(conn, layout_uuid)
        if session_row_id is not None:
            target = int(session_row_id)
            _resolve_rows(conn, [target])
        else:
            target = _row_id_for_uuid(conn, str(session_uuid))
        current = json.loads(row[4])
        try:
            shape = shape_rules.with_member_added(current, target)
        except shape_rules.ShapeInvalid as exc:
            raise LayoutShapeInvalid(str(exc)) from None
        if shape is current:
            if expected_revision is not None and int(expected_revision) != int(row[5]):
                raise LayoutStale(_hydrate(conn, row))
            return WriteResult(layout=_hydrate(conn, row))
        return _store_shape(conn, row, shape, expected_revision, now)


def remove_member(conn: sqlite3.Connection, layout_uuid: str, session_uuid: str, *,
                  expected_revision: Optional[int] = None,
                  now: Optional[str] = None) -> WriteResult:
    require_tables(conn)
    with transaction(conn):
        row = _row_for(conn, layout_uuid)
        target = _row_id_for_uuid(conn, session_uuid)
        shape, was_there = shape_rules.with_member_removed(json.loads(row[4]), target)
        if not was_there:
            raise MemberUnresolved([str(session_uuid)])
        return _store_shape(conn, row, shape, expected_revision, now)


def delete_layout(conn: sqlite3.Connection, layout_uuid: str) -> bool:
    require_tables(conn)
    with transaction(conn):
        row = _row_for(conn, layout_uuid)
        conn.execute("DELETE FROM layouts WHERE id = ?", (int(row[0]),))
        _clear_group_membership(conn, layout_uuid)
    return True


def set_order(conn: sqlite3.Connection, layout_uuids: Iterable[str]) -> List[SavedLayout]:
    require_tables(conn)
    wanted = list(dict.fromkeys(str(u) for u in layout_uuids))
    with transaction(conn):
        known = [str(r[0]) for r in conn.execute(
            "SELECT layout_uuid FROM layouts ORDER BY position ASC, layout_uuid ASC").fetchall()]
        missing = [u for u in wanted if u not in known]
        if missing:
            raise LayoutNotFound(f"no layout {missing[0]}")
        final = wanted + [u for u in known if u not in wanted]
        for position, public in enumerate(final):
            conn.execute("UPDATE layouts SET position = ? WHERE layout_uuid = ?", (position, public))
    return list_layouts(conn)


def member_row_ids_of(conn: sqlite3.Connection, layout_uuids: Iterable[str]) -> Set[int]:
    wanted = [str(u) for u in layout_uuids]
    if not wanted or not table_exists(conn, LAYOUTS_TABLE):
        return set()
    marks = ",".join("?" for _ in wanted)
    rows = conn.execute(
        "SELECT m.session_row_id FROM layout_members m JOIN layouts l ON l.id = m.layout_id "
        f"WHERE l.layout_uuid IN ({marks})", tuple(wanted)).fetchall()
    return {int(r[0]) for r in rows}
