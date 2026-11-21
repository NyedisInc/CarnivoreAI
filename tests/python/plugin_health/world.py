
from __future__ import annotations

import os
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, HARNESS_CLAUDE, SCOPE_GLOBAL, InstalledItem, InstallTarget
from src.plugins.host import identity, runtime, sidecar_boot, sidecar_registry, sideload
from src.plugins.host import state as owner_state

STAMP = "2026-11-09T00:00:00Z"
FAR_FUTURE = "2099-01-01T00:00:00Z"


def manifest_json(name: str, *, trust: bool = False) -> Dict[str, Any]:
    raw: Dict[str, Any] = {"schema": 1, "id": name, "name": name.title(), "description": "A test plugin.", "version": "1.0.0", "entry": "main.py",
                           "tools": [], "permissions": {"app": ["notify"]}}
    if trust:
        raw["trust"] = "unrestricted"
    return raw


def write_code(folder: Path, name: str, *, trust: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cplug.json").write_text(json.dumps(manifest_json(name, trust=trust)))
    (folder / "main.py").write_text("print('tick')\n")
    return folder


class World(SimpleNamespace):

    def add_ledger(self, item: InstalledItem, targets: tuple = ()) -> None:
        conn = connect(db_path_for(self.state), create=False)
        try:
            InstallLedger(conn).insert(item, targets)
        finally:
            conn.close()

    def item(self, item_id: str, *, kind: str = kinds.KIND_CPLUG, source: str = "https://catalog.test/index.json", key: str = "KEYOK",
             digest: str = "d", consented: Optional[str] = None, version: str = "1.0.0") -> InstalledItem:
        publisher, _, name = item_id.partition("/")
        return InstalledItem(install_id=f"inst-{publisher}-{name}", item_id=item_id, kind=kind, publisher=publisher, name=f"{kind}-{publisher}-{name}",
                             version=version, digest=digest, scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH, auto_update=False,
                             source_index_url=source, consented_digest=consented, consented_body_sha=None, publisher_key_id=key, revision=1,
                             installed_at=STAMP, updated_at=STAMP, consent_via="sheet")

    def install_catalog(self, item_id: str, *, trust: bool = False, enabled: Optional[bool] = None, local_source: Optional[Path] = None) -> Path:
        publisher, _, name = item_id.partition("/")
        code = write_code(self.state / "plugins" / name, name, trust=trust)
        local = publisher == sideload.LOCAL_PUBLISHER
        identity.register_install(self.state, name, item_id, frozenset(d.id for d in runtime.definitions()), sideload=local,
                                  source=os.path.realpath(local_source or code) if local else "", publisher_key_id="" if local else "KEYOK")
        self.add_ledger(self.item(item_id, source="sideload" if local else "https://catalog.test/index.json", key="sideload" if local else "KEYOK"))
        if local:
            self.remember_sideload(name, local_source or code)
        if enabled is not None:
            self.pending_state[name] = enabled
        return code

    def remember_sideload(self, name: str, source: Path) -> None:
        sideload.set_switch(self.state, True, hours=None)
        path = sideload.switch_path(self.state)
        data = json.loads(path.read_text())
        data.setdefault("items", {})[name] = {"files": {}, "digest": "x", "changed": [], "source": str(source), "synced_at": time.time()}
        path.write_text(json.dumps(data))

    def settle(self) -> None:
        self.rt.load_registry()
        for name, enabled in self.pending_state.items():
            d = sidecar_registry.find(name)
            owner_state.update(self.state, d.manifest, None, lambda s, d=d, enabled=enabled: replace(
                s, enabled=enabled, grants=("notify",), digest=d.manifest.code_digest))
        self.pending_state.clear()

    def set_index(self, index: Optional[dict]) -> None:
        asyncio.run(self.rt.supervisor.set_index(index))


class StubProcess:

    def __init__(self) -> None:
        self.stops: List[str] = []

    async def stop(self, reason: str) -> None:
        self.stops.append(reason)


def make_world(tmp_path: Path, *, real_host: bool = False) -> World:
    state = tmp_path / "support"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    host = runtime.Host(state)
    fake_host = SimpleNamespace(state_dir=state, publish=lambda topic: None, install_key=host.install_key)
    app = SimpleNamespace(state=SimpleNamespace())
    alerts: List[Any] = []
    rt = sidecar_boot.SidecarRuntime(host if real_host else fake_host, app, asyncio.new_event_loop(), env_safe=lambda: False, app_version="9.9.9",
                                     raise_alert=lambda key, **k: alerts.append((key, k)), resolve_alert=lambda key: None)
    rt.supervisor.set_safe_mode(False)
    host.app = SimpleNamespace(state=SimpleNamespace(sidecar_runtime=rt))
    return World(state=state, host=host, rt=rt, pending_state={}, alerts=alerts)
