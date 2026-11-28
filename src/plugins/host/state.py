
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import structlog

from src.plugins.host.permission_renames import current_names
from src.plugins.sdk.manifest import Manifest
from src.plugins.sdk.permission_registry import DEFAULT_GRANTED, FIRST_PARTY_TIERS, PLATFORM_GRANTED
from src.plugins.host import developer_mode, registry_store

logger = structlog.get_logger()

STATE_DIR_NAME = registry_store.STATE_DIR_NAME
STATE_VERSION = 1

_STATE_FIELDS = ("enabled", "grants", "settings", "revision", "digest", "updated_at", "ui_slot_grants")
_IDENTITY_FIELDS = (
    "kind",
    "source",
    "catalog_id",
    "install_uuid",
    "publisher_key_id",
    "source_path",
    "ledger_extra",
    "sideload_record",
    "unstored",
)

_lock = threading.RLock()


class StaleRevision(Exception):

    def __init__(self, current: "CplugState") -> None:
        super().__init__(f"revision is {current.revision}")
        self.current = current


class StateWriteFailed(OSError):
    pass


class StateUnreadable(StateWriteFailed):
    pass


@dataclass(frozen=True)
class CplugState:

    id: str
    enabled: bool = False
    grants: Tuple[str, ...] = ()
    settings: Dict[str, Any] = field(default_factory=dict)
    revision: int = 0
    stored: bool = False
    digest: str = ""
    ui_slot_grants: Tuple[str, ...] = ()

    def as_wire(self) -> Dict[str, Any]:
        grants_wire: Dict[str, Any] = {"app": list(self.grants)}
        if self.ui_slot_grants:
            grants_wire["ui_slots"] = list(self.ui_slot_grants)
        return {"enabled": self.enabled, "grants": grants_wire, "settings": dict(self.settings),
                "revision": self.revision, "digest": self.digest}


def _declared_ui_slots(manifest: Any) -> Tuple[str, ...]:
    contribute = getattr(manifest, "ui_contribute", None)
    if not isinstance(contribute, Mapping):
        return ()
    return tuple(str(k) for k in contribute.keys())


def default_state(manifest: Manifest) -> CplugState:
    asked = tuple(manifest.permissions)
    declared_slots = _declared_ui_slots(manifest)
    if manifest.tier not in FIRST_PARTY_TIERS:
        return CplugState(manifest.id, enabled=False, grants=(), ui_slot_grants=())
    if manifest.tier == "core" or manifest.default_enabled is True:
        return CplugState(manifest.id, enabled=True, grants=asked, ui_slot_grants=declared_slots)
    if manifest.default_enabled is False:
        return CplugState(manifest.id, enabled=False, grants=(), ui_slot_grants=())
    if set(asked) <= DEFAULT_GRANTED and not declared_slots:
        return CplugState(manifest.id, enabled=True, grants=asked, ui_slot_grants=())
    return CplugState(manifest.id, enabled=False, grants=(), ui_slot_grants=())


def _extract_state_entry(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, Mapping) or item.get("unstored") is True or "state_raw" in item:
        return None
    has_state = any(k in item for k in _STATE_FIELDS) or isinstance(item.get("state_extra"), Mapping)
    if not has_state:
        return None
    entry = {k: copy.deepcopy(item[k]) for k in _STATE_FIELDS if k in item}
    if isinstance(item.get("state_extra"), Mapping):
        entry.update(copy.deepcopy(item["state_extra"]))
    return entry


def _load(state_dir: Path) -> Optional[Dict[str, Any]]:
    doc, status = registry_store.load_registry(state_dir)
    if status == registry_store.STATUS_UNREADABLE:
        return None
    if status == registry_store.STATUS_MISSING or doc is None:
        return {}
    cplugs: Dict[str, Any] = {}
    items = doc.get("items")
    if isinstance(items, Mapping):
        for cplug_id, item in items.items():
            entry = _extract_state_entry(item)
            if entry is not None:
                cplugs[str(cplug_id)] = entry
    tombstones = doc.get("tombstones")
    if isinstance(tombstones, Mapping):
        for cplug_id, tomb in tombstones.items():
            if isinstance(tomb, Mapping) and isinstance(tomb.get("state"), Mapping):
                cplugs[str(cplug_id)] = copy.deepcopy(dict(tomb["state"]))
    return cplugs


def _read_file(state_dir: Path) -> Dict[str, Any]:
    loaded = _load(state_dir)
    return {} if loaded is None else loaded


def _doc_for_update(state_dir: Path) -> Dict[str, Any]:
    try:
        return registry_store.read_for_mutation(state_dir, log_event="cplug_host_state_unreadable")
    except registry_store.RegistryUnreadable as exc:
        raise StateUnreadable(str(exc)) from exc


