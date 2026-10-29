
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.notifications import doc_model
from src.core.notifications.destinations.store import MAX_GLOBAL_DESTINATIONS, owned_paths
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.sync import sanitize, seen

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MergeOutcome:

    changed: bool
    incoming: Mapping[str, Mapping[str, Any]]
    deleted_dests: Tuple[str, ...] = ()


def _dest_of(path: str) -> Optional[str]:
    try:
        parsed = doc_model.parse_path(path)
    except ValueError:
        return None
    if parsed.kind == doc_model.KIND_DEST or parsed.kind == doc_model.KIND_EXTRA:
        return parsed.dest
    if parsed.kind == doc_model.KIND_TICK and parsed.col != doc_model.COL_SCREEN:
        return parsed.col
    return None


def _cap_destinations(merged: Dict[str, Any], mine: Mapping[str, Any]) -> None:
    live = sanitize.live_dest_ids(merged)
    mine_live = set(sanitize.live_dest_ids(mine))
    over = len(live) - MAX_GLOBAL_DESTINATIONS
    if over <= 0:
        return
    refused = [d for d in reversed(live) if d not in mine_live][:over]
    for path in [p for p in merged if _dest_of(p) in refused]:
        if path in mine:
            merged[path] = mine[path]
        else:
            del merged[path]
    log.warning("notification_sync_destination_cap", refused=len(refused))


def merge_into(store: SettingsDocStore, theirs_raw: Any, now: float) -> MergeOutcome:
    theirs = sanitize.clean_map(theirs_raw, now)
    deleted: List[str] = []
    wrote: List[bool] = []

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        mine = doc["global"]
        merged = doc_model.merge_global(mine, theirs)
        _cap_destinations(merged, mine)
        if merged == mine:
            return None
        gone = set(sanitize.live_dest_ids(mine)) - set(sanitize.live_dest_ids(merged))
        deleted[:] = sorted(d for d in gone if doc_model.dest_path(d) in merged)
        new = {**doc, "global": merged}
        for dest_id in deleted:
            for path in owned_paths(new, dest_id):
                new = doc_model.clear_local(new, path)
            new = seen.forget(new, dest_id)
        wrote.append(True)
        return new

    store.update(mutate)
    return MergeOutcome(changed=bool(wrote), incoming=theirs, deleted_dests=tuple(deleted))
