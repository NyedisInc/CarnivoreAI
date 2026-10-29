
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core import resource_push
from src.core.db import set_meta, transaction
from src.core.resource_push import topics

logger = structlog.get_logger()

CRATE_WRITTEN_PREFIX = "crate_written:"


def crate_written_key(bundle_id: str) -> str:
    return f"{CRATE_WRITTEN_PREFIX}{bundle_id}"


FAMILIES: Tuple[str, ...] = ("claude", "codex")
SCOPES: Tuple[str, ...] = ("session", "project")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_LOCATIONS = 50
MAX_WHERE_CHARS = 1000
_BATCH = 500


class ExportsError(Exception):
    pass


class InvalidExport(ExportsError):
    pass


class BundleNotFound(ExportsError):
    pass


@dataclass(frozen=True)
class Location:

    where: str
    verified_at: Optional[float] = None


@dataclass(frozen=True)
class Bundle:

    bundle_id: str
    sha256: str
    scope: str
    created_at: float
    project_uid: Optional[str] = None
    session_uuid: Optional[str] = None
    label: Optional[str] = None
    locations: Tuple[Location, ...] = ()
    verified_at: Optional[float] = None
    local_removed: bool = False
    updated_at: float = 0.0
    conversations: int = 0


@dataclass(frozen=True)
class Pointer:

    conversation_id: str
    family: str
    bundle_id: str
    exported_at: float
    title: Optional[str] = None


def _check_bundle(bundle: Bundle) -> None:
    if not BUNDLE_ID.match(bundle.bundle_id or ""):
        raise InvalidExport("a bundle id is 3 to 80 letters, digits, dots, underscores or dashes")
    if not SHA256.match(bundle.sha256 or ""):
        raise InvalidExport("sha256 must be 64 lowercase hex characters")
    if bundle.scope not in SCOPES:
        raise InvalidExport(f"scope must be one of {list(SCOPES)}")
    _check_locations(bundle.locations)


def _check_locations(locations: Sequence[Location]) -> None:
    if len(locations) > MAX_LOCATIONS:
        raise InvalidExport(f"a bundle lists at most {MAX_LOCATIONS} locations")
    for loc in locations:
        if not isinstance(loc.where, str) or not loc.where.strip() or len(loc.where) > MAX_WHERE_CHARS:
            raise InvalidExport("every location needs a non-empty 'where' of at most 1000 characters")


def _check_pointer(pointer: Pointer, bundle_id: str) -> None:
    if pointer.family not in FAMILIES:
        raise InvalidExport(f"family must be one of {list(FAMILIES)}")
    if not pointer.conversation_id or not pointer.conversation_id.strip():
        raise InvalidExport("a pointer needs a conversation id")
    if pointer.bundle_id != bundle_id:
        raise InvalidExport("a pointer must name the bundle it is recorded with")


def _locations_json(locations: Sequence[Location]) -> str:
    return json.dumps([{"where": loc.where, "verified_at": loc.verified_at} for loc in locations], separators=(",", ":"))


def _locations_of(text: Optional[str]) -> Tuple[Location, ...]:
    try:
        rows = json.loads(text or "[]")
        return tuple(Location(str(r["where"]), r.get("verified_at")) for r in rows)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("export_locations_unreadable", error_type=type(exc).__name__)
        return ()


_BUNDLE_COLUMNS = ("bundle_id, sha256, scope, project_uid, session_uuid, label, created_at, locations_json, verified_at, "
                   "local_removed, updated_at")


def iso_utc(epoch: Optional[float]) -> Optional[str]:
    return None if epoch is None else datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _bundle_of(row: Sequence, conversations: int) -> Bundle:
    return Bundle(bundle_id=row[0], sha256=row[1], scope=row[2], project_uid=row[3], session_uuid=row[4], label=row[5],
                  created_at=float(row[6]), locations=_locations_of(row[7]), verified_at=row[8],
                  local_removed=bool(row[9]), updated_at=float(row[10]), conversations=conversations)


def list_bundles(conn: sqlite3.Connection) -> List[Bundle]:
    counts = dict(conn.execute("SELECT bundle_id, COUNT(*) FROM export_pointers GROUP BY bundle_id").fetchall())
    rows = conn.execute(f"SELECT {_BUNDLE_COLUMNS} FROM export_bundles ORDER BY created_at DESC, bundle_id").fetchall()
    return [_bundle_of(r, int(counts.get(r[0], 0))) for r in rows]


def bundle(conn: sqlite3.Connection, bundle_id: str) -> Bundle:
    row = conn.execute(f"SELECT {_BUNDLE_COLUMNS} FROM export_bundles WHERE bundle_id = ?", (bundle_id,)).fetchone()
    if row is None:
        raise BundleNotFound(f"no export bundle {bundle_id}")
    (count,) = conn.execute("SELECT COUNT(*) FROM export_pointers WHERE bundle_id = ?", (bundle_id,)).fetchone()
    return _bundle_of(row, int(count))


