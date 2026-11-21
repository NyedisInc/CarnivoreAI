
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.catalog import plugin_pack
from src.core.json_artifact import UnreadableArtifact
from src.core.plugin_registry import plugin_layout
from src.plugins.host.identity import LOCAL_PUBLISHER
from src.plugins.host import developer_mode, registry_files, registry_store
from src.plugins.host.sideload_copy import changed_files, copy_tree
from src.plugins.host.sideload_errors import SideloadRefused
from src.plugins.host.sidecar_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest
from src.plugins.runtime.integrity import SIDECAR_NAME
from src.plugins.sdk import api_contract

logger = structlog.get_logger()

FILE_NAME = registry_store.SIDELOAD_FILE
DURATION_HOURS = (1, 12, 24, 168)
DEFAULT_HOURS = 12
TTL_SECONDS = DEFAULT_HOURS * 60 * 60
TIER_LOCAL = "local"
API_VERSION_UNSUPPORTED = "api_version_unsupported"

_lock = threading.RLock()
_busy = partial(SideloadRefused, "registry_busy", status=503)
_snapshots: Dict[Path, Tuple[Tuple[int, int, int, int], Mapping[str, Any]]] = {}
_EMPTY: Mapping[str, Any] = MappingProxyType({})


def wall() -> float:
    return time.time()


def as_local(manifest: SidecarManifest) -> SidecarManifest:
    return replace(manifest, tier=TIER_LOCAL)


def is_local(item_id: str) -> bool:
    return item_id.partition("/")[0] == LOCAL_PUBLISHER


def switch_path(state_dir: Path) -> Path:
    return Path(state_dir) / "cplugs" / FILE_NAME


def contained(path: Path, root: Path) -> Path:
    real = Path(os.path.realpath(path))
    if not real.is_relative_to(Path(os.path.realpath(root))):
        raise SideloadRefused("source_outside_root", "the folder resolves outside the folder it must stay in", 422)
    return real


def code_root_of(state_dir: Path, name: str) -> Path:
    return plugin_layout.code_root(state_dir, name)


