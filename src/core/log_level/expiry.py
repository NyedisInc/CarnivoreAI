
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import structlog

from src.core.log_level import live, store

logger = structlog.get_logger()

MAX_DEBUG_SECONDS = 1800

DEBUG_BOOT_ENV = "CARNIVORE_DEBUG_BOOT"

_handle: Optional[asyncio.TimerHandle] = None
_expires_at: Optional[float] = None
_revert_to: Optional[str] = None


def expires_at() -> Optional[float]:
    return _expires_at


def clamp(expires_in_s: Optional[int]) -> int:
    if expires_in_s is None:
        return MAX_DEBUG_SECONDS
    return max(1, min(int(expires_in_s), MAX_DEBUG_SECONDS))


def arm(revert_to: str, expires_in_s: Optional[int]) -> float:
    global _handle, _expires_at, _revert_to
    seconds = clamp(expires_in_s)
    if _handle is not None:
        _handle.cancel()
    else:
        _revert_to = revert_to
    _expires_at = time.time() + seconds
    _handle = asyncio.get_running_loop().call_later(seconds, _expire)
    live.apply_level("debug")
    return _expires_at


def clear() -> None:
    global _handle, _expires_at, _revert_to
    if _handle is not None:
        _handle.cancel()
    _handle = _expires_at = _revert_to = None


def _expire() -> None:
    target = _revert_to or live.DEFAULT_LEVEL
    clear()
    live.apply_level(target)
    logger.warning("debug_log_level_expired", reverted_to=target)


def debug_boot_requested() -> bool:
    return os.environ.get(DEBUG_BOOT_ENV) == "1"


def boot_level(env_value: str, config_path: Path) -> str:
    if debug_boot_requested():
        return "debug"
    return store.effective_name(env_value, config_path)


def arm_at_boot(env_value: str, config_path: Path) -> Optional[Tuple[str, float]]:
    saved = store.read_chosen_from_file(config_path)
    fallback = store.env_name(env_value)
    if debug_boot_requested():
        revert_to = saved if saved and saved != "debug" else fallback
    elif saved == "debug":
        revert_to = fallback
        try:
            store.set_chosen(config_path, None)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("saved_debug_not_cleared", error_type=type(exc).__name__)
    else:
        return None
    ends = arm(revert_to, None)
    logger.warning("debug_log_level_boot", reverts_to=revert_to, expires_at=ends)
    return revert_to, ends
