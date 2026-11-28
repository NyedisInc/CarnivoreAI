
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from src.plugins.host import runtime
from src.plugins.sdk.manifest import load_manifest
from tests.helpers.catalog_text import catalog_text

ROOT = Path(__file__).resolve().parents[3]
PLUGINS = ROOT / "src" / "plugins"
SHIPPED = [d.id for d in runtime.definitions()]


def test_every_shipped_plugin_has_a_v2_toml_manifest() -> None:
    for plugin_id in SHIPPED:
        toml_path = PLUGINS / plugin_id / "carnivore.toml"
        assert toml_path.is_file(), f"{plugin_id} missing carnivore.toml"
        assert not (PLUGINS / plugin_id / "cplug.json").exists(), f"{plugin_id} still has cplug.json"
        manifest = load_manifest(str(PLUGINS / plugin_id / "__init__.py"))
        assert manifest.id == plugin_id
        assert manifest.data is not None


@pytest.mark.parametrize("plugin_id", SHIPPED)
def test_the_manifest_name_is_the_catalog_name_the_plugins_page_draws(plugin_id: str) -> None:
    doc = tomllib.loads((PLUGINS / plugin_id / "carnivore.toml").read_text(encoding="utf-8"))
    name_key = doc.get("name_key") or f"cplug.{plugin_id}.name"
    match = re.search(r"'%s': '((?:[^'\\]|\\.)*)'" % re.escape(name_key), catalog_text())
    assert match and match.group(1) == doc["name"], f"{plugin_id}: manifest name {doc['name']!r} vs catalog"
    assert doc["id"] == plugin_id and doc["kind"] == "plugin"


def test_loading_the_real_ship_list_succeeds_cleanly() -> None:
    runtime._definitions = None
    try:
        defs = runtime.definitions()
        assert len(defs) == len(SHIPPED)
    finally:
        runtime._definitions = None
        runtime.definitions()


@pytest.mark.parametrize("plugin_id", SHIPPED)
def test_a_plugin_with_agent_gated_mcp_tools_declares_agent_writes(plugin_id: str) -> None:
    mcp_file = PLUGINS / plugin_id / "mcp.py"
    if not mcp_file.is_file() or not re.search(r'gate\s*=\s*"agent(_direct)?"', mcp_file.read_text()):
        pytest.skip("no agent-gated MCP tools")
    doc = tomllib.loads((PLUGINS / plugin_id / "carnivore.toml").read_text(encoding="utf-8"))
    perms = doc.get("permissions", {})
    assert "agent_writes" in perms.get("write", []) or "agent_writes" in perms.get("app", []), f"{plugin_id} carnivore.toml"
