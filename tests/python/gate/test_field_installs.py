
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


def test_the_live_known_table_names_only_what_p49_accepted() -> None:
    from scripts.gate.known_defects import KNOWN
    assert sorted(k for k in KNOWN if k.startswith("field:")) == [
        "field:v1.16.2:external/cleanyourtv", "field:v1.16.3:external/cleanyourtv"]
    assert all(KNOWN[k][0] == 2507 for k in KNOWN if k.startswith("field:"))
