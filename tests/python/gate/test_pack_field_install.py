
from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any, Dict

import pytest

from scripts.gate import field_installs as fi
from src.core.catalog import plugin_pack
from src.core.skills.digest import digest_directory

ROOT_DIR = "CarnivoreAI-Catalog-abc123"
AUTHORED: Dict[str, Any] = {
    "name": "clock", "id": "clock", "description": "Tells the time.", "version": "1.0.0", "author": "harbor", "license": "MIT",
    "permissions": [{"name": "notify", "reason": "tells you once when the hour turns"}],
    "sidecar": {"entry": "clock_main.py", "tools": [{"name": "clock_now", "description": "The time.", "gate": "read",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]},
}
MAIN = b'"""clock."""\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n'


@pytest.fixture(scope="module")
def cores(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Path]:
    return {tag: fi.export_core(tag, tmp_path_factory.mktemp(tag)) for tag in (f"v{fi.FIELD_FLOOR}", "v1.16.7")}


def _packed_job(tmp: Path, authored: Dict[str, Any], as_authored: bool = False):
    folder = tmp / "pkg"
    folder.mkdir()
    (folder / "clock_main.py").write_bytes(MAIN)
    if as_authored:
        (folder / "carnivore.json").write_bytes(plugin_pack.dump(dict(authored, id="harbor/clock", tier="catalog")))
        (folder / "cplug.json").write_bytes(plugin_pack.dump(plugin_pack.pack_manifest(authored, "harbor").cplug))
    else:
        files = {"carnivore.json": plugin_pack.dump(authored), "clock_main.py": MAIN}
        out, _ = plugin_pack.pack_files(files, "harbor")
        for name, body in out.items():
            (folder / name).write_bytes(body)
    tarball = tmp / "x.tgz"
    with tarfile.open(tarball, "w:gz") as tar:
        for base in ("plugins/harbor/clock", "cplugs/harbor/clock"):
            for f in sorted(folder.iterdir()):
                info = tarfile.TarInfo(f"{ROOT_DIR}/{base}/{f.name}")
                body = f.read_bytes()
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
    job = {"id": "harbor/clock", "kind": "cplug", "name": "clock", "publisher": "harbor", "v": "1.0.0", "src_path": "plugins/harbor/clock",
           "repo": "x/y", "commit": "abc123", "digest": digest_directory(folder)[0], "key_id": ""}
    return job, tarball


@pytest.mark.parametrize("tag", [f"v{fi.FIELD_FLOOR}", "v1.16.7"])
def test_a_packed_one_file_plugin_installs_on_the_floor_and_the_newest(cores: Dict[str, Path], tmp_path: Path, tag: str) -> None:
    job, tarball = _packed_job(tmp_path, AUTHORED)
    (res,) = fi.run_cell(tag, cores[tag], [job], {"harbor/clock": str(tarball)})
    assert res["ok"], res


def test_the_authored_file_shipped_as_is_is_refused_by_the_floor(cores: Dict[str, Path], tmp_path: Path) -> None:
    job, tarball = _packed_job(tmp_path, AUTHORED, as_authored=True)
    (res,) = fi.run_cell(f"v{fi.FIELD_FLOOR}", cores[f"v{fi.FIELD_FLOOR}"], [job], {"harbor/clock": str(tarball)})
    assert not res["ok"] and res["step"] == "gates", res


def test_a_page_plugin_is_packed_with_the_floor_that_lets_the_new_app_take_it() -> None:
    authored = dict(AUTHORED, page={"menu": "face", "main": "face"}, topics=["tick"])
    authored["sidecar"] = dict(AUTHORED["sidecar"], views=[{"name": "face", "surfaces": ["panel"], "files": ["index.html"]}])
    assert plugin_pack.pack_manifest(authored, "harbor").carnivore["min_app_version"] == "1.16.6"
