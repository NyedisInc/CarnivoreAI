
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple

import structlog

from src.config import settings
from src.core import config_writer, resource_push
from src.core.approvals.auto_answer.catalog import SCOPES
from src.core.approvals.beast_grid import cell_defaults
from src.core.mcp import beast_mode
from src.core.resource_push import topics

logger = structlog.get_logger()

AUTO_OFF_HOURS: Tuple[int, ...] = (1, 4, 8)


def until_for(hours: Optional[int], now: Optional[datetime] = None) -> Optional[str]:
    if hours is None:
        return None
    if hours not in AUTO_OFF_HOURS:
        raise ValueError(f"auto-off must be one of {AUTO_OFF_HOURS} hours")
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=hours)).isoformat()


async def persist(*, enabled: bool, prompts: bool = False, hours: Optional[int] = None) -> None:
    """Write the switch, then drop the config cache and announce ``beast_mode``.

    Inputs: enabled (bool); prompts (bool) - the "also answer permission prompts" scope, kept only while
      armed; hours (int | None) - auto-off, kept only while armed.
    Output: None. Raises: FileNotFoundError, ValueError, OSError - config.json could not be written.
    Example: await persist(enabled=True, prompts=True, hours=4)
    """
    await asyncio.to_thread(write_switch, enabled=enabled, prompts=prompts, hours=hours)


def write_switch(*, enabled: bool, prompts: bool = False, hours: Optional[int] = None) -> None:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat() if enabled else None
    until = until_for(hours, now) if enabled else None

    def mutate(doc: dict) -> dict:
        block = doc.get("mcp")
        block = dict(block) if isinstance(block, dict) else {}
        block.update(beast_mode=enabled, beast_mode_since=stamp, beast_prompts=bool(enabled and prompts),
                     beast_mode_until=until)
        return {**doc, "mcp": block}

    config_writer.commit(Path(settings.auth_config_file).expanduser(), mutate)
    settings.drop_auth_config_cache()
    resource_push.notify(topics.BEAST_MODE)


def write_grid(*, cells: Optional[Mapping[str, bool]] = None, trust_scope: Optional[str] = None) -> None:
    """
    Inputs: cells ({cell key: bool}; a key outside ``beast_grid.cell_defaults`` or a non-bool value is refused); trust_scope (one of
      ``auto_answer.catalog.SCOPES``). Absent arguments leave their part alone. The armed switch is never touched here.
    Output: None. Raises: ValueError - an unknown key, a non-bool box or an unknown scope (nothing is written);
      FileNotFoundError, OSError - config.json could not be written.
    Example: write_grid(cells={"agentWritesOff": True}, trust_scope="every")
    """
    known = cell_defaults()
    for key, value in (cells or {}).items():
        if key not in known or not isinstance(value, bool):
            raise ValueError(f"{key!r} is not a beast mode box")
    if trust_scope is not None and trust_scope not in SCOPES:
        raise ValueError(f"trust scope must be one of {SCOPES}")

    def mutate(doc: dict) -> dict:
        block = doc.get("mcp")
        block = dict(block) if isinstance(block, dict) else {}
        grid = dict(block.get("beast_grid")) if isinstance(block.get("beast_grid"), dict) else {}
        grid.update(cells or {})
        block["beast_grid"] = grid
        if trust_scope is not None:
            block["beast_trust_scope"] = trust_scope
        return {**doc, "mcp": block}

    config_writer.commit(Path(settings.auth_config_file).expanduser(), mutate)
    settings.drop_auth_config_cache()
    resource_push.notify(topics.BEAST_MODE)


async def disarm_if_expired() -> bool:
    if not beast_mode.armed_but_expired():
        return False
    async with beast_mode.toggle_lock:
        if not beast_mode.armed_but_expired():
            return False
        try:
            await persist(enabled=False)
        except (FileNotFoundError, ValueError, OSError) as exc:
            logger.error("beast_mode_auto_off_unwritable", error_type=type(exc).__name__)
            return False
    logger.info("beast_mode_auto_off")
    return True
