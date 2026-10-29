
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Mapping, Optional

from src.core.notifications import doc_model, types
from src.core.notifications.settings_doc.store import SettingsDocStore

SCOPE_HERE = "here"
SCOPE_EVERYWHERE = "everywhere"
SCOPES = (SCOPE_HERE, SCOPE_EVERYWHERE)

_HERE_PREFIX = "mute_here."
_DEVICE_RE = re.compile(r"^(b_[0-9a-f]{16,32}|link:[A-Za-z0-9_-]{1,64})$")
MAX_LABEL = 40

Doc = Dict[str, Any]


def check_device(device: Any) -> str:
    if not isinstance(device, str) or not _DEVICE_RE.match(device):
        raise ValueError("not a device key")
    return device


def link_device_key(link_device: str) -> str:
    return check_device(f"link:{link_device}")


def _here_key(device: str) -> str:
    return doc_model.local_key(_HERE_PREFIX + check_device(device))


def muted_everywhere(doc: Mapping[str, Any]) -> List[str]:
    return [t.id for t in types.ordered_types()
            if doc_model.effective_value(doc, doc_model.mute_path(t.id), False) is True]


def muted_here(doc: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    prefix = doc_model.LOCAL_PREFIX + _HERE_PREFIX
    for key, val in doc["local"].items():
        if not key.startswith(prefix) or not isinstance(val, Mapping):
            continue
        listed = val.get("types") if isinstance(val.get("types"), list) else []
        kept = [t for t in listed if isinstance(t, str) and types.is_registered(t)]
        if kept:
            label = val.get("label") if isinstance(val.get("label"), str) else ""
            out[key[len(prefix):]] = {"label": label, "types": kept}
    return out


def view(doc: Mapping[str, Any], device: Optional[str]) -> Dict[str, Any]:
    devices = muted_here(doc)
    own = devices.get(device, {}).get("types", []) if device else []
    return {"device": device, "everywhere": muted_everywhere(doc), "here": list(own), "devices": devices}


def is_muted_for(doc: Mapping[str, Any], type_id: str, device: Optional[str]) -> bool:
    if doc_model.effective_value(doc, doc_model.mute_path(type_id), False) is True:
        return True
    if not device:
        return False
    rec = doc["local"].get(doc_model.LOCAL_PREFIX + _HERE_PREFIX + device)
    return isinstance(rec, Mapping) and isinstance(rec.get("types"), list) and type_id in rec["types"]


def _check_type(type_id: Any) -> str:
    if not isinstance(type_id, str) or not types.is_registered(type_id):
        raise ValueError("unknown type")
    return type_id


def set_mute(store: SettingsDocStore, type_id: str, scope: str, muted: bool, *,
             device: Optional[str] = None, label: str = "", now: Optional[float] = None) -> Doc:
    _check_type(type_id)
    if scope not in SCOPES:
        raise ValueError("unknown scope")
    if scope == SCOPE_HERE:
        key = _here_key(device or "")
    clean_label = (label or "").strip()[:MAX_LABEL]

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        if scope == SCOPE_EVERYWHERE:
            path = doc_model.mute_path(type_id)
            current = doc_model.effective_value(doc, path, False) is True
            if current == muted:
                return None
            if muted:
                return doc_model.set_global(doc, path, True, me)
            return doc_model.delete_global(doc, path, me, time.time() if now is None else now)
        rec = doc["local"].get(key)
        listed = list(rec.get("types", [])) if isinstance(rec, Mapping) and isinstance(rec.get("types"), list) else []
        if (type_id in listed) == muted:
            return None
        listed = listed + [type_id] if muted else [t for t in listed if t != type_id]
        if not listed:
            return doc_model.clear_local(doc, key)
        old_label = rec.get("label") if isinstance(rec, Mapping) and isinstance(rec.get("label"), str) else ""
        return doc_model.set_local(doc, key, {"label": clean_label or old_label, "types": listed})

    return store.update(mutate)
