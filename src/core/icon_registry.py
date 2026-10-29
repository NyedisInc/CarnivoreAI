
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional, Tuple

import structlog

logger = structlog.get_logger()

REGISTRY_PATH: Path = (
    Path(__file__).resolve().parents[2] / "client" / "js" / "icons" / "icon-registry.js"
)

_REGISTRY_BLOCK = re.compile(
    r"ICON_REGISTRY\s*=\s*Object\.freeze\(\s*\[(.*?)\]\s*\)", re.DOTALL
)
_RETIRED_BLOCK = re.compile(
    r"RETIRED_ICON_IDS\s*=\s*Object\.freeze\(\s*\{(.*?)\}\s*\)", re.DOTALL
)
_ENTRY_ID = re.compile(r"""\bid\s*:\s*['"]([a-z0-9-]+)['"]""")
_RETIRED_KEY = re.compile(r"""['"]([a-z0-9-]+)['"]\s*:""")


UNAVAILABLE_CODE = "icon_registry_unavailable"


class IconRegistryUnavailable(Exception):
    pass


@dataclass(frozen=True)
class IconIds:

    current: FrozenSet[str]
    retired: FrozenSet[str]

    def accepts(self, icon_id: str) -> bool:
        return icon_id in self.current or icon_id in self.retired


_cache: Optional[Tuple[Tuple[int, int], IconIds]] = None


def parse(source: str) -> IconIds:
    block = _REGISTRY_BLOCK.search(source)
    current = frozenset(_ENTRY_ID.findall(block.group(1))) if block else frozenset()
    if not current:
        raise IconRegistryUnavailable("the icon registry names no icon")
    retired_block = _RETIRED_BLOCK.search(source)
    retired = (
        frozenset(_RETIRED_KEY.findall(retired_block.group(1)))
        if retired_block else frozenset()
    )
    return IconIds(current=current, retired=retired)


def known_ids(path: Path = REGISTRY_PATH) -> IconIds:
    global _cache
    try:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        if path == REGISTRY_PATH and _cache is not None and _cache[0] == key:
            return _cache[1]
        ids = parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("icon_registry_unreadable", path=str(path), error=str(exc))
        raise IconRegistryUnavailable(f"the icon registry could not be read: {exc}") from exc
    if path == REGISTRY_PATH:
        _cache = (key, ids)
    return ids
