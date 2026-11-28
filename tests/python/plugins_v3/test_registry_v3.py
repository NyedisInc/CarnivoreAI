
from __future__ import annotations

import json
from pathlib import Path

from src.plugins.host import owner_switch, registry_boot, registry_store, state as owner_state


def test_fresh_boot_initializes_single_plugins_registry_json(tmp_path: Path) -> None:
    out = registry_boot.run(tmp_path, retired=lambda: None)
    assert out.action == registry_boot.A_NORMAL

    reg = registry_store.registry_path(tmp_path)
    assert reg == tmp_path / "plugins" / "registry.json"
    assert reg.exists()

    doc = json.loads(reg.read_text(encoding="utf-8"))
    assert doc["schema"] == 2
    assert doc["migration"]["version"] == 2
    assert doc["switches"]["third_party"] is False
    assert doc["switches"]["sideload"]["hours"] == 12
    assert doc["items"] == {}
    assert doc["tombstones"] == {}

    assert registry_store.lock_path(tmp_path) == tmp_path / ".plugins.lock"


def test_boot_normalizes_pre_v2_registry_json_to_v2(tmp_path: Path) -> None:
    reg = registry_store.registry_path(tmp_path)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        json.dumps(
            {
                "schema": 1,
                "generation": 4,
                "switches": {"third_party": True, "sideload": {"enabled_at": None, "hours": 12, "expires_at": None}},
                "items": {
                    "notes": {
                        "kind": "plugin",
                        "install_uuid": "u-notes-1",
                        "catalog_id": "acme/notes",
                        "enabled": True,
                        "grants": ["notify"],
                        "settings": {},
                        "revision": 2,
                    }
                },
                "tombstones": {},
            }
        ),
        encoding="utf-8",
    )

    out = registry_boot.run(tmp_path, retired=lambda: None)
    assert out.action == registry_boot.A_NORMAL
    doc = json.loads(reg.read_text(encoding="utf-8"))
    assert doc["schema"] == 2
    assert doc["migration"]["version"] == 2
    assert doc["generation"] == 5
    assert doc["items"]["notes"]["enabled"] is True
    assert doc["switches"]["third_party"] is True


def test_registry_writes_use_single_registry_json_without_legacy_files(tmp_path: Path) -> None:
    registry_boot.run(tmp_path, retired=lambda: None)
    legacy_state = tmp_path / "cplugs" / "state.json"

    registry_store.commit(
        tmp_path,
        lambda doc: doc["items"].__setitem__(
            "alpha",
            {"kind": "feature", "enabled": True, "grants": [], "settings": {}, "revision": 1},
        ),
    )
    owner_switch.write(tmp_path, True)

    assert registry_store.registry_path(tmp_path).exists()
    assert not legacy_state.exists(), "legacy 4-file writes must remain retired"
    doc, status = registry_store.load_registry(tmp_path)
    assert status == registry_store.STATUS_OK and doc is not None
    assert doc["items"]["alpha"]["enabled"] is True
    assert owner_state.stored_enabled(tmp_path, "alpha") is True
    assert owner_switch.read(tmp_path) is True
    assert registry_store.is_migrated(doc) is True
