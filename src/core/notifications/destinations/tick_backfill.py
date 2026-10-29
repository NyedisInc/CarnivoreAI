
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import SettingsDocStore

log = structlog.get_logger()
Doc = Dict[str, Any]

BACKFILL_TYPES = ("pack.skills",)


def _columns(doc: Doc) -> List[str]:
    cols = set(view.dest_ids(doc))
    for path in (*doc["global"], *doc["local"]):
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == doc_model.KIND_TICK and kind_specs.is_push_destination_id(parts[1]):
            cols.add(parts[1])
    return sorted(cols)


def _kind_of(doc: Doc, col: str) -> Optional[str]:
    record = view.dest_record(doc, col)
    return record["kind"] if record else kind_specs.virtual_kind_of(col)


async def backfill_type_ticks(docs: SettingsDocStore) -> int:
    count = 0

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        nonlocal count
        count = 0
        for col in _columns(doc):
            kind = _kind_of(doc, col)
            for type_id in BACKFILL_TYPES:
                row = types.get_type(type_id)
                path = doc_model.tick_path(col, type_id)
                if (row is None or kind is None or not row.defaults.seed or row.defaults.outside_locked_off or kind in row.seed_excluded_kinds
                        or doc_model.effective_source(doc, path) != "absent"):
                    continue
                is_global = view.dest_scope(doc, col) == view.SRC_GLOBAL
                doc = doc_model.set_global(doc, path, True, me) if is_global else doc_model.set_local(doc, path, True)
                count += 1
        return doc if count else None

    await asyncio.to_thread(docs.update, mutate)
    if count:
        log.info("notification_tick_backfilled", cells=count)
    return count
