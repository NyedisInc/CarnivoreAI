
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from src.core.pipeline.contract import Plugin, validate_all
from src.core.deepsearch.pipeline_plugin import DEEPSEARCH
from src.core.stats.plugin.pipeline_plugin import STATS

PLUGINS: Tuple[Plugin, ...] = (STATS, DEEPSEARCH)


def plugins(entries: Optional[Iterable[Plugin]] = None) -> Tuple[Plugin, ...]:
    found = tuple(PLUGINS if entries is None else entries)
    validate_all(found)
    return found


def find(plugin_id: str, entries: Optional[Iterable[Plugin]] = None) -> Optional[Plugin]:
    return next((p for p in plugins(entries) if p.id == plugin_id), None)
