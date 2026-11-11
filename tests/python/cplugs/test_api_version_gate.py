
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.plugin import check, templates
from src.core.catalog import plugin_pack
from src.core.plugin_health.model import HealthRow
from src.cplugs.host import install_gates, sideload
from src.cplugs.sdk import api_contract

UNSERVED = max(api_contract.SERVED_API_VERSIONS) + 1
CPLUGS_ROOT = Path(api_contract.__file__).resolve().parents[1]


def source(tmp_path: Path, api_version: Any = None) -> Path:
    folder = tmp_path / "src" / "clock"
    folder.parent.mkdir(parents=True)
    templates.scaffold(folder, "clock", "sidecar")
    if api_version is not None:
        path = folder / "carnivore.json"
        doc = json.loads(path.read_text())
        doc["api_version"] = api_version
        path.write_text(json.dumps(doc))
    return folder


def packed(tmp_path: Path, api_version: Any = None) -> Path:
    out = tmp_path / "pkg" / "clock"
    plugin_pack.pack_folder(source(tmp_path, api_version), out, "author", frozenset({"tests"}))
    return out


def test_served_set_is_the_documented_contracts() -> None:
    assert api_contract.SERVED_API_VERSIONS == frozenset({1})
    docs = Path(__file__).resolve().parents[3] / "docs" / "plugins"
    assert all((docs / f"api-v{v}.md").is_file() for v in api_contract.SERVED_API_VERSIONS)


@pytest.mark.parametrize("value,served", [(1, True), (UNSERVED, False), (0, False), (True, False), ("1", False)])
def test_is_served(value: Any, served: bool) -> None:
    assert api_contract.is_served(value) is served


def test_install_refuses_an_unserved_version_with_its_code(tmp_path: Path) -> None:
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.evaluate("author/clock", packed(tmp_path, UNSERVED))
    assert caught.value.code == install_gates.API_VERSION_UNSUPPORTED == "cplug_api_version_unsupported"
    assert str(UNSERVED) in caught.value.detail


def test_install_accepts_a_served_version(tmp_path: Path) -> None:
    assert install_gates.evaluate("author/clock", packed(tmp_path)).facts["id"] == "clock"


def test_sideload_refuses_an_unserved_version_and_leaves_no_staging(tmp_path: Path) -> None:
    state = tmp_path / "state"
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload.stage(state, "clock", source(tmp_path, UNSERVED))
    assert (caught.value.code, caught.value.status) == (sideload.API_VERSION_UNSUPPORTED, 422)
    parent = sideload.code_root_of(state, "clock").parent
    assert not parent.exists() or not any(parent.iterdir())


def test_sideload_accepts_a_served_version(tmp_path: Path) -> None:
    staging, _files, manifest = sideload.stage(tmp_path / "state", "clock", source(tmp_path))
    try:
        assert manifest.id == "clock"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def test_plugin_check_reports_an_unserved_version(tmp_path: Path) -> None:
    report = check.check_folder(source(tmp_path, UNSERVED))
    assert not report.ok and any("api_version" in e for e in report.errors)


def test_health_row_carries_api_version() -> None:
    assert api_contract.read_api_version(CPLUGS_ROOT / "share") == 1
    assert api_contract.read_api_version(CPLUGS_ROOT / "no-such-plugin") is None
    row = HealthRow(id="share", kind="feature", source="built_in", word="on", api_version=1)
    assert row.as_wire()["api_version"] == 1
