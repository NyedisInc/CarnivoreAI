
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.archive_db_partition import SIDE_ARCHIVE, side_for_table
from src.core.db_models import (
    DDL_V1,
    DDL_V2,
    DDL_V7,
    DDL_V8,
    DDL_V14,
    DDL_V27,
    DDL_V28,
    DDL_V30,
)
from src.core.archive_overlay_ddl import DDL_V19
from src.core.browser_sessions_ddl import DDL_V32
from src.core.session_group_style_ddl import DDL_V33
from src.core.layouts.ddl import DDL_V34
from src.core.blueprints_ddl import DDL_V35
from src.core.layouts.style_ddl import DDL_V36
from src.core.layouts.broadcast_ddl import DDL_V37
from src.core.item_settings_ddl import DDL_V38
from src.core.federation.ddl import DDL_V43, V44_COLUMNS
from src.core.federation.ddl_peer_sessions import DDL_V45
from src.core.conversation_index.ddl import DDL_V46, V48_COLUMNS
from src.core.lineage.ddl import DDL_V49, RETIRED_OBJECTS as V49_RETIRED
from src.core.app_alerts.ddl import DDL_V50
from src.core.db_ddl.pipeline import DDL_V51, V53_COLUMNS
from src.core.db_ddl.search_index import DDL_V52, DDL_V55, V55_COLUMNS
from src.core.transcript_manifest.ddl import DDL_V54
from src.core.launch_profiles.ddl import V56_COLUMNS
from src.core.companies.ddl import DDL_V58, V58_COLUMNS, V72_COLUMNS
from src.core.swarm.ddl import DDL_V59, DDL_V62, DDL_V63, DDL_V64, DDL_V65, V60_COLUMNS, V65_COLUMNS, V66_COLUMNS, V67_COLUMNS, V68_COLUMNS, V69_COLUMNS, V70_COLUMNS, V71_COLUMNS, V99_COLUMNS, V100_COLUMNS
from src.core.project_colors.ddl import V61_COLUMNS
from src.core.crosstalk.ddl import DDL_V57, DDL_V102
from src.core.messaging.ddl import DDL_V73, V92_COLUMNS
from src.core.exports.ddl import DDL_V93
from src.core.session_group_rule import DDL_V101
from src.core.descriptions.ddl import V74_COLUMNS
from src.core.project_pack.ddl import DDL_V75
from src.core.pack.machines.ddl import DDL_PACK_MACHINES
from src.core.pack.identity.ddl import DDL_V80, V80_COLUMNS
from src.core.pack.relay.ddl import DDL_PACK_RELAY
from src.core.pack.placement.ddl import DDL_PACK_PLACEMENT
from src.core.pack.span.ddl import DDL_V82, V82_COLUMNS
from src.core.pack.transport.ddl import DDL_PACK_TRANSPORT
from src.core.pack.migrate.ddl import DDL_PACK_MIGRATE
from src.core.pack.move.ddl import DDL_PACK_MOVE
from src.core.computers.ddl import DDL_COMPUTER_LINKS
from src.core.companion_shell.ddl import DDL_V86, V86_COLUMNS
from src.core.pack.rollup_import.ddl import DDL_V89
from src.core.pack.trust_carry.ddl import DDL_V87, V88_COLUMNS
from src.core.flow_data.ddl import DDL_V90, V90_COLUMNS, V95_COLUMNS
from src.core.crosstalk.ddl import V94_COLUMNS
from src.core.hosts.ddl import DDL_V40, TRIPLE_INSTANCE_INDEX, V40_COLUMNS, V96_COLUMNS
from src.core.skills.consent_via_ddl import V41_COLUMNS
from src.core.skills.fork_mark_ddl import V42_COLUMNS

logger = structlog.get_logger()

AUDIT_OK = "ok"

AUDIT_MISSING = "missing"

AUDIT_CANNOT_DETERMINE = "cannot_determine"

UNGATED_VERSION_DDL: Dict[int, Tuple[str, ...]] = {
    1: DDL_V1,
    2: DDL_V2,
    7: DDL_V7,
    8: DDL_V8,
    14: DDL_V14,
    19: DDL_V19,
    27: DDL_V27,
    28: DDL_V28,
    30: DDL_V30,
    32: DDL_V32,
    33: DDL_V33,
    34: DDL_V34,
    35: DDL_V35,
    36: DDL_V36,
    37: DDL_V37,
    38: DDL_V38,
    40: DDL_V40,
    43: DDL_V43,
    45: DDL_V45,
    46: DDL_V46,
    49: DDL_V49,
    50: DDL_V50,
    51: DDL_V51,
    52: DDL_V52,
    54: DDL_V54,
    55: DDL_V55,
    57: DDL_V57,
    58: DDL_V58,
    59: DDL_V59,
    62: DDL_V62,
    63: DDL_V63,
    64: DDL_V64,
    65: DDL_V65,
    73: DDL_V73,
    75: DDL_V75,
    77: DDL_PACK_MACHINES,
    78: DDL_PACK_RELAY,
    79: DDL_PACK_PLACEMENT,
    80: DDL_V80,
    81: DDL_PACK_TRANSPORT,
    82: DDL_V82,
    83: DDL_PACK_MIGRATE,
    84: DDL_PACK_MOVE,
    85: DDL_COMPUTER_LINKS,
    86: DDL_V86,
    87: DDL_V87,
    89: DDL_V89,
    90: DDL_V90,
    93: DDL_V93,
    101: DDL_V101,
    102: DDL_V102,
}

