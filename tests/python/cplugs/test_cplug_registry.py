
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.cplugs.host import runtime
from tests.helpers.catalog_text import catalog_text
from src.cplugs.sdk import ManifestError
from src.cplugs.sdk.manifest import parse_manifest, version_tuple

ROOT = Path(__file__).resolve().parents[3]
TASK_MANAGER = json.loads((ROOT / "src/cplugs/huddle/cplug.json").read_text())


def test_every_shipped_cplug_validates_and_matches_its_code():
    defs = runtime.definitions()
    assert [d.id for d in defs] == ["huddle", "unread", "share", "save", "flow", "reviewboard", "publicboard", "tmdevtools", "crate", "devwidgetlab", "timemachine"]
    runtime.check_definitions(defs)
    app_version = json.loads((ROOT / "macOS/package.json").read_text())["version"]
    for d in defs:
        assert version_tuple(d.manifest.min_app_version) <= version_tuple(app_version), d.id
        assert (ROOT / "src/cplugs" / d.id / "cplug.json").is_file()


def test_every_manifest_string_key_is_in_the_one_catalog():
    catalog = catalog_text()
    for d in runtime.definitions():
        for key in (d.manifest.name_key, d.manifest.description_key):
            assert f"'{key}'" in catalog or f'"{key}"' in catalog, key


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m.update(id="Huddle"), "must match"),
    (lambda m: m.update(id="session"), "reserved"),
    (lambda m: m.update(name_key="huddle.name"), "name_key"),
    (lambda m: m.update(tier="plugin"), "tier"),
    (lambda m: m["permissions"].update(app=["root"]), "unknown app permission"),
    (lambda m: m["surfaces"].update(mcp_tools=["list_huddle"]), "huddle_<verb>"),
    (lambda m: m["surfaces"].update(tabs=["other"]), "start with huddle-"),
    (lambda m: m.update(extra=1), "unknown field"),
    (lambda m: m.update(settings_schema={"version": 0, "fields": {}}), "settings_schema"),
])
def test_a_broken_manifest_is_refused(mutate, message):
    raw = copy.deepcopy(TASK_MANAGER)
    parse_manifest(raw)
    mutate(raw)
    with pytest.raises(ManifestError, match=message):
        parse_manifest(raw)


def test_a_surface_used_but_not_declared_or_the_reverse_refuses_the_whole_list():
    task_manager = runtime.find("huddle")
    runtime.check_definitions((task_manager,))
    with pytest.raises(runtime.RegistryError, match="two plugins"):
        runtime.check_definitions((task_manager, task_manager))
    with pytest.raises(runtime.RegistryError, match="mcp_tools"):
        runtime.check_definitions((replace(task_manager, tools={}),))
    with pytest.raises(runtime.RegistryError, match="router"):
        runtime.check_definitions((replace(task_manager, router=None),))
    with pytest.raises(runtime.RegistryError, match="storage"):
        runtime.check_definitions((replace(task_manager, storage=None),))
