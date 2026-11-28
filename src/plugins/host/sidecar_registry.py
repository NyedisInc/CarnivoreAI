
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

import structlog

from src.core.plugin_registry import plugin_layout
from src.core.skills import kinds
from src.plugins.host import identity, sideload
from src.plugins.host.plugin_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest
from src.plugins.sdk.permission_registry import TIER_CATALOG

logger = structlog.get_logger()

_BUILTIN_SOURCE = "builtin"


@dataclass(frozen=True)
class SidecarDefinition:

    manifest: SidecarManifest
    item_id: str
    install_key: str
    code_root: Path
    folder: Path
    publisher_key_id: str = ""
    router: Any = None
    tools: Mapping[str, Any] = field(default_factory=dict)
    storage: Any = None
    on_start: Any = None
    on_stop: Any = None
    on_settings: Any = None
    settings_check: Any = None

    @property
    def id(self) -> str:
        return self.manifest.id


class SidecarRegistry:

    def __init__(self, state_dir: Path, rows: Callable[[], Iterable[Any]]) -> None:
        self.state_dir = Path(state_dir)
        self._rows = rows
        self._lock = threading.RLock()
        self._entries: Dict[str, SidecarDefinition] = {}

    def code_root_of(self, name: str) -> Path:
        return plugin_layout.code_root(self.state_dir, name)

    def _load_one(self, row: Any) -> Optional[SidecarDefinition]:
        _, _, name = row.item_id.partition("/")
        try:
            record = identity.lookup(self.state_dir, name)
        except identity.LedgerUnreadable:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="install_ledger_unreadable")
            return None
        if record is None or record.catalog_id != row.item_id:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="no_install_record")
            return None
        root = self.code_root_of(name)
        try:
            sideload.contained(root, root.parent)
        except sideload.SideloadRefused:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="code_root_outside")
            return None
        local = sideload.is_local(row.item_id)
        github = identity.is_unverified_github(row.item_id)
        try:
            manifest = load_sidecar_manifest(root, name, allow_local=local or github)
        except SidecarManifestError as exc:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="manifest", detail=str(exc)[:200])
            return None
        if local:
            manifest = sideload.as_local(manifest)
        elif github:
            from dataclasses import replace  # noqa: PLC0415

            manifest = replace(manifest, tier=identity.TIER_UNVERIFIED_GITHUB, default_enabled=False)
        elif manifest.tier != TIER_CATALOG or manifest.default_enabled:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="invalid_tier")
            return None
        return SidecarDefinition(manifest, row.item_id, record.uuid, root, identity.data_dir(self.state_dir, record.uuid), str(row.publisher_key_id))

    def reload(self) -> int:
        found: Dict[str, SidecarDefinition] = {}
        for row in self._rows():
            if row.kind != kinds.KIND_CPLUG or row.source_index_url == _BUILTIN_SOURCE or "/" not in row.item_id:
                continue
            definition = self._load_one(row)
            if definition is not None:
                found[definition.id] = definition
        with self._lock:
            self._entries = found
        return len(found)

    def reload_one(self, item_id: str) -> Optional[SidecarDefinition]:
        _, _, name = item_id.partition("/")
        target_row = None
        for row in self._rows():
            if row.kind == kinds.KIND_CPLUG and row.source_index_url != _BUILTIN_SOURCE and row.item_id == item_id:
                target_row = row
                break
        if target_row is None:
            with self._lock:
                self._entries.pop(name, None)
            return None
        definition = self._load_one(target_row)
        with self._lock:
            if definition is None:
                self._entries.pop(name, None)
            else:
                self._entries[definition.id] = definition
        return definition

    def _visible(self, d: SidecarDefinition) -> bool:
        return not sideload.is_local(d.item_id) or sideload.allowed(self.state_dir)

    def find(self, name: str) -> Optional[SidecarDefinition]:
        with self._lock:
            found = self._entries.get(name)
        return found if found is not None and self._visible(found) else None

    def listed(self) -> Tuple[SidecarDefinition, ...]:
        with self._lock:
            found = tuple(self._entries[n] for n in sorted(self._entries))
        return tuple(d for d in found if self._visible(d))

    def folder(self, name: str) -> Optional[Path]:
        d = self.find(name)
        return d.folder if d else None

    def code_root(self, name: str) -> Optional[Path]:
        d = self.find(name)
        return d.code_root if d else None

    def unload(self, name: str) -> bool:
        with self._lock:
            return self._entries.pop(name, None) is not None


_registry: Optional[SidecarRegistry] = None


_install_listeners: list = []


def on_install(listener: Callable[[], None]) -> None:
    _install_listeners.append(listener)


def install(registry: Optional[SidecarRegistry]) -> None:
    global _registry
    _registry = registry
    for listener in list(_install_listeners):
        listener()


def current() -> Optional[SidecarRegistry]:
    return _registry


def find(name: str) -> Optional[SidecarDefinition]:
    return _registry.find(name) if _registry is not None else None


def listed() -> Tuple[SidecarDefinition, ...]:
    return _registry.listed() if _registry is not None else ()


def folder(name: str) -> Optional[Path]:
    return _registry.folder(name) if _registry is not None else None


def code_root(name: str) -> Optional[Path]:
    return _registry.code_root(name) if _registry is not None else None


def unload(name: str) -> bool:
    return _registry.unload(name) if _registry is not None else False