def bundles_for(conn: sqlite3.Connection, bundle_ids: Iterable[str]) -> Dict[str, Bundle]:
    ids = list(dict.fromkeys(bundle_ids))
    found: Dict[str, Bundle] = {}
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start:start + _BATCH]
        marks = ", ".join("?" for _ in chunk)
        for row in conn.execute(f"SELECT {_BUNDLE_COLUMNS} FROM export_bundles WHERE bundle_id IN ({marks})", chunk):
            found[row[0]] = _bundle_of(row, 0)
    return found


def _pointer_of(row: Sequence) -> Pointer:
    return Pointer(conversation_id=row[0], family=row[1], bundle_id=row[2], title=row[3], exported_at=float(row[4]))


def pointer(conn: sqlite3.Connection, conversation_id: str, family: Optional[str] = None) -> Optional[Pointer]:
    sql = "SELECT conversation_id, family, bundle_id, title, exported_at FROM export_pointers WHERE conversation_id = ?"
    params: List[object] = [conversation_id]
    if family is not None:
        sql += " AND family = ?"
        params.append(family)
    row = conn.execute(sql + " ORDER BY exported_at DESC LIMIT 1", params).fetchone()
    return _pointer_of(row) if row else None


def pointers_for(conn: sqlite3.Connection, conversation_ids: Iterable[str]) -> Dict[str, Pointer]:
    ids = list(dict.fromkeys(conversation_ids))
    found: Dict[str, Pointer] = {}
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start:start + _BATCH]
        marks = ", ".join("?" for _ in chunk)
        for row in conn.execute("SELECT conversation_id, family, bundle_id, title, exported_at FROM export_pointers "
                                f"WHERE conversation_id IN ({marks}) ORDER BY exported_at", chunk):
            found[row[0]] = _pointer_of(row)
    return found


def record_bundle(conn: sqlite3.Connection, new: Bundle, pointers: Sequence[Pointer], *,
                  written_mark: Optional[str] = None) -> Bundle:
    _check_bundle(new)
    for p in pointers:
        _check_pointer(p, new.bundle_id)
    now = time.time()
    with transaction(conn):
        conn.execute(
            f"INSERT INTO export_bundles ({_BUNDLE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(bundle_id) DO UPDATE SET sha256 = excluded.sha256, scope = excluded.scope, "
            "project_uid = excluded.project_uid, session_uuid = excluded.session_uuid, label = excluded.label, "
            "locations_json = excluded.locations_json, verified_at = excluded.verified_at, "
            "local_removed = excluded.local_removed, updated_at = excluded.updated_at",
            (new.bundle_id, new.sha256, new.scope, new.project_uid, new.session_uuid, new.label, float(new.created_at),
             _locations_json(new.locations), new.verified_at, 1 if new.local_removed else 0, now))
        conn.executemany(
            "INSERT INTO export_pointers (conversation_id, family, bundle_id, title, exported_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(family, conversation_id) DO UPDATE SET bundle_id = excluded.bundle_id, title = excluded.title, "
            "exported_at = excluded.exported_at WHERE excluded.exported_at >= export_pointers.exported_at",
            [(p.conversation_id, p.family, p.bundle_id, p.title, float(p.exported_at)) for p in pointers])
        if written_mark is not None:
            set_meta(conn, crate_written_key(new.bundle_id), written_mark)
    resource_push.notify(topics.EXPORTS)
    logger.info("export_bundle_recorded", bundle_id=new.bundle_id, scope=new.scope, conversations=len(pointers))
    return bundle(conn, new.bundle_id)


def update_bundle(conn: sqlite3.Connection, bundle_id: str, *, locations: Optional[Sequence[Location]] = None,
                  verified_at: Optional[float] = None, local_removed: Optional[bool] = None) -> Bundle:
    if locations is not None:
        _check_locations(locations)
    sets, params = ["updated_at = ?"], [time.time()]
    if locations is not None:
        sets.append("locations_json = ?")
        params.append(_locations_json(locations))
    if verified_at is not None:
        sets.append("verified_at = ?")
        params.append(float(verified_at))
    if local_removed is not None:
        sets.append("local_removed = ?")
        params.append(1 if local_removed else 0)
    with transaction(conn):
        changed = conn.execute(f"UPDATE export_bundles SET {', '.join(sets)} WHERE bundle_id = ?", [*params, bundle_id]).rowcount
        if not changed:
            raise BundleNotFound(f"no export bundle {bundle_id}")
    resource_push.notify(topics.EXPORTS)
    logger.info("export_bundle_updated", bundle_id=bundle_id, fields=len(sets) - 1)
    return bundle(conn, bundle_id)
