
from typing import Any

from src.plugins.sdk import CplugDefinition, load_manifest, ports

PORT_NAME = "argent"


async def _start(ctx: Any) -> None:
    ports.register(PORT_NAME, {"on": True})


async def _stop(ctx: Any) -> None:
    ports.unregister(PORT_NAME)


CPLUG = CplugDefinition(manifest=load_manifest(__file__), on_start=_start, on_stop=_stop)

__all__ = ["CPLUG"]
