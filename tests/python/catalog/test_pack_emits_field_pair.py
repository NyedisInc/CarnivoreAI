
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.catalog import plugin_pack, publish_prepare_kinds as kinds
from src.plugins.host import sideload
from src.plugins.host.sidecar_manifest import _TOP_KEYS, parse_sidecar_manifest
from src.plugins.sdk.schema_check import SchemaSet

ROOT = Path(__file__).resolve().parents[3]
SMOKE = ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"
AUTHORED: Dict[str, Any] = {
    "name": "clock", "id": "clock", "description": "Tells the time.", "version": "1.0.0", "author": "harbor", "license": "MIT",
    "permissions": [{"name": "notify", "reason": "tells you once when the hour turns"}],
    "sidecar": {"entry": "clock_main.py", "routes": ["now"], "tools": [{"name": "clock_now", "description": "The time.", "gate": "read",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]},
}
PAGE_FIELDS = {"page": {"menu": "face", "main": "face"}, "topics": ["tick"]}


def authored(**edits: Any) -> Dict[str, Any]:
    doc = copy.deepcopy(AUTHORED)
    for key, value in edits.items():
        doc.pop(key, None) if value is None else doc.__setitem__(key, value)
    return doc


@pytest.fixture(scope="module")
def schemas_at(tmp_path_factory: pytest.TempPathFactory):
    cache: Dict[str, SchemaSet] = {}

    def load(tag: str) -> SchemaSet:
        if tag not in cache:
            dest = tmp_path_factory.mktemp(f"schemas-{tag}")
            arch = subprocess.run(["git", "archive", tag, "src/schemas/extensions"], cwd=ROOT, capture_output=True, check=True)
            subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout, check=True)
            cache[tag] = SchemaSet.load(dest / "src" / "schemas" / "extensions")
        return cache[tag]

    return load


@pytest.mark.parametrize("tag", ["v1.16.2", "v1.16.4", "v1.16.7"])
def test_packed_carnivore_json_validates_against_the_released_schema(schemas_at, tag: str) -> None:
    packed = plugin_pack.pack_manifest(authored(), "harbor")
    assert "sidecar" not in packed.carnivore
    assert schemas_at(tag).validate("warez/cplug.schema.json", packed.carnivore) == []
    assert schemas_at("v1.16.2").validate("warez/cplug.schema.json", authored(id="harbor/clock", tier="catalog")) != [], \
        "the authored file itself must be refused by the closed 1.16.2 schema, which is why it is never shipped"


def test_page_and_topics_raise_min_app_version_to_1_16_6_and_old_schemas_refuse_the_keys(schemas_at) -> None:
    plain = plugin_pack.pack_manifest(authored(min_app_version="1.16.2"), "harbor")
    assert plain.carnivore["min_app_version"] == "1.16.2" and "page" not in plain.carnivore and "topics" not in plain.carnivore
    paged = plugin_pack.pack_manifest(authored(min_app_version="1.16.2", **PAGE_FIELDS), "harbor")
    assert paged.carnivore["min_app_version"] == "1.16.6" and paged.notes
    assert paged.carnivore["page"] == PAGE_FIELDS["page"] and paged.carnivore["topics"] == ["tick"]
    assert schemas_at("v1.16.7").validate("warez/cplug.schema.json", paged.carnivore) == []
    assert schemas_at("v1.16.2").validate("warez/cplug.schema.json", paged.carnivore) != [], "1.16.2 refuses page: the floor is what keeps it out"
    assert plugin_pack.pack_manifest(authored(min_app_version="1.17.0", **PAGE_FIELDS), "harbor").carnivore["min_app_version"] == "1.17.0"


