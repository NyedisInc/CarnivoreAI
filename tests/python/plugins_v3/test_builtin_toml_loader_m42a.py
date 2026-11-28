
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gate import default_state, tree_copy
from src.core.catalog import builtins
from src.core.notifications import catalog_lines
from src.core.widget_fits import plugin_rows
from src.plugins import registry
from src.plugins.cli import templates
from src.plugins.host import identity, runtime
from src.plugins.sdk import api_contract, old_names
from src.plugins.sdk.definition import CplugDefinition, ToolSpec
from src.plugins.sdk.manifest import ManifestError, load_manifest
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2
from src.plugins.sdk.routing import cplug_router


def _base_third_party(**overrides: object) -> dict:
    raw = {
        "schema": 2,
        "id": "thirdplug",
        "name": "Third Plug",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Third party plugin",
        "author": "Tester",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
    }
    raw.update(overrides)
    return raw


def test_builtin_toml_full_roundtrip_and_runtime_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(old_names, "_declared", {})
    pkg_dir = tmp_path / "taskmanager"
    pkg_dir.mkdir()
    (pkg_dir / "carnivore.toml").write_text(
        """
schema = 2
api_version = 1
id = "taskmanager"
name = "Task Manager"
description = "Built-in Task Manager over carnivore.toml."
version = "1.0.0"
kind = "plugin"
author = "Carnivore"
min_app_version = "1.16.0"
icon = "chat"
tier = "builtin"
default_enabled = true
css_prefix = "hdr"
tool_family = "task_manager"
data = []

[legacy_ids]
nudge = "nudgeEnabled"

[mcp_tool_aliases]
nudge_ping = "task_manager_tasks_list"

[settings_aliases]
sendQuietSeconds = "tellQuietSeconds"

[permissions]
read = ["sessions"]
write = ["notify"]
app = ["swarm", "work"]

[ui]
routes = true
storage = true
topics = ["list", "delta"]
tabs = ["taskmanager"]
menu_links = ["taskmanager-extra"]
plugins = ["session-card-action"]
widgets = ["chat"]
page_section = "work"
page_section_label_key = "cplug.taskmanager.page_section"
page_section_icon = "chat"

[ui.contribute]
"session.row_actions" = [{ id = "add_task", label = "Add Task" }]

[mcp]
tools = ["task_manager_tasks_list", "taskmanager_ping"]

[services]
consumes = ["pulse.state"]
[[services.provides]]
name = "taskmanager.tasks"
methods = ["list_tasks"]

[events]
on = ["pulse.ready"]
emit = ["taskmanager.updated"]

[owns]
strings = ["cplug.taskmanager."]
styles = ["task-manager.css"]
contributions = ["chat.widget_kind"]

[settings_schema]
version = 1

[settings_schema.fields.nudgeEnabled]
kind = "boolean"
labelKey = "cplug.taskmanager.settings.nudge_enabled"
default = false

[settings_schema.fields.sendQuietSeconds]
kind = "number"
labelKey = "cplug.taskmanager.settings.send_quiet_seconds"
min = 1
max = 300
default = 10

[widgets.chat]
instancing = "per-target"
fits = { sizes = ["medium", "large"], anySize = true }
""",
        encoding="utf-8",
    )

    manifest = load_manifest(str(pkg_dir / "__init__.py"))
    assert manifest.id == "taskmanager"
    assert manifest.name_key == "cplug.taskmanager.name"
    assert manifest.description_key == "cplug.taskmanager.description"
    assert manifest.css_prefix == "hdr"
    assert manifest.tier == "builtin"
    assert manifest.default_enabled is True
    assert manifest.tool_family == "task_manager"
    assert manifest.legacy_ids == {"nudge": "nudgeEnabled"}
    assert manifest.mcp_tool_aliases == {"nudge_ping": "task_manager_tasks_list"}
    assert manifest.settings_aliases == {"sendQuietSeconds": "tellQuietSeconds"}
    assert manifest.data == ()
    assert manifest.surfaces.routes is True
    assert manifest.surfaces.storage is True
    assert manifest.surfaces.mcp_tools == ("task_manager_tasks_list", "taskmanager_ping")
    assert manifest.surfaces.topics == ("list", "delta")
    assert manifest.surfaces.tabs == ("taskmanager",)
    assert manifest.surfaces.menu_links == ("taskmanager-extra",)
    assert manifest.surfaces.plugins == ("session-card-action",)
    assert manifest.surfaces.widgets == ("chat",)
    assert manifest.surfaces.page_section == "work"
    assert manifest.surfaces.page_section_label_key == "cplug.taskmanager.page_section"
    assert manifest.surfaces.page_section_icon == "chat"
    assert "chat" in manifest.widgets
    assert manifest.services_consumes == ("pulse.state",)
    assert len(manifest.services_provides) == 1
    assert manifest.events_on == ("pulse.ready",)
    assert manifest.events_emit == ("taskmanager.updated",)
    assert not hasattr(manifest, "tier0")

    router = cplug_router("taskmanager")

    @router.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    async def _noop(*_args: object, **_kwargs: object) -> dict:
        return {}

    defn = CplugDefinition(
        manifest=manifest,
        router=router,
        tools={
            "task_manager_tasks_list": ToolSpec(description="list", properties={}, required=(), handler=_noop, gate="read"),
            "taskmanager_ping": ToolSpec(description="ping", properties={}, required=(), handler=_noop, gate="read"),
        },
        storage=object(),  # type: ignore[arg-type]
    )
    runtime.check_definitions((defn,))

    monkeypatch.setattr(registry, "CPLUGS", (defn,))
    assert plugin_rows.plugin_widget_rows() == [
        {"id": "taskmanager.chat", "instancing": "per-target", "fits": {"sizes": ["medium", "large"], "anySize": True}}
    ]