def _set_item_state(doc: Dict[str, Any], cplug_id: str, entry_out: Mapping[str, Any]) -> None:
    items = doc.setdefault("items", {})
    tombstones = doc.setdefault("tombstones", {})
    if cplug_id not in items and isinstance(tombstones.get(cplug_id), dict):
        tomb = tombstones[cplug_id]
        tomb["state"] = copy.deepcopy(dict(entry_out))
        if "grants" in entry_out:
            tomb["grants"] = copy.deepcopy(entry_out["grants"])
        if "settings" in entry_out:
            tomb["settings"] = copy.deepcopy(entry_out["settings"])
        return
    core_part = {k: copy.deepcopy(v) for k, v in entry_out.items() if k in _STATE_FIELDS}
    extra_part = {k: copy.deepcopy(v) for k, v in entry_out.items() if k not in _STATE_FIELDS and k not in _IDENTITY_FIELDS}
    existing = items.get(cplug_id)
    if isinstance(existing, dict):
        existing.pop("unstored", None)
        existing.pop("state_raw", None)
        existing.pop("state_extra", None)
        for field_name in _STATE_FIELDS:
            existing.pop(field_name, None)
        existing.update(core_part)
        if extra_part:
            existing["state_extra"] = extra_part
    else:
        new_item: Dict[str, Any] = {"kind": registry_store.KIND_FEATURE, **core_part}
        if extra_part:
            new_item["state_extra"] = extra_part
        items[cplug_id] = new_item


def _from_entry(manifest: Manifest, entry: Dict[str, Any]) -> CplugState:
    grants = entry.get("grants") if isinstance(entry.get("grants"), list) else []
    grants = [*grants, *(p for p in manifest.permissions if p in PLATFORM_GRANTED and p not in grants)]
    declared_slots = set(_declared_ui_slots(manifest))
    raw_slots = entry.get("ui_slot_grants") if isinstance(entry.get("ui_slot_grants"), list) else []
    slot_grants = tuple(dict.fromkeys(s for s in raw_slots if isinstance(s, str) and s in declared_slots))
    settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
    revision = entry.get("revision")
    return CplugState(manifest.id, enabled=entry.get("enabled") is True,
                      grants=tuple(g for g in current_names(g for g in grants if isinstance(g, str)) if g in manifest.permissions), settings=dict(settings),
                      revision=revision if isinstance(revision, int) and revision >= 0 else 0, stored=True,
                      digest=entry["digest"] if isinstance(entry.get("digest"), str) else "",
                      ui_slot_grants=slot_grants)


_core_off_logged: set = set()


def get(state_dir: Path, manifest: Manifest) -> CplugState:
    state = _stored_or_default(state_dir, manifest)
    if manifest.tier == "dev" and state.enabled and not developer_mode.is_on():
        return replace(state, enabled=False)
    return state


def _stored_or_default(state_dir: Path, manifest: Manifest) -> CplugState:
    stored = _read_file(state_dir)
    entry = stored.get(manifest.id)
    if not isinstance(entry, dict):
        pending = carry_state(state_dir, manifest)
        if pending == CARRY_PENDING:
            return replace(_from_entry(manifest, stored[manifest.renamed_from]), stored=False)
        if pending == CARRY_STRANDED:
            return CplugState(manifest.id, enabled=False, grants=())
        return default_state(manifest)
    state = _from_entry(manifest, entry)
    if manifest.tier == "core" and not state.enabled:
        if manifest.id not in _core_off_logged:
            _core_off_logged.add(manifest.id)
            logger.info("cplug_core_stored_off_ignored", cplug=manifest.id)
        return replace(state, enabled=True)
    return state


def stored_enabled(state_dir: Path, cplug_id: str) -> Optional[bool]:
    entry = _read_file(state_dir).get(cplug_id)
    if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
        return entry["enabled"]
    return None


def stored_entry(state_dir: Path, cplug_id: str) -> Optional[Dict[str, Any]]:
    entry = _read_file(state_dir).get(cplug_id)
    return dict(entry) if isinstance(entry, dict) else None


CARRY_PENDING = "pending"
CARRY_STRANDED = "stranded"


def carry_state(state_dir: Path, manifest: Manifest) -> str:
    renamed_from = getattr(manifest, "renamed_from", "")
    if not renamed_from:
        return ""
    stored = _read_file(state_dir)
    if not (isinstance(stored.get(renamed_from), dict) and manifest.id not in stored):
        return ""
    from src.plugins.host import renamed_entry

    try:
        return CARRY_STRANDED if renamed_entry.is_recorded(state_dir, renamed_from, manifest.id) else CARRY_PENDING
    except OSError:
        return CARRY_PENDING


