
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.host.activity_log import ActivityLog
from src.cplugs.host.egress_log import EgressLog
from src.cplugs.host import identity, net_routes, runtime, sidecar_registry
from src.cplugs.host import state as owner_state
from src.cplugs.host.secret_store import SecretStore, network_key
from src.cplugs.host.sidecar_manifest import SidecarManifestError, parse_sidecar_manifest
from src.cplugs.host.sidecar_registry import SidecarRegistry

SHIPPED = {"huddle"}
ITEM = "acme/clock"
MANIFEST = {
    "schema": 1, "id": "clock", "name": "Clo‮ck\n", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
    "default_enabled": True, "permissions": {"app": ["notify", "network_hosts:api.example.com"]},
    "tools": [{"name": "clock_now", "description": "The time.", "gate": "read"}],
    "network_hosts": [{"host": "api.example.com", "reason": "time source", "methods": ["GET"],
                       "auth": {"secret": "token", "header": "Authorization", "scheme": "Bearer"}}],
    "secrets": [{"name": "token", "label": "API token", "help": "From the provider dashboard."}],
}


class FakeKeychain:

    def __init__(self) -> None:
        self.items = {}

    def read(self, service, account):
        return self.items.get((service, account))

    def write(self, service, account, secret):
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


def _install_code(state: Path, name: str = "clock", raw=None) -> Path:
    root = state / "cplug-code" / name
    root.mkdir(parents=True)
    (root / "cplug.json").write_text(json.dumps(raw or MANIFEST), encoding="utf-8")
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return root


def _row(item_id: str, source: str = "https://index.example/v1", kind: str = "cplug"):
    return SimpleNamespace(item_id=item_id, kind=kind, source_index_url=source, publisher_key_id="K")


@pytest.fixture
def state(tmp_path):
    yield tmp_path
    sidecar_registry.install(None)


def _manifest(digest: str = "d" * 64):
    return parse_sidecar_manifest(MANIFEST, "clock", digest)


def test_reinstall_after_purge_is_a_new_identity_and_cannot_read_the_old_secret(state):
    keychain = FakeKeychain()
    store = SecretStore(state, keychain=keychain)
    first = identity.register_install(state, "clock", ITEM, SHIPPED)
    key1 = network_key("clock", state)
    assert key1 == first.uuid != "clock"
    store.set(key1, _manifest(), "token", "abc123")
    assert store.value_for(key1, _manifest(), "token", "api.example.com") == "abc123"

    identity.release_install(state, "clock")
    second = identity.register_install(state, "clock", ITEM, SHIPPED)
    key2 = network_key("clock", state)

    assert second.uuid != first.uuid and key2 == second.uuid != key1
    assert identity.data_dir(state, key1) != identity.data_dir(state, key2)
    assert store.value_for(key2, _manifest(), "token", "api.example.com") is None
    assert store.status(key2, _manifest(), "token") == {"secret_present": False, "needs_reentry": False}
    net_routes.purge_network_data(state, "clock")
    assert store.value_for(key1, _manifest(), "token", "api.example.com") == "abc123"


def test_a_catalog_tier_manifest_starts_off_with_no_grants_and_a_builtin_one_is_unchanged(state):
    catalog = _manifest()
    assert catalog.tier == "catalog" and catalog.permissions == ("notify", "network_hosts:api.example.com")
    asking_notify = dataclasses.replace(catalog, permissions=("notify",), network=type(catalog.network)())
    for declared in (None, True, False):
        got = owner_state.default_state(dataclasses.replace(asking_notify, default_enabled=declared))
        assert (got.enabled, got.grants) == (False, ())
    builtin = dataclasses.replace(runtime.find("unread").manifest, permissions=("notify",), default_enabled=None)
    control = owner_state.default_state(builtin)
    assert (control.enabled, control.grants) == (True, ("notify",))
    assert owner_state.get(state, catalog).enabled is False


def test_the_registry_loads_only_held_non_builtin_cplug_rows_and_runtime_falls_through_to_it(state):
    record = identity.register_install(state, "clock", ITEM, SHIPPED)
    _install_code(state)
    _install_code(state, "orphan", {**MANIFEST, "id": "orphan"})
    rows = [_row(ITEM), _row("nyedis/huddle", source="builtin"), _row("acme/orphan"), _row("acme/theme", kind="theme")]
    registry = SidecarRegistry(state, lambda: rows)
    assert registry.reload() == 1
    sidecar_registry.install(registry)
    before = runtime.definitions()

    found = runtime.find("clock")
    assert found is registry.find("clock") and found.install_key == record.uuid
    assert found.folder == identity.data_dir(state, record.uuid) == registry.folder("clock")
    assert registry.code_root("clock") == state / "cplug-code" / "clock" and found.manifest.code_digest
    assert runtime.find("huddle") is not found and runtime.find("huddle").id == "huddle"
    assert runtime.find("orphan") is None and runtime.definitions() is before and "clock" not in {d.id for d in before}
    assert found in runtime.listed() and [d.id for d in runtime.listed()][-1] == "clock"

    host = runtime.Host(state)
    assert host.folder("clock") == found.folder and host.enabled("clock") is False and host.state("clock").grants == ()
    assert host.install_key("clock") == record.uuid and host.install_key("huddle") == "huddle"
    assert registry.unload("clock") and runtime.find("clock") is None


