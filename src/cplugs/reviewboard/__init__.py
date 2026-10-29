
import asyncio
from typing import Any, Callable, Optional

import structlog

from src.cplugs.reviewboard import artifact_port, attachments_port, artifact_source, capabilities, mcp, mcp_attachments, mcp_live, mcp_scratch, migrate, pages_port, relink_port, root_port, routes
from src.cplugs.sdk import CplugDefinition, load_manifest, ports, with_capabilities

logger = structlog.get_logger()

_copy: Optional["asyncio.Task[Any]"] = None
_unlisten: Optional[Callable[[], None]] = None


def _start_copy(ctx: Any, loop: asyncio.AbstractEventLoop) -> None:
    global _copy
    if _copy is not None and not _copy.done():
        return
    _copy = loop.create_task(migrate.run(ctx))


def _copy_when_task_manager_is_up(ctx: Any) -> None:
    global _unlisten
    loop = asyncio.get_running_loop()
    if artifact_source.get() is not None:
        _start_copy(ctx, loop)
        return

    def heard(name: str) -> None:
        global _unlisten
        if name != artifact_source.NAME or artifact_source.get() is None:
            return
        if _unlisten is not None:
            _unlisten()
            _unlisten = None
        if loop.is_closed():
            logger.info("reviewboard_copy_listener_stale")
            return
        loop.call_soon_threadsafe(_start_copy, ctx, loop)

    _unlisten = ports.subscribe(heard)


async def _start(ctx: Any) -> None:
    root_port.register(ctx)
    attachments_port.register(ctx)
    relink_port.register(ctx)
    pages_port.register()
    artifact_port.register(ctx)
    _copy_when_task_manager_is_up(ctx)


async def _stop(ctx: Any) -> None:
    global _copy, _unlisten
    root_port.unregister()
    attachments_port.unregister()
    relink_port.unregister()
    pages_port.unregister()
    artifact_port.unregister()
    if _unlisten is not None:
        _unlisten()
        _unlisten = None
    if _copy is not None and not _copy.done():
        _copy.cancel()
    _copy = None


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities({**mcp.TOOLS, **mcp_scratch.TOOLS, **mcp_attachments.TOOLS, **mcp_live.TOOLS}, capabilities.TABLE), on_start=_start, on_stop=_stop)

__all__ = ["CPLUG"]