def carry_pending(state_dir: Path, manifest: Manifest) -> bool:
    return carry_state(state_dir, manifest) == CARRY_PENDING


def carry_blocked(state_dir: Path, manifest: Manifest) -> bool:
    return carry_state(state_dir, manifest) != ""


def stored_ids(state_dir: Path) -> Tuple[str, ...]:
    return tuple(sorted(_read_file(state_dir)))


def update(state_dir: Path, manifest: Manifest, expected_revision: Optional[int],
           mutate: Callable[[CplugState], CplugState]) -> CplugState:
    path = registry_store.registry_path(state_dir)
    with registry_store.locked(state_dir, _lock, StateWriteFailed):
        current = get(state_dir, manifest)
        if expected_revision is not None and expected_revision != current.revision:
            raise StaleRevision(current)
        changed = replace(mutate(current), revision=current.revision + 1, stored=True)
        doc = _doc_for_update(state_dir)
        entry_out: Dict[str, Any] = {
            "enabled": changed.enabled,
            "grants": list(changed.grants),
            "settings": changed.settings,
            "revision": changed.revision,
            "digest": changed.digest,
            "updated_at": time.time(),
        }
        if changed.ui_slot_grants:
            entry_out["ui_slot_grants"] = list(changed.ui_slot_grants)
        _set_item_state(doc, manifest.id, entry_out)
        if not registry_store.save_document(state_dir, doc, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        return changed


def granted_ui_slots(state_dir: Path, manifest: Any) -> Tuple[str, ...]:
    from src.plugins.host import risk  # noqa: PLC0415

    st = get(state_dir, manifest)
    if not st.enabled or risk.consent_owed(manifest.tier, manifest.code_digest, st.digest):
        return ()
    return getattr(st, "ui_slot_grants", ())


def strip_consent(state_dir: Path, cplug_id: str) -> bool:
    path = registry_store.registry_path(state_dir)
    with registry_store.locked(state_dir, _lock, StateWriteFailed):
        doc = _doc_for_update(state_dir)
        entry = _extract_state_entry(doc.get("items", {}).get(cplug_id))
        if entry is None:
            tomb = doc.get("tombstones", {}).get(cplug_id)
            entry = dict(tomb["state"]) if isinstance(tomb, Mapping) and isinstance(tomb.get("state"), Mapping) else None
        if not isinstance(entry, dict) or (not entry.get("grants") and not entry.get("digest") and not entry.get("ui_slot_grants")):
            return False
        stripped = {**entry, "grants": [], "digest": "", "revision": int(entry.get("revision") or 0) + 1, "updated_at": time.time()}
        stripped.pop("ui_slot_grants", None)
        _set_item_state(doc, cplug_id, stripped)
        if not registry_store.save_document(state_dir, doc, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        return True


def switch_off(state_dir: Path, cplug_id: str) -> bool:
    path = registry_store.registry_path(state_dir)
    with registry_store.locked(state_dir, _lock, StateWriteFailed):
        loaded = _load(state_dir)
        entry = loaded.get(cplug_id) if loaded is not None else None
        if not isinstance(entry, dict) or entry.get("enabled") is not True:
            return False
        doc = _doc_for_update(state_dir)
        updated = {**entry, "enabled": False, "revision": int(entry.get("revision") or 0) + 1, "updated_at": time.time()}
        _set_item_state(doc, cplug_id, updated)
        if not registry_store.save_document(state_dir, doc, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        return True


def forget(state_dir: Path, cplug_id: str) -> bool:
    path = registry_store.registry_path(state_dir)
    with registry_store.locked(state_dir, _lock, StateWriteFailed):
        doc = _doc_for_update(state_dir)
        items = doc.setdefault("items", {})
        tombstones = doc.setdefault("tombstones", {})
        changed = False
        item = items.get(cplug_id)
        if _extract_state_entry(item) is not None:
            if isinstance(item, dict) and ("install_uuid" in item or "sideload_record" in item):
                for field_name in _STATE_FIELDS:
                    item.pop(field_name, None)
                item.pop("state_extra", None)
                item.pop("state_raw", None)
                item["unstored"] = True
            else:
                items.pop(cplug_id, None)
            changed = True
        elif isinstance(tombstones.get(cplug_id), dict) and "state" in tombstones[cplug_id]:
            del tombstones[cplug_id]["state"]
            changed = True
        if not changed:
            return False
        if not registry_store.save_document(state_dir, doc, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        return True


def restore_entry(state_dir: Path, cplug_id: str, entry: Mapping[str, Any]) -> None:
    path = registry_store.registry_path(state_dir)
    with registry_store.locked(state_dir, _lock, StateWriteFailed):
        doc = _doc_for_update(state_dir)
        _set_item_state(doc, cplug_id, dict(entry))
        if not registry_store.save_document(state_dir, doc, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