def test_a_catalog_manifest_is_data(state):
    parsed = parse_sidecar_manifest(MANIFEST, "clock", "d" * 64)
    assert parsed.name == "Clock" and parsed.default_enabled is False and parsed.tier == "catalog"
    assert parsed.tools[0]["gate"] == "read"
    bad = [
        ({**MANIFEST, "id": "other"}, "id"),
        ({**MANIFEST, "tools": [{"name": "clock_now", "description": "x", "gate": "open"}]}, "gate"),
        ({**MANIFEST, "entry": "../main.py"}, "entry"),
        ({**MANIFEST, "permissions": {"app": ["swarm"]}}, "permission"),
        ({**MANIFEST, "name_key": "cplug.clock.name"}, "keys"),
    ]
    for raw, _why in bad:
        with pytest.raises(SidecarManifestError):
            parse_sidecar_manifest(raw, "clock", "d" * 64)


def test_the_owner_may_take_a_reserved_first_party_name_and_nobody_else_may(state):
    assert identity.register_install(state, "huddle", "carnivore/huddle", SHIPPED).catalog_id == "carnivore/huddle"
    with pytest.raises(identity.InstallRefused) as other:
        identity.register_install(state, "unread", "acme/unread", SHIPPED)
    assert other.value.code == "name_reserved"
    with pytest.raises(identity.InstallRefused) as host_word:
        identity.register_install(state, "state", "carnivore/state", SHIPPED)
    assert host_word.value.code == "name_reserved"


def _log_rows(state: Path, key: str) -> None:
    EgressLog(state).record(key, host="api.example.com", method="GET", permission="network_hosts:api.example.com", status=200,
                           bytes_out=0, bytes_in=0, ms=1, outcome="ok")
    ActivityLog(state).record(key, method="ping", permission="notify", target="t")


def _rows(state: Path, key: str) -> int:
    return len(EgressLog(state).recent(key)) + len(ActivityLog(state).recent(key))


def test_purge_forgets_the_egress_and_activity_rows_and_the_state_entry_of_the_right_key(state):
    record = identity.register_install(state, "clock", ITEM, SHIPPED)
    identity.register_install(state, "huddle", "carnivore/huddle", SHIPPED)
    _install_code(state)
    registry = SidecarRegistry(state, lambda: [_row(ITEM)])
    assert registry.reload() == 1
    sidecar_registry.install(registry)
    for key in (record.uuid, "clock", "huddle", "other"):
        _log_rows(state, key)
        assert _rows(state, key) == 2

    net_routes.purge_network_data(state, "huddle")
    assert _rows(state, "huddle") == 0 and _rows(state, record.uuid) == 2
    net_routes.purge_network_data(state, "clock")
    assert _rows(state, record.uuid) == 0 and _rows(state, "clock") == 2 and _rows(state, "other") == 2

    manifest = registry.find("clock").manifest
    owner_state.update(state, manifest, None, lambda s: dataclasses.replace(s, enabled=True, grants=("notify",)))
    assert owner_state.get(state, manifest).enabled is True
    assert owner_state.forget(state, "clock") is True
    assert (owner_state.get(state, manifest).enabled, owner_state.get(state, manifest).grants) == (False, ())


def test_a_tool_may_not_carry_control_or_invisible_characters(state):
    base = MANIFEST["tools"][0]
    for tool in ({**base, "description": "ok‮ evil"}, {**base, "description": "a​b"}, {**base, "description": "a\x07b"},
                 {**base, "inputSchema": {"type": "object", "description": "x⁦y"}}):
        with pytest.raises(SidecarManifestError):
            parse_sidecar_manifest({**MANIFEST, "tools": [tool]}, "clock", "d" * 64)
    fine = {**base, "description": "two lines\nand a tab\there"}
    assert parse_sidecar_manifest({**MANIFEST, "tools": [fine]}, "clock", "d" * 64).tools[0] == fine
