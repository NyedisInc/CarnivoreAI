
from __future__ import annotations

from typing import Any, List, Mapping, Optional

import pydantic

from src.core.federation import peer_hosts, peer_listing, shadow_rows
from src.models import SessionInfo


def _session_id(raw: Mapping[str, Any]) -> str:
    session = raw.get("session")
    return str(session.get("id", "")) if isinstance(session, Mapping) else ""


def _changed_keys(frame: Mapping[str, Any], before_rows: Mapping[str, Any]) -> Optional[List[str]]:
    if frame.get("full") is True or frame.get("asleep"):
        return None
    change = frame.get("list")
    if not change:
        return []
    if not isinstance(change, Mapping) or change.get("remove") or "order" in change:
        return None
    upserts = change.get("upsert") or []
    keys = [item.get("key") for item in upserts if isinstance(item, Mapping)]
    if len(keys) != len(upserts) or any(not isinstance(k, str) or k not in before_rows for k in keys):
        return None
    return keys


def refresh_delta(frame: Mapping[str, Any], before: Any, after: Any, peer: "peer_hosts.PeerRow",
                  snapshot_rows: List[SessionInfo]) -> Optional[List[SessionInfo]]:
    if before is None or before.stream != after.stream:
        return None
    keys = _changed_keys(frame, dict(before.rows))
    if keys is None:
        return None
    old_rows, new_rows = dict(before.rows), dict(after.rows)
    by_uuid = {row.session_uuid: i for i, row in enumerate(snapshot_rows)}
    if len(by_uuid) != len(snapshot_rows):
        return None
    if any(row.host_key != peer.key or row.host_label != peer.label for row in snapshot_rows):
        return None
    out = list(snapshot_rows)
    try:
        for key in keys:
            old, new = old_rows[key], new_rows[key]
            if not (peer_listing.accept(new, peer.peer_install_id) and peer_listing.accept(old, peer.peer_install_id)):
                return None
            if (peer_listing.sync_row(old) != peer_listing.sync_row(new) or _session_id(old) != _session_id(new)
                    or old.get("origin_install_id") != new.get("origin_install_id") or old.get("host_key") != new.get("host_key")):
                return None
            at = by_uuid.get(shadow_rows.shadow_uuid(peer.peer_install_id, str(new["session_uuid"])))
            if at is None:
                return None
            held = snapshot_rows[at]
            shadow = shadow_rows.Shadow(held.session_row_id, held.project_id, held.project_name)
            out[at] = peer_listing.to_info(new, shadow, peer)
    except (pydantic.ValidationError, ValueError, KeyError, TypeError):
        return None
    return out
