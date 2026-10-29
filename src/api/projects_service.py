
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core import project_authority as authority
from src.core.project_authority import (
    ProjectsReadOnlyError,
    ProjectsView,
    require_writable,
    resolve_projects,
)

logger = structlog.get_logger()




def current_view(
    settings: Any, *, include_archived: bool = False
) -> ProjectsView:
    return resolve_projects(
        settings.get_state_dir(), include_archived=include_archived
    )



def readonly_http_error(exc: ProjectsReadOnlyError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "cloude.db is unreachable, so project changes are refused. "
            "Projects live only in cloude.db, so there is nothing else to "
            f"apply this to. ({exc.detail})"
        ),
    )


def open_db_or_503(settings: Any):
    """Open the authoritative database for a write, or raise 503.

    Description: the write path opens its own connection rather than
      reusing the one ``resolve_projects`` used and closed, because
      sqlite3 connections are thread-affine and the two calls can land on
      different worker threads.
    Inputs: settings (Any) - the Settings singleton.
    Output: sqlite3.Connection - caller must close it.
    Raises: HTTPException 503 - the database could not be opened.
    """
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    try:
        return connect(db_path_for(settings.get_state_dir()), create=False)
    except DatastoreUnreadableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"cloude.db is unreachable, so the change was refused. ({exc})",
        )


def guard_writable(settings: Any) -> ProjectsView:
    view = current_view(settings)
    try:
        require_writable(view)
    except ProjectsReadOnlyError as exc:
        raise readonly_http_error(exc)
    return view



def authority_payload(settings: Any) -> Dict[str, Any]:
    return current_view(settings).to_dict()


def _storage_by_project(view: ProjectsView) -> Dict[int, Dict[str, Any]]:
    """The pack ``storage`` object per project id for a list read; empty when the datastore is not readable.

    Inputs: view (ProjectsView). Output: dict[int, dict]. Never raises: a listing must not fail because the
    pack table could not be read (a project then shows ``storage`` null, "not measured").
    """
    import sqlite3
    from contextlib import closing

    from src.config import settings
    from src.core.project_pack import jobs
    from src.core.project_pack.view import storage_by_project

    if view.degraded:
        return {}
    try:
        with closing(open_db_or_503(settings)) as conn:
            roots = {item["id"]: item["root"] for item in view.projects}
            return storage_by_project(conn, roots, jobs.progress_of)
    except (HTTPException, sqlite3.Error) as exc:
        logger.warning("project_storage_list_unreadable", error=str(exc))
        return {}


def views_to_responses(view: ProjectsView, response_cls: Any) -> List[Any]:
    from src.core.companies import hero_images
    from src.core.project_lineage.parents import parent_project_ids

    revs = hero_images.index(hero_images.PROJECT)
    parents = parent_project_ids(view.projects)
    storage = _storage_by_project(view)
    return [
        response_cls(
            id=item["id"],
            name=item["name"],
            path=item["path"],
            description=item["description"],
            short_description=item.get("short_description"),
            root=item["root"],
            default_launch_profile=item.get("agent_type"),
            work_at=item.get("work_at"),
            archived_at=item.get("archived_at"),
            company_id=item.get("company_id"),
            company_name=item.get("company_name"),
            color=item.get("color"),
            parent_project_id=parents.get(item["id"]),
            storage=storage.get(item["id"]),
            uid=item.get("uid"),
            pack_state=item.get("pack_state"),
            home_install_id=item.get("home_install_id"),
            home_label=item.get("home_label"),
            moved_to_install_id=item.get("moved_to_install_id"),
            moved_to_label=item.get("moved_to_label"),
            air_gap=item.get("air_gap"),
            has_image=item["id"] in revs,
            image_rev=revs.get(item["id"]),
        )
        for item in view.projects
    ]


def resolve_target(conn: Any, name: str) -> Dict[str, Any]:
    from src.core.project_writes import (
        ProjectNameAmbiguous,
        ProjectNotFound,
        resolve_by_name,
    )

    try:
        return resolve_by_name(conn, name)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    except ProjectNameAmbiguous as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{name}' does not identify one project: {exc}. "
                "Rename one of them before editing either."
            ),
        )


def touch_project_best_effort(settings: Any, working_dir: str) -> Optional[Dict]:
    """Mark a project most-recently-opened in the datastore.

    Description: the replacement for ``Settings.move_project_to_top``,
      called when a session starts in a directory. Best-effort in the
      same way the original was - a session must never fail to start
      because the launcher's ordering could not be updated - but unlike
      the original it distinguishes "no project at that path" (a normal
      miss, returns None) from "the datastore could not be reached" (a
      warning in the log), rather than swallowing both in one bare
      ``except Exception``.
    Inputs: settings (Any) - the Settings singleton. working_dir (str).
    Output: dict | None - the touched row, or None if nothing matched or
      the update could not be attempted.
    """
    from contextlib import closing

    from src.core.project_writes import touch_project_by_path

    try:
        with closing(open_db_or_503(settings)) as conn:
            row = touch_project_by_path(conn, working_dir)
    except HTTPException as exc:
        logger.warning(
            "project_touch_datastore_unreachable",
            working_dir=working_dir,
            detail=exc.detail,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "project_touch_failed", working_dir=working_dir, error=str(exc)
        )
        return None

    return row


def agent_type_for(settings: Any, project_name: str) -> Optional[str]:
    view = current_view(settings)
    for item in view.projects:
        if item["name"] == project_name:
            return item["agent_type"]
    return None


__all__ = [
    "agent_type_for",
    "authority_payload",
    "current_view",
    "guard_writable",
    "open_db_or_503",
    "readonly_http_error",
    "resolve_target",
    "touch_project_best_effort",
    "views_to_responses",
    "authority",
]
