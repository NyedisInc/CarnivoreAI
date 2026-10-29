
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Sequence, Tuple

from src.core.conversation_index import constants as _CI
from src.core.lineage import constants as _LN
from src.core.app_alerts import constants as _AA
from src.core.db_ddl import tables as _SP
from src.core.deepsearch import constants as _SI
from src.core.transcript_manifest import constants as _TM

ARCHIVE_DB_FILENAME = "cloude-archive.db"

ARCHIVE_SCHEMA = "archive"

SIDE_APP = "app"
SIDE_ARCHIVE = "archive"
SIDE_UNCLASSIFIED = "unclassified"

APP_TABLES: FrozenSet[str] = frozenset({
    "sessions",
    "projects",
    "meta",
    "migration_trail",
    "project_tombstones",
    "session_groups",
    "session_group_members",
    "session_group_membership",
    "browser_sessions",
    "session_group_styles",
    "layouts",
    "layout_members",
    "blueprints",
    "layout_styles",
    "layout_broadcast_off",
    "item_settings",
    "hosts",
    "federation_grants",
    "peer_sessions",
    _CI.TABLE,
    _CI.FTS_TABLE,
    *_CI.FTS_SHADOW_TABLES,
    _LN.EDGES_TABLE,
    _LN.NODES_TABLE,
    _LN.SOURCES_TABLE,
    _LN.MILESTONES_TABLE,
    _AA.TABLE,
    _SP.JOBS_TABLE,
    _SP.STAGES_TABLE,
    _SI.DOCS_TABLE,
    _SI.ROWS_TABLE,
    _SI.FTS_TABLE,
    *_SI.FTS_SHADOW_TABLES,
    _SI.LIVE_TABLE,
    _TM.TABLE,
})

ARCHIVE_PREFIXES: Tuple[str, ...] = (
    "transcript_",
    "message_",
    "archive_",
)

EXPECTED_CROSSING_FKS: Tuple[Tuple[str, str, str], ...] = (
    ("transcript_archives", "project_id", "projects"),
    ("transcript_archives", "root_session_id", "sessions"),
    ("transcript_root_decisions", "project_id", "projects"),
)


def archive_db_path_for(state_dir: Path) -> Path:
    """Return the cloude-archive.db path inside a state directory.

    Description: the archive twin of ``db.db_path_for``, so the filename
      lives in exactly one place.
    Inputs: state_dir (Path) - as resolved by Settings.get_state_dir().
    Output: Path - state_dir / "cloude-archive.db".
    Example: archive_db_path_for(Path("/s")).name  # 'cloude-archive.db'
    """
    return Path(state_dir) / ARCHIVE_DB_FILENAME


def side_for_table(name: str) -> str:
    if name in APP_TABLES:
        return SIDE_APP
    if name.startswith(ARCHIVE_PREFIXES):
        return SIDE_ARCHIVE
    return SIDE_UNCLASSIFIED


@dataclass(frozen=True)
class ObjectRow:

    name: str
    kind: str
    sql: str
    side: str


def classify_objects(conn: sqlite3.Connection, schema: str = "main") -> List[ObjectRow]:
    rows = conn.execute(
        f"SELECT name, type, sql FROM {schema}.sqlite_master "
        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [
        ObjectRow(name=r[0], kind=r[1], sql=r[2] or "", side=side_for_table(r[0]))
        for r in rows
    ]


def shadow_tables(conn: sqlite3.Connection, schema: str = "main") -> FrozenSet[str]:
    virtual = [
        r[0] for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master "
            "WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%'"
        )
    ]
    if not virtual:
        return frozenset()
    names = [
        r[0] for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        )
    ]
    return frozenset(
        n for n in names
        if any(n.startswith(f"{v}_") for v in virtual) and n not in virtual
    )


def unclassified_objects(objects: Sequence[ObjectRow]) -> List[str]:
    """Name every object the partition map could not place.

    Description: a non-empty result is refusal rung UNCLASSIFIED_OBJECT.
      It is a MEASURED unknown, not an unchecked one: sqlite_master was
      read and these names were in it.
    Inputs: objects (Sequence[ObjectRow]) - from classify_objects.
    Output: list[str] - the names, sorted.
    Example: unclassified_objects(classify_objects(c))  # []
    """
    return sorted(o.name for o in objects if o.side == SIDE_UNCLASSIFIED)


def crossing_foreign_keys(
    conn: sqlite3.Connection, schema: str = "main",
) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for obj in classify_objects(conn, schema):
        if obj.kind != "table" or obj.side == SIDE_UNCLASSIFIED:
            continue
        for row in conn.execute(
            f'PRAGMA {schema}.foreign_key_list("{obj.name}")'
        ).fetchall():
            parent, column = row[2], row[3]
            if side_for_table(parent) != obj.side:
                out.append((obj.name, column, parent))
    return sorted(out)


def orphaned_reference_counts(
    conn: sqlite3.Connection, crossings: Sequence[Tuple[str, str, str]],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for child, column, parent in crossings:
        row = conn.execute(
            f'SELECT COUNT(*) FROM "{child}" x '
            f'LEFT JOIN "{parent}" p ON x."{column}" = p.id '
            f'WHERE x."{column}" IS NOT NULL AND p.id IS NULL'
        ).fetchone()
        counts[f"{child}.{column}"] = int(row[0])
    return counts
