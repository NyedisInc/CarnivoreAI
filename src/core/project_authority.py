"""
THE ANSWER IS ALWAYS cloude.db. Projects used to live in two places -
this table and a mirrored ``projects`` key in config.json kept as a
rollback artifact - and this module's job was to decide which of the two
was speaking, serve the right one, and report when they disagreed. That
second source is gone. ``projects_config_migration`` moves anything the
file still held into the table once, per install, and removes the key.

WHY THE SECOND SOURCE WENT. Two sources need a comparison, a comparison
needs both sides read the same way, and the two sides were NOT read the
same way: the table was read live on every request while config.json came
from ``Settings._auth_config_cache``, which is invalidated only when the
app itself writes the file. So a user who hand-edited config.json - which
the app's own Edit Config menu item invites - got a divergence report
built from a live measurement on one side and a stale one on the other,
and it named disagreements that did not exist on disk. On top of that the
two detectors that fed the UI each formed their own opinion, and shipped
two banners at once that flatly contradicted each other about which
source the user was looking at.

Neither defect is fixed by a better comparison. Both are removed by
having nothing to compare.

TWO OUTCOMES, AND THE SECOND IS NOT "ZERO PROJECTS":

  db              cloude.db opened and answered. Authoritative. Writes
                  allowed. An empty list here is a real, measured empty
                  list.
  db_unreadable   cloude.db could not be opened or could not be read.
                  The list is EMPTY because nothing could be read, not
                  because nothing is there, and the mode plus the message
                  both say so. Writes are refused: a write in this state
                  could not detect a conflict and could not record itself
                  anywhere durable.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.project_reconcile import reconcile_summary
from src.core.project_writes import list_projects_ordered

logger = structlog.get_logger()

MODE_DB = "db"
MODE_DB_UNREADABLE = "db_unreadable"

READONLY_MODES = (MODE_DB_UNREADABLE,)


class ProjectsReadOnlyError(RuntimeError):

    def __init__(self, mode: str, detail: str) -> None:
        super().__init__(detail)
        self.mode = mode
        self.detail = detail


@dataclass(frozen=True)
class ProjectsView:
    """The resolved answer to one project read, with its provenance.

    Description: the list and the reason the list is what it is travel
      together, always. A caller cannot obtain the projects without also
      obtaining the mode they came from, which is what makes it
      impossible to render a could-not-read as an empty-but-healthy list
      by forgetting a second lookup.
    Inputs (constructor): mode (str - one of the MODE_* constants),
      projects (list[dict] - each ``{"id", "name", "path", "description",
      "root", "agent_type"}``), message (str - one sentence for a user),
      detail (str | None - the underlying error, when there is one),
      reconcile (dict | None - what the last startup project reconcile
      did; None only when the database could not be read).
    Output: a ProjectsView instance.
    """

    mode: str
    projects: List[Dict[str, Any]] = field(default_factory=list)
    message: str = ""
    detail: Optional[str] = None
    reconcile: Optional[Dict[str, Any]] = None

    @property
    def writable(self) -> bool:
        return self.mode not in READONLY_MODES

    @property
    def degraded(self) -> bool:
        return self.mode != MODE_DB

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "writable": self.writable,
            "degraded": self.degraded,
            "message": self.message,
            "detail": self.detail,
            "project_count": len(self.projects),
            "reconcile": self.reconcile,
        }


def _row_to_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["display_name"],
        "path": row["raw_path"],
        "description": row["description"],
        "short_description": row.get("short_description"),
        "root": row["root"],
        "agent_type": row["default_agent_type"],
        "work_at": row.get("work_at"),
        "archived_at": row.get("archived_at"),
        "company_id": row.get("company_id"),
        "company_name": row.get("company_name"),
        "color": row.get("color"),
        "uid": row.get("uid"),
        "pack_state": row.get("pack_state"),
        "home_install_id": row.get("home_install_id"),
        "home_label": row.get("home_label"),
        "moved_to_install_id": row.get("moved_to_install_id"),
        "moved_to_label": row.get("moved_to_label"),
        "air_gap": None if row.get("air_gap") is None else bool(row.get("air_gap")),
        "host_key": row.get("host_key"),
    }


def resolve_projects(
    state_dir: Path, *, include_archived: bool = False
) -> ProjectsView:
    """Read the project list from the datastore, or say it could not be.

    Description: the single read entry point. Takes no config list and
      has no fallback source - that is the enforcement, not an omission.
      While the signature accepted a config list, any caller could hand
      one in and this module could grow a second opinion about where
      projects come from, which is the exact condition that produced two
      contradictory banners.
    """
    db_file = db_path_for(state_dir)

    try:
        with closing(connect(db_file, create=False)) as conn:
            rows = list_projects_ordered(
                conn, include_archived=include_archived
            )
            reconcile = reconcile_summary(conn)
    except DatastoreUnreadableError as exc:
        return _unreadable(str(exc), db_file)
    except Exception as exc:  # noqa: BLE001
        return _unreadable(f"{type(exc).__name__}: {exc}", db_file)

    return ProjectsView(
        mode=MODE_DB,
        projects=[_row_to_view(row) for row in rows],
        message="projects are served from cloude.db, which is authoritative.",
        reconcile=reconcile,
    )


def _unreadable(detail: str, db_file: Path) -> ProjectsView:
    logger.warning(
        "projects_datastore_unreadable", db_path=str(db_file), error=detail
    )
    return ProjectsView(
        mode=MODE_DB_UNREADABLE,
        projects=[],
        message=(
            "cloude.db is UNREACHABLE, so your projects CANNOT BE READ "
            "right now. This is NOT a claim that you have no projects - "
            "the list is empty because nothing could be read, not because "
            "nothing is there. Adding, renaming and removing projects is "
            "refused until the datastore answers again."
        ),
        detail=detail,
    )


def require_writable(view: ProjectsView) -> None:
    if not view.writable:
        raise ProjectsReadOnlyError(view.mode, view.detail or view.message)
