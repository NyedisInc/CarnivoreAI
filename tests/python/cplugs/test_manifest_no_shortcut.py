
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest

CPLUGS = Path(__file__).resolve().parents[3] / "src" / "plugins"


def _declared_keys(manifest: Any) -> List[str]:
    if not isinstance(manifest, dict):
        return []
    keys = list(manifest)
    for value in manifest.values():
        entries = value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else []
        keys += [k for entry in entries if isinstance(entry, dict) for k in entry]
    return keys


def _manifests() -> List[Path]:
    return sorted(CPLUGS.glob("*/carnivore.toml")) + sorted(CPLUGS.glob("*/cplug.json")) + sorted(CPLUGS.glob("*/carnivore.json"))


def _read_manifest(path: Path) -> Any:
    return tomllib.loads(path.read_text()) if path.suffix == ".toml" else json.loads(path.read_text())


def test_no_shipped_manifest_declares_shortcut() -> None:
    paths = _manifests()
    assert len(paths) > 5, "the population check: an empty glob would pass for the wrong reason"
    offenders = [str(p.relative_to(CPLUGS)) for p in paths if "shortcut" in _declared_keys(_read_manifest(p))]
    assert offenders == []


def _write_sidecar(root: Path, extra: Dict[str, Any]) -> None:
    doc: Dict[str, Any] = {
        "schema": 2,
        "id": "oldplug",
        "name": "Old",
        "description": "d",
        "version": "1.0.0",
        "kind": "plugin",
        "author": "me",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        **extra,
    }
    (root / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    (root / "main.py").write_text("", encoding="utf-8")


def test_v2_manifest_without_shortcut_loads(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, {})
    assert load_sidecar_manifest(tmp_path, "oldplug").id == "oldplug"


def test_shortcut_key_is_refused_by_the_generic_unknown_key_rule_only(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, {"shortcut": "X"})
    with pytest.raises(SidecarManifestError, match=r"unknown field\(s\) \['shortcut'\]"):
        load_sidecar_manifest(tmp_path, "oldplug")
    _write_sidecar(tmp_path, {"zzz_not_a_key": "X"})
    with pytest.raises(SidecarManifestError, match=r"unknown field\(s\) \['zzz_not_a_key'\]"):
        load_sidecar_manifest(tmp_path, "oldplug")
