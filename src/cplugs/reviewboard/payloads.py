
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.reviewboard.errors import BadRequest
from src.cplugs.reviewboard.layers import payload as layer_payload
from src.cplugs.reviewboard.schema import MAX_DIFF_PATHS, MAX_SAVES, Sidecar

PATH_JOIN = "."
MAX_PATH = 200


def _leaves(value: Any, prefix: str, out: Dict[str, Any]) -> None:
    if isinstance(value, dict) and value:
        for key, child in value.items():
            _leaves(child, f"{prefix}{PATH_JOIN}{key}" if prefix else str(key), out)
    else:
        out[prefix] = value


def diff(previous: Optional[Dict[str, Any]], current: Dict[str, Any], previous_round: Optional[str]) -> Dict[str, Any]:
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    _leaves(previous or {}, "", before)
    _leaves(current, "", after)
    before.pop("", None)
    after.pop("", None)
    groups = {"added": sorted(set(after) - set(before)),
              "removed": sorted(set(before) - set(after)),
              "changed": sorted(p for p in set(before) & set(after) if before[p] != after[p])}
    more = sum(max(0, len(paths) - MAX_DIFF_PATHS) for paths in groups.values())
    out: Dict[str, Any] = {k: [p[:MAX_PATH] for p in paths[:MAX_DIFF_PATHS]] for k, paths in groups.items()}
    out["more"] = more
    if previous_round is not None:
        out = {"previous": previous_round, **out}
    return out


def previous_send(current: Sidecar) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    for rnd in reversed(current.rounds):
        if rnd.payload is not None:
            return rnd.payload, rnd.id
    return None, None


def check_fits_layer(row: Dict[str, Any], revision_id: str, payload: Dict[str, Any]) -> None:
    if not row.get("layer"):
        return
    layer = layer_payload.LAYER_ADAPTER.validate_python(row["layer"])
    found = layer_payload.problems(layer, payload)
    if found:
        raise BadRequest(f"{revision_id}: the payload does not fit its {layer.kind} layer: " + "; ".join(found[:5]))


def set_draft(doc: Dict[str, Any], revision_id: str, payload: Dict[str, Any], at: str) -> bool:
    row = next((r for r in doc["revisions"] if r["id"] == revision_id), None)
    if row is None:
        raise BadRequest(f"the board has no revision {revision_id}")
    if not row.get("payload_mode"):
        raise BadRequest(f"{revision_id} does not hold its own answers (payload_mode); there is nothing to draft")
    check_fits_layer(row, revision_id, payload)
    if (row.get("draft") or {}).get("payload") == payload:
        return False
    row["draft"] = {"at": at, "payload": payload}
    return True


def add_save(doc: Dict[str, Any], revision_id: str, payload: Dict[str, Any], note: Optional[str], at: str) -> int:
    row = next((r for r in doc["revisions"] if r["id"] == revision_id), None)
    if row is None:
        raise BadRequest(f"the board has no revision {revision_id}")
    if not row.get("payload_mode"):
        raise BadRequest(f"{revision_id} does not hold its own answers (payload_mode); there is nothing to save")
    check_fits_layer(row, revision_id, payload)
    saves: List[Dict[str, Any]] = list(row.get("saves") or [])
    if len(saves) >= MAX_SAVES:
        raise BadRequest(f"{revision_id} holds {MAX_SAVES} saves, the most one revision keeps; publish a new revision to continue")
    save: Dict[str, Any] = {"n": len(saves) + 1, "at": at, "payload": payload}
    if note and note.strip():
        save["note"] = note.strip()
    row["saves"] = [*saves, save]
    return save["n"]
