
import asyncio
from typing import Any

from src.cplugs.publicboard import capabilities, links, mcp, routes_owner, wiring
from src.cplugs.publicboard.read import READER
from src.cplugs.publicboard.service import SERVICE
from src.cplugs.publicboard.settings import check_settings
from src.cplugs.sdk import CplugDefinition, StorageSpec, load_manifest, with_capabilities


async def _start(ctx: Any) -> None:
    READER.bind(wiring.build(ctx))
    await SERVICE.apply(ctx.settings)


async def _stop(ctx: Any) -> None:
    await SERVICE.stop()
    READER.unbind()


async def _before_purge(ctx: Any) -> None:
    if ctx.storage.db_path.exists():
        await asyncio.to_thread(links.revoke_all, ctx.storage)


async def _settings_saved(ctx: Any) -> None:
    await SERVICE.apply(ctx.settings_now())


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes_owner.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE),
                        storage=StorageSpec(db="links.db", migrations=links.MIGRATIONS, private=True), on_start=_start, on_stop=_stop, on_settings=_settings_saved, before_purge=_before_purge, settings_check=check_settings)

__all__ = ["CPLUG"]
