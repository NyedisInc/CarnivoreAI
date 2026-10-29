
from __future__ import annotations

from typing import FrozenSet, Tuple

from src.core.conversation_index import constants as _CI
from src.core.lineage import constants as _LN
from src.core.app_alerts import constants as _AA
from src.core.db_ddl import tables as _SP
from src.core.deepsearch import constants as _SI
from src.core.transcript_manifest import constants as _TM

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

def side_for_table(name: str) -> str:
    if name in APP_TABLES:
        return SIDE_APP
    if name.startswith(ARCHIVE_PREFIXES):
        return SIDE_ARCHIVE
    return SIDE_UNCLASSIFIED
