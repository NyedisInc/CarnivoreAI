
from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.plugins.sdk import CplugDefinition
from src.plugins.ship_order import ship_order

logger = structlog.get_logger()

PLUGINS_ROOT = Path(__file__).resolve().parent
TOML_FILE = "carnivore.toml"


class ShipListError(Exception):
    pass


def manifest_path(folder: Path) -> Optional[Path]:
    candidate = folder / TOML_FILE
    return candidate if candidate.is_file() else None


def plugin_folders(root: Path = PLUGINS_ROOT) -> List[str]:
    found = (
        sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").is_file() and manifest_path(p) is not None)
        if root.is_dir()
        else []
    )
    rank = {name: i for i, name in enumerate(ship_order())}
    return sorted(found, key=lambda n: (rank.get(n, len(rank)), n))


def discover(root: Path = PLUGINS_ROOT) -> Tuple[CplugDefinition, ...]:
    out: List[CplugDefinition] = []
    for name in plugin_folders(root):
        module = importlib.import_module(f"src.plugins.{name}")
        definition = getattr(module, "CPLUG", None)
        if not isinstance(definition, CplugDefinition):
            raise ShipListError(f"src/plugins/{name} has a manifest but no CPLUG definition")
        if definition.id != name:
            raise ShipListError(f"src/plugins/{name} declares id {definition.id!r}; the folder name must be the plugin id")
        out.append(definition)
    logger.info("cplug_ship_list", plugins=[d.id for d in out])
    return tuple(out)


CPLUGS: Tuple[CplugDefinition, ...] = discover()
