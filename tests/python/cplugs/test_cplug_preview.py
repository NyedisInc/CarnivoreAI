
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from src.cplugs.host import install_gates
from src.cplugs.host.sidecar_manifest import SidecarManifestError, load_sidecar_manifest
from tests.python.cplugs.preview_fixtures import BAD, GOOD

PACKAGE = Path(__file__).resolve().parents[3] / "packages" / "cplugs" / "mcphealth"


def _staged(tmp_path: Path, preview: object = "preview.png", data: bytes = GOOD["png"], extra_key: bool = False, name: str = "preview.png") -> Path:
    dest = tmp_path / "mcphealth"
    shutil.copytree(PACKAGE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    doc = json.loads((dest / "cplug.json").read_text())
    if preview is not None:
        doc["preview"] = preview
    if extra_key:
        doc["banner"] = "x"
    (dest / "cplug.json").write_text(json.dumps(doc))
    if data is not None:
        (dest / name).write_bytes(data)
    return dest


@pytest.mark.parametrize("kind,name", [("png", "preview.png"), ("jpeg", "art/p.jpg"), ("webp", "p.webp")])
def test_a_declared_preview_passes_the_gate_and_loads_for_a_sandboxed_plugin(tmp_path, kind, name):
    (tmp_path / "x").mkdir()
    root = _staged(tmp_path, preview=name, data=None)
    (root / name).parent.mkdir(exist_ok=True)
    (root / name).write_bytes(GOOD[kind])
    facts = install_gates.evaluate("carnivore/mcphealth", root)
    assert facts.facts["files"] >= 1
    assert load_sidecar_manifest(root, "mcphealth").preview == name


@pytest.mark.parametrize("why", sorted(BAD))
def test_a_preview_that_breaks_a_rule_is_refused_by_the_gate_and_the_loader(tmp_path, why):
    root = _staged(tmp_path, data=BAD[why])
    with pytest.raises(install_gates.CplugGateRefusal):
        install_gates.evaluate("carnivore/mcphealth", root)
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(root, "mcphealth")


@pytest.mark.parametrize("value", ["../preview.png", "/etc/preview.png", "a\\b.png", "preview.gif", "main.py", 5, ""])
def test_a_preview_path_that_is_not_a_plain_relative_image_is_refused(tmp_path, value):
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(_staged(tmp_path, preview=value), "mcphealth")


def test_a_missing_file_or_a_symlink_out_is_refused(tmp_path):
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(_staged(tmp_path / "a", data=None), "mcphealth")
    outside = tmp_path / "outside.png"
    outside.write_bytes(GOOD["png"])
    root = _staged(tmp_path / "b", data=None)
    os.symlink(outside, root / "preview.png")
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(root, "mcphealth")


def test_only_the_declared_file_is_exempt_and_every_other_unknown_key_is_still_refused(tmp_path):
    root = _staged(tmp_path / "a", preview=None, data=None)
    (root / "other.png").write_bytes(GOOD["png"])
    with pytest.raises(install_gates.CplugGateRefusal):
        install_gates.evaluate("carnivore/mcphealth", root)
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(_staged(tmp_path / "b", extra_key=True), "mcphealth")
