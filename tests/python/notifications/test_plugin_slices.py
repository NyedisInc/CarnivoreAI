
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.notifications import catalog_lines, types

TYPE_ID = "cplug.acme.thing"


def _plugin(root: Path, pid: str, body: str, manifest: bool = True) -> Path:
    folder = root / pid
    folder.mkdir(parents=True)
    if manifest:
        (folder / "cplug.json").write_text("{}", encoding="utf-8")
    path = folder / catalog_lines.PLUGIN_SLICE_NAME
    path.write_text("export default {\n" + body + "};\n", encoding="utf-8")
    return path


def _remove(slice_path: Path) -> None:
    for child in slice_path.parent.iterdir():
        child.unlink()
    slice_path.parent.rmdir()


def test_namespace_of_a_plugin_type_is_its_own_and_core_types_keep_theirs() -> None:
    assert types.catalog_namespace(TYPE_ID) == ("cplug.acme.notify.type.thing", "cplug.acme.notify.copy.thing")
    assert types.catalog_namespace("session.died") == ("notify.type.session.died", "notify.copy.session.died")


def test_an_absent_plugin_has_no_strings(tmp_path: Path) -> None:
    present = _plugin(tmp_path, "alpha", "    'cplug.alpha.notify.copy.x.title': 'a',\n")
    assert catalog_lines.read_plugin_slices(("notify.",), tmp_path) == {"cplug.alpha.notify.copy.x.title": "a"}
    _remove(present)
    assert catalog_lines.read_plugin_slices(("notify.",), tmp_path) == {}


def test_a_slice_without_its_manifest_is_not_read(tmp_path: Path) -> None:
    _plugin(tmp_path, "ghost", "    'cplug.ghost.notify.copy.x.title': 'g',\n", manifest=False)
    assert catalog_lines.read_plugin_slices(("notify.",), tmp_path) == {}


def test_a_slice_cannot_define_a_key_outside_its_namespace(tmp_path: Path) -> None:
    _plugin(tmp_path, "evil", "    'cplug.evil.notify.copy.x.title': 'ok',\n    'cplug.other.notify.copy.x.title': 'spoof',\n")
    with pytest.raises(ValueError):
        catalog_lines.read_plugin_slices(("notify.",), tmp_path)


def test_the_slice_is_read_as_data_never_run(tmp_path: Path) -> None:
    _plugin(tmp_path, "data", "    'cplug.data.notify.copy.x.title': 'fine',\n    'cplug.data.notify.copy.y.title': (() => 'code')(),\n")
    with pytest.raises(ValueError):
        catalog_lines.read_plugin_slices(("notify.",), tmp_path)
