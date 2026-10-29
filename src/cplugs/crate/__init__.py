
from src.cplugs.crate import capabilities, mcp, routes, start
from src.cplugs.sdk import CplugDefinition, load_manifest, with_capabilities

CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router,
                        tools=with_capabilities(mcp.TOOLS, capabilities.TABLE), on_start=start.on_start,
                        on_stop=start.on_stop)

__all__ = ["CPLUG"]
