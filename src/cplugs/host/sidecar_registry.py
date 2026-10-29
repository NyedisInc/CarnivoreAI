
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

import structlog

from src.core.live_install_roots import CPLUG_CODE_DIR_NAME
from src.core.skills import kinds
from src.cplugs.host import identity, sideload
from src.cplugs.host.sidecar_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest, with_sidecar_facts

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
        return self.state_dir / CPLUG_CODE_DIR_NAME / name

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
            manifest = with_sidecar_facts(load_sidecar_manifest(root, name), root)
        except SidecarManifestError as exc:
            logger.warning("cplug_sidecar_skipped", cplug=name, reason="manifest", detail=str(exc)[:200])
            return None
        if sideload.is_local(row.item_id):
            manifest = sideload.as_local(manifest)
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

    def _visible(self, d: SidecarDefinition) -> bool:
        return not sideload.is_local(d.item_id) or sideload.is_on(self.state_dir)

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


def install(registry: Optional[SidecarRegistry]) -> None:
    global _registry
    _registry = registry


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
