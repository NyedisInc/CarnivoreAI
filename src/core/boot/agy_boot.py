
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.core.boot.steps import BootStep

if TYPE_CHECKING:
    from src.core.boot.context import BootContext


def _start(ctx: "BootContext") -> None:
    from src.core.agy.install import install

    state_dir = ctx.state_dir()
    ctx.app.state.agy_boot_task = asyncio.get_running_loop().create_task(asyncio.to_thread(install, state_dir))


def steps() -> list[BootStep]:
    return [BootStep(name="agy_boot", order=616, start=_start)]
