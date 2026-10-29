
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture()
def features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("features_check_under_test", SCRIPTS / "features.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = tmp_path / "features"
    (root / "changes").mkdir(parents=True)
    (root / "areas.json").write_text(json.dumps([{"blurb": "b", "id": "a", "name": "A"}]), encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "FEATURES_DIR", root)
    monkeypatch.setattr(mod, "AREAS_FILE", root / "areas.json")
    monkeypatch.setattr(mod, "CATALOG_DIR", root / "catalog")
    monkeypatch.setattr(mod, "CHANGES_DIR", root / "changes")
    return mod


def _entry(mod, **over: object) -> None:
    data = {"date": "2026-10-22", "features": [], "issue": 1, "summary": "x", "type": "internal"}
    data.update(over)
    (mod.CHANGES_DIR / "e.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("over", [{"type": "fix"}, {"type": "fixed", "features": []}], ids=["type-fix", "empty-features"])
def test_check_refuses_what_render_refuses(features, over, capsys) -> None:
    _entry(features, **over)
    assert features.cmd_check(argparse.Namespace(branch=False)) == 1
    assert "violation" in capsys.readouterr().err


def test_check_passes_a_valid_internal_entry(features) -> None:
    _entry(features)
    assert features.cmd_check(argparse.Namespace(branch=False)) == 0
