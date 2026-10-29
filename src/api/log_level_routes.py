
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.log_level import expiry, live, store
from src.models.log_level import LogLevelState, LogLevelWrite
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["log-level"])


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def _env_level() -> str:
    from src.config import settings

    return store.env_name(settings.log_level)


def _env_name_raw() -> str:
    from src.config import settings

    return settings.log_level


def _state() -> LogLevelState:
    chosen = store.read_chosen_from_file(_config_path())
    ends = expiry.expires_at()
    return LogLevelState(
        expires_at=datetime.fromtimestamp(ends, timezone.utc).isoformat() if ends is not None else None,
        level=live.name_for_number(live.current_number()),
        source="setting" if chosen else "env",
        env_level=_env_level(),
        choices=list(live.LEVEL_NAMES),
    )


@router.get("/log-level", response_model=LogLevelState, dependencies=[Depends(require_auth)])
async def get_log_level() -> LogLevelState:
    """The log level in force and where it came from."""
    return await asyncio.to_thread(_state)


@router.put("/log-level", response_model=LogLevelState, dependencies=[Depends(require_auth)])
async def put_log_level(body: LogLevelWrite) -> LogLevelState:
    """Set the log level live and store it; ``null`` goes back to LOG_LEVEL.

    Description: ``debug`` is the exception (#1897): it is applied live only, never stored, and the
      server puts the previous level back after ``expires_in_s`` (default and cap 1800 s). A second
      debug write replaces the first expiry. ``expires_in_s`` is ignored for any other level.
    Raises: HTTPException(422) - the level is not error, warn, info or debug
      (raised by validation); HTTPException(500) - config.json is missing or
      unreadable, in which case the level is left as it was.
    Example: PUT /api/v1/log-level {"level": "debug", "expires_in_s": 600}
    """
    if body.level == "debug":
        revert_to = await asyncio.to_thread(
            lambda: store.effective_name(_env_name_raw(), _config_path())
        )
        ends = expiry.arm(revert_to, body.expires_in_s)
        logger.warning("log_level_debug_armed", expires_at=ends, reverts_to=revert_to)
        return await asyncio.to_thread(_state)
    try:
        await asyncio.to_thread(store.set_chosen, _config_path(), body.level)
    except (FileNotFoundError, ValueError) as exc:
        raise api_error(500, "config_unreadable", None, error_type=type(exc).__name__) from exc
    expiry.clear()
    name = body.level or _env_level()
    live.apply_level(name)
    logger.info("log_level_changed", level=name, source="setting" if body.level else "env")
    return await asyncio.to_thread(_state)
