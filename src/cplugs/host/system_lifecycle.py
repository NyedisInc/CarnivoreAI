
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Awaitable, Callable, Dict, Tuple

import structlog

from src.cplugs.sdk import CplugDefinition

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
    from src.cplugs.host import runtime  # noqa: PLC0415

    hook = PURGE_HOOKS.get(cplug_id)
    if hook is not None:
        await hook(app)
    found = runtime.find(cplug_id)
    if not isinstance(found, CplugDefinition) or found.before_purge is None:
        return
    try:
        await asyncio.wait_for(found.before_purge(runtime.host_for(app).context(cplug_id, background=True)), timeout=runtime.HOOK_TIMEOUT_S)
    except PurgeHookFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("cplug_purge_hook_failed", cplug=cplug_id, error_type=type(exc).__name__, error=str(exc)[:300], exc_info=True)
        raise PurgeHookFailed(f"{cplug_id}: its pre-purge step could not finish") from exc
