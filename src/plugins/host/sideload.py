
from __future__ import annotations

import copy
import os
import secrets
import shutil
import threading
import time
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.plugin_registry import plugin_layout
from src.plugins.host.identity import LOCAL_PUBLISHER
from src.plugins.host import developer_mode, registry_store
from src.plugins.host.plugin_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS, changed_files, copy_tree
from src.plugins.host.sideload_errors import SideloadRefused
from src.plugins.runtime.integrity import SIDECAR_NAME
from src.plugins.sdk import api_contract, manifest_v2

logger = structlog.get_logger()

DURATION_HOURS = (1, 12, 24, 168)
DEFAULT_HOURS = 12
TTL_SECONDS = DEFAULT_HOURS * 60 * 60
TIER_LOCAL = "local"
API_VERSION_UNSUPPORTED = "api_version_unsupported"

_lock = threading.RLock()
_busy = partial(SideloadRefused, "registry_busy", status=503)
_EMPTY: Mapping[str, Any] = MappingProxyType({})
_STATE_FIELDS = ("enabled", "grants", "settings", "revision", "digest", "updated_at", "ui_slot_grants", "state_extra", "state_raw")


def wall() -> float:
    return time.time()


def as_local(manifest: SidecarManifest) -> SidecarManifest:
    return replace(manifest, tier=TIER_LOCAL)


def is_local(item_id: str) -> bool:
    return item_id.partition("/")[0] == LOCAL_PUBLISHER


def contained(path: Path, root: Path) -> Path:
    real = Path(os.path.realpath(path))
    if not real.is_relative_to(Path(os.path.realpath(root))):
        raise SideloadRefused("source_outside_root", "the folder resolves outside the folder it must stay in", 422)
    return real


def code_root_of(state_dir: Path, name: str) -> Path:
    return plugin_layout.code_root(state_dir, name)


def _load(state_dir: Path) -> Optional[Dict[str, Any]]:
    doc, status = registry_store.load_registry(state_dir)
    if status == registry_store.STATUS_UNREADABLE:
        return None
    if status == registry_store.STATUS_MISSING or doc is None:
        return {}
    switches = doc.get("switches") if isinstance(doc.get("switches"), dict) else {}
    sl_switch = switches.get("sideload") if isinstance(switches.get("sideload"), dict) else {}
    items_map: Dict[str, Any] = {}
    for container in ("items", "tombstones"):
        section = doc.get(container)
        if isinstance(section, dict):
            for name, entry in section.items():
                if isinstance(entry, dict) and isinstance(entry.get("sideload_record"), dict):
                    items_map[name] = entry["sideload_record"]
    non_sidecar = doc.get("non_sidecar_sideloads") if isinstance(doc.get("non_sidecar_sideloads"), dict) else {}
    return {
        "enabled_at": sl_switch.get("enabled_at"),
        "hours": sl_switch.get("hours", DEFAULT_HOURS),
        "expires_at": sl_switch.get("expires_at"),
        "items": items_map,
        "installs": non_sidecar,
    }


def _doc_for_update(state_dir: Path) -> Dict[str, Any]:
    try:
        return registry_store.read_for_mutation(state_dir, log_event="cplug_sideload_unreadable")
    except registry_store.RegistryUnreadable as exc:
        raise SideloadRefused("sideload_unreadable", f"the sideload record is unreadable and was left as it is: {exc}", 500) from exc


def _write(state_dir: Path, doc: Dict[str, Any]) -> bool:
    return registry_store.save_document(state_dir, doc, log_event="cplug_sideload_write_failed")


def _save(state_dir: Path, doc: Dict[str, Any]) -> None:
    if not _write(state_dir, doc):
        raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def _snapshot(state_dir: Path) -> Mapping[str, Any]:
    data = _load(state_dir)
    return MappingProxyType(data) if data is not None else _EMPTY


def valid_duration(hours: object) -> bool:
    return hours is None or (type(hours) is int and hours in DURATION_HOURS)


def _hours_in(data: Mapping[str, Any]) -> Optional[int]:
    if "hours" not in data:
        return DEFAULT_HOURS
    found = data["hours"]
    return found if valid_duration(found) else DEFAULT_HOURS


def _enabled_in(data: Mapping[str, Any]) -> Optional[float]:
    stamp = data.get("enabled_at")
    return float(stamp) if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None


def _expiry_in(data: Mapping[str, Any]) -> Optional[float]:
    stamp, hours = _enabled_in(data), _hours_in(data)
    if stamp is None or hours is None:
        return None
    stored = data.get("expires_at")
    return float(stored) if isinstance(stored, (int, float)) and not isinstance(stored, bool) else stamp + hours * 3600


def duration_hours(state_dir: Path) -> Optional[int]:
    return _hours_in(_snapshot(state_dir))


def _enabled_at(state_dir: Path) -> Optional[float]:
    return _enabled_in(_snapshot(state_dir))


def expires_at(state_dir: Path) -> Optional[float]:
    return _expiry_in(_snapshot(state_dir))


def is_on(state_dir: Path, now: Optional[Callable[[], float]] = None) -> bool:
    data = _snapshot(state_dir)
    started = _enabled_in(data)
    if started is None:
        return False
    current = (now or wall)()
    if current < started:
        return False
    end = _expiry_in(data)
    return end is None or current < end


def allowed(state_dir: Path, now: Optional[Callable[[], float]] = None) -> bool:
    return developer_mode.is_on() and is_on(state_dir, now)


