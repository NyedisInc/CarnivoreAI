
from typing import Any

from src.cplugs.sdk import CplugDefinition, load_manifest, with_capabilities
from src.cplugs.tmdevtools import capabilities, commands, mcp, routes


async def _stop(ctx: Any) -> None:
    commands.reset()


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE), on_stop=_stop)

__all__ = ["CPLUG"]
