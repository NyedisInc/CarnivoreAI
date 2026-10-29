
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
from src.api.error_response import api_error

logger = structlog.get_logger()




def current_view(
    settings: Any, *, include_archived: bool = False
) -> ProjectsView:
    return resolve_projects(
        settings.get_state_dir(), include_archived=include_archived
    )



def readonly_http_error(exc: ProjectsReadOnlyError) -> HTTPException:
    return api_error(503, "projects_read_only", None, reason=exc.detail)


def open_db_or_503(settings: Any):
    from src.core.db import DatastoreUnreadableError, db_path_for
    from src.core.db_reuse.core_read import lend_pooled_or_raise

    try:
        return lend_pooled_or_raise(db_path_for(settings.get_state_dir()))
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="open_db_or_503") from exc


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
    import sqlite3
    from contextlib import closing

    from src.config import settings
    from src.core.db import db_path_for
    from src.core.db_reuse.change_cache import HOT_READS
    from src.core.project_pack import jobs, store
    from src.core.project_pack.view import storage_from_rows

    def read_rows() -> Dict[int, Dict[str, Any]]:
        with closing(open_db_or_503(settings)) as conn:
            return store.all_rows(conn)

    if view.degraded:
        return {}
    try:
        rows = HOT_READS.fetch(db_path_for(settings.get_state_dir()), ("project_storage_rows",), read_rows)
        return storage_from_rows(rows, {item["id"]: item["root"] for item in view.projects}, jobs.progress_of)
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
        raise api_error(409, "project_ambiguous", exc, name=name) from exc


def touch_project_best_effort(settings: Any, working_dir: str) -> Optional[Dict]:
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
