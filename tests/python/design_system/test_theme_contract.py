from __future__ import annotations

import json
import re
from pathlib import Path

from structlog.testing import capture_logs

from src.api import themes_routes
from src.core.design_base import theme_contract
from src.core.design_base.theme_contract import check, load_contract

REPO = Path(__file__).resolve().parents[3]
THEMES = sorted((REPO / "client" / "css" / "themes").glob("*/theme.json"))
OLD_RADII = ("--radius-full", "--radius-lg", "--radius-md", "--radius-pill", "--radius-sm")


def _vars(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")).get("cssVars", {})


def test_every_bundled_theme_is_checked() -> None:
    assert len(THEMES) >= 12, f"found {len(THEMES)} bundled themes; the glob is broken"


def test_contract_names_have_kinds() -> None:
    names = load_contract()["names"]
    assert len([n for n, s in names.items() if s.get("required")]) == 16
    assert all(spec.get("kind") in {"color", "shadow", "font", "length"} for spec in names.values())


def test_bundled_themes_keep_the_contract() -> None:
    broken = {}
    for path in THEMES:
        report = check(_vars(path))
        problems = report.unknown + report.base_tokens + report.missing + [n for n, _ in report.bad_values]
        if problems:
            broken[path.parent.name] = problems
    assert not broken, f"theme sets names outside client/js/themes/theme-contract.json: {broken}"


def test_no_bundled_theme_sets_a_deprecated_name() -> None:
    found = {}
    for path in THEMES:
        names = tuple(sorted(n for n, _ in check(_vars(path)).deprecated))
        if names:
            found[path.parent.name] = names
    assert not found, f"bundled themes still set deprecated tokens: {found}"


def test_base_stylesheet_maps_old_radius_names_onto_the_legacy_tokens() -> None:
    css = (REPO / "client" / "css" / "styles.css").read_text(encoding="utf-8")
    for old in ("sm", "md", "lg"):
        for chunk in css.split(f"--radius-{old}:")[1:3]:
            assert f"var(--legacy-radius-{old}," in chunk.split(";", 1)[0]


def test_negative_control_each_break_is_named() -> None:
    contract_vars = {name: "#000000" for name, spec in load_contract()["names"].items() if spec.get("required")}
    planted = {**contract_vars, "--oc-space-3": "20px", "--my-glow": "red", "--radius-control": "6px",
               "--radius-sm": "2px"}
    del planted["--color-fg"]
    report = check(planted)
    assert report.base_tokens == ["--oc-space-3"]
    assert report.unknown == ["--my-glow"]
    assert report.missing == ["--color-fg"]
    assert report.bad_values == [("--radius-control", "above 4px")]
    assert report.deprecated == [("--radius-sm", "--radius-control")]
    assert check(contract_vars).clean


def test_negative_control_the_loader_reports_and_serves_unchanged(tmp_path: Path) -> None:
    theme_dir = tmp_path / "planted"
    theme_dir.mkdir()
    manifest = json.loads(THEMES[0].read_text(encoding="utf-8"))
    manifest["id"] = "planted"
    manifest["cssVars"] = {**manifest.get("cssVars", {}), "--oc-space-3": "20px"}
    for key in ("effects", "themeCss", "background", "audio"):
        manifest.pop(key, None)
    (theme_dir / "theme.json").write_text(json.dumps(manifest), encoding="utf-8")
    theme_contract._REPORTED.clear()
    with capture_logs() as logs:
        loaded = themes_routes._load_manifest(theme_dir, "user")
    assert loaded is not None and loaded.cssVars["--oc-space-3"] == "20px"
    reports = [e for e in logs if e["event"] == "theme_contract_report"]
    assert len(reports) == 1 and reports[0]["base_tokens"] == ["--oc-space-3"]


PRE_MIGRATION_RADII = {
    "carnivore-light": [
        "2px",
        "2px",
        "3px"
    ],
    "metal": [
        "2px",
        "3px",
        "4px"
    ],
    "claude": [
        "3px",
        "4px",
        "8px"
    ],
    "black_ops": [
        "2px",
        "2px",
        "3px"
    ],
    "dracula": [
        "3px",
        "4px",
        "8px"
    ],
    "acid_trip": [
        "3px",
        "4px",
        "8px"
    ],
    "lovecraft": [
        "3px",
        "4px",
        "8px"
    ],
    "blade_runner": [
        "3px",
        "4px",
        "8px"
    ],
    "carnivore": [
        "2px",
        "2px",
        "3px"
    ]
}


def test_legacy_radii_keep_each_themes_pre_migration_values() -> None:
    found = {}
    for path in THEMES:
        v = _vars(path)
        if "--legacy-radius-sm" in v:
            found[path.parent.name] = (v["--legacy-radius-sm"], v["--legacy-radius-md"], v["--legacy-radius-lg"])
    assert found == {k: tuple(x) for k, x in PRE_MIGRATION_RADII.items()}


def test_svelte_radii_resolve_to_2px_and_4px_under_every_builtin_theme() -> None:
    tokens = (REPO / "web" / "src" / "opscenter" / "tokens.css").read_text(encoding="utf-8")
    control = re.search(r"--oc-radius-control:\s*clamp\(0px, var\(--radius-control, (\d+)px\)", tokens)
    panel = re.search(r"--oc-radius-panel:\s*clamp\(0px, var\(--radius-panel, (\d+)px\)", tokens)
    assert control and panel and (control.group(1), panel.group(1)) == ("2", "4")
    setting = {p.parent.name: sorted({"--radius-control", "--radius-panel"} & set(_vars(p))) for p in THEMES}
    assert not any(setting.values()), f"built-in themes set the Svelte radius tokens: {setting}"
