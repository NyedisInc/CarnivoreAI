
from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional, Tuple

import structlog

from src.core.attention.evidence import FAMILY_CLAUDE
from src.core.notifications import contracts
from src.core.notifications.sources import common, toast as toast_source
from src.core.sessions.agent_update import agent_update_status, version_text

logger = structlog.get_logger(__name__)

TYPE_ID = "agent.update_ready"


def observation_update(observation: Any) -> Any:
    evidence = getattr(observation, "evidence", None)
    if observation is None or observation.stale or getattr(evidence, "agent_family", None) not in (None, FAMILY_CLAUDE):
        return None
    registry = getattr(evidence, "registry", None)
    if registry is None or not getattr(registry, "known", False):
        return None
    update = agent_update_status(pid=getattr(registry, "pid", None), registry_version=version_text(getattr(registry, "version", None)))
    return update if update is not None and update.ready else None


def stale_sessions(watcher: Any) -> Tuple[Optional[str], List[Tuple[str, Tuple[int, ...]]]]:
    installed, stale = None, []
    if watcher is None:
        return None, []
    for session_id in watcher.observed_session_ids():
        observation = watcher.observation_for(session_id)
        update = observation_update(observation)
        if update is not None:
            installed = update.installed
            stale.append((session_id, tuple(getattr(observation.evidence.registry, "version", None) or ())))
    return installed, stale


def stale_installed_version(watcher: Any) -> Optional[str]:
    return stale_sessions(watcher)[0]


def check_once(watcher: Any, state_dir: Optional[Any] = None, manager: Any = None) -> bool:
    installed, stale = stale_sessions(watcher)
    if installed is None:
        return False
    names = [common.session_fields(manager, sid).get("session_ref") or sid for sid, _ in stale]
    oldest = min((v for _, v in stale if v), default=())
    hint = {"to": installed, "sessions": names, "ids": [sid for sid, _ in stale], **({"from": version_text(oldest)} if oldest else {})}
    event = contracts.NotifyEvent(
        type_id=TYPE_ID, kind="agent_update", title=common.type_title(TYPE_ID), ts=common.now(),
        instance_key=f"agent_update:{installed}", card_hint=hint,
    )
    fired = common.fire_once(TYPE_ID, installed, event, state_dir)
    if fired and manager is not None and _loop is not None and not _loop.is_closed() and stale:
        asyncio.run_coroutine_threadsafe(_record_mac_toast(manager, stale[0][0], event, _app_state), _loop)
    return fired


async def _record_mac_toast(manager: Any, session_id: str, event: contracts.NotifyEvent, app_state: Any = None) -> None:
    from src.core.notifications import agent_message  # noqa: PLC0415

    try:
        toast = manager.record_toast(session_id, "Notification", event.title, event.details, notify_type=TYPE_ID)
        toast_source.remember_hint(toast.id, event.card_hint)
        await agent_message._broadcast(toast, app_state=app_state)
    except (ValueError, AttributeError, OSError) as exc:
        logger.info("agent_update_mac_toast_skipped", error_type=type(exc).__name__)


_get_watcher: Optional[Callable[[], Any]] = None


_get_manager: Optional[Callable[[], Any]] = None


_loop: Optional[asyncio.AbstractEventLoop] = None

_app_state: Any = None


def install(get_watcher: Callable[[], Any], get_manager: Optional[Callable[[], Any]] = None, loop: Optional[asyncio.AbstractEventLoop] = None, app_state: Any = None) -> None:
    global _get_watcher, _get_manager, _loop, _app_state
    _get_watcher, _get_manager, _loop, _app_state = get_watcher, get_manager, loop, app_state


def check_now() -> bool:
    if _get_watcher is None:
        return False
    try:
        return check_once(_get_watcher(), manager=_get_manager() if _get_manager is not None else None)
    except (AttributeError, OSError, ValueError) as exc:
        logger.warning("agent_update_check_failed", error_type=type(exc).__name__)
        return False
