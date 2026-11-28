
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.plugins.taskmanager import service
from src.plugins.taskmanager.roles import route
from src.plugins.taskmanager.roles.store import RoleStore
from src.plugins.sdk import CplugContext

logger = structlog.get_logger()


def lead_wake_key(ctx: CplugContext, rows: List[Dict[str, Any]], key: str) -> str:
    return route.lead_to_wake(service.store(ctx), rows, key)


def choose(ctx: CplugContext, rows: List[Dict[str, Any]], key: str) -> Optional[str]:
    huddle = service.store(ctx)
    led = route.lead_target(huddle, rows, key)
    if led is not None:
        return led
    free = route.without_dnd(rows, RoleStore(huddle).dnd_keys())
    return free[0]["id"] if free else None
