
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Set

GENERIC_LABEL = "phone"


def doubled_subscriptions(subs: Iterable[Mapping[str, Any]], native_rows: Iterable[Mapping[str, Any]],
                          labels: Mapping[str, str]) -> Set[str]:
    app_devices = {r.get("device_id") for r in native_rows if r.get("device_id")}
    app_labels = {labels.get(d) for d in app_devices} - {None, "", GENERIC_LABEL}
    hits: Set[str] = set()
    for sub in subs:
        device = sub.get("device_id")
        if not device:
            continue
        if device in app_devices or labels.get(device) in app_labels:
            hits.add(sub["id"])
    return hits


def device_labels(manager: Any) -> Dict[str, str]:
    if manager is None:
        return {}
    return {d.id: d.label for d in manager.pairing.devices()}