def _load(state_dir: Path) -> Optional[Dict[str, Any]]:
    views = registry_files.flipped_views(state_dir)
    if views is not None:
        return views["sideload"]
    try:
        data = json.loads(switch_path(state_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("cplug_sideload_unreadable", error_type=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else {}


def _read(state_dir: Path) -> Dict[str, Any]:
    try:
        return registry_store.read_store(state_dir, "sideload", log_event="cplug_sideload_unreadable")
    except UnreadableArtifact as exc:
        raise SideloadRefused("sideload_unreadable", f"the sideload record is unreadable and was left as it is: {exc}", 500) from exc


def _write(state_dir: Path, data: Dict[str, Any]) -> bool:
    try:
        return registry_store.write_document(state_dir, "sideload", data, log_event="cplug_sideload_write_failed")
    finally:
        _snapshots.pop(switch_path(state_dir), None)


def _save(state_dir: Path, data: Dict[str, Any]) -> None:
    if not _write(state_dir, data):
        raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def _snapshot(state_dir: Path) -> Mapping[str, Any]:
    if registry_files.flipped_views(state_dir) is not None:
        return MappingProxyType(_load(state_dir) or {})
    path = switch_path(state_dir)
    try:
        st = path.stat()
    except OSError:
        _snapshots.pop(path, None)
        return _EMPTY
    signature = (st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)
    cached = _snapshots.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]
    data = _load(state_dir)
    if data is None:
        _snapshots.pop(path, None)
        return _EMPTY
    view = MappingProxyType(data)
    _snapshots[path] = (signature, view)
    return view


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
        data = _read(state_dir)
        started = (now or wall)() if on else None
        data["enabled_at"] = started
        if on:
            data["hours"] = hours
            data["expires_at"] = None if hours is None else started + hours * 3600
        else:
            data["expires_at"] = None
        data.setdefault("items", {})
        return _write(state_dir, data)


def items(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = (_load(state_dir) or {}).get("items")
    return {n: v for n, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def forget(state_dir: Path, name: str) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        data = _read(state_dir)
        if isinstance(data.get("items"), dict) and data["items"].pop(name, None) is not None:
            _save(state_dir, data)


def installs(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = (_load(state_dir) or {}).get("installs")
    return {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def put_install(state_dir: Path, record: Dict[str, Any]) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        data = _read(state_dir)
        data.setdefault("items", {})
        data.setdefault("installs", {})[f"{record['kind']}/{record['name']}"] = record
        _save(state_dir, data)


def forget_install(state_dir: Path, kind: str, name: str) -> None:
    with registry_store.locked(state_dir, _lock, _busy):
        data = _read(state_dir)
        if isinstance(data.get("installs"), dict) and data["installs"].pop(f"{kind}/{name}", None) is not None:
            _save(state_dir, data)


def pack_authored_in_place(staging: Path, files: Dict[str, str]) -> None:
    side = staging / plugin_pack.CARNIVORE_FILE
    try:
        authored = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not plugin_pack.is_authored(authored):
        return
    try:
        present = {plugin_pack.CARNIVORE_FILE: side.read_bytes()}
        if plugin_pack.CPLUG_FILE in files:
            present[plugin_pack.CPLUG_FILE] = b""
        packed_files, _ = plugin_pack.pack_files(present)
    except plugin_pack.PackError as exc:
        raise SideloadRefused("manifest_invalid", str(exc), 422) from exc
    for name in (plugin_pack.CPLUG_FILE, plugin_pack.CARNIVORE_FILE):
        (staging / name).write_bytes(packed_files[name])
        os.chmod(staging / name, 0o644)
        files[name] = hashlib.sha256(packed_files[name]).hexdigest()


def require_served_contract(staging: Path) -> None:
    try:
        doc = json.loads((staging / plugin_pack.CARNIVORE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(doc, dict):
        return
    try:
        api_contract.require_served(doc)
    except api_contract.ApiVersionUnsupported as exc:
        raise SideloadRefused(API_VERSION_UNSUPPORTED, str(exc), 422) from exc


def stage(state_dir: Path, name: str, source: Path) -> "tuple[Path, Dict[str, str], SidecarManifest]":
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise SideloadRefused("source_missing", "give the absolute path of a folder (not a link)", 422)
    staging = code_root_of(state_dir, f".sideload-{name}-{os.getpid()}-{time.monotonic_ns()}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        files = copy_tree(source, staging)
        pack_authored_in_place(staging, files)
        require_served_contract(staging)
        (staging / SIDECAR_NAME).unlink(missing_ok=True)
        files.pop(SIDECAR_NAME, None)
        manifest = as_local(load_sidecar_manifest(staging, name))
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
        data = _read(state_dir)
        data["items"][name]["synced_at"] = (now or wall)()
        data["items"][name]["source"] = str(source)
        _save(state_dir, data)


def install_staged(state_dir: Path, name: str, staging: Path, files: Dict[str, str], digest: str, source: Path,
                   now: Optional[Callable[[], float]] = None) -> List[str]:
    root = code_root_of(state_dir, name)
    old = code_root_of(state_dir, f".sideload-old-{name}-{os.getpid()}")
    if os.path.lexists(root):
        contained(root, root.parent)
    with registry_store.locked(state_dir, _lock, _busy):
        data = _read(state_dir)
        data.setdefault("items", {})
        previous = data["items"].get(name)
        changed = changed_files(previous.get("files", {}) if isinstance(previous, dict) else {}, files)
        if root.exists():
            os.replace(root, old)
        os.replace(staging, root)
        shutil.rmtree(old, ignore_errors=True)
        data["items"][name] = {"files": files, "digest": digest, "changed": changed, "source": str(source), "synced_at": (now or wall)()}
        _save(state_dir, data)
    return changed
