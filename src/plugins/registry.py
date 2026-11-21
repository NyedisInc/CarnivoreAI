
from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Tuple

import structlog

from src.plugins.sdk import CplugDefinition
from src.plugins.ship_order import ship_order

logger = structlog.get_logger()

PLUGINS_ROOT = Path(__file__).resolve().parent
MANIFEST_FILE = "cplug.json"
class ShipListError(Exception):
    pass


def plugin_folders(root: Path = PLUGINS_ROOT) -> List[str]:
    found = sorted(p.parent.name for p in root.glob(f"*/{MANIFEST_FILE}") if (p.parent / "__init__.py").is_file())
    rank = {name: i for i, name in enumerate(ship_order())}
    return sorted(found, key=lambda n: (rank.get(n, len(rank)), n))


def discover(root: Path = PLUGINS_ROOT) -> Tuple[CplugDefinition, ...]:
    out: List[CplugDefinition] = []
    for name in plugin_folders(root):
        module = importlib.import_module(f"src.plugins.{name}")
        definition = getattr(module, "CPLUG", None)
        if not isinstance(definition, CplugDefinition):
            raise ShipListError(f"src/plugins/{name} has a {MANIFEST_FILE} but no CPLUG definition")
        if definition.id != name:
            raise ShipListError(f"src/plugins/{name} declares id {definition.id!r}; the folder name must be the plugin id")
        out.append(definition)
    logger.info("cplug_ship_list", plugins=[d.id for d in out])
    return tuple(out)


CPLUGS: Tuple[CplugDefinition, ...] = discover()
