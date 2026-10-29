
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.cplugs.host import install_gates

PACKAGE = Path(__file__).resolve().parents[3] / "packages" / "cplugs" / "mcphealth"
PINNED = "3463B8E83B44738B"


def _staged(tmp_path: Path, trust: bool) -> Path:
    dest = tmp_path / "mcphealth"
    shutil.copytree(PACKAGE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    doc = json.loads((dest / "cplug.json").read_text())
    if trust:
        doc["trust"] = "unrestricted"
    (dest / "cplug.json").write_text(json.dumps(doc))
    (dest / "panel.html").write_text("<p>view</p>")
    return dest


def test_an_html_view_passes_only_for_an_approved_unrestricted_plugin(tmp_path):
    ok = install_gates.evaluate("carnivore/mcphealth", _staged(tmp_path / "a", True), PINNED.lower(), PINNED)
    assert ok.facts["files"] >= 1
    for name, trust, key in (("b", True, "DEADBEEFDEADBEEF"), ("c", False, PINNED), ("d", True, "")):
        with pytest.raises(install_gates.CplugGateRefusal) as exc:
            install_gates.evaluate("carnivore/mcphealth", _staged(tmp_path / name, trust), key, PINNED)
        assert exc.value.code == install_gates.NOT_SAFE and "panel.html" in exc.value.detail
