
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.plugins.host import install_gates

PACKAGE = Path(__file__).resolve().parents[3] / "packages" / "cplugs" / "mcphealth"
PINNED = "3463B8E83B44738B"


def _staged(tmp_path: Path, trust: bool, declared: bool = True) -> Path:
    dest = tmp_path / "mcphealth"
    shutil.copytree(PACKAGE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    text = (dest / "carnivore.toml").read_text()
    if trust:
        text = 'trust = "unrestricted"\n' + text
    if declared:
        text += '\n[[ui.views]]\nname = "panel"\nsurfaces = ["panel"]\nfiles = ["index.html"]\n'
    (dest / "carnivore.toml").write_text(text)
    (dest / "views" / "panel").mkdir(parents=True)
    (dest / "views" / "panel" / "index.html").write_text("<p>view</p>")
    return dest


def test_a_declared_html_view_passes_regardless_of_trust_and_undeclared_is_refused(tmp_path):
    ok = install_gates.evaluate("carnivore/mcphealth", _staged(tmp_path / "a", True), PINNED.lower(), PINNED)
    assert ok.facts["files"] >= 1
    for name, trust, key in (("b", True, "DEADBEEFDEADBEEF"), ("c", False, PINNED), ("d", True, "")):
        assert install_gates.evaluate("carnivore/mcphealth", _staged(tmp_path / name, trust), key, PINNED).facts["files"] >= 1
    with pytest.raises(install_gates.CplugGateRefusal) as exc:
        install_gates.evaluate("carnivore/mcphealth", _staged(tmp_path / "e", True, False), PINNED, PINNED)
    assert exc.value.code == install_gates.NOT_SAFE and "index.html" in exc.value.detail


def test_an_undeclared_view_asset_is_refused_even_beside_a_declared_view(tmp_path):
    for name, trust, key in (("f", True, PINNED), ("g", False, "")):
        staged = _staged(tmp_path / name, trust)
        (staged / "views" / "panel" / "extra.css").write_text("body { color: red; }")
        with pytest.raises(install_gates.CplugGateRefusal) as exc:
            install_gates.evaluate("carnivore/mcphealth", staged, key, PINNED)
        assert exc.value.code == install_gates.NOT_SAFE and "extra.css" in exc.value.detail