def test_builtin_toml_renamed_from_and_keeps(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "alpha"
    pkg_dir.mkdir()
    (pkg_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "alpha"
name = "Alpha"
description = "Renamed builtin"
version = "1.0.0"
kind = "plugin"
author = "Carnivore"
tier = "builtin"
renamed_from = "beta"
renamed_from_keeps = ["strings", "widgets"]
name_key = "cplug.beta.name"
description_key = "cplug.beta.description"
data = []

[ui]
tabs = ["alpha"]
widgets = ["beta.chat"]
page_section = "work"
page_section_label_key = "cplug.beta.page_section"
page_section_icon = "chat"

[owns]
strings = ["cplug.beta."]

[widgets."beta.chat"]
instancing = "per-target"
fits = { sizes = ["medium"] }
""",
        encoding="utf-8",
    )

    manifest = load_manifest(str(pkg_dir / "__init__.py"))
    assert manifest.renamed_from == "beta"
    assert manifest.renamed_from_keeps == ("strings", "widgets")
    assert manifest.name_key == "cplug.beta.name"
    assert manifest.description_key == "cplug.beta.description"
    assert manifest.owns.strings == ("cplug.beta.",)
    assert manifest.surfaces.widgets == ("beta.chat",)

    with pytest.raises(ManifestV2Error, match="other plugin ids"):
        parse_manifest_v2(
            {
                "schema": 2,
                "id": "alpha",
                "name": "Alpha",
                "description": "Self-require old id",
                "version": "1.0.0",
                "kind": "plugin",
                "author": "Carnivore",
                "tier": "builtin",
                "renamed_from": "beta",
                "requires": ["beta"],
            },
            tier="builtin",
            allow_tier_override=True,
        )


def test_ui_storage_preserves_catalog_data_while_defaulting_builtin_false(tmp_path: Path) -> None:
    cat_dir = tmp_path / "catstore"
    cat_dir.mkdir()
    (cat_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "catstore"
name = "Catalog Store"
description = "Catalog sidecar with [[data]]"
version = "1.0.0"
kind = "plugin"
author = "ThirdParty"
tier = "catalog"

[run]
cmd = ["python3", "main.py"]

[[data]]
id = "catstore"
kind = "db"
state_path = "catstore.db"
scope_by = "session_uuid"
policy = { own = "carried", share = "excluded", purge = "removed", reason = "test store" }
""",
        encoding="utf-8",
    )
    cat_manifest = load_manifest(str(cat_dir / "__init__.py"))
    assert cat_manifest.surfaces.storage is True

    builtin_dir = tmp_path / "builtinstore"
    builtin_dir.mkdir()
    (builtin_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "builtinstore"
name = "Builtin Store"
description = "Built-in with [[data]] but no [ui].storage"
version = "1.0.0"
kind = "plugin"
author = "Carnivore"
tier = "builtin"

[[data]]
id = "builtinstore"
kind = "db"
state_path = "builtinstore.db"
scope_by = "session_uuid"
policy = { own = "carried", share = "excluded", purge = "removed", reason = "test store" }
""",
        encoding="utf-8",
    )
    builtin_manifest = load_manifest(str(builtin_dir / "__init__.py"))
    assert builtin_manifest.surfaces.storage is False


@pytest.mark.parametrize("target_tier", ["catalog", "local"])
@pytest.mark.parametrize(
    "patch",
    [
        {"renamed_from": "beta"},
        {"renamed_from_keeps": ["strings"]},
        {"tool_family": "task_manager"},
        {"legacy_ids": {"old": "flag"}},
        {"mcp_tool_aliases": {"thirdplug_old": "thirdplug_new"}},
        {"settings_aliases": {"new": "old"}},
        {"widgets": {"card": {"instancing": "singleton", "fits": {"sizes": ["small"]}}}},
        {"css_prefix": "tp"},
        {"name_key": "cplug.thirdplug.name"},
        {"description_key": "cplug.thirdplug.description"},
        {"ui": {"routes": True}},
        {"ui": {"tabs": ["thirdplug"]}},
        {"ui": {"menu_links": ["thirdplug"]}},
        {"ui": {"plugins": ["session-card-action"]}},
        {"ui": {"widgets": ["card"]}},
        {"ui": {"page_section": "work"}},
        {"ui": {"storage": True}},
        {"mcp": {"tools": ["thirdplug_ping"]}},
    ],
)
def test_third_party_rejects_builtin_only_fields(target_tier: str, patch: dict) -> None:
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_base_third_party(tier=target_tier, **patch), tier=target_tier, allow_tier_override=True)


@pytest.mark.parametrize("target_tier", ["catalog", "local"])
@pytest.mark.parametrize(
    "patch",
    [
        {"mcp": {"tools": [{"name": "thirdplug_read", "description": "r", "gate": "read"}]}},
        {"ui": {"routes": ["status"]}},
        {"timers": {"tick": {"every_seconds": 30}}},
        {"services": {"provides": [{"name": "thirdplug.svc", "methods": ["ping"]}]}},
    ],
)
def test_third_party_tier0_still_rejects_runnable_surfaces(target_tier: str, patch: dict) -> None:
    raw = _base_third_party(tier=target_tier, **patch)
    raw.pop("run")
    with pytest.raises(ManifestV2Error, match="Tier 0"):
        parse_manifest_v2(raw, tier=target_tier, allow_tier_override=True)


def test_registry_and_helpers_coexist_with_carnivore_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "plugins"
    root.mkdir()

    toml_plug = root / "tomlplug"
    toml_plug.mkdir()
    (toml_plug / "__init__.py").write_text("", encoding="utf-8")
    (toml_plug / "notify.catalog.en.js").write_text("'cplug.tomlplug.hi': 'hi',\n", encoding="utf-8")
    (toml_plug / "carnivore.toml").write_text(
        """
schema = 2
api_version = 1
id = "tomlplug"
name = "TOML Plug"
description = "Built-in TOML plugin"
version = "1.2.3"
kind = "plugin"
author = "Carnivore"
min_app_version = "1.16.0"
tier = "builtin"
default_enabled = true
data = []
""",
        encoding="utf-8",
    )

    json_plug = root / "jsonplug"
    json_plug.mkdir()
    (json_plug / "__init__.py").write_text("", encoding="utf-8")
    (json_plug / "cplug.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "jsonplug",
                "name_key": "cplug.jsonplug.name",
                "description_key": "cplug.jsonplug.description",
                "version": "0.9.0",
                "icon": "plug",
                "author": "Carnivore",
                "min_app_version": "1.16.0",
                "tier": "builtin",
                "default_enabled": False,
                "permissions": {"app": []},
                "surfaces": {},
            }
        ),
        encoding="utf-8",
    )
    (json_plug / "carnivore.json").write_text(json.dumps({"name": "JSON Plug", "api_version": 1}), encoding="utf-8")

    monkeypatch.setattr("src.plugins.registry.ship_order", lambda: ["jsonplug", "tomlplug"])
    assert registry.plugin_folders(root) == ["tomlplug"]
    assert registry.manifest_path(toml_plug) == toml_plug / "carnivore.toml"
    assert registry.manifest_path(json_plug) is None

    assert api_contract.read_api_version(toml_plug) == 1
    manifest = load_manifest(str(toml_plug / "__init__.py"))
    assert manifest.id == "tomlplug" and manifest.data == ()

    entries = builtins.plugin_entries(root)
    assert [(e.id, e.name, e.version) for e in entries] == [
        ("nyedis/tomlplug", "TOML Plug", "1.2.3"),
    ]

    assert catalog_lines.plugin_slice_paths(root) == [toml_plug / "notify.catalog.en.js"]

    fake_repo = tmp_path / "repo"
    (fake_repo / "src").mkdir(parents=True)
    (fake_repo / "src" / "plugins").symlink_to(root)
    assert tree_copy.shipped_ids(fake_repo) == ["tomlplug"]
    assert default_state.default_plugin_states(fake_repo) == {"tomlplug": True}

    monkeypatch.setattr(templates, "_SHIPPED_ROOT", root)
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset())
    assert "reserved" in templates.name_problem("tomlplug")

    both = tmp_path / "both"
    both.mkdir()
    (both / "carnivore.toml").write_text('schema = 2\nid = "both"\n', encoding="utf-8")
    (both / "cplug.json").write_text('{"schema": 1}', encoding="utf-8")
    with pytest.raises(ManifestError, match="cannot coexist"):
        load_manifest(str(both / "__init__.py"))


def test_builtin_string_list_mcp_tools_enforces_max_tools() -> None:
    raw_ok = {
        "schema": 2,
        "id": "manytools",
        "name": "Many Tools",
        "description": "Tests MAX_TOOLS on built-in string list",
        "version": "1.0.0",
        "kind": "plugin",
        "author": "Carnivore",
        "tier": "builtin",
        "mcp": {"tools": [f"manytools_t{i}" for i in range(32)]},
    }
    parsed = parse_manifest_v2(raw_ok, tier="builtin", allow_tier_override=True)
    assert len(parsed.mcp_tools) == 32

    raw_too_many = {
        **raw_ok,
        "mcp": {"tools": [f"manytools_t{i}" for i in range(33)]},
    }
    with pytest.raises(ManifestV2Error, match="at most 32"):
        parse_manifest_v2(raw_too_many, tier="builtin", allow_tier_override=True)
