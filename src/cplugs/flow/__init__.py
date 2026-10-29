
from src.core.flow_data import live, tail
from src.cplugs.flow import capabilities, mcp, routes, store
from src.cplugs.sdk import CplugDefinition, StorageSpec, load_manifest, with_capabilities


async def _stop(ctx: object) -> None:
    live.WATCH.stop()
    tail.CACHE.clear()


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE),
                        storage=StorageSpec(db="flow.db", migrations=store.MIGRATIONS), on_stop=_stop)

__all__ = ["CPLUG"]
