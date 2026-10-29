
from __future__ import annotations

import json
from pathlib import Path

from src.core import slash_command_discovery
from src.core.catalog import publish_plugin_sources


def make_plugin(folder: Path) -> Path:
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text('{"name": "x"}')
    return folder


def register(home: Path, marketplaces: dict) -> None:
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "known_marketplaces.json").write_text(json.dumps(marketplaces))


def test_only_plugins_from_a_local_directory_marketplace_are_listed(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    monkeypatch.setattr(slash_command_discovery, "CLAUDE_HOME", home)
    market = tmp_path / "my-market"
    make_plugin(market / "plugins" / "helper")
    make_plugin(market / "plugins" / "owned")
    (market / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [
        {"name": "helper", "source": "./plugins/helper"},
        {"name": "owned", "source": "./plugins/owned"},
        {"name": "escape", "source": "./../elsewhere"},
        {"name": "remote", "source": {"source": "github", "repo": "a/b"}},
    ]}))
    solo = make_plugin(tmp_path / "solo-plugin")
    register(home, {
        "mine": {"source": {"source": "directory", "path": str(market)}},
        "solo": {"source": {"source": "directory", "path": str(solo)}},
        "upstream": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}},
    })
    found = publish_plugin_sources.own_plugin_locations({"owned"})
    assert [(loc["location_id"], loc["kind"]) for loc in found] == [
        ("plugin:helper", "plugin"), ("plugin:solo-plugin", "plugin"),
    ]
    assert found[0]["path"] == str(market / "plugins" / "helper")


def test_no_registry_or_a_broken_one_lists_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(slash_command_discovery, "CLAUDE_HOME", tmp_path / "none")
    assert publish_plugin_sources.own_plugin_locations(set()) == []
    (tmp_path / "bad" / "plugins").mkdir(parents=True)
    (tmp_path / "bad" / "plugins" / "known_marketplaces.json").write_text("{not json")
    monkeypatch.setattr(slash_command_discovery, "CLAUDE_HOME", tmp_path / "bad")
    assert publish_plugin_sources.own_plugin_locations(set()) == []
