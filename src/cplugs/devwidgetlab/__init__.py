
from pathlib import Path
from typing import Any

from src.cplugs.devwidgetlab import capabilities, mcp, routes
from src.cplugs.devwidgetlab.drafts import checkout, renames
from src.cplugs.sdk import CplugDefinition, load_manifest, with_capabilities


async def _start(ctx: Any) -> None:
    renames.migrate_records(Path(ctx.storage.path))
    checkout.bind_setting(lambda: str(ctx.settings_now().get(checkout.SETTING) or ""))


async def _stop(ctx: Any) -> None:
    checkout.bind_setting(None)


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE), on_start=_start, on_stop=_stop)

__all__ = ["CPLUG"]