UNGATED_VERSION_COLUMNS: Dict[int, Tuple[Tuple[str, str, str], ...]] = {
    40: V40_COLUMNS,
    41: V41_COLUMNS,
    42: V42_COLUMNS,
    44: V44_COLUMNS,
    48: V48_COLUMNS,
    53: V53_COLUMNS,
    55: V55_COLUMNS,
    56: V56_COLUMNS,
    58: V58_COLUMNS,
    60: V60_COLUMNS,
    61: V61_COLUMNS,
    65: V65_COLUMNS,
    66: V66_COLUMNS,
    67: V67_COLUMNS,
    68: V68_COLUMNS,
    69: V69_COLUMNS,
    70: V70_COLUMNS,
    71: V71_COLUMNS,
    72: V72_COLUMNS,
    74: V74_COLUMNS,
    80: V80_COLUMNS,
    82: V82_COLUMNS,
    86: V86_COLUMNS,
    88: V88_COLUMNS,
    90: V90_COLUMNS,
    92: V92_COLUMNS,
    94: V94_COLUMNS,
    95: V95_COLUMNS,
    96: V96_COLUMNS,
    99: V99_COLUMNS,
    100: V100_COLUMNS,
}

SUPERSEDED_OBJECTS: frozenset = frozenset({"ix_sessions_claude_uuid", TRIPLE_INSTANCE_INDEX, *V49_RETIRED})

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)",
    re.IGNORECASE,
)
_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"[\"'`\[]?(\w+)[\"'`\]]?\s+ON\s+[\"'`\[]?(\w+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeclaredObject:

    name: str
    kind: str
    owner_table: str
    version: int
    sql: str


@dataclass(frozen=True)
class SchemaAudit:

    status: str
    missing: List[DeclaredObject] = field(default_factory=list)
    checked: int = 0
    skipped_archive: int = 0
    error: Optional[str] = None

    @property
    def missing_names(self) -> List[str]:
        return [obj.name for obj in self.missing]


def _objects_in(statement: str, version: int) -> List[DeclaredObject]:
    match = _CREATE_TABLE.search(statement)
    if match is not None:
        name = match.group(1)
        return [DeclaredObject(name, "table", name, version, statement)]
    match = _CREATE_INDEX.search(statement)
    if match is not None:
        return [
            DeclaredObject(
                match.group(1), "index", match.group(2), version, statement
            )
        ]
    return []


def declared_objects(schema_version: int) -> List[DeclaredObject]:
    return [
        obj for obj in _all_declared(schema_version)
        if side_for_table(obj.owner_table) != SIDE_ARCHIVE
        and obj.name not in SUPERSEDED_OBJECTS
    ]


def _present_names(
    conn: sqlite3.Connection, declared: Sequence[DeclaredObject] = ()
) -> Optional[set]:
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        ).fetchall()
        names = {row[0] for row in rows}
        for table in sorted({o.owner_table for o in declared if o.kind == "column"}):
            names.update(
                f"{table}.{row[1]}" for row in conn.execute(f"PRAGMA table_info({table})")
            )
    except sqlite3.DatabaseError:
        return None
    return names


def audit_schema(conn: sqlite3.Connection, schema_version: int) -> SchemaAudit:
    declared = declared_objects(schema_version)
    present = _present_names(conn, declared)
    if present is None:
        return SchemaAudit(
            status=AUDIT_CANNOT_DETERMINE,
            error="sqlite_master could not be read",
        )
    skipped = len(_all_declared(schema_version)) - len(declared)
    missing = [obj for obj in declared if obj.name not in present]
    if missing:
        return SchemaAudit(
            status=AUDIT_MISSING,
            missing=missing,
            checked=len(declared),
            skipped_archive=skipped,
        )
    return SchemaAudit(
        status=AUDIT_OK, checked=len(declared), skipped_archive=skipped
    )


def _all_declared(schema_version: int) -> List[DeclaredObject]:
    out: List[DeclaredObject] = []
    for version in sorted(set(UNGATED_VERSION_DDL) | set(UNGATED_VERSION_COLUMNS)):
        if version > schema_version:
            continue
        for statement in UNGATED_VERSION_DDL.get(version, ()):
            out.extend(_objects_in(statement, version))
        for table, column, statement in UNGATED_VERSION_COLUMNS.get(version, ()):
            out.append(DeclaredObject(f"{table}.{column}", "column", table, version, statement))
    return out


def repair_missing(
    conn: sqlite3.Connection, missing: Sequence[DeclaredObject]
) -> List[str]:
    created: List[str] = []
    rank = {"table": 0, "column": 1, "index": 2}
    for obj in sorted(missing, key=lambda o: (o.version, rank.get(o.kind, 2))):
        if obj.kind == "column":
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({obj.owner_table})")}
            if obj.name.split(".", 1)[1] in have:
                continue
        conn.execute(obj.sql)
        created.append(obj.name)
    return created


def repair_after_chain(conn: sqlite3.Connection, schema_version: int) -> List[str]:
    audit = audit_schema(conn, schema_version)
    if audit.status != AUDIT_MISSING:
        return []
    conn.execute("SAVEPOINT repair_after_chain")
    try:
        created = repair_missing(conn, audit.missing)
    except sqlite3.DatabaseError as exc:
        conn.execute("ROLLBACK TO repair_after_chain")
        conn.execute("RELEASE repair_after_chain")
        logger.error(
            "db_schema_repair_after_chain_failed",
            schema_version=schema_version,
            missing=audit.missing_names,
            error=str(exc),
            note="the chain still commits; the next boot's audit reports the gap",
        )
        return []
    conn.execute("RELEASE repair_after_chain")
    logger.warning(
        "db_schema_repaired_after_chain",
        schema_version=schema_version,
        created=created,
        note="the chain's version range skipped steps whose objects were absent",
    )
    return [f"repair:{name}" for name in created]
