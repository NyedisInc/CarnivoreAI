
from __future__ import annotations

import copy
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.db import DatastoreUnreadableError, db_path_for
from src.core.db_reuse.core_read import lend_pooled_or_raise
from src.core.db_reuse.change_cache import HOT_READS
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
    db_file = db_path_for(state_dir)

    try:
        rows, reconcile = HOT_READS.fetch(
            db_file,
            ("projects", include_archived),
            lambda: _read_project_rows(db_file, include_archived),
        )
    except DatastoreUnreadableError as exc:
        return _unreadable(str(exc), db_file)
    except Exception as exc:  # noqa: BLE001
        return _unreadable(f"{type(exc).__name__}: {exc}", db_file)

    return ProjectsView(
        mode=MODE_DB,
        projects=[_row_to_view(row) for row in rows],
        message="projects are served from cloude.db, which is authoritative.",
        reconcile=copy.deepcopy(reconcile),
    )


def _read_project_rows(
    db_file: Path, include_archived: bool
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with closing(lend_pooled_or_raise(db_file)) as conn:
        return (
            list_projects_ordered(conn, include_archived=include_archived),
            reconcile_summary(conn),
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
