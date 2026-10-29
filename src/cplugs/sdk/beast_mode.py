
from __future__ import annotations

from typing import Any, Dict


def armed() -> bool:
    from src.core.mcp import beast_mode  # noqa: PLC0415

    return beast_mode.stored_armed()


def prompts_armed() -> bool:
    from src.core.mcp import beast_mode  # noqa: PLC0415

    return beast_mode.stored_prompts_armed()


async def status() -> Dict[str, Any]:
    from src.api.beast_mode_routes import get_beast_mode  # noqa: PLC0415

    return await get_beast_mode()


async def disarm() -> Dict[str, Any]:
    from src.api.beast_mode_routes import BeastSetting, set_beast_mode  # noqa: PLC0415

    return await set_beast_mode(BeastSetting(enabled=False), "plugin_sdk")
