
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import structlog

from src.core.attention.evidence import FAMILY_CLAUDE
from src.core.notifications import contracts
from src.core.notifications.sources import common
from src.core.sessions.agent_update import agent_update_status, version_text

logger = structlog.get_logger(__name__)

TYPE_ID = "agent.update_ready"
INTERVAL_SECONDS = 60.0


def stale_installed_version(watcher: Any) -> Optional[str]:
    if watcher is None:
        return None
    for session_id in watcher.observed_session_ids():
        observation = watcher.observation_for(session_id)
        evidence = getattr(observation, "evidence", None)
        if observation is None or observation.stale or getattr(evidence, "agent_family", None) not in (None, FAMILY_CLAUDE):
            continue
        registry = getattr(evidence, "registry", None)
        if registry is None or not getattr(registry, "known", False):
            continue
        update = agent_update_status(
            pid=getattr(registry, "pid", None), registry_version=version_text(getattr(registry, "version", None)),
        )
        if update is not None and update.ready:
            return update.installed
    return None


def check_once(watcher: Any, state_dir: Optional[Any] = None) -> bool:
    installed = stale_installed_version(watcher)
    if installed is None:
        return False
    event = contracts.NotifyEvent(
        type_id=TYPE_ID, kind="agent_update", title=common.type_title(TYPE_ID), ts=common.now(),
        instance_key=f"agent_update:{installed}",
    )
    return common.fire_once(TYPE_ID, installed, event, state_dir)


async def run(get_watcher: Callable[[], Any], interval: float = INTERVAL_SECONDS) -> None:
    while True:
        try:
            check_once(get_watcher())
        except (AttributeError, OSError, ValueError) as exc:
            logger.warning("agent_update_check_failed", error_type=type(exc).__name__)
        await asyncio.sleep(interval)
