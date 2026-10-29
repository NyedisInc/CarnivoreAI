
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from src.cplugs.host.permission_renames import current_names
from src.cplugs.sdk.manifest import Manifest
from src.cplugs.sdk.permission_registry import DEFAULT_GRANTED, FIRST_PARTY_TIERS, PLATFORM_GRANTED
from src.cplugs.host import developer_mode
from src.core.json_artifact import atomic_write_json

logger = structlog.get_logger()

STATE_DIR_NAME = "cplugs"
STATE_FILE = "state.json"
STATE_VERSION = 1

_lock = threading.RLock()


class StaleRevision(Exception):

    def __init__(self, current: "CplugState") -> None:
        super().__init__(f"revision is {current.revision}")
        self.current = current


class StateWriteFailed(OSError):
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

    def as_wire(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "grants": {"app": list(self.grants)}, "settings": dict(self.settings),
                "revision": self.revision, "digest": self.digest}


def state_path(state_dir: Path) -> Path:
    return Path(state_dir) / STATE_DIR_NAME / STATE_FILE


def default_state(manifest: Manifest) -> CplugState:
    asked = tuple(manifest.permissions)
    if manifest.tier not in FIRST_PARTY_TIERS:
        return CplugState(manifest.id, enabled=False, grants=())
    if manifest.tier == "core" or manifest.default_enabled is True:
        return CplugState(manifest.id, enabled=True, grants=asked)
    if manifest.default_enabled is False:
        return CplugState(manifest.id, enabled=False, grants=())
    if set(asked) <= DEFAULT_GRANTED:
        return CplugState(manifest.id, enabled=True, grants=asked)
    return CplugState(manifest.id, enabled=False, grants=())


_file_cache: Dict[str, Tuple[int, int, int, Dict[str, Any]]] = {}


def _load(state_dir: Path) -> Optional[Dict[str, Any]]:
    path = state_path(state_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _file_cache.pop(key, None)
        return {}
    except OSError as exc:
        logger.warning("cplug_host_state_unreadable", error_type=type(exc).__name__)
        return None
    signature = (info.st_ino, info.st_mtime_ns, info.st_size)
    cached = _file_cache.get(key)
    if cached is not None and cached[:3] == signature:
        return cached[3]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("cplug_host_state_unreadable", error_type=type(exc).__name__)
        return None
    cplugs = data.get("cplugs") if isinstance(data, dict) else None
    cplugs = cplugs if isinstance(cplugs, dict) else {}
    _file_cache[key] = (*signature, cplugs)
    return cplugs


def _read_file(state_dir: Path) -> Dict[str, Any]:
    loaded = _load(state_dir)
    return {} if loaded is None else loaded


def _from_entry(manifest: Manifest, entry: Dict[str, Any]) -> CplugState:
    grants = entry.get("grants") if isinstance(entry.get("grants"), list) else []
    grants = [*grants, *(p for p in manifest.permissions if p in PLATFORM_GRANTED and p not in grants)]
    settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
    revision = entry.get("revision")
    return CplugState(manifest.id, enabled=entry.get("enabled") is True,
                      grants=tuple(g for g in current_names(g for g in grants if isinstance(g, str)) if g in manifest.permissions), settings=dict(settings),
                      revision=revision if isinstance(revision, int) and revision >= 0 else 0, stored=True,
                      digest=entry["digest"] if isinstance(entry.get("digest"), str) else "")


_core_off_logged: set = set()


def get(state_dir: Path, manifest: Manifest) -> CplugState:
    state = _stored_or_default(state_dir, manifest)
    if manifest.tier == "dev" and state.enabled and not developer_mode.is_on():
        return replace(state, enabled=False)
    return state


def _stored_or_default(state_dir: Path, manifest: Manifest) -> CplugState:
    entry = _read_file(state_dir).get(manifest.id)
    if not isinstance(entry, dict):
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


def stored_ids(state_dir: Path) -> Tuple[str, ...]:
    return tuple(sorted(_read_file(state_dir)))


def update(state_dir: Path, manifest: Manifest, expected_revision: Optional[int],
           mutate: Callable[[CplugState], CplugState]) -> CplugState:
    path = state_path(state_dir)
    with _lock:
        current = get(state_dir, manifest)
        if expected_revision is not None and expected_revision != current.revision:
            raise StaleRevision(current)
        changed = replace(mutate(current), revision=current.revision + 1, stored=True)
        cplugs = dict(_read_file(state_dir))
        cplugs[manifest.id] = {"enabled": changed.enabled, "grants": list(changed.grants),
                               "settings": changed.settings, "revision": changed.revision, "digest": changed.digest,
                               "updated_at": time.time()}
        _file_cache.pop(str(path), None)
        if not atomic_write_json(path, {"version": STATE_VERSION, "cplugs": cplugs}, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        _file_cache.pop(str(path), None)
        return changed


def strip_consent(state_dir: Path, cplug_id: str) -> bool:
    path = state_path(state_dir)
    with _lock:
        cplugs = dict(_read_file(state_dir))
        entry = cplugs.get(cplug_id)
        if not isinstance(entry, dict) or (not entry.get("grants") and not entry.get("digest")):
            return False
        cplugs[cplug_id] = {**entry, "grants": [], "digest": "", "revision": int(entry.get("revision") or 0) + 1, "updated_at": time.time()}
        _file_cache.pop(str(path), None)
        if not atomic_write_json(path, {"version": STATE_VERSION, "cplugs": cplugs}, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        _file_cache.pop(str(path), None)
        return True


def forget(state_dir: Path, cplug_id: str) -> bool:
    path = state_path(state_dir)
    with _lock:
        cplugs = dict(_read_file(state_dir))
        if cplugs.pop(cplug_id, None) is None:
            return False
        _file_cache.pop(str(path), None)
        if not atomic_write_json(path, {"version": STATE_VERSION, "cplugs": cplugs}, log_event="cplug_host_state_write_failed"):
            raise StateWriteFailed(str(path))
        _file_cache.pop(str(path), None)
        return True
