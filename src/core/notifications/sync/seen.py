
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from src.core.notifications import doc_model, kind_specs
from src.core.notifications.settings_doc import view

SEEN_KEY = doc_model.local_key("secret_seen")


def record_rev(record: Mapping[str, Any]) -> int:
    rev = record.get("secret_rev")
    return rev if isinstance(rev, int) and not isinstance(rev, bool) and rev > 0 else 0


def seen_rev(doc: Mapping[str, Any], dest_id: str) -> int:
    seen = doc["local"].get(SEEN_KEY)
    rev = seen.get(dest_id) if isinstance(seen, Mapping) else None
    return rev if isinstance(rev, int) and not isinstance(rev, bool) and rev > 0 else 0


def mark_seen(doc: Mapping[str, Any], dest_id: str, rev: int) -> Dict[str, Any]:
    seen = dict(doc["local"].get(SEEN_KEY) or {})
    seen[dest_id] = rev
    return doc_model.set_local(doc, SEEN_KEY, seen)


def forget(doc: Mapping[str, Any], dest_id: str) -> Dict[str, Any]:
    seen = dict(doc["local"].get(SEEN_KEY) or {})
    if dest_id not in seen:
        return dict(doc)
    del seen[dest_id]
    return doc_model.set_local(doc, SEEN_KEY, seen)


def stale_destinations(doc: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for dest_id in view.dest_ids(doc):
        if view.dest_scope(doc, dest_id) != view.SRC_GLOBAL or not kind_specs.is_destination_id(dest_id):
            continue
        record = doc["global"][doc_model.dest_path(dest_id)]["val"]
        if isinstance(record, Mapping) and record.get("secret_fields") and record_rev(record) > seen_rev(doc, dest_id):
            out.append(dest_id)
    return out
