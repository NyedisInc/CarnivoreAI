
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.plugins.huddle import groups as groups_mod, service
from src.plugins.huddle.rules import JOE, TaskManagerNotFound
from src.plugins.sdk import CplugContext, ports
from src.plugins.sdk.project_lists import NAME

logger = structlog.get_logger()


class ProjectListsPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def clear(self, project_id: int) -> Dict[str, Any]:
        key = str(project_id)
        store = service.store(self._ctx)
        writer = groups_mod.GroupWriter(store)
        items = 0
        for item_id in store.live_item_ids(key):
            try:
                store.delete(item_id, actor=JOE, reason="its project was deleted")
                items += 1
            except TaskManagerNotFound:
                continue
        removed = 0
        for group_id in store.live_group_ids(key):
            try:
                writer.remove(group_id, actor=JOE)
                removed += 1
            except TaskManagerNotFound:
                continue
        logger.info("task_manager_project_list_cleared", list=key, items=items, groups=removed)
        return {"list": key, "items": items, "groups": removed}


def register(ctx: CplugContext) -> None:
    ports.register(NAME, ProjectListsPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)