def test_cplug_json_is_built_from_sidecar_and_agrees_with_carnivore_json() -> None:
    packed = plugin_pack.pack_manifest(authored(), "harbor")
    cplug, side = packed.cplug, packed.carnivore
    assert set(cplug) <= _TOP_KEYS and plugin_pack.CPLUG_JSON_KEYS == _TOP_KEYS, "pack and sidecar_manifest must accept the same cplug.json keys"
    assert (cplug["id"], side["id"], side["tier"]) == ("clock", "harbor/clock", "catalog")
    assert cplug["version"] == side["version"] == "1.0.0" and cplug["permissions"] == {"app": ["notify"]}
    assert cplug["entry"] == side["runtime"]["entry"] == "clock_main.py"
    parse_sidecar_manifest(cplug, "clock", "0" * 64)
    plugin_pack.check_pair(side, cplug)


def test_without_a_publisher_the_package_is_a_local_sideload() -> None:
    side = plugin_pack.pack_manifest(authored()).carnivore
    assert (side["id"], side["tier"]) == ("local/clock", "local")


@pytest.mark.parametrize("edit,needle", [
    ({"surprise": 1}, "surprise"),
    ({"sidecar": {"entry": "x.py", "version": "2.0.0"}}, "written once"),
    ({"sidecar": {"entry": "x.txt"}}, "entry"),
    ({"sidecar": {"entry": "x.py", "permissions": {"app": ["other"]}}}, "permissions"),
    ({"author": None}, "author"),
    ({"min_app_version": "latest"}, "dotted"),
    ({"permissions": "notify"}, "permissions"),
])
def test_a_bad_authored_file_is_refused_with_the_field_named(edit: Dict[str, Any], needle: str) -> None:
    with pytest.raises(plugin_pack.PackError, match=needle):
        plugin_pack.pack_manifest(authored(**edit), "harbor")


def test_a_hand_written_old_pair_is_accepted_unchanged_after_the_agreement_check(tmp_path: Path) -> None:
    carn, cplug = (json.loads((SMOKE / n).read_text()) for n in ("carnivore.json", "cplug.json"))
    packed = plugin_pack.check_pair(carn, cplug)
    assert packed.carnivore == carn and packed.cplug == cplug
    files = {n: (SMOKE / n).read_bytes() for n in ("carnivore.json", "cplug.json", "warezsmoke_main.py")}
    out, _ = plugin_pack.pack_files(files)
    assert out == files
    for bad in (dict(cplug, version="9.9.9"), dict(cplug, id="other"), dict(cplug, permissions={"app": ["x"]})):
        with pytest.raises(plugin_pack.PackError):
            plugin_pack.check_pair(carn, bad)


def test_repacking_is_byte_stable_and_a_stray_cplug_json_is_refused() -> None:
    files = {"carnivore.json": plugin_pack.dump(authored()), "clock_main.py": b"x = 1\n"}
    first, _ = plugin_pack.pack_files(files, "harbor")
    second, _ = plugin_pack.pack_files(files, "harbor")
    assert first == second and set(first) == {"carnivore.json", "cplug.json", "clock_main.py"}
    with pytest.raises(plugin_pack.PackError, match="generated"):
        plugin_pack.pack_files(dict(first, **{"carnivore.json": files["carnivore.json"]}), "harbor")


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "clock"
    src.mkdir()
    (src / "carnivore.json").write_bytes(plugin_pack.dump(authored()))
    (src / "clock_main.py").write_text('"""clock."""\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n')
    return src


def test_the_publish_door_packs_the_authored_folder(tmp_path: Path) -> None:
    src = _source(tmp_path)
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.refusals == [], [r.detail for r in prepared.refusals]
    members = dict(prepared.members)
    side, runtime = json.loads(members["carnivore.json"]), json.loads(members["cplug.json"])
    assert "sidecar" not in side and (side["id"], side["tier"]) == ("harbor/clock", "catalog") and runtime["entry"] == "clock_main.py"
    assert not (src / "cplug.json").exists(), "the author's folder is never rewritten"


def test_the_sideload_door_packs_the_staged_copy_only(tmp_path: Path) -> None:
    src = _source(tmp_path)
    state = tmp_path / "state"
    staging, files, manifest = sideload.stage(state, "clock", src)
    try:
        assert "cplug.json" in files and manifest.entry == "clock_main.py" and manifest.id == "clock"
        assert "sidecar" not in json.loads((staging / "carnivore.json").read_text())
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    assert not (src / "cplug.json").exists()
