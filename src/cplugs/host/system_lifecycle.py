
from __future__ import annotations

import sqlite3
from typing import Any, Awaitable, Callable, Dict, Tuple

import structlog

logger = structlog.get_logger()

SystemHook = Callable[[Any], Awaitable[None]]


HOOKS: Dict[str, Tuple[SystemHook, SystemHook]] = {
}


class PurgeHookFailed(RuntimeError):
    pass


async def revoke_share_links(app: Any) -> None:
    from src.core.spectator.revoke import revoke_all_live  # noqa: PLC0415

    try:
        await revoke_all_live(getattr(app.state, "spectator_links", None), getattr(app.state, "relay", None))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        logger.error("cplug_purge_revoke_failed", cplug="share", error_type=type(exc).__name__, error=str(exc)[:300])
        raise PurgeHookFailed("the plugin's live share links could not be revoked") from exc


PURGE_HOOKS: Dict[str, SystemHook] = {
    "share": revoke_share_links,
}


async def before_purge(app: Any, cplug_id: str) -> None:
    hook = PURGE_HOOKS.get(cplug_id)
    if hook is not None:
        await hook(app)
