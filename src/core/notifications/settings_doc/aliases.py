
from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.notifications import doc_model, types

Doc = Dict[str, Any]

_HERE_PREFIX = doc_model.LOCAL_PREFIX + "mute_here."


def _counter(entry: Mapping[str, Any]) -> int:
    try:
        return doc_model.parse_version(entry.get("ver"))[0]
    except ValueError:
        return 0


def _live(entry: Optional[Mapping[str, Any]]) -> bool:
    return isinstance(entry, Mapping) and not doc_model.is_tombstone(entry) and "val" in entry


def _old_paths(doc: Mapping[str, Any]) -> List[Tuple[str, str]]:
    pairs = []
    for path in set(doc["global"]) | set(doc["local"]):
        head, _, rest = path.partition("/")
        if head in (doc_model.KIND_DEFAULT, doc_model.KIND_MUTE) and rest in types.ALIASES:
            pairs.append((path, f"{head}/{types.ALIASES[rest]}"))
        elif head == doc_model.KIND_TICK:
            col, _, type_id = rest.partition("/")
            if type_id in types.ALIASES:
                pairs.append((path, f"{head}/{col}/{types.ALIASES[type_id]}"))
    return sorted(pairs)


def _fold_path(doc: Doc, old: str, new: str, me: str, now: float) -> Doc:
    g_old, g_new = doc["global"].get(old), doc["global"].get(new)
    if _live(g_old) and not (_live(g_new) and _counter(g_new) >= 2) and new not in doc["local"]:
        merged = bool(g_old["val"]) or (bool(g_new["val"]) if _live(g_new) else False)
        if not _live(g_new) or g_new["val"] != merged:
            doc = doc_model.set_global(doc, new, merged, me)
    if old in doc["local"]:
        if new not in doc["local"] or doc["local"][old] is True:
            doc = doc_model.set_local(doc, new, bool(doc["local"][old]) or bool(doc["local"].get(new, False)))
        doc["local"].pop(old, None)
    if _live(g_old):
        doc["global"][old] = {"tomb": now, "ver": [_counter(g_old) + 1, me]}
    return doc


def _fold_mute_here(doc: Doc) -> Doc:
    for key, rec in list(doc["local"].items()):
        if not key.startswith(_HERE_PREFIX) or not isinstance(rec, Mapping) or not isinstance(rec.get("types"), list):
            continue
        if not any(isinstance(t, str) and t in types.ALIASES for t in rec["types"]):
            continue
        renamed: List[Any] = []
        for t in rec["types"]:
            t = types.canonical(t)
            if t not in renamed:
                renamed.append(t)
        doc["local"][key] = {**rec, "types": renamed}
    return doc


def _move_seeds(doc: Doc, me: str) -> Doc:
    seeded = set(types.seed_type_ids())
    for row in types.ordered_types():
        path = doc_model.default_path(row.id)
        entry = doc["global"].get(path)
        if _live(entry) and _counter(entry) == 1 and bool(entry["val"]) != (row.id in seeded):
            doc = doc_model.set_global(doc, path, row.id in seeded, me)
    return doc


def fold(doc: Mapping[str, Any], me: str, now: Optional[float] = None) -> Doc:
    out = copy.deepcopy(dict(doc))
    stamp = time.time() if now is None else now
    for old, new in _old_paths(out):
        out = _fold_path(out, old, new, me, stamp)
    return _move_seeds(_fold_mute_here(out), me)


def needs_fold(doc: Mapping[str, Any]) -> bool:
    return fold(doc, "n_check", 0.0) != dict(doc)


def fold_store(store: Any) -> bool:
    if not needs_fold(store.snapshot()):
        return False
    store.update(lambda doc, me: doc)
    return True
