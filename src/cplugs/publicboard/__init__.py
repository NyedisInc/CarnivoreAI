
from typing import Any

from src.cplugs.publicboard.service import SERVICE
from src.cplugs.publicboard.settings import check_settings
from src.cplugs.sdk import CplugDefinition, load_manifest


async def _start(ctx: Any) -> None:
    await SERVICE.apply(ctx.settings)


async def _stop(ctx: Any) -> None:
    await SERVICE.stop()


async def _settings_saved(ctx: Any) -> None:
    await SERVICE.apply(ctx.settings_now())


CPLUG = CplugDefinition(manifest=load_manifest(__file__), on_start=_start, on_stop=_stop, on_settings=_settings_saved, settings_check=check_settings)

__all__ = ["CPLUG"]
