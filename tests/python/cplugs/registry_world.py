
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.cplugs.host import registry_files

UUID_CLOCK = "0123456789abcdef0123456789abcdef"
UUID_MINE = "fedcba9876543210fedcba9876543210"
UUID_OLD = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
UUID_ORPHAN = "dddddddddddddddddddddddddddddddd"

JOE_STATE: Dict[str, Any] = {
    "huddle": {"enabled": True, "grants": ["net.loopback", "files.read"], "revision": 12, "digest": None, "updated_at": 1762646400.0,
               "settings": {"accordion": True, "density": "compact", "hideCompleted": False, "nudgeEnabled": True, "showEmptyGroups": False, "view": "list"}},
    "save": {"enabled": True, "grants": ["files.read"], "revision": 4, "digest": None, "updated_at": 1.0,
             "settings": {"offloadEnabled": True, "vaultLocation": "/Volumes/Backup/vault"}},
    "reviewboard": {"enabled": True, "grants": [], "revision": 9, "digest": None, "updated_at": 2.0,
                    "settings": {"bindAddress": "127.0.0.1", "boardsRoot": "/Volumes/Backup/boards", "hostnames": ["boards.example"], "port": 8150,
                                 "publicLinksEnabled": False, "trustedProxies": ["192.0.2.11"]}},
    "publicboard": {"enabled": False, "grants": [], "revision": 2, "digest": None, "updated_at": 3.0, "settings": {"bind": "0.0.0.0", "port": 8160}},
    "devwidgetlab": {"enabled": True, "grants": [], "revision": 1, "digest": None, "updated_at": 4.0, "settings": {"sourceFolder": "/Users/me/lab"}},
    "flow": {"enabled": True, "grants": [], "revision": 3, "digest": None, "updated_at": 5.0, "settings": {"showTab": True}},
    "xtalk": {"enabled": False, "grants": [], "revision": 1, "digest": None, "updated_at": 6.0, "settings": {"keepCards": 25}},
}
SECOND_STATE: Dict[str, Any] = {
    "huddle": {"enabled": False, "grants": [], "revision": 1, "digest": None, "updated_at": 1.0, "settings": {}},
    "swarm": {"enabled": True, "grants": ["swarm"], "revision": 7, "digest": None, "updated_at": 9.5, "settings": {"mode": "alpha"}},
}


def put_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def ledger_item(item_id: str, *, source: str, digest: str = "d1", consented: Optional[str] = "d1", key: str = "KEYOK") -> InstalledItem:
    publisher, _, name = item_id.partition("/")
    return InstalledItem(install_id=f"inst-{publisher}-{name}", item_id=item_id, kind=kinds.KIND_CPLUG, publisher=publisher, name=f"cplug-{publisher}-{name}", version="1.2.0",
                         digest=digest, scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH, auto_update=False, source_index_url=source, consented_digest=consented,
                         consented_body_sha=None, publisher_key_id=key, revision=3, installed_at="2026-11-01T00:00:00Z", updated_at="2026-11-02T00:00:00Z",
                         consent_via="sheet")


def code_folder(folder: Path, name: str, body: str = "print('tick')\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cplug.json").write_text(json.dumps({"schema": 1, "id": name, "name": name, "version": "1.0.0", "entry": "main.py"}))
    (folder / "main.py").write_text(body)
    return folder


def insert_ledger(state: Path, items: List[InstalledItem]) -> None:
    conn = connect(db_path_for(state), create=False)
    try:
        for item in items:
            InstallLedger(conn).insert(item, ())
    finally:
        conn.close()


def support(tmp_path: Path, shape: str = "joe", *, with_installs: bool = True) -> SimpleNamespace:
    state = tmp_path / "support"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    cplugs = state / "cplugs"
    docs: Dict[str, Dict[str, Any]] = {n: {} for n in registry_files.LEGACY_FILES}
    out = SimpleNamespace(state=state, docs=docs, code={}, data={}, source=tmp_path / "src-myclock")
    if shape == "empty":
        return out
    docs["state"] = {"version": 1, "cplugs": dict(JOE_STATE if shape == "joe" else SECOND_STATE)}
    docs["third_party"] = {"enabled": shape == "joe"}
    if with_installs and shape == "joe":
        _add_installs(out)
    for name, doc in docs.items():
        if doc:
            put_json(cplugs / registry_files.LEGACY_FILES[name], doc)
    return out


def _add_installs(out: SimpleNamespace) -> None:
    state, docs = out.state, out.docs
    docs["state"]["cplugs"].update({
        "clock": {"enabled": True, "grants": ["net.fetch"], "settings": {"tz": "UTC"}, "revision": 3, "digest": "sha256:old-approval", "updated_at": 7.0},
        "oldtool": {"enabled": False, "grants": ["net.fetch"], "settings": {"a": 1}, "revision": 2, "digest": "sha256:bb", "updated_at": 8.0}})
    docs["installs"] = {"version": 1, "installs": {
        "clock": {"uuid": UUID_CLOCK, "catalog_id": "acme/clock", "publisher_key_id": "KEYOK"},
        "myclock": {"uuid": UUID_MINE, "catalog_id": "local/myclock", "source": str(out.source)},
        "oldtool": {"uuid": UUID_OLD, "catalog_id": "acme/oldtool", "publisher_key_id": "KEYOK",
                    "removed": {"at": "2026-11-09T00:00:00Z", "version": "0.9.1", "publisher_key_id": "KEYOK"}}}}
    docs["sideload"] = {"enabled_at": 1762646400.0, "hours": 24, "expires_at": 1762732800.0,
                        "items": {"myclock": {"files": {"main.py": "h"}, "digest": "sha256:cc", "changed": [], "source": str(out.source), "synced_at": 5.5}}}
    for name in ("clock", "myclock"):
        out.code[name] = code_folder(state / "cplug-code" / name, name)
    out.source.mkdir()
    for uuid in (UUID_CLOCK, UUID_MINE, UUID_OLD, UUID_ORPHAN):
        folder = state / "cplugs" / uuid
        (folder / "files").mkdir(parents=True)
        (folder / "files" / "note.txt").write_text(f"data of {uuid[:4]}")
        out.data[uuid] = folder
    insert_ledger(state, [ledger_item("acme/clock", source="https://catalog.test/index.json"), ledger_item("local/myclock", source="sideload", key="sideload")])
    out.uuids = {"clock": UUID_CLOCK, "myclock": UUID_MINE, "oldtool": UUID_OLD, "orphan": UUID_ORPHAN}


def files_bytes(state: Path) -> Dict[str, bytes]:
    return {p.relative_to(state).as_posix(): p.read_bytes() for p in sorted(state.rglob("*"))
            if p.is_file() and not p.name.startswith("carnivore.db") and p.name != ".plugins.lock"}
