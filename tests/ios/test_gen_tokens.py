
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "ios"
GENERATED = IOS / "Carnivore" / "Generated"

_spec = importlib.util.spec_from_file_location("gen_tokens", ROOT / "scripts" / "ios" / "gen-tokens.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _hand_written_swift() -> list:
    return [p for p in IOS.rglob("*.swift") if GENERATED not in p.parents]


def test_generated_files_are_current_and_cover_every_theme() -> None:
    clone = os.environ.get("CARNIVORE_CATALOG_CLONE")
    files = gen.build(catalog_clone=Path(clone) if clone else None)
    for name, src in files.items():
        written = (GENERATED / name).read_text(encoding="utf-8")
        if name == "Palettes.swift" and not clone:
            assert all(f'Palette(id: "{t["id"]}"' in written for t in gen.load_themes()), "Palettes.swift misses a bundled theme"
            continue
        assert written == src, f"{name} is stale: run scripts/ios/gen-tokens.py --catalog-clone <clone>"
    shipped = {p.parent.name for p in (ROOT / "client/css/themes").glob("*/theme.json")}
    assert shipped and all(f'Palette(id: "{t}"' in files["Palettes.swift"] for t in shipped)


def test_missing_catalog_key_fails(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.en.js"
    kept = [l for l in (ROOT / "client/js/i18n/catalog.en.js").read_text().splitlines()
            if "'ios.action.retry'" not in l]
    catalog.write_text("\n".join(kept) + "\n")
    with pytest.raises(gen.GenError, match="ios.action.retry"):
        gen.build(catalog=catalog)


def test_missing_theme_role_fails(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "client/css/themes/carnivore", tmp_path / "carnivore")
    path = tmp_path / "carnivore" / "theme.json"
    data = json.loads(path.read_text())
    del data["cssVars"]["--color-accent"]
    path.write_text(json.dumps(data))
    with pytest.raises(gen.GenError, match="--color-accent"):
        gen.load_themes(tmp_path)


def test_no_hex_color_literal_in_hand_written_swift() -> None:
    literal = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b0x[0-9a-fA-F]{6,8}\b|\b(?:UI)?Color\(\s*(?:red|white|hue)\s*:")
    swift = _hand_written_swift()
    assert swift, "found no hand-written Swift: the check looked at nothing"
    offenders = [f"{p.relative_to(ROOT)}:{n}" for p in swift
                 for n, line in enumerate(p.read_text().splitlines(), 1) if literal.search(line)]
    assert not offenders, offenders


def test_swift_only_reads_strings_the_generator_makes() -> None:
    generated = set(re.findall(r"static let (\w+) =", (GENERATED / "Strings.swift").read_text()))
    used = {m for p in _hand_written_swift() for m in re.findall(r"\bStrings\.(\w+)", p.read_text())} - {"fill"}
    assert used and not (used - generated), used - generated


def test_no_bare_text_or_system_color_in_hand_written_swift() -> None:
    literal = re.compile(r"\b(?:Text|Button|TextField|Picker|Label|Toggle)\(\s*\"")
    system = re.compile(r"\.(?:orange|red|black|white|green|blue|yellow|gray|secondary)\b(?!\s*\()|\bColor\.\w+")
    swift = [p for p in _hand_written_swift() if "Tests" not in p.parts]
    assert swift, "found no hand-written Swift: the check looked at nothing"
    offenders = []
    for p in swift:
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if literal.search(line) or (system.search(line) and "backgroundColor =" not in line):
                offenders.append(f"{p.relative_to(ROOT)}:{n}")
    assert not offenders, offenders


def test_bridge_routes_theme_message_and_version_fields_follow_project_yml() -> None:
    bridge = (IOS / "Carnivore" / "ShellBridge.swift").read_text()
    assert 'case "theme"' in bridge and "ThemeStore.shared.report" in bridge
    plist = (IOS / "Carnivore" / "Info.plist").read_text()
    assert "$(MARKETING_VERSION)" in plist and "$(CURRENT_PROJECT_VERSION)" in plist
