
from __future__ import annotations

from typing import Any, Dict

from src.core.pack.jobs import boot
from src.core.pack.jobs.types import JobError

HERE, AUTO = "here", "auto"
PLACEABLE_KIND = "blueprint_launch"


def applies(target: Dict[str, Any]) -> bool:
    return target.get("kind") == PLACEABLE_KIND


def get(automation_id: str) -> str:
    return boot.engine().store.automation_placement_get(automation_id) or HERE


def put(automation_id: str, placement: str) -> str:
    boot.engine().store.automation_placement_set(automation_id, placement)
    return placement


def drop(automation_id: str) -> None:
    try:
        boot.engine().store.automation_placement_delete(automation_id)
    except JobError as exc:
        if exc.code != "jobs_not_ready":
            raise