def set_switch(state_dir: Path, on: bool, now: Optional[Callable[[], float]] = None, hours: Optional[int] = DEFAULT_HOURS) -> bool:
    if on and not valid_duration(hours):
        raise SideloadRefused("duration_invalid", f"the duration is one of {list(DURATION_HOURS)} hours, or null for until turned off", 422)
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        switches = doc.setdefault("switches", {})
        sl = switches.get("sideload")
        if not isinstance(sl, dict):
            sl = {"enabled_at": None, "hours": DEFAULT_HOURS, "expires_at": None}
            switches["sideload"] = sl
        started = (now or wall)() if on else None
        sl["enabled_at"] = started
        if on:
            sl["hours"] = hours
            sl["expires_at"] = None if hours is None else started + hours * 3600
        else:
            sl["expires_at"] = None
        return _write(state_dir, doc)


def items(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = (_load(state_dir) or {}).get("items")
    return {n: copy.deepcopy(v) for n, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def forget(state_dir: Path, name: str) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        items_map = doc.setdefault("items", {})
        tombstones = doc.setdefault("tombstones", {})
        changed = False
        item = items_map.get(name)
        if isinstance(item, dict) and "sideload_record" in item:
            item.pop("sideload_record", None)
            if "install_uuid" not in item:
                item.pop("source_path", None)
            has_state = item.get("unstored") is not True and any(k in item for k in _STATE_FIELDS)
            if "install_uuid" not in item and not has_state:
                items_map.pop(name, None)
            changed = True
        tomb = tombstones.get(name)
        if isinstance(tomb, dict) and "sideload_record" in tomb:
            tomb.pop("sideload_record", None)
            changed = True
        if changed:
            _save(state_dir, doc)


def installs(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = (_load(state_dir) or {}).get("installs")
    return {k: copy.deepcopy(v) for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def put_install(state_dir: Path, record: Dict[str, Any]) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        doc.setdefault("non_sidecar_sideloads", {})[f"{record['kind']}/{record['name']}"] = dict(record)
        _save(state_dir, doc)


def forget_install(state_dir: Path, kind: str, name: str) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        non_sidecar = doc.get("non_sidecar_sideloads")
        if isinstance(non_sidecar, dict) and non_sidecar.pop(f"{kind}/{name}", None) is not None:
            _save(state_dir, doc)


def require_served_contract(staging: Path) -> None:
    try:
        doc, _filename = manifest_v2.load_raw_v2(staging)
    except (OSError, ValueError, manifest_v2.ManifestV2Error):
        return
    if not isinstance(doc, dict):
        return
    try:
        api_contract.require_served(doc)
    except api_contract.ApiVersionUnsupported as exc:
        raise SideloadRefused(API_VERSION_UNSUPPORTED, str(exc), 422) from exc


def stage(state_dir: Path, name: str, source: Path, *, dev: bool = False) -> "tuple[Path, Dict[str, str], SidecarManifest]":
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise SideloadRefused("source_missing", "give the absolute path of a folder (not a link)", 422)
    staging = code_root_of(state_dir, f".sideload-{name}-{os.getpid()}-{time.monotonic_ns()}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        files = copy_tree(source, staging, skip_dirs=DEV_SKIP_DIRS) if dev else copy_tree(source, staging)
        require_served_contract(staging)
        (staging / SIDECAR_NAME).unlink(missing_ok=True)
        files.pop(SIDECAR_NAME, None)
        manifest = as_local(load_sidecar_manifest(staging, name, allow_local=True))
    except SidecarManifestError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise SideloadRefused("manifest_invalid", str(exc), 422) from exc
    except (SideloadRefused, OSError):
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging, files, manifest


def unchanged(state_dir: Path, name: str, digest: str) -> bool:
    return items(state_dir).get(name, {}).get("digest") == digest and code_root_of(state_dir, name).is_dir()


def touch(state_dir: Path, name: str, source: Path, now: Optional[Callable[[], float]] = None) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        item = doc.setdefault("items", {}).get(name)
        if isinstance(item, dict) and isinstance(item.get("sideload_record"), dict):
            item["sideload_record"]["synced_at"] = (now or wall)()
            item["sideload_record"]["source"] = str(source)
            item["source_path"] = str(source)
            _save(state_dir, doc)


def install_staged(
    state_dir: Path,
    name: str,
    staging: Path,
    files: Dict[str, str],
    digest: str,
    source: Path,
    now: Optional[Callable[[], float]] = None,
) -> List[str]:
    root = code_root_of(state_dir, name)
    old = code_root_of(state_dir, f".sideload-old-{name}-{os.getpid()}-{secrets.token_hex(4)}")
    if os.path.lexists(root):
        contained(root, root.parent)
    with registry_store.locked(state_dir, _lock, _busy):
        doc = _doc_for_update(state_dir)
        items_map = doc.setdefault("items", {})
        item = items_map.get(name)
        previous = item.get("sideload_record") if isinstance(item, dict) else None
        changed = changed_files(previous.get("files", {}) if isinstance(previous, dict) else {}, files)
        if root.exists():
            os.replace(root, old)
        os.replace(staging, root)
        shutil.rmtree(old, ignore_errors=True)
        if not isinstance(item, dict):
            item = {"kind": registry_store.KIND_PLUGIN, "source": registry_store.SOURCE_FOLDER, "unstored": True}
            items_map[name] = item
        item["source_path"] = str(source)
        item["sideload_record"] = {
            "files": files,
            "digest": digest,
            "changed": changed,
            "source": str(source),
            "synced_at": (now or wall)(),
        }
        _save(state_dir, doc)
    return changed
