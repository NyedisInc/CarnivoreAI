
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.core import resource_push
from src.core.notifications import doc_model
from src.core.notifications.sync.peers import PeerInfo
from src.core.resource_push import topics

OFF_KEY = doc_model.local_key("sync_off")

R_OK, R_NO_CHANGE, R_OFF, R_OLDER = "ok", "no_change", "off", "older"
R_DISCONNECTED, R_REFUSED, R_RATE_LIMITED, R_ERROR = "disconnected", "refused", "rate_limited", "error"


def is_enabled(doc: Mapping[str, Any], install_id: str) -> bool:
    off = doc["local"].get(OFF_KEY)
    return not (isinstance(off, list) and install_id in off)


def with_enabled(doc: Mapping[str, Any], install_id: str, enabled: bool) -> Dict[str, Any]:
    off = {i for i in (doc["local"].get(OFF_KEY) or []) if isinstance(i, str)}
    off = off - {install_id} if enabled else off | {install_id}
    return doc_model.set_local(doc, OFF_KEY, sorted(off))


@dataclass(frozen=True)
class LastExchange:

    at: float
    result: str


class SyncStatus:

    def __init__(self) -> None:
        self._last: Dict[str, LastExchange] = {}

    def record(self, install_id: str, result: str, now: float) -> None:
        record = LastExchange(now, result)
        changed = self._last.get(install_id) != record
        self._last[install_id] = record
        if changed:
            resource_push.notify(topics.NOTIFICATION_SETTINGS)

    def get(self, install_id: str) -> Optional[LastExchange]:
        return self._last.get(install_id)


def summarise(roster: Iterable[PeerInfo], doc: Mapping[str, Any], status: SyncStatus) -> Dict[str, Any]:
    peers: List[Dict[str, Any]] = []
    for peer in roster:
        last = status.get(peer.install_id)
        protocol = "unknown" if not peer.connected else "ok" if peer.speaks_sync else "older"
        peers.append({
            "key": peer.key, "label": peer.label, "enabled": is_enabled(doc, peer.install_id),
            "protocol": protocol, "connected": peer.connected,
            "last_exchange_at": last.at if last else None, "last_result": last.result if last else None,
        })
    return {"peers": peers}
