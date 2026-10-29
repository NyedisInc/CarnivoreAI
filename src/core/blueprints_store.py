
from __future__ import annotations

import json
import sqlite3
import uuid as uuid_lib
from dataclasses import dataclass
from typing import List, Optional

from pydantic import ValidationError

from src.core.blueprints_ddl import BLUEPRINTS_TABLE
from src.core.db import table_exists, transaction
from src.core.message_model_secrets import scan_text
from src.core.trail_entry import utc_now
from src.models.blueprints import BlueprintSpec

BLUEPRINT_MAX = 100

SPEC_MAX_BYTES = 512 * 1024


class BlueprintError(Exception):
    pass


class BlueprintsUnavailable(BlueprintError):
    """The table is absent: CANNOT DETERMINE, never an empty list."""


class BlueprintNotFound(BlueprintError):
    pass


class BlueprintNameTaken(BlueprintError):
    pass


class BlueprintLimitReached(BlueprintError):
    pass


class BlueprintSecret(BlueprintError):

    def __init__(self, detectors: List[str]) -> None:
        super().__init__("the blueprint holds what looks like a credential ("
                         + ", ".join(detectors) + "); a blueprint never carries a secret")
        self.detectors = detectors


class BlueprintCorrupt(BlueprintError):
    pass


@dataclass(frozen=True)
class SavedBlueprint:

    blueprint_uuid: str
    name: str
    spec: BlueprintSpec
    created_at: str
    updated_at: str


def fold_name(name: str) -> str:
    return name.casefold()


def serialize(spec: BlueprintSpec) -> str:
    doc = spec.model_dump(mode="json", exclude_none=True)
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    scanned = json.dumps({**doc, "sessions": [{k: v for k, v in m.items() if k != "host_key"}
                                              for m in doc["sessions"]]},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    findings = scan_text(scanned)
    if findings:
        raise BlueprintSecret(sorted({f.detector for f in findings}))
    if len(text.encode("utf-8")) > SPEC_MAX_BYTES:
        raise ValueError(f"a blueprint is at most {SPEC_MAX_BYTES} bytes")
    return text


def require_table(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, BLUEPRINTS_TABLE):
        raise BlueprintsUnavailable("the blueprints table is not present (schema before v35)")


_COLUMNS = "id, blueprint_uuid, name, spec, created_at, updated_at"


def _hydrate(row: sqlite3.Row) -> SavedBlueprint:
    try:
        spec = BlueprintSpec.model_validate(json.loads(row[3]))
    except (ValueError, ValidationError) as exc:
        raise BlueprintCorrupt(f"blueprint {row[1]} no longer validates: {exc}") from None
    return SavedBlueprint(blueprint_uuid=str(row[1]), name=str(row[2]), spec=spec,
                          created_at=str(row[4]), updated_at=str(row[5]))


def _row_for(conn: sqlite3.Connection, blueprint_uuid: str) -> sqlite3.Row:
    found = conn.execute(f"SELECT {_COLUMNS} FROM blueprints WHERE blueprint_uuid = ?",
                         (str(blueprint_uuid),)).fetchone()
    if found is None:
        raise BlueprintNotFound(f"no blueprint {blueprint_uuid}")
    return found


def list_blueprints(conn: sqlite3.Connection) -> List[SavedBlueprint]:
    require_table(conn)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM blueprints ORDER BY name_fold ASC, blueprint_uuid ASC").fetchall()
    return [_hydrate(r) for r in rows]


def get_blueprint(conn: sqlite3.Connection, blueprint_uuid: str) -> SavedBlueprint:
    require_table(conn)
    return _hydrate(_row_for(conn, blueprint_uuid))


def _check_name_free(conn: sqlite3.Connection, name: str, except_id: Optional[int]) -> None:
    found = conn.execute("SELECT id FROM blueprints WHERE name_fold = ?",
                         (fold_name(name),)).fetchone()
    if found is not None and int(found[0]) != except_id:
        raise BlueprintNameTaken(f"a blueprint called '{name}' already exists")


def create_blueprint(conn: sqlite3.Connection, spec: BlueprintSpec, *,
                     now: Optional[str] = None) -> SavedBlueprint:
    require_table(conn)
    text = serialize(spec)
    stamp = now or utc_now()
    public = str(uuid_lib.uuid4())
    with transaction(conn):
        if int(conn.execute("SELECT COUNT(*) FROM blueprints").fetchone()[0]) >= BLUEPRINT_MAX:
            raise BlueprintLimitReached(f"at most {BLUEPRINT_MAX} blueprints")
        _check_name_free(conn, spec.name, None)
        conn.execute(
            "INSERT INTO blueprints (blueprint_uuid, name, name_fold, spec, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (public, spec.name, fold_name(spec.name), text, stamp, stamp))
        return _hydrate(_row_for(conn, public))


def replace_blueprint(conn: sqlite3.Connection, blueprint_uuid: str, spec: BlueprintSpec, *,
                      now: Optional[str] = None) -> SavedBlueprint:
    require_table(conn)
    text = serialize(spec)
    with transaction(conn):
        row = _row_for(conn, blueprint_uuid)
        _check_name_free(conn, spec.name, int(row[0]))
        conn.execute(
            "UPDATE blueprints SET name = ?, name_fold = ?, spec = ?, updated_at = ? WHERE id = ?",
            (spec.name, fold_name(spec.name), text, now or utc_now(), int(row[0])))
        return _hydrate(_row_for(conn, blueprint_uuid))


def delete_blueprint(conn: sqlite3.Connection, blueprint_uuid: str) -> bool:
    require_table(conn)
    with transaction(conn):
        row = _row_for(conn, blueprint_uuid)
        conn.execute("DELETE FROM blueprints WHERE id = ?", (int(row[0]),))
    return True
