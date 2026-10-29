
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import structlog

from src.cplugs.huddle import service, store_identity, title
from src.cplugs.sdk import CapabilityMissing, CplugContext, ports
from src.cplugs.sdk import task_folders

logger = structlog.get_logger()

ROOT_PORT = task_folders.ROOT_PORT
PASTES = task_folders.PASTES
ARTIFACTS = task_folders.ARTIFACTS


class RootPort(Protocol):

    def root(self) -> Optional[Path]:
        pass


def root_now() -> Optional[Path]:
    port = ports.get(ROOT_PORT)
    return port.root() if port is not None else None


def project_name(ctx: CplugContext, list_key: str) -> Optional[str]:
    if not task_folders.is_project_key(list_key):
        return None
    try:
        return service.project_names(ctx).get(list_key)
    except CapabilityMissing:
        return None


def own_store_id(ctx: CplugContext) -> Optional[str]:
    found = store_identity.of(ctx.storage)
    if found is not None:
        return found
    try:
        with closing(ctx.storage.connect(True)) as conn, conn:
            return store_identity.ensure(conn)
    except sqlite3.Error as exc:
        logger.warning("task_manager_store_id_unavailable", error=type(exc).__name__, detail=str(exc)[:200])
        return None


def task_dir(ctx: CplugContext, item: Dict[str, Any], root: Path, store_id: str) -> Path:
    return task_folders.ensure_task(root, item["id"], item["list"], project_name(ctx, item["list"]), title.display(item), store_id=store_id)


def folder_for(ctx: CplugContext, item_id: int, kind: str) -> Optional[Path]:
    root = root_now()
    if root is None:
        return None
    store_id = own_store_id(ctx)
    if store_id is None:
        logger.warning("task_manager_task_folder_skipped_no_store_id", item=item_id, kind=kind)
        return None
    item = service.store(ctx).item(item_id)
    try:
        return task_folders.kind_dir(task_dir(ctx, item, root, store_id), kind)
    except OSError as exc:
        logger.warning("task_manager_task_folder_failed", item=item_id, kind=kind, error=type(exc).__name__, detail=str(exc)[:200])
        return None


def search_dirs(item_id: int) -> List[Path]:
    root = root_now()
    if root is None:
        return []
    return [task_folders.kind_dir(found, kind, create=False) for found in task_folders.tasks_for(root, item_id) for kind in (PASTES, ARTIFACTS)]


__all__ = ["ARTIFACTS", "PASTES", "ROOT_PORT", "folder_for", "own_store_id", "project_name", "root_now", "search_dirs", "task_dir"]
