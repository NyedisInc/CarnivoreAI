
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

import structlog

from src.core.db_models import (
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)
from src.core.hosts.ddl import host_scope
from src.core.project_attribution import attribute, unresolved_roots
from src.core.session_import_mapping import _project_roots
from src.core.session_store import sessions_table_ready
from src.core.tmux_listing import TmuxListing
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


@dataclass(frozen=True)
class BackfillResult:

    considered: int = 0
    attributed_project: int = 0
    attributed_none: int = 0
    still_unknown: int = 0
    unmatchable_roots: List[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return self.attributed_project + self.attributed_none


_RUNNING_LIFECYCLE = "running"

InstanceKey = Tuple[str, str, int]


def live_instance_keys(socket: str, listing: TmuxListing) -> FrozenSet[InstanceKey]:
    keys = set()
    if not listing.ok:
        return frozenset()
    for row in listing.sessions:
        if not isinstance(row, dict):
            continue
        try:
            keys.add((socket, str(row["name"]), int(row["created_at_epoch"])))
        except (KeyError, TypeError, ValueError):
            continue
    return frozenset(keys)


def _may_probe(row: Iterable[Any], socket_hint: Optional[FrozenSet[InstanceKey]]) -> bool:
    name, lifecycle, sock, epoch = row
    if not name or lifecycle != _RUNNING_LIFECYCLE:
        return False
    if socket_hint is None:
        return True
    return epoch is not None and (str(sock), str(name), int(epoch)) in socket_hint


def backfill_attribution(
    conn: sqlite3.Connection,
    *,
    working_dir_probe: Optional[Callable[[str], Optional[str]]] = None,
    now: Optional[str] = None,
    live_instances: Optional[FrozenSet[InstanceKey]] = None,
) -> BackfillResult:
    if not sessions_table_ready(conn):
        return BackfillResult()

    roots: Dict[str, int] = _project_roots(conn)
    unmatchable = list(unresolved_roots(roots.keys()))
    if unmatchable:
        logger.warning(
            "attribution_roots_unmatchable",
            roots=unmatchable,
            note="these project roots cannot be situated and match nothing",
        )

    stamp = now or utc_now()
    scope_sql, scope_params = host_scope(conn)
    rows = conn.execute(
        "SELECT id, tmux_name, working_dir, lifecycle, tmux_socket, tmux_created_epoch FROM sessions "
        "WHERE project_attribution = ?" + scope_sql,
        (SESSION_ATTRIBUTION_UNKNOWN, *scope_params),
    ).fetchall()

    considered = len(rows)
    to_project = 0
    to_none = 0
    still_unknown = 0

    for row in rows:
        row_id = int(row[0])
        tmux_name = row[1]
        working_dir = row[2]
        if not working_dir and working_dir_probe is not None and _may_probe(row[1:2] + row[3:6], live_instances):
            working_dir = working_dir_probe(str(tmux_name))

        project_id, attribution = attribute(working_dir, roots)
        if attribution == SESSION_ATTRIBUTION_UNKNOWN:
            still_unknown += 1
            continue

        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = ?, "
            "working_dir = ?, updated_at = ? WHERE id = ?",
            (project_id, attribution, working_dir, stamp, row_id),
        )
        if attribution == SESSION_ATTRIBUTION_NONE:
            to_none += 1
        else:
            to_project += 1

    result = BackfillResult(
        considered=considered,
        attributed_project=to_project,
        attributed_none=to_none,
        still_unknown=still_unknown,
        unmatchable_roots=unmatchable,
    )
    if considered:
        logger.info(
            "session_attribution_backfill",
            considered=considered,
            attributed_project=to_project,
            attributed_none=to_none,
            still_unknown=still_unknown,
            note=(
                "still_unknown is reported separately from attributed_none "
                "on purpose: could-not-read and belongs-to-nothing are "
                "different answers"
            ),
        )
    return result
