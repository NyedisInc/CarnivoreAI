
from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, List

import pytest

from scripts.gate import field_installs as fi
from src.core.skills.digest import digest_directory

ROOT = "CarnivoreAI-Catalog-abc123"
FILES = {"cplug.json": b'{"id": "n"}\n', "carnivore.json": b'{"id": "h/n"}\n', "main.py": b"x = 1\n"}


def make_tarball(path: Path, folders: List[str]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for folder in folders:
            for name, body in FILES.items():
                info = tarfile.TarInfo(f"{ROOT}/{folder}/{name}")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))


def job(item_id: str, kind: str = "cplug") -> Dict[str, str]:
    pub, _, name = item_id.partition("/")
    return {"id": item_id, "kind": kind, "name": name, "publisher": pub, "v": "1.0.0", "src_path": f"plugins/{pub}/{name}",
            "repo": "x/y", "commit": "abc123", "digest": "0" * 64, "key_id": ""}


@pytest.fixture(scope="module")
def core_1162(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fi.export_core(f"v{fi.FIELD_FLOOR}", tmp_path_factory.mktemp("core"))


def test_no_twin_fails_on_1_16_2_and_the_twin_gets_past_stage(core_1162: Path, tmp_path: Path) -> None:
    bare, twinned = tmp_path / "bare.tgz", tmp_path / "twin.tgz"
    make_tarball(bare, ["plugins/h/n"])
    make_tarball(twinned, ["plugins/h/n", "cplugs/h/n"])
    row = job("h/n")
    (res,) = fi.run_cell("v1.16.2", core_1162, [row], {"h/n": str(bare)})
    assert not res["ok"] and res["step"] == "stage", res
    row["digest"] = digest_directory(_folder(tmp_path, FILES))[0]
    (res,) = fi.run_cell("v1.16.2", core_1162, [row], {"h/n": str(twinned)})
    assert res["step"] != "stage", f"with the twin the old app's stage_archive accepts it and the digest matches: {res}"


def _folder(tmp: Path, files: Dict[str, bytes]) -> Path:
    d = tmp / "digest"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_bytes(body)
    return d


def test_a_built_in_id_is_a_pass_on_the_app_that_ships_it(core_1162: Path) -> None:
    (res,) = fi.run_cell("v1.16.2", core_1162, [job("carnivore/mcphealth")], {})
    assert res["ok"] and res["step"] == "builtin", res


def test_a_missing_tag_is_refused_never_a_pass(tmp_path: Path) -> None:
    with pytest.raises(fi.Refused):
        fi.export_core("v0.0.0-no-such-tag", tmp_path / "c")
    subprocess.run(["git", "init", "-q", str(tmp_path / "empty")], check=True)
    with pytest.raises(fi.Refused, match="field floor"):
        fi.field_tags(tmp_path / "empty")


def test_known_entries_are_exact_and_shrink_only() -> None:
    red = {"ok": False, "id": "a/b", "v": "0.1.0", "step": "gates", "detail": "no"}
    cells = {"v1.16.2": [dict(red)], "master": [dict(red), dict(red, id="a/c")]}
    table = {"field:v1.16.2:a/b": (1, "all versions"), "field:master:a/b@0.1.0": (2, "pinned"), "field:master:a/gone": (3, "fixed")}
    failures, known, stale = fi.judge(cells, table)
    assert [f.split(" x ")[1] for f in failures] == ["a/c@0.1.0"], "a different plugin stays red"
    assert len(known) == 2 and stale == ["field:master:a/gone: known defect fixed, delete the entry from scripts/gate/known_defects.py"]
    cells["master"][0]["v"] = "0.1.1"
    assert len(fi.judge(cells, table)[0]) == 2, "a pin to 0.1.0 does not cover 0.1.1"


def test_master_skips_the_version_floor_and_a_field_cell_refuses_on_it() -> None:
    refusal, note = fi.floor_check("1.16.4", "1.16.3", upcoming=False)
    assert refusal == "needs app 1.16.4, this is 1.16.3" and not note, "a field app refuses a plugin newer than itself"
    refusal, note = fi.floor_check("1.16.4", "1.16.3", upcoming=True)
    assert not refusal and "1.16.4" in note, "master is the upcoming release: noted, not refused"
    assert fi.floor_check("1.16.3", "1.16.3", upcoming=False) == ("", "")


def test_the_live_known_table_has_no_field_entries() -> None:
    from scripts.gate.known_defects import KNOWN
    assert [k for k in KNOWN if k.startswith("field:")] == [], "the canaries have no accepted defect; a non-canary one is not a bump failure"


def test_only_canaries_are_checked_and_a_missing_one_is_refused() -> None:
    def item(i: str, kind: str) -> dict:
        return {"id": i, "kind": kind, "name": i.split("/")[1], "publisher": i.split("/")[0], "latest": "1", "versions": [
            {"v": "1", "digest": "d", "src": {"path": "p", "repo": "r", "commit": "c"}}]}
    index = {"items": [item("a/one", "plugin"), item("a/two", "cplug"), item("a/other", "plugin")]}
    assert [j["id"] for j in fi.plugin_jobs(index, ("a/one", "a/two"))] == ["a/one", "a/two"]
    with pytest.raises(fi.Refused, match="a/gone"):
        fi.plugin_jobs(index, ("a/one", "a/gone"))
    assert {"plugin", "cplug"} == {j["kind"] for j in fi.plugin_jobs({"items": [item("carnivore/mcphealth", "cplug"), item("external/rea", "plugin")]})}


def test_v2_canary_reads_carnivore_toml_on_master_and_falls_back_to_v1_on_pre_v2_cores(tmp_path: Path) -> None:
    index = {"items": [{
        "id": "carnivore/mcphealth", "kind": "cplug", "name": "mcphealth", "publisher": "carnivore", "latest": "1.0.2",
        "versions": [
            {"v": "1.0.1", "manifest_schema": 1, "digest": "d1", "src": {"path": "plugins/carnivore/mcphealth", "repo": "r", "commit": "c1"}},
            {"v": "1.0.2", "manifest_schema": 2, "digest": "d2", "src": {"path": "plugins/carnivore/mcphealth", "repo": "r", "commit": "c2"}},
        ],
    }]}
    (row,) = fi.plugin_jobs(index, ("carnivore/mcphealth",))
    assert row["v"] == "1.0.2" and row["manifest_schema"] == 2
    assert row["v1_fallback"]["v"] == "1.0.1" and row["v1_fallback"]["commit"] == "c1"

    pkg = fi.REPO / "packages" / "cplugs" / "mcphealth"
    tarball = tmp_path / "mcphealth-v2.tgz"
    with tarfile.open(tarball, "w:gz") as tar:
        for f in sorted(pkg.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                rel = f.relative_to(pkg).as_posix()
                info = tarfile.TarInfo(f"{ROOT}/plugins/carnivore/mcphealth/{rel}")
                body = f.read_bytes()
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
    v2_row = dict(row, digest=digest_directory(pkg)[0])
    (res,) = fi.run_cell("master", fi.REPO, [v2_row], {"carnivore/mcphealth": str(tarball)}, upcoming=True)
    assert res["ok"] and res["step"] == "ok", res
