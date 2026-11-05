
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.cplugs.host.sidecar_manifest import SidecarManifestError, load_sidecar_manifest

CPLUGS = Path(__file__).resolve().parents[3] / "src" / "cplugs"


def _declared_keys(manifest: Any) -> List[str]:
    if not isinstance(manifest, dict):
        return []
    keys = list(manifest)
    for value in manifest.values():
        entries = value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else []
        keys += [k for entry in entries if isinstance(entry, dict) for k in entry]
    return keys


def _manifests() -> List[Path]:
    return sorted(CPLUGS.glob("*/cplug.json")) + sorted(CPLUGS.glob("*/carnivore.json"))


def test_no_shipped_manifest_declares_shortcut() -> None:
    paths = _manifests()
    assert len(paths) > 5, "the population check: an empty glob would pass for the wrong reason"
    offenders = [str(p.relative_to(CPLUGS)) for p in paths if "shortcut" in _declared_keys(json.loads(p.read_text()))]
    assert offenders == []


def _write_sidecar(root: Path, base_extra: Dict[str, Any], side_extra: Dict[str, Any]) -> None:
    base: Dict[str, Any] = {"schema": 1, "id": "oldplug", "name": "Old", "description": "d", "version": "1.0.0", "entry": "main.py", **base_extra}
    (root / "cplug.json").write_text(json.dumps(base))
    (root / "carnivore.json").write_text(json.dumps({"icon": "flow", **side_extra}))
    (root / "main.py").write_text("")


def test_carnivore_json_carrying_shortcut_still_loads(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, {}, {"shortcut": "X"})
    assert load_sidecar_manifest(tmp_path, "oldplug").id == "oldplug"


def test_cplug_json_shortcut_is_refused_by_the_generic_unknown_key_rule_only(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, {"shortcut": "X"}, {})
    with pytest.raises(SidecarManifestError, match=r"unknown keys \['shortcut'\]"):
        load_sidecar_manifest(tmp_path, "oldplug")
    _write_sidecar(tmp_path, {"zzz_not_a_key": "X"}, {})
    with pytest.raises(SidecarManifestError, match=r"unknown keys \['zzz_not_a_key'\]"):
        load_sidecar_manifest(tmp_path, "oldplug")
