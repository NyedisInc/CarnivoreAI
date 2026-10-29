
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from src.core.skills import kinds
from src.core.skills.consent_via_ddl import CONSENT_ONE_CLICK
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.cplugs.host import catalog_move, state as owner_state
from src.cplugs.host.adoption import BUILTIN_SOURCE, NAME_PREFIX
from src.cplugs.host.sidecar_manifest import load_sidecar_manifest

PACKAGE = Path(__file__).resolve().parents[3] / "packages" / "cplugs" / "mcphealth"


class _Ledger:

    def __init__(self, rows):
        self.rows = {r.name: r for r in rows}

    def find_by_name(self, name, scope, project_path):
        assert (scope, project_path) == (SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
        return self.rows.get(name)

    def delete(self, install_id):
        gone = [n for n, r in self.rows.items() if r.install_id == install_id]
        for n in gone:
            del self.rows[n]
        return bool(gone)


def _row(plugin_id, publisher="nyedis", source=BUILTIN_SOURCE, kind=kinds.KIND_CPLUG):
    return InstalledItem(
        install_id=f"i_{plugin_id}", item_id=f"{publisher}/{plugin_id}", kind=kind, publisher=publisher, name=f"{NAME_PREFIX}{plugin_id}",
        version="1.0.0", digest="builtin:1", scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH, auto_update=False, source_index_url=source,
        consented_digest=None, consented_body_sha=None, publisher_key_id=source, revision=1, installed_at="t", updated_at="t",
        consent_via=CONSENT_ONE_CLICK)


def _services(ledger):
    @contextmanager
    def open_ledger():
        yield ledger

    return SimpleNamespace(catalog=SimpleNamespace(ledger=open_ledger))


def _seed_state(state_dir, enabled, grants=("notify",)):
    path = owner_state.state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "cplugs": {"mcphealth": {
        "enabled": enabled, "grants": list(grants), "settings": {"warnMode": "allow", "servers": "linear", "notify": True},
        "revision": 3, "digest": ""}}}))


def test_an_owner_who_had_it_on_keeps_settings_loses_consent_and_gets_one_alert(tmp_path):
    _seed_state(tmp_path, True)
    ledger, alerts = _Ledger([_row("mcphealth"), _row("save")]), []
    done = catalog_move.migrate(_services(ledger), tmp_path, lambda key, **kw: alerts.append((key, kw)) or {"id": 1})
    assert done == ["mcphealth"] and set(ledger.rows) == {"cplug-save"}
    entry = owner_state.stored_entry(tmp_path, "mcphealth")
    assert entry["enabled"] is True and entry["grants"] == [] and entry["digest"] == ""
    assert entry["settings"] == {"warnMode": "allow", "servers": "linear", "notify": True} and entry["revision"] == 4
    manifest = load_sidecar_manifest(PACKAGE, "mcphealth")
    now = owner_state.get(tmp_path, manifest)
    assert now.enabled is True and now.grants == () and now.settings["servers"] == "linear"
    assert [p for p in manifest.permissions if p not in now.grants] == list(manifest.permissions)
    assert len(alerts) == 1 and alerts[0][0] == "cplug.mcphealth.moved_to_catalog"
    assert alerts[0][1]["actions"][0]["href"] == "#warez/carnivore/mcphealth" and alerts[0][1]["title_key"] == "app_alert.cplug_moved.title"
    assert catalog_move.migrate(_services(ledger), tmp_path, lambda *a, **k: alerts.append(a)) == [] and len(alerts) == 1


def test_an_owner_who_had_it_off_gets_no_alert_but_the_row_still_goes(tmp_path):
    _seed_state(tmp_path, False, grants=())
    ledger, alerts = _Ledger([_row("mcphealth", publisher="carnivore")]), []
    assert catalog_move.migrate(_services(ledger), tmp_path, lambda *a, **k: alerts.append(a)) == ["mcphealth"]
    assert ledger.rows == {} and alerts == []
    assert owner_state.stored_entry(tmp_path, "mcphealth")["settings"]["servers"] == "linear"


def test_a_catalog_row_or_no_row_is_never_touched(tmp_path):
    _seed_state(tmp_path, True)
    alerts = []
    for rows in ([], [_row("mcphealth", publisher="carnivore", source="https://catalog.example/v1/index.json")]):
        ledger = _Ledger(rows)
        assert catalog_move.migrate(_services(ledger), tmp_path, lambda *a, **k: alerts.append(a)) == []
        assert set(ledger.rows) == {r.name for r in rows}
    assert alerts == [] and owner_state.stored_entry(tmp_path, "mcphealth")["grants"] == ["notify"]


def test_an_alert_that_was_not_stored_keeps_the_row_for_the_next_boot(tmp_path):
    _seed_state(tmp_path, True)
    ledger = _Ledger([_row("mcphealth")])
    assert catalog_move.migrate(_services(ledger), tmp_path, lambda *a, **k: None) == [] and "cplug-mcphealth" in ledger.rows
    assert owner_state.stored_entry(tmp_path, "mcphealth")["grants"] == ["notify"]
