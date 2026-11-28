
from __future__ import annotations

import copy
import fnmatch
import json
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.inventory.registry_side import EXCLUDED_STORES
from src.plugins.host import runtime
from src.plugins.sdk import data_decl
from src.plugins.sdk.manifest import ManifestError, load_manifest
from src.plugins.sdk.manifest_v2 import ManifestV2Error, load_manifest_v2
from src.plugins.sdk.schema_check import validate_document
from tests.python.cplugs.test_extension_schemas import good

ROOT = Path(__file__).resolve().parents[3]
PLUGINS = ROOT / "src" / "plugins"
SHIPPED = [d.id for d in runtime.definitions()]
POLICY = {"own": "carried", "share": "excluded", "reason": "the owner's own work"}
DB = {"id": "summaries", "kind": "db", "path": "ai_summaries.db", "scope_by": "session_uuid", "policy": POLICY, "secret_columns": []}
FOLDER = {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id", "policy": {**POLICY, "purge": "kept"}}


def entry(base: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    out = {**copy.deepcopy(base), **over}
    return {k: v for k, v in out.items() if v is not None}


def errors_for(*entries: Dict[str, Any]) -> List[str]:
    return validate_document(good("cplug", data=list(entries)))



def test_valid_blocks_pass() -> None:
    assert errors_for() == []
    assert errors_for(DB, FOLDER) == []
    assert errors_for(entry(FOLDER, sub="2026/boards")) == []
    assert errors_for(entry(DB, kind="file", path="notes.json", secret_columns=None)) == []
    assert errors_for(entry(DB, path="cplugs/x/y.db")) == []


def test_a_cplug_without_the_data_key_is_invalid_and_a_widget_may_omit_it() -> None:
    doc = good("cplug")
    del doc["data"]
    assert any("missing required property 'data'" in e for e in validate_document(doc))
    assert validate_document(good("widget")) == []
    assert validate_document(good("widget", data=[DB])) == []


@pytest.mark.parametrize("bad", [
    entry(DB, root_setting="boardsRoot"),
    entry(DB, path=None),
    entry(DB, path="/var/db/x.db"),
    entry(DB, path="../x.db"),
    entry(DB, path="a/../../x.db"),
    entry(DB, path=".."),
    entry(DB, path="a\\b.db"),
    entry(FOLDER, root_setting=None, path="d", sub="x"),
    entry(FOLDER, sub="/abs"),
    entry(FOLDER, sub="../up"),
    entry(FOLDER, secret_columns=["token"]),
    entry(DB, kind="file", secret_columns=["token"]),
    entry(DB, id="Bad-Id"), entry(DB, id="1x"), entry(DB, id=None),
    entry(DB, kind="table"), entry(DB, kind=None),
    entry(DB, scope_by="company"), entry(DB, scope_by=None),
    entry(DB, policy=None), entry(DB, extra=1),
    entry(DB, policy={**POLICY, "reason": ""}), entry(DB, policy={**POLICY, "reason": "   "}),
    entry(DB, policy={"own": "carried", "share": "excluded"}),
    entry(DB, policy={**POLICY, "own": "kept"}), entry(DB, policy={**POLICY, "share": "maybe"}),
    entry(DB, policy={**POLICY, "extra": 1}),
])
def test_each_shape_rule_refuses(bad: Dict[str, Any]) -> None:
    assert errors_for(bad), bad



def test_cross_field_rules_the_schema_cannot_say() -> None:
    fields = {"boardsRoot": {"kind": "string"}}
    assert data_decl.problems_in([FOLDER], fields) == []
    assert any("declared twice" in p for p in data_decl.problems_in([DB, DB], {}))
    assert any("not a setting this plugin declares" in p for p in data_decl.problems_in([FOLDER], {}))
    assert any("must be array" in p for p in data_decl.problems_in({"id": "x"}, {}))
    with pytest.raises(data_decl.DataDeclError):
        data_decl.parse_data([DB, DB], {})
    parsed = data_decl.parse_data([FOLDER, entry(DB, secret_columns=["token"])], fields)
    assert (parsed[0].root_setting, parsed[0].path, parsed[0].policy.own, parsed[0].full_id("reviewboard")) == ("boardsRoot", "", "carried", "reviewboard.boards")
    assert (parsed[1].path, parsed[1].secret_columns, parsed[1].scope_by) == ("ai_summaries.db", ("token",), "session_uuid")


def _plugin_copy(plugin_id: str, tmp_path: Path, data: Any = "keep") -> Path:
    folder = tmp_path / plugin_id
    folder.mkdir()
    doc: Dict[str, Any] = {
        "schema": 2,
        "id": plugin_id,
        "name": "share read only",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Share plugin.",
        "author": "Alex (example-owner)",
        "tier": "builtin",
        "default_enabled": True,
        "data": [] if data == "keep" else data,
    }
    if data == "drop":
        del doc["data"]
    (folder / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def test_the_loaded_manifest_carries_the_checked_block() -> None:
    crate = load_manifest(str(PLUGINS / "crate" / "__init__.py")).data
    assert crate is not None and {"bundles", "second_copies"} <= {d.id for d in crate}
    assert next(d for d in crate if d.id == "bundles").root_setting is not None
    assert load_manifest(str(PLUGINS / "share" / "__init__.py")).data == ()
    assert load_manifest(str(PLUGINS / "taskmanager" / "__init__.py")).data == ()


def test_a_broken_data_block_is_refused_by_v2_loader(tmp_path: Path) -> None:
    folder = _plugin_copy("share", tmp_path, data=[DB, DB])
    with pytest.raises(ManifestError, match="declared twice"):
        load_manifest(str(folder / "__init__.py"))


def test_the_v2_loader_reports_the_cross_field_problems(tmp_path: Path) -> None:
    folder = _plugin_copy("share", tmp_path, data=[FOLDER])
    with pytest.raises(ManifestV2Error, match="not a setting this plugin declares"):
        load_manifest_v2(folder, tier="builtin", allow_tier_override=True)


@pytest.mark.parametrize("plugin_id", SHIPPED)
def test_every_shipped_plugin_declares_its_data(plugin_id: str) -> None:
    doc = tomllib.loads((PLUGINS / plugin_id / "carnivore.toml").read_text(encoding="utf-8"))
    assert isinstance(doc.get("data"), list), "a plugin that keeps nothing says data: []"
    assert load_manifest(str(PLUGINS / plugin_id / "__init__.py")).data is not None



CORE_LEFTOVERS = {
    "cplugs/huddle/huddle.db": "the Task Manager's read-only leftover; huddle's sidecar is the split owner's",
    "cplugs/huddle/IMPORTED.json": "beside the huddle.db leftover",
    "addons/huddle/huddle.db": "the Task Manager's database before it moved to cplugs/huddle",
    "cplugs/mcpondemand/mcpondemand.db": "dormant leftover of the parked MCP on-demand surface B (#1948); no plugin owns it, so core keeps it excluded",
    "ai_summaries.db": "dormant leftover of summarize (removed in #1898); no plugin owns it, so core keeps it excluded",
}
DECLARED_BEYOND_THE_TABLES = {("crate", "second_copies"), ("save", "legacy_points")}


def _declared() -> Dict[str, Dict[str, data_decl.DataDecl]]:
    return {i: {d.id: d for d in (load_manifest(str(PLUGINS / i / "__init__.py")).data or ())} for i in SHIPPED}


def _covers(table_path: str, plugin_id: str, decl: data_decl.DataDecl) -> bool:
    if decl.root_setting and decl.default:
        full = decl.default
    elif decl.path:
        full = f"cplugs/{plugin_id}/{decl.path}"
    else:
        return False
    root = table_path.rstrip("*").rstrip("/")
    return fnmatch.fnmatch(full, table_path) or full == root or full.startswith(root + "/")


def test_every_plugin_store_in_the_core_tables_matches_a_declaration() -> None:
    declared, unmatched = _declared(), []
    for store in EXCLUDED_STORES:
        path = store.store
        if path in CORE_LEFTOVERS:
            continue
        if not path.startswith("cplugs/"):
            continue
        owner = path.split("/")[1]
        if owner in ("state.json", "renamed-carried.json", "activity.db", "ai_budget.db", "egress.db"):
            continue
        if not any(_covers(path, owner, d) for d in declared.get(owner, {}).values()):
            unmatched.append(path)
    assert not unmatched, f"plugin stores in registry_side.EXCLUDED_STORES with no declaration in the plugin's sidecar: {unmatched}"


def test_the_leftover_list_names_stores_the_tables_really_hold() -> None:
    tables = {s.store for s in EXCLUDED_STORES}
    assert {"cplugs/huddle/huddle.db", "cplugs/huddle/IMPORTED.json", "addons/huddle/huddle.db"} <= tables
    declared = _declared()
    assert all(decl_id in declared.get(plugin_id, {}) for plugin_id, decl_id in DECLARED_BEYOND_THE_TABLES)


def test_the_save_plugin_declares_its_vault_as_a_backup_destination_placed_by_its_own_setting() -> None:
    from src.plugins.sdk import crate_sources as cs
    from src.plugins.crate import policy

    assert f"{cs.STORE_VAULT}/*" in policy.POLICY and set(_declared()["save"]) == {"vault", "legacy_points"}
    vault = _declared()["save"]["vault"]
    assert (vault.kind, vault.root_setting, vault.default, vault.role, vault.scope_by) == (
        "folder", "vaultLocation", "vault", "backup_destination", "session_uuid")
    assert (vault.policy.own, vault.policy.share, vault.policy.purge, vault.policy.backup) == ("excluded", "excluded", "kept", "none")
    legacy = _declared()["save"]["legacy_points"]
    assert (legacy.state_path, legacy.policy.purge) == ("time-machine", "kept")
    assert policy.POLICY[f"{cs.STORE_POINTS}/*"].own == "exclude" and legacy.policy.own == "excluded"


def test_policy_backup_vault_is_only_for_a_folder_that_is_not_a_destination() -> None:
    from src.plugins.sdk.data_decl import problems_in

    base = {"id": "a", "kind": "folder", "path": "a", "scope_by": "install", "policy": {"own": "excluded", "share": "excluded", "reason": "r", "backup": "vault"}}
    assert problems_in([base], {}) == []
    assert any("policy.backup" in p for p in problems_in([{**base, "kind": "db"}], {}))
    dest = {**base, "path": None, "state_path": "x", "role": "backup_destination", "policy": {**base["policy"], "purge": "kept"}}
    del dest["path"]
    assert any("policy.backup" in p for p in problems_in([dest], {}))
    assert problems_in([{**base, "policy": {**base["policy"], "backup": "cloud"}}], {})
    fixture = data_decl.parse_data([base, {**base, "id": "b", "path": "b", "policy": {**base["policy"], "backup": "none"}}], {})
    assert fixture[0].wants_vault and not fixture[1].wants_vault



POLICY_DIFFERENCES_OK: Dict[str, str] = {}


def _table_row_for(plugin_id: str, decl: data_decl.DataDecl) -> str:
    for store in EXCLUDED_STORES:
        if _covers(store.store, plugin_id, decl) or (decl.root_setting and store.store == f"cplugs/{plugin_id}/*"):
            return store.store
    return ""


def policy_differences(declared: Optional[Dict[str, Dict[str, data_decl.DataDecl]]] = None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for plugin_id, decls in (declared if declared is not None else _declared()).items():
        for decl in decls.values():
            row = _table_row_for(plugin_id, decl)
            if row and "excluded" != decl.policy.own or row and "excluded" != decl.policy.share:
                out[decl.full_id(plugin_id)] = row
    return out


def test_declared_policies_agree_with_the_core_table_except_the_listed_ones() -> None:
    found = policy_differences()
    assert set(found) == set(POLICY_DIFFERENCES_OK), f"policy differences changed: found {sorted(found)}, listed {sorted(POLICY_DIFFERENCES_OK)}"


def test_the_policy_check_can_fail() -> None:
    row = "cplugs/huddle/IMPORTED.json"
    assert any(s.store == row for s in EXCLUDED_STORES), "the subject row left the core table: pick another"
    carried = data_decl.parse_data([entry(DB, path="IMPORTED.json", policy={**POLICY, "own": "carried"})], {})[0]
    assert _table_row_for("huddle", carried) == row and carried.policy.own != "excluded"
    assert policy_differences({"huddle": {carried.id: carried}}) == {carried.full_id("huddle"): row}
    excluded = data_decl.parse_data([entry(DB, path="IMPORTED.json", policy={**POLICY, "own": "excluded"})], {})[0]
    assert policy_differences({"huddle": {excluded.id: excluded}}) == {}, "an excluded store agrees with the table"



def test_purge_is_required_outside_the_plugin_folder_and_default_role_state_path_parse() -> None:
    no_purge = entry(FOLDER, policy=POLICY)
    assert any("purge" in e for e in errors_for(no_purge))
    assert errors_for(entry(FOLDER, policy={**POLICY, "purge": "removed"}), entry(DB, id="other", policy=POLICY)) == []
    assert any("purge" in e for e in errors_for(entry(FOLDER, policy={**POLICY, "purge": "burn"})))
    state = entry(DB, id="old", kind="folder", path=None, state_path="time-machine", secret_columns=None)
    assert any("purge" in e for e in errors_for(state)) and errors_for(entry(state, policy={**POLICY, "purge": "kept"})) == []
    assert errors_for(entry(FOLDER, default="crates")) == []
    assert errors_for(entry(DB, default="crates")), "default is only for a root_setting"
    assert errors_for(entry(FOLDER, default="/abs")) and errors_for(entry(FOLDER, default="../x"))
    assert errors_for(entry(FOLDER, role="backup_destination")) == [] and errors_for(entry(FOLDER, role="vault"))
    assert errors_for(entry(DB, state_path="x", path="y"))


def test_kept_inside_the_plugin_folder_and_a_destination_that_is_not_a_placed_folder_are_refused() -> None:
    fields = {"boardsRoot": {"kind": "string"}}
    inside_kept = entry(DB, policy={**POLICY, "purge": "kept"})
    assert any("removed with it" in p for p in data_decl.problems_in([inside_kept], fields))
    assert any("backup_destination" in p for p in data_decl.problems_in([entry(DB, role="backup_destination", kind="folder", path="x", secret_columns=None)], fields))
    assert any("backup_destination" in p for p in data_decl.problems_in([entry(FOLDER, role="backup_destination", kind="file")], fields))
    parsed = data_decl.parse_data([entry(FOLDER, role="backup_destination", default="crates")], fields)[0]
    assert (parsed.role, parsed.default, parsed.outlives_purge) == ("backup_destination", "crates", True)


def test_shipped_stores_outside_the_plugin_folder_say_what_a_purge_does() -> None:
    kept = {(i, d.id): d.policy.purge for i, decls in _declared().items() if i != "reviewboard" for d in decls.values() if d.root_setting or d.state_path}
    assert kept == {("crate", "bundles"): "kept", ("crate", "second_copies"): "kept", ("save", "legacy_points"): "kept",
                    ("save", "vault"): "kept"}
    roles = {(i, d.id) for i, decls in _declared().items() for d in decls.values() if d.role == "backup_destination"}
    assert roles == {("crate", "bundles"), ("crate", "second_copies"), ("save", "vault")}
    assert _declared()["crate"]["bundles"].default == "crates"
